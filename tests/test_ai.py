"""AI contract tests use synthetic transports and never contact a model provider."""

import asyncio
import copy
import json
import math
import socket

import httpx
import pytest
import pytest_asyncio

import oj.ai as ai_module
from oj.ai import AIService, SYSTEM_PROMPT
from oj.common import APIError


@pytest.fixture
def config():
    return {
        "provider_url": "https://models.example/v1",
        "model": "example-model",
        "api_key": "synthetic-test-secret-only",
        "input_price": 2,
        "output_price": 8,
        "price_unit": 1_000_000,
        "currency": "CNY",
    }


@pytest.fixture
def problem():
    return {
        "id": "AI_SUM",
        "title": "整数求和",
        "description": "计算两个整数的和。",
        "input_description": "输入两个整数a和b。",
        "output_description": "输出a+b。",
        "constraints": "-100 <= a,b <= 100",
        "samples": [{"input": "1 2\n", "output": "3\n"}],
        "testcases": [
            {"input": "-100 100\n", "output": "0\n"},
            {"input": "100 100\n", "output": "200\n"},
        ],
        "time_limit": 1.0,
        "memory_limit": 128,
        "reference_solution": "a,b=map(int,input().split()); print(a+b)",
        "test_generator": "import json\nprint(json.dumps([]))\n",
        "validation_notes": "正负边界已列出；未声称执行验证。",
        "test_generation_notes": "确定性生成器；本单元测试夹具不增加大数据测试点。",
        "translations": {
            "en": {
                "title": "Integer Sum",
                "description": "Compute the sum of two integers.",
                "input_description": "Read two integers a and b.",
                "output_description": "Print a + b.",
                "constraints": "Both integers are between -100 and 100.",
                "hint": "Use integer addition.",
            }
        },
    }


def event(value):
    return ("data: " + json.dumps(value, ensure_ascii=False) + "\n\n").encode()


def delta(text, finish=None):
    return event({"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]})


def stream_bytes(problem, *, usage=True):
    text = json.dumps(problem, ensure_ascii=False)
    chunks = [delta(text[:20]), delta(text[20:], "stop")]
    if usage:
        chunks.append(
            event(
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 500,
                        "total_tokens": 1500,
                    },
                }
            )
        )
    chunks.append(b"data: [DONE]\n\n")
    return b"".join(chunks)


def stream_text(text, *, usage=True):
    chunks = [delta(text, "stop")]
    if usage:
        chunks.append(
            event(
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 500,
                        "total_tokens": 1500,
                    },
                }
            )
        )
    chunks.append(b"data: [DONE]\n\n")
    return b"".join(chunks)


def response(body, status=200):
    return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})


@pytest_asyncio.fixture
async def services():
    instances = []

    def create(config=None, handler=None, **kwargs):
        transport = httpx.MockTransport(handler) if handler else None
        service = AIService(config, transport=transport, **kwargs)
        instances.append(service)
        return service

    yield create
    for service in instances:
        await service.close()


async def finished(service, task, user="alice"):
    await asyncio.wait_for(service._tasks[task["task_id"]].future, timeout=15)
    return await service.get(task["task_id"], user)


class GatedStream(httpx.AsyncByteStream):
    def __init__(self, first=b"", rest=b""):
        self.first = first
        self.rest = rest
        self.received = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False
        self.cancelled = False

    async def __aiter__(self):
        try:
            if self.first:
                yield self.first
            self.received.set()
            await self.release.wait()
            yield self.rest
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_config_controls_request_and_isolated_snapshot(services, config, problem):
    requests = []

    def handler(request):
        requests.append(request)
        return response(stream_bytes(problem))

    service = services(config, handler)
    configured = {
        **config,
        "provider_url": "https://second.example/custom",
        "model": "changed-model",
        "api_key": "changed-synthetic-secret",
    }
    public = await service.configure("alice", configured)
    assert "api_key" not in public and public["api_key_configured"]
    assert (await service.get_config("bob"))["model"] == config["model"]
    task = await service.start("alice", "知识点：整数运算；难度：入门")
    assert task["status"] == "pending" and task["result"] is None
    await service.configure("alice", {**configured, "model": "later-model"})
    final = await finished(service, task)
    payload = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://second.example/custom/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer changed-synthetic-secret"
    assert payload["model"] == "changed-model"
    assert payload["stream"] and payload["stream_options"]["include_usage"]
    assert payload["response_format"] == {"type": "json_object"}
    assert final["status"] == "completed" and final["result"]["id"] == "AI_SUM"
    assert final["result"]["reference_solution"] == problem["reference_solution"]
    assert "changed-synthetic-secret" not in json.dumps(final)
    assert final["usage"]["source"] == "provider"
    assert final["usage"]["cost"] == pytest.approx(0.006)
    assert "不等于官方账单" in final["usage"]["note"]
    assert not final["usage"]["incomplete"]
    assert final["elapsed_seconds"] >= 0
    final["result"]["title"] = "mutated client copy"
    assert (await service.get(task["task_id"], "alice"))["result"]["title"] == "整数求和"


@pytest.mark.asyncio
async def test_generated_complete_english_statement_is_preserved(services, config, problem):
    bilingual = copy.deepcopy(problem)
    bilingual["translations"] = {
        "en": {
            "title": "Integer Sum",
            "description": "Compute the sum of two integers.",
            "input_description": "Read two integers a and b.",
            "output_description": "Print a + b.",
            "constraints": "Both integers are between -100 and 100.",
            "hint": "Use integer addition.",
        }
    }
    service = services(config, lambda _: response(stream_bytes(bilingual)))

    final = await finished(service, await service.start("alice", "生成双语整数求和题"))

    assert final["status"] == "completed"
    assert final["result"]["translations"]["en"]["title"] == "Integer Sum"
    assert all(case in final["result"]["testcases"] for case in problem["testcases"])


@pytest.mark.asyncio
async def test_missing_validation_note_gets_truthful_checked_fallback(services, config, problem):
    candidate = copy.deepcopy(problem)
    candidate.pop("validation_notes")
    requests = []

    def handler(request):
        requests.append(request)
        return response(stream_bytes(candidate))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "生成可审阅的完整题目"))

    assert final["status"] == "completed"
    assert final["provider_calls"] == 1
    assert len(requests) == 1
    assert "系统已实际运行参考解" in final["result"]["validation_notes"]
    assert "人工审阅" in final["result"]["validation_notes"]


@pytest.mark.asyncio
async def test_missing_provider_translation_enters_bounded_repair(services, config, problem):
    legacy = copy.deepcopy(problem)
    legacy.pop("translations")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response(stream_bytes(legacy if len(requests) == 1 else problem))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "生成完整双语题目"))

    assert final["status"] == "completed"
    assert final["result"]["translations"]["en"]["title"] == "Integer Sum"
    assert len(requests) == 2
    feedback = requests[1]["messages"][-1]["content"]
    assert "authoring_check:problem_translation" in feedback
    assert "translations.en" in feedback


@pytest.mark.asyncio
async def test_config_empty_key_retained_only_for_same_provider(services, config):
    service = services(config, lambda _: response(b""))
    public = await service.configure("alice", {**config, "api_key": ""})
    assert public["api_key_configured"]
    with pytest.raises(APIError) as caught:
        await service.configure(
            "alice", {**config, "api_key": "", "provider_url": "https://other.example"}
        )
    assert caught.value.status == 400
    assert config["api_key"] not in caught.value.message


@pytest.mark.asyncio
async def test_no_config_and_invalid_input(services):
    service = services()
    assert not (await service.get_config("alice"))["api_key_configured"]
    for requirement in (None, "", 123, " " * 20):
        with pytest.raises(APIError) as caught:
            await service.start("alice", requirement)
        assert caught.value.status == 400
    with pytest.raises(APIError) as caught:
        await service.start("alice", "正常需求")
    assert caught.value.status == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"provider_url": "http://models.example"},
        {"provider_url": "https://127.0.0.1"},
        {"provider_url": "https://169.254.169.254"},
        {"provider_url": "https://[::1]"},
        {"provider_url": "https://[::ffff:127.0.0.1]"},
        {"provider_url": "https://localhost"},
        {"provider_url": "https://host.internal"},
        {"provider_url": "https://user:password@models.example"},
        {"provider_url": "https://models.example?secret=value"},
        {"provider_url": "https://models.example/#fragment"},
        {"provider_url": "https://2130706433"},
        {"model": ""},
        {"api_key": "header\ninjection"},
        {"api_key": False},
        {"input_price": -1},
        {"input_price": float("nan")},
        {"input_price": 10**400},
        {"output_price": 10**400},
        {"output_price": True},
        {"price_unit": 0},
        {"price_unit": True},
        {"price_unit": 10**400},
        {"currency": "not-currency"},
    ],
)
async def test_invalid_config_is_rejected(services, config, updates):
    service = services(config, lambda _: response(b""))
    with pytest.raises(APIError) as caught:
        await service.configure("alice", {**config, **updates})
    assert caught.value.status == 400


@pytest.mark.asyncio
async def test_dns_rejects_mixed_private_addresses_and_pins_public(services, config, monkeypatch):
    service = services(config)
    loop = asyncio.get_running_loop()

    async def mixed(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", mixed)
    with pytest.raises(APIError) as caught:
        await service.configure("alice", config)
    assert caught.value.status == 400

    async def public(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(loop, "getaddrinfo", public)
    await service.configure("alice", config)
    url, headers, extensions = await service._destination(config["provider_url"])
    assert url.host == "8.8.8.8"
    assert headers["Host"] == "models.example"
    assert extensions["sni_hostname"] == "models.example"


@pytest.mark.asyncio
async def test_progress_elapsed_and_true_cancel_close_http(services, config, problem):
    text = json.dumps(problem, ensure_ascii=False)
    stream = GatedStream(delta(text[:30]), delta(text[30:], "stop"))
    service = services(
        config,
        lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream),
    )
    task = await service.start("alice", "请出一道求和题")
    await asyncio.wait_for(stream.received.wait(), 1)
    progress = await service.get(task["task_id"], "alice")
    assert progress["status"] == "running" and "30个正文字符" in progress["progress"]
    assert progress["usage"]["source"] == "estimated"
    earlier = progress["elapsed_seconds"]
    # Windows' event-loop clock can wake a 10ms timer early (15.6ms resolution).
    # Keep the strict elapsed-time invariant without assuming one timer's duration.
    for _ in range(10):
        await asyncio.sleep(0.02)
        later = (await service.get(task["task_id"], "alice"))["elapsed_seconds"]
        if later > earlier:
            break
    assert later > earlier
    for operation in (service.get, service.cancel):
        with pytest.raises(APIError) as caught:
            await operation(task["task_id"], "bob")
        assert caught.value.status == 403
    assert (await service.get(task["task_id"], "admin", True))["status"] == "running"
    cancelled = await service.cancel(task["task_id"], "admin", True)
    assert cancelled["status"] == "cancelled" and cancelled["result"] is None
    assert cancelled["usage"]["incomplete"]
    assert stream.closed and stream.cancelled
    stream.release.set()
    await asyncio.sleep(0)
    assert await service.get(task["task_id"], "alice") == cancelled
    with pytest.raises(APIError) as caught:
        await service.cancel(task["task_id"], "alice")
    assert caught.value.status == 409


@pytest.mark.asyncio
async def test_pending_cancel_sends_no_request(services, config):
    seen = []
    service = services(config, lambda request: seen.append(request))
    task = await service.start("alice", "简单题")
    assert (await service.cancel(task["task_id"], "alice"))["status"] == "cancelled"
    assert not seen


@pytest.mark.asyncio
async def test_task_permissions_missing_and_completed_cancel(services, config, problem):
    service = services(config, lambda _: response(stream_bytes(problem)))
    for operation in (service.get, service.cancel):
        with pytest.raises(APIError) as caught:
            await operation("absent", "alice")
        assert caught.value.status == 404
    task = await service.start("alice", "求和")
    await finished(service, task)
    with pytest.raises(APIError) as caught:
        await service.cancel(task["task_id"], "alice")
    assert caught.value.status == 409


@pytest.mark.asyncio
async def test_official_deepseek_peak_catalog_and_zero_before_start(services, config):
    default = {
        **config,
        "provider_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "currency": "USD",
    }
    default.pop("input_price")
    default.pop("output_price")
    service = services(default, lambda _: response(b""))
    public = await service.get_config("alice")
    assert public["input_price"] == 0.44 and public["output_price"] == 1.32
    assert public["rate_source"] == "deepseek_official_catalog"
    assert public["rate_version"] == "deepseek-pricing-checked-2026-09-09"
    assert public["cache_assumption"] == "peak_cache_miss"
    assert public["pricing_url"] == "https://api-docs.deepseek.com/quick_start/pricing/"

    task = await service.start("alice", "求和")
    assert task["usage"]["cost"] == 0.0
    assert task["usage"]["source"] == "zero_before_start"
    assert task["usage"]["cost_basis"] == "zero_before_start"
    assert task["provider_calls"] == 0
    await service.cancel(task["task_id"], "alice")


@pytest.mark.asyncio
async def test_configured_price_wins_over_catalog_per_field(services, config):
    configured = {
        **config,
        "provider_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "currency": "CNY",
        "input_price": 6.5,
    }
    configured.pop("output_price")
    service = services(config, lambda _: response(b""))
    await service.configure("alice", configured)
    public = await service.get_config("alice")
    assert public["input_price"] == 6.5 and public["output_price"] == 27.0
    assert public["rate_source"] == "configured+conservative_fallback"
    assert public["rate_version"] == "conservative-fallback-2026-09-09"
    assert public["pricing_url"] is None
    task = await service.start("alice", "求和")
    assert task["usage"]["rate_source"] == "configured+conservative_fallback"
    await service.cancel(task["task_id"], "alice")


@pytest.mark.asyncio
async def test_cny_deepseek_defaults_are_explicit_application_fallback(services, config):
    default = {
        **config,
        "provider_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "currency": "CNY",
    }
    default.pop("input_price")
    default.pop("output_price")
    service = services(default, lambda _: response(b""))
    public = await service.get_config("alice")
    assert public["input_price"] == 9.0 and public["output_price"] == 27.0
    assert public["rate_source"] == "conservative_fallback"
    assert public["rate_version"] == "conservative-fallback-2026-09-09"
    assert public["pricing_url"] is None


@pytest.mark.asyncio
async def test_unknown_price_and_estimated_usage(services, config, problem):
    config.pop("input_price")
    config.pop("output_price")
    service = services(config, lambda _: response(stream_bytes(problem, usage=False)))
    final = await finished(service, await service.start("alice", "求和"))
    assert final["status"] == "completed"
    usage = final["usage"]
    assert usage["source"] == "estimated" and "粗估" in usage["note"]
    assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    assert usage["cost"] > 0 and not usage["incomplete"]
    assert usage["rate_source"] == "conservative_fallback"
    assert usage["rate_version"] == "conservative-fallback-2026-09-09"
    assert usage["cache_assumption"] == "peak_cache_miss"


@pytest.mark.asyncio
async def test_partial_provider_usage_remains_partial(services, config, problem):
    body = delta(json.dumps(problem), "stop")
    body += event({"choices": [], "usage": {"total_tokens": 77}}) + b"data: [DONE]\n\n"
    service = services(config, lambda _: response(body))
    usage = (await finished(service, await service.start("alice", "求和")))["usage"]
    assert usage["source"] == "provider_partial"
    assert usage["input_tokens"] > 0 and usage["output_tokens"] > 0
    assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    assert usage["total_tokens"] >= 77
    assert usage["provider_reported_total_tokens"] == 77
    assert set(usage["estimated_fields"]) >= {"input_tokens", "output_tokens"}
    assert usage["cost"] > 0 and usage["cost_basis"] == "input_output_tokens"
    assert "UTF-8" in usage["note"]
    assert usage["incomplete"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_usage", "exact_field", "exact_value", "estimated_field"),
    [
        ({"prompt_tokens": 11}, "input_tokens", 11, "output_tokens"),
        ({"completion_tokens": 7}, "output_tokens", 7, "input_tokens"),
        (
            {"prompt_tokens": 11, "total_tokens": 13},
            "input_tokens",
            11,
            "output_tokens",
        ),
    ],
)
async def test_partial_provider_usage_fills_missing_components_from_payload(
    services,
    config,
    problem,
    provider_usage,
    exact_field,
    exact_value,
    estimated_field,
):
    encoded = json.dumps(problem)
    body = delta(encoded, "stop")
    body += event({"choices": [], "usage": provider_usage}) + b"data: [DONE]\n\n"
    service = services(config, lambda _: response(body))
    usage = (await finished(service, await service.start("alice", "求和")))["usage"]

    assert usage[exact_field] == exact_value
    assert usage[estimated_field] >= math.ceil(len(encoded.encode()) / 3)
    assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    assert estimated_field in usage["estimated_fields"]
    assert usage["source"] == "provider_partial" and usage["incomplete"]
    assert usage["cost"] > 0


@pytest.mark.asyncio
async def test_huge_provider_usage_cost_is_decimal_safe_and_finite(services, config, problem):
    enormous = 10**400
    body = delta(json.dumps(problem), "stop")
    body += event(
        {
            "choices": [],
            "usage": {
                "prompt_tokens": enormous,
                "completion_tokens": enormous,
                "total_tokens": enormous * 2,
            },
        }
    )
    body += b"data: [DONE]\n\n"
    service = services(config, lambda _: response(body))
    usage = (await finished(service, await service.start("alice", "求和")))["usage"]
    assert usage["cost"] > 0 and usage["cost"] < float("inf")
    assert usage["cost_basis"] == "input_output_tokens_clamped"


@pytest.mark.asyncio
async def test_deadline_cancels_stream(services, config, monkeypatch):
    monkeypatch.setattr(ai_module, "TASK_TIMEOUT_SECONDS", 0.02)
    stream = GatedStream()
    service = services(
        config,
        lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream),
    )
    final = await finished(service, await service.start("alice", "求和"))
    assert final["status"] == "failed" and "超时" in final["error"]
    assert stream.closed and stream.cancelled
    assert final["result"] is None and final["usage"]["incomplete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 307, 401, 403, 429, 500])
async def test_http_errors_are_safe_and_no_redirect_follow(services, config, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            text=config["api_key"] + " private server path",
            headers={"location": "https://evil.example"},
        )

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "求和"))
    assert final["status"] == "failed" and str(status) in final["error"]
    assert config["api_key"] not in json.dumps(final) and len(calls) == 1
    assert final["error_code"] == "provider_http_error"
    assert final["retryable"] is (status == 429 or status >= 500)
    assert final["usage"]["cost"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "bad-event",
        "bad-json",
        "bad-problem",
        "truncated",
        "no-finish",
        "wrong-usage",
        "secret",
        "not-stream",
    ],
)
async def test_invalid_model_responses_fail_closed(services, config, problem, kind):
    if kind == "bad-event":
        body = b"data: not-json\n\n"
    elif kind == "bad-json":
        body = delta("```json\n{}\n```", "stop")
    elif kind == "bad-problem":
        body = delta('{"title":"only title"}', "stop")
    elif kind == "truncated":
        body = delta(json.dumps(problem), "length")
    elif kind == "no-finish":
        body = delta(json.dumps(problem))
    elif kind == "wrong-usage":
        body = stream_bytes(problem, usage=False).replace(
            b"data: [DONE]\n\n",
            event({"usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 5}}),
        )
    elif kind == "secret":
        body = stream_bytes({**problem, "title": config["api_key"]})
    else:
        body = json.dumps(problem).encode()
    service = services(
        config,
        lambda _: response(body) if kind != "not-stream" else httpx.Response(200, json=problem),
    )
    final = await finished(service, await service.start("alice", "求和"))
    assert final["status"] == "failed" and final["result"] is None
    assert final["error"] and config["api_key"] not in json.dumps(final)
    assert final["error_code"] and final["usage"]["cost"] is not None


@pytest.mark.asyncio
async def test_truncated_provider_output_retries_with_concise_full_request(
    services, config, problem
):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return response(delta('{"id":"partial', "length"))
        return response(stream_bytes(problem))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "生成完整题目"))

    assert final["status"] == "completed"
    assert final["provider_calls"] == 2
    assert len(requests) == 2
    retry = requests[1]["messages"][-1]
    assert retry["role"] == "user"
    assert "输出长度限制" in retry["content"]
    assert "partial" not in retry["content"]


@pytest.mark.asyncio
async def test_repeated_reference_runtime_failure_uses_fresh_final_design(
    services, config, problem
):
    broken = copy.deepcopy(problem)
    broken["reference_solution"] = "raise ValueError('broken candidate')"
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        candidate = broken if len(requests) < 3 else problem
        return response(stream_bytes(candidate))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "生成可靠题目"))

    assert final["status"] == "completed"
    assert final["provider_calls"] == 3
    assert len(requests[1]["messages"]) == 4
    assert len(requests[2]["messages"]) == 3
    fresh_messages = json.dumps(requests[2]["messages"], ensure_ascii=False)
    assert "不要复用前稿" in fresh_messages
    assert "broken candidate" not in fresh_messages


@pytest.mark.asyncio
async def test_network_exception_is_sanitized(services, config):
    def handler(request):
        raise httpx.ConnectError(config["api_key"] + " request headers", request=request)

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "求和"))
    assert final["status"] == "failed" and "连接失败" in final["error"]
    assert config["api_key"] not in json.dumps(final)


@pytest.mark.asyncio
async def test_response_byte_limit_before_unbounded_line(services, config, monkeypatch):
    monkeypatch.setattr(ai_module, "MAX_STREAM_BYTES", 64)
    service = services(config, lambda _: response(b"data: " + b"x" * 1000))
    final = await finished(service, await service.start("alice", "求和"))
    assert final["status"] == "failed" and "安全长度" in final["error"]


@pytest.mark.asyncio
async def test_content_and_event_limits_independent_of_wire_limit(services, config, monkeypatch):
    monkeypatch.setattr(ai_module, "MAX_CONTENT_BYTES", 50)
    service = services(config, lambda _: response(delta("x" * 51, "stop")))
    final = await finished(service, await service.start("alice", "求和"))
    assert final["status"] == "failed" and "生成内容" in final["error"]
    monkeypatch.setattr(ai_module, "MAX_EVENT_LINE_BYTES", 100)
    service = services(config, lambda _: response(b"data: " + b"x" * 101))
    final = await finished(service, await service.start("alice", "求和"))
    assert final["status"] == "failed" and "流事件" in final["error"]


@pytest.mark.asyncio
async def test_reference_validation_and_prompt(services, config, problem):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response(stream_bytes(problem))

    service = services(config, handler)
    with pytest.raises(APIError) as caught:
        await service.start("alice", "改编题目", {"id": "missing-fields"})
    assert caught.value.status == 400
    await finished(service, await service.start("alice", "改编题目", copy.deepcopy(problem)))
    prompt_input = json.loads(requests[0]["messages"][1]["content"])
    assert prompt_input["reference_problem"]["id"] == problem["id"]
    assert "不声称已经运行代码" in SYSTEM_PROMPT and "不同复杂度" in SYSTEM_PROMPT
    assert "不要 Markdown" in SYSTEM_PROMPT and "真实多线程" in SYSTEM_PROMPT
    actual_system = requests[0]["messages"][0]["content"]
    assert actual_system == SYSTEM_PROMPT
    for required in (
        "自然的低效解法",
        "多层汇合分叉的无环图",
        "不以sleep、人为重复运算制造慢解",
        "预期区分而非已验证TLE",
    ):
        assert required in actual_system


@pytest.mark.asyncio
async def test_deepseek_disables_thinking_without_forcing_model(services, config, problem):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response(stream_bytes(problem))

    service = services(
        {**config, "provider_url": "https://api.deepseek.com", "model": "configured-flash-model"},
        handler,
    )
    await finished(service, await service.start("alice", "求和"))
    assert requests[0]["thinking"] == {"type": "disabled"}
    assert requests[0]["model"] == "configured-flash-model"


@pytest.mark.asyncio
async def test_shutdown_cancels_and_clears_credentials(services, config):
    stream = GatedStream()
    service = services(
        config,
        lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream),
    )
    await service.configure("alice", config)
    task = await service.start("alice", "求和")
    await asyncio.wait_for(stream.received.wait(), 1)
    await service.close()
    assert stream.closed and stream.cancelled
    assert not (await service.get_config("alice"))["api_key_configured"]
    with pytest.raises(APIError) as caught:
        await service.get(task["task_id"], "alice")
    assert caught.value.status == 404


@pytest.mark.asyncio
async def test_utf8_sse_across_network_boundaries(services, config, problem):
    class ByteChunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for value in stream_bytes(problem):
                yield bytes([value])

    service = services(
        config,
        lambda _: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=ByteChunks()
        ),
    )
    final = await finished(service, await service.start("alice", "中文题目"))
    assert final["status"] == "completed" and final["result"]["title"] == "整数求和"


@pytest.mark.asyncio
async def test_reset_during_configure_cannot_restore_key(services, config, monkeypatch):
    service = services(config)
    started, release = asyncio.Event(), asyncio.Event()

    async def gated_destination(url):
        started.set()
        await release.wait()

    monkeypatch.setattr(service, "_destination", gated_destination)
    configuring = asyncio.create_task(service.configure("alice", config))
    await asyncio.wait_for(started.wait(), 1)
    await service.close()
    release.set()
    with pytest.raises(APIError) as caught:
        await configuring
    assert caught.value.status == 409
    assert not (await service.get_config("alice"))["api_key_configured"]


@pytest.mark.asyncio
async def test_real_consistency_gate_repairs_once_and_accumulates_usage(services, config, problem):
    broken = copy.deepcopy(problem)
    broken["testcases"][0]["output"] = "999"
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response(stream_bytes(broken if len(requests) == 1 else problem))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "整数求和"))
    assert final["status"] == "completed"
    assert len(requests) == 2 and len(requests[1]["messages"]) == 4
    assert "authoring_check:answer_mismatch:case=1" in requests[1]["messages"][-1]["content"]
    assert final["result"]["quality"]["reference_checked"]
    assert final["result"]["quality"]["checked_cases"] == 3
    assert final["usage"]["input_tokens"] == 2000
    assert final["usage"]["output_tokens"] == 1000
    assert final["usage"]["total_tokens"] == 3000
    assert final["usage"]["cost"] == pytest.approx(0.012)
    assert not final["usage"]["incomplete"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first_body", "expected_code", "feedback_fragment"),
    [
        (stream_text("{not valid json"), "authoring_check:problem_json", "严格JSON"),
        (
            stream_text(json.dumps({"title": "字段不足"}, ensure_ascii=False)),
            "authoring_check:problem_schema",
            "字段合同",
        ),
    ],
)
async def test_json_and_schema_candidates_enter_targeted_repair(
    services, config, problem, first_body, expected_code, feedback_fragment
):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        body = first_body if len(requests) == 1 else stream_bytes(problem)
        return response(body)

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "整数求和"))
    assert final["status"] == "completed" and final["provider_calls"] == 2
    feedback = requests[1]["messages"][-1]["content"]
    assert expected_code in feedback and feedback_fragment in feedback
    assert final["usage"]["total_tokens"] == 3000
    assert final["usage"]["cost"] == pytest.approx(0.012)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["test_generator", "test_generation_notes"])
async def test_missing_generator_contract_enters_bounded_repair(services, config, problem, missing):
    incomplete = copy.deepcopy(problem)
    incomplete.pop(missing)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response(stream_bytes(incomplete if len(requests) == 1 else problem))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "整数求和"))

    assert final["status"] == "completed" and final["provider_calls"] == 2
    feedback = requests[1]["messages"][-1]["content"]
    assert "authoring_check:problem_schema" in feedback
    assert "test_generator" in feedback and "test_generation_notes" in feedback
    assert final["result"][missing]


@pytest.mark.asyncio
async def test_persistently_missing_generator_contract_fails_structurally(
    services, config, problem
):
    incomplete = copy.deepcopy(problem)
    incomplete.pop("test_generator")
    calls = []

    def handler(request):
        calls.append(request)
        return response(stream_bytes(incomplete))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "整数求和"))

    assert len(calls) == 3
    assert final["status"] == "failed" and final["result"] is None
    assert final["error_code"] == "authoring_validation_exhausted"
    assert final["error_detail"] == "authoring_check:problem_schema"


@pytest.mark.asyncio
async def test_exact_deadlock_requirement_repairs_generator_output_and_runs_full_gate(
    services, config
):
    requirement = (
        "多线程死锁检测：设计一道与多线程资源竞争有关的题目。给出若干线程获取锁的先后关系，"
        "要求判断这些线程是否可能发生死锁。题目不依赖真实线程运行，预期将锁的依赖关系转换为"
        "有向图，并使用拓扑排序或环检测算法完成判断。"
    )
    reference_solution = """import sys
data = list(map(int, sys.stdin.read().split()))
n, m = data[0], data[1]
graph = [[] for _ in range(n)]
indegree = [0] * n
position = 2
for _ in range(m):
    source = data[position] - 1
    target = data[position + 1] - 1
    position += 2
    graph[source].append(target)
    indegree[target] += 1
queue = [node for node in range(n) if indegree[node] == 0]
head = 0
visited = 0
while head < len(queue):
    node = queue[head]
    head += 1
    visited += 1
    for target in graph[node]:
        indegree[target] -= 1
        if indegree[target] == 0:
            queue.append(target)
print("YES" if visited < n else "NO")
"""
    valid_generator = """import json
inputs = []
edges = [(1, 2), (2, 3), (3, 1)]
lines = ["3 " + str(len(edges))]
for source, target in edges:
    lines.append(str(source) + " " + str(target))
inputs.append("\\n".join(lines) + "\\n")
edges = [(1, 2), (1, 3), (2, 4), (3, 4)]
lines = ["4 " + str(len(edges))]
for source, target in edges:
    lines.append(str(source) + " " + str(target))
inputs.append("\\n".join(lines) + "\\n")
print(json.dumps(inputs))
"""
    valid = {
        "id": "AI_DEADLOCK",
        "title": "锁依赖环检测",
        "description": "将线程的锁等待关系抽象为有向图，判断是否存在死锁环。",
        "input_description": "第一行n和m，随后m行每行两个线程编号u和v，表示u等待v。",
        "output_description": "若存在有向环输出YES，否则输出NO。",
        "constraints": "1 <= n <= 200000, 0 <= m <= 300000",
        "samples": [
            {"input": "3 3\n1 2\n2 3\n3 1\n", "output": "YES\n"},
            {"input": "3 2\n1 2\n2 3\n", "output": "NO\n"},
        ],
        "testcases": [
            {"input": "3 3\n1 2\n2 3\n3 1\n", "output": "YES\n"},
            {"input": "3 2\n1 2\n2 3\n", "output": "NO\n"},
        ],
        "time_limit": 2.0,
        "memory_limit": 256,
        "reference_solution": reference_solution,
        "test_generator": valid_generator,
        "validation_notes": "使用拓扑排序判断是否存在未被移除的节点。",
        "test_generation_notes": "覆盖有环与多层汇合的无环图，预期复杂度O(n+m)。",
        "translations": {
            "en": {
                "title": "Lock Dependency Cycle Detection",
                "description": (
                    "Model thread lock dependencies as a directed graph and detect a cycle."
                ),
                "input_description": (
                    "The first line contains n and m. Each following line u v means "
                    "thread u waits for thread v."
                ),
                "output_description": "Print YES when a directed cycle exists; otherwise NO.",
                "constraints": "1 <= n <= 200000, 0 <= m <= 300000",
                "hint": "Use topological sorting or directed-cycle detection.",
            }
        },
    }
    broken = copy.deepcopy(valid)
    broken["test_generator"] = 'print("not-json")\n'
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response(stream_bytes(broken if len(requests) == 1 else valid))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", requirement))
    assert final["status"] == "completed" and final["provider_calls"] == 2
    original = json.loads(requests[0]["messages"][1]["content"])
    assert original["requirement"] == requirement
    feedback = requests[1]["messages"][-1]["content"]
    assert "authoring_check:generator_json" in feedback
    assert "测试生成器未通过检查" in feedback
    assert final["result"]["quality"]["reference_checked"]
    assert final["result"]["quality"]["generated_cases"] == 2
    assert final["result"]["quality"]["checked_cases"] == 4


@pytest.mark.asyncio
async def test_persistently_invalid_generator_uses_reviewable_deterministic_fallback(
    services, config, problem
):
    broken = copy.deepcopy(problem)
    broken["test_generator"] = 'print("not-json")\n'
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return response(stream_bytes(broken))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "整数求和"))

    assert len(calls) == 3
    assert final["status"] == "completed" and final["provider_calls"] == 3
    assert final["result"]["quality"]["reference_checked"] is True
    assert final["result"]["quality"]["generated_cases"] == len(problem["testcases"])
    assert "系统安全回退" in final["result"]["test_generation_notes"]
    assert 'print("not-json")' not in final["result"]["test_generator"]


@pytest.mark.asyncio
async def test_generator_and_literal_answer_fallbacks_compose_after_bounded_retries(
    services, config, problem
):
    broken = copy.deepcopy(problem)
    broken["test_generator"] = 'print("not-json")\n'
    broken["testcases"][0]["output"] = "999\n"
    calls = []

    def handler(request):
        calls.append(request)
        return response(stream_bytes(broken))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "整数求和"))

    assert len(calls) == 3
    assert final["status"] == "completed" and final["provider_calls"] == 3
    assert final["result"]["testcases"][0]["output"].strip() == "0"
    assert "系统安全回退" in final["result"]["test_generation_notes"]
    assert "系统一致性回退" in final["result"]["validation_notes"]
    assert final["result"]["quality"]["reference_checked"] is True


@pytest.mark.asyncio
async def test_generator_fallback_discards_one_unexecutable_hidden_literal(
    services, config, problem
):
    broken = copy.deepcopy(problem)
    broken["reference_solution"] = (
        "import sys\n"
        "value = int(sys.stdin.read())\n"
        "if value == 13:\n"
        "    raise ValueError()\n"
        "print(value * 2)\n"
    )
    broken["samples"] = [{"input": "1\n", "output": "2\n"}]
    broken["testcases"] = [
        {"input": "1\n", "output": "2\n"},
        {"input": "2\n", "output": "4\n"},
        {"input": "3\n", "output": "6\n"},
        {"input": "13\n", "output": "26\n"},
    ]
    broken["test_generator"] = 'print("not-json")\n'
    calls = []

    def handler(request):
        calls.append(request)
        return response(stream_bytes(broken))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "边界求和"))

    assert len(calls) == 3
    assert final["status"] == "completed" and final["provider_calls"] == 3
    assert "13\n" not in {case["input"] for case in final["result"]["testcases"]}
    assert "单个测例" in final["result"]["validation_notes"]
    assert final["result"]["quality"]["reference_checked"] is True


@pytest.mark.asyncio
async def test_repeated_answer_mismatch_uses_reviewable_materialization_fallback(
    services, config, problem
):
    problem["testcases"][0]["output"] = "999"
    calls = []

    def handler(request):
        calls.append(request)
        return response(stream_bytes(problem))

    service = services(config, handler)
    final = await finished(service, await service.start("alice", "整数求和"))
    assert len(calls) == 3
    assert final["status"] == "completed" and final["error"] is None
    assert final["result"]["testcases"][0]["output"].strip() == "0"
    assert final["result"]["samples"][0]["output"].strip() == "3"
    assert "系统一致性回退" in final["result"]["validation_notes"]
    assert final["result"]["quality"]["reference_checked"] is True
    assert final["provider_calls"] == 3
    assert final["usage"]["total_tokens"] == 4500
    assert final["usage"]["cost"] == pytest.approx(0.018)


@pytest.mark.asyncio
async def test_cancel_during_checker_and_total_deadline(services, config, problem, monkeypatch):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def blocking_check(value, progress):
        progress("正在校验参考解与答案")
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(ai_module, "check_generated", blocking_check)
    service = services(config, lambda _: response(stream_bytes(problem)))
    task = await service.start("alice", "整数求和")
    await asyncio.wait_for(entered.wait(), 1)
    assert (await service.get(task["task_id"], "alice"))["progress"] == "正在校验参考解与答案"
    assert (await service.cancel(task["task_id"], "alice"))["status"] == "cancelled"
    assert cancelled.is_set()
    monkeypatch.setattr(ai_module, "TASK_TIMEOUT_SECONDS", 0.05)
    final = await finished(service, await service.start("alice", "整数求和"))
    assert final["status"] == "failed" and "超时" in final["error"]


@pytest.mark.asyncio
async def test_retry_does_not_reset_overall_deadline(services, config, problem, monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0.08)
        return response(stream_bytes(problem))

    async def reject(value, progress):
        raise APIError(400, "authoring_check:answer_mismatch:case=1")

    monkeypatch.setattr(ai_module, "check_generated", reject)
    monkeypatch.setattr(ai_module, "TASK_TIMEOUT_SECONDS", 0.13)
    service = services(config, handler)
    final = await finished(service, await service.start("alice", "整数求和"))
    assert len(calls) == 2 and final["status"] == "failed" and "超时" in final["error"]
    assert final["usage"]["incomplete"] and final["usage"]["cost"] >= 0
    assert final["error_code"] == "authoring_timeout" and final["retryable"]


@pytest.mark.asyncio
async def test_opt_in_candidate_evidence_excludes_configuration(
    services, config, problem, tmp_path
):
    problem["testcases"][0]["output"] = "999"
    service = services(
        config, lambda _: response(stream_bytes(problem)), evidence_directory=tmp_path
    )
    final = await finished(service, await service.start("alice", "整数求和"))
    assert final["status"] == "completed"
    artifacts = list(tmp_path.glob("*.json"))
    assert len(artifacts) == 3
    for path in artifacts:
        text = path.read_text(encoding="utf-8")
        assert config["api_key"] not in text and "alice" not in text
        assert set(json.loads(text)) == {"candidate", "check"}
