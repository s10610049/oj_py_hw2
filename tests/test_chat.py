"""Programming chat tests use synthetic transports and never contact a provider."""

import asyncio
import copy
import json

import httpx
import pytest
import pytest_asyncio

import oj.chat as chat_module
from oj.chat import (
    CONTEXT_SCHEMA,
    IDEMPOTENCY_NAMESPACE,
    IDEMPOTENCY_SCHEMA,
    INTRODUCTION,
    SESSION_NAMESPACE,
    SESSION_SCHEMA,
    SYSTEM_PROMPT,
    TURN_NAMESPACE,
    TURN_SCHEMA,
    ChatError,
    ProgrammingChatService,
    build_programming_context,
    normalize_programming_context,
)
from oj.progress import build_progress_snapshot
from oj.store import Store

OWNER = "student"
EPOCH = "a" * 64
MODEL_SECRET = "synthetic-chat-secret-only"


def context(epoch=EPOCH):
    return {
        "schema_version": CONTEXT_SCHEMA,
        "context_epoch": epoch,
        "summary": {
            "catalog_problem_count": 2,
            "submission_count": 3,
            "earned_score": 70,
            "available_score": 200,
            "attempted_count": 2,
            "passed_count": 1,
            "pass_rate": 0.5,
        },
        "problems": [
            {
                "problem_id": "P1",
                "title": "两数之和",
                "state": "passed",
                "latest_outcome": "accepted",
                "version_unknown": False,
                "available_score": 100,
                "best_score": 100,
                "difficulty_id": "beginner",
                "difficulty_label": "入门",
                "tags": ["数组", "哈希表"],
            },
            {
                "problem_id": "P2",
                "title": "最短路",
                "state": "partial",
                "latest_outcome": "partial",
                "version_unknown": False,
                "available_score": 100,
                "best_score": 20,
                "difficulty_id": "advanced",
                "difficulty_label": "进阶",
                "tags": ["图论"],
            },
        ],
    }


def model_config():
    return {
        "provider_url": "https://models.example/v1",
        "model": "synthetic-model",
        "api_key": MODEL_SECRET,
    }


def event(value):
    return ("data: " + json.dumps(value, ensure_ascii=False) + "\n\n").encode("utf-8")


def delta(text, finish=None):
    return event({"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]})


def answer_stream(text="先确认输入边界，再选择合适的数据结构。"):
    middle = max(1, len(text) // 2)
    return delta(text[:middle]) + delta(text[middle:], "stop") + b"data: [DONE]\n\n"


def response(body, status=200, *, text=None):
    headers = {"content-type": "text/event-stream"}
    return httpx.Response(status, content=body if text is None else text, headers=headers)


class GatedStream(httpx.AsyncByteStream):
    def __init__(self, first=b"", rest=b""):
        self.first = first
        self.rest = rest
        self.first_sent = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False
        self.cancelled = False

    async def __aiter__(self):
        try:
            if self.first:
                yield self.first
            self.first_sent.set()
            await self.release.wait()
            if self.rest:
                yield self.rest
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self):
        self.closed = True


@pytest_asyncio.fixture
async def environment(tmp_path):
    store = Store(tmp_path / "chat.sqlite3")
    await store.initialize()
    services = []

    def create(handler=None):
        transport = httpx.MockTransport(handler) if handler is not None else None
        service = ProgrammingChatService(store, transport=transport)
        services.append(service)
        return service

    yield store, create
    for service in reversed(services):
        await service.close()


async def wait_terminal(service, turn_id, owner=OWNER):
    for _ in range(300):
        turn = await service.get_turn(turn_id, owner)
        if turn["status"] in {"completed", "cancelled", "failed"}:
            return turn
        await asyncio.sleep(0.01)
    raise AssertionError("chat turn did not become terminal")


async def start_turn(service, session_id, *, key="turn-key", **updates):
    values = {
        "session_id": session_id,
        "owner": OWNER,
        "message": "我在最短路状态设计上卡住了，应该先检查什么？",
        "expected_context_epoch": EPOCH,
        "context": context(),
        "config": model_config(),
        "idempotency_key": key,
    }
    values.update(updates)
    return await service.create_turn(**values)


@pytest.mark.asyncio
async def test_session_intro_once_list_read_persist_and_owner_only(environment):
    store, create = environment
    service = create()
    session = await service.create_session(OWNER, "图论答疑")
    assert session["schema_version"] == SESSION_SCHEMA
    assert [message["content"] for message in session["messages"]] == [INTRODUCTION]
    assert session["messages"][0]["role"] == "assistant"
    listed = await service.list_sessions(OWNER)
    assert listed[0]["session_id"] == session["session_id"]
    assert "messages" not in listed[0] and listed[0]["message_count"] == 1
    assert (await service.get_session(session["session_id"], OWNER))["messages"] == session[
        "messages"
    ]
    for method in (service.get_session, service.list_turns, service.delete_session):
        with pytest.raises(ChatError) as caught:
            await method(session["session_id"], "admin")
        assert caught.value.status == 404 and caught.value.error_code == "chat_session_not_found"

    await service.close()
    restarted = ProgrammingChatService(
        store, transport=httpx.MockTransport(lambda _: response(b""))
    )
    recovered = await restarted.get_session(session["session_id"], OWNER)
    assert len(recovered["messages"]) == 1 and recovered["messages"][0]["content"] == INTRODUCTION
    await restarted.close()


def test_context_builder_whitelists_progress_and_rejects_unsafe_direct_fields():
    safe = context()
    problem = {**safe["problems"][0], "source_code": "print('secret')", "testcases": [1]}
    stats = {
        "schema_version": "oj.learning-stats.v1",
        "context_epoch": EPOCH,
        "scope": {
            "user_id": OWNER,
            "catalog_problem_count": 1,
            "submission_count": 4,
        },
        "kpis": {
            "earned_score": 100,
            "available_score": 100,
            "attempted_count": 1,
            "passed_count": 1,
            "pass_rate": 1.0,
        },
        "problems": [problem],
        "hidden_testcases": ["never"],
    }
    statuses = {
        "schema_version": "oj.problem-status.v1",
        "context_epoch": EPOCH,
        "items": [],
    }
    projected = build_programming_context(statuses, stats)
    encoded = json.dumps(projected, ensure_ascii=False)
    assert "source_code" not in encoded and "testcases" not in encoded
    assert OWNER not in encoded and projected["summary"]["submission_count"] == 4

    unsafe = copy.deepcopy(projected)
    unsafe["problems"][0]["reference_solution"] = "secret"
    with pytest.raises(ChatError) as caught:
        normalize_programming_context(unsafe)
    assert caught.value.error_code == "unsafe_chat_context"


def test_context_builder_accepts_real_empty_progress_projection():
    problem = {
        "id": "P0",
        "title": "初次练习",
        "description": "输出输入的整数。",
        "input_description": "一个整数。",
        "output_description": "原样输出。",
        "constraints": "0 <= n <= 10",
        "samples": [{"input": "1\n", "output": "1\n"}],
        "testcases": [{"input": "0\n", "output": "0\n"}],
        "time_limit": 1,
        "memory_limit": 128,
        "difficulty": "",
        "tags": [],
    }
    progress = build_progress_snapshot([problem], [], OWNER, generated_at="2026-09-09T00:00:00Z")
    projected = build_programming_context(progress["statuses"], progress["stats"])
    assert projected["summary"]["pass_rate"] is None
    assert projected["problems"][0]["difficulty_id"] is None
    assert projected["problems"][0]["state"] == "unattempted"


@pytest.mark.asyncio
async def test_epoch_mismatch_is_409_before_any_provider_request(environment):
    _, create = environment
    requests = []
    service = create(lambda request: requests.append(request))
    session = await service.create_session(OWNER)
    with pytest.raises(ChatError) as caught:
        await start_turn(
            service,
            session["session_id"],
            expected_context_epoch="b" * 64,
        )
    assert caught.value.status == 409
    assert caught.value.error_code == "context_epoch_mismatch" and caught.value.retryable
    assert not requests and await service.list_turns(session["session_id"], OWNER) == []
    assert len((await service.get_session(session["session_id"], OWNER))["messages"]) == 1


@pytest.mark.asyncio
async def test_partial_progress_completion_history_and_safe_provider_payload(environment):
    store, create = environment
    stream = GatedStream(
        delta("先画出状态图。"),
        delta("再检查松弛条件。", "stop") + b"data: [DONE]\n\n",
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    service = create(handler)
    session = await service.create_session(OWNER)
    turn = await start_turn(service, session["session_id"])
    await asyncio.wait_for(stream.first_sent.wait(), 1)
    for _ in range(100):
        progress = await service.get_turn(turn["turn_id"], OWNER)
        if progress["partial"]:
            break
        await asyncio.sleep(0.01)
    assert progress["status"] == "running" and progress["partial"] == "先画出状态图。"
    assert "已接收" in progress["progress"] and progress["result"] is None
    stream.release.set()
    final = await wait_terminal(service, turn["turn_id"])
    assert final["status"] == "completed"
    assert final["result"] == "先画出状态图。再检查松弛条件。"
    assert final["partial"] == final["result"] and final["provider_calls"] == 1
    history = (await service.get_session(session["session_id"], OWNER))["messages"]
    assert [message["role"] for message in history] == ["assistant", "user", "assistant"]
    assert history[-1]["content"] == final["result"]
    with pytest.raises(ChatError) as caught:
        await service.get_turn(turn["turn_id"], "admin")
    assert caught.value.status == 404 and caught.value.error_code == "chat_turn_not_found"

    payload = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://models.example/v1/chat/completions"
    assert payload["stream"] and payload["max_tokens"] == chat_module.MAX_OUTPUT_TOKENS
    assert payload["messages"][0]["content"] == SYSTEM_PROMPT
    context_payload = payload["messages"][1]["content"]
    assert CONTEXT_SCHEMA in context_payload and "source_code" not in context_payload
    assert "testcases" not in context_payload and OWNER not in context_payload
    assert MODEL_SECRET not in requests[0].content.decode("utf-8")

    persisted = await store.snapshot(SESSION_NAMESPACE, TURN_NAMESPACE, IDEMPOTENCY_NAMESPACE)
    stored_text = json.dumps(persisted, ensure_ascii=False)
    assert MODEL_SECRET not in stored_text and "安全学习上下文" not in stored_text
    assert "turn-key" not in stored_text


@pytest.mark.asyncio
async def test_deepseek_chat_disables_thinking_for_fast_tutoring(environment):
    _, create = environment
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response(answer_stream())

    service = create(handler)
    session = await service.create_session(OWNER)
    turn = await start_turn(
        service,
        session["session_id"],
        config={**model_config(), "provider_url": "https://api.deepseek.com"},
    )
    assert (await wait_terminal(service, turn["turn_id"]))["status"] == "completed"
    assert requests[0]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_idempotent_parallel_retry_is_one_turn_and_changed_payload_conflicts(environment):
    _, create = environment
    stream = GatedStream(rest=answer_stream())
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    service = create(handler)
    session = await service.create_session(OWNER)
    first, repeated = await asyncio.gather(
        start_turn(service, session["session_id"], key="same-key"),
        start_turn(service, session["session_id"], key="same-key"),
    )
    assert first["turn_id"] == repeated["turn_id"]
    with pytest.raises(ChatError) as caught:
        await start_turn(
            service,
            session["session_id"],
            key="same-key",
            message="另一条消息",
        )
    assert caught.value.error_code == "idempotency_conflict"
    stream.release.set()
    await wait_terminal(service, first["turn_id"])
    assert len(calls) == 1
    history = (await service.get_session(session["session_id"], OWNER))["messages"]
    assert sum(message["role"] == "user" for message in history) == 1


@pytest.mark.asyncio
async def test_idempotency_and_completed_history_survive_service_restart(environment):
    store, create = environment
    service = create(lambda _: response(answer_stream()))
    session = await service.create_session(OWNER)
    original = await start_turn(service, session["session_id"], key="persistent-key")
    completed = await wait_terminal(service, original["turn_id"])
    await service.close()

    requests = []
    restarted = ProgrammingChatService(
        store, transport=httpx.MockTransport(lambda request: requests.append(request))
    )
    repeated = await start_turn(
        restarted,
        session["session_id"],
        key="persistent-key",
    )
    assert repeated == completed and not requests
    history = (await restarted.get_session(session["session_id"], OWNER))["messages"]
    assert [message["role"] for message in history] == ["assistant", "user", "assistant"]
    await restarted.close()


@pytest.mark.asyncio
async def test_concurrent_distinct_turn_is_rejected_until_first_finishes(environment):
    _, create = environment
    stream = GatedStream(rest=answer_stream())
    service = create(
        lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
    )
    session = await service.create_session(OWNER)
    first = await start_turn(service, session["session_id"], key="first")
    with pytest.raises(ChatError) as caught:
        await start_turn(service, session["session_id"], key="second")
    assert caught.value.status == 409 and caught.value.error_code == "chat_turn_in_progress"
    stream.release.set()
    await wait_terminal(service, first["turn_id"])


@pytest.mark.asyncio
async def test_cancel_closes_real_stream_and_keeps_partial_without_assistant_message(environment):
    _, create = environment
    stream = GatedStream(delta("第一步先缩小问题。"))
    service = create(
        lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
    )
    session = await service.create_session(OWNER)
    turn = await start_turn(service, session["session_id"])
    await asyncio.wait_for(stream.first_sent.wait(), 1)
    for _ in range(100):
        current = await service.get_turn(turn["turn_id"], OWNER)
        if current["partial"]:
            break
        await asyncio.sleep(0.01)
    cancelled = await service.cancel_turn(turn["turn_id"], OWNER)
    assert cancelled["status"] == "cancelled" and cancelled["partial"]
    assert cancelled["result"] is None and stream.closed and stream.cancelled
    history = (await service.get_session(session["session_id"], OWNER))["messages"]
    assert [message["role"] for message in history] == ["assistant", "user"]
    with pytest.raises(ChatError) as caught:
        await service.cancel_turn(turn["turn_id"], OWNER)
    assert caught.value.error_code == "chat_turn_already_ended"


@pytest.mark.asyncio
async def test_provider_failure_and_secret_output_are_sanitized_and_not_persisted(environment):
    store, create = environment
    private_body = MODEL_SECRET + " internal stack trace"
    service = create(lambda _: response(b"", 500, text=private_body))
    session = await service.create_session(OWNER)
    final = await wait_terminal(
        service, (await start_turn(service, session["session_id"]))["turn_id"]
    )
    assert final["status"] == "failed" and final["error_code"] == "provider_http_error"
    assert final["retryable"] and MODEL_SECRET not in json.dumps(final, ensure_ascii=False)

    second = create(lambda _: response(answer_stream("回答中包含" + MODEL_SECRET)))
    second_session = await second.create_session("second-owner")
    second_turn = await second.create_turn(
        second_session["session_id"],
        "second-owner",
        "请解释循环不变量",
        expected_context_epoch=EPOCH,
        context=context(),
        config=model_config(),
        idempotency_key="secret-output",
    )
    blocked = await wait_terminal(second, second_turn["turn_id"], "second-owner")
    assert blocked["status"] == "failed"
    assert blocked["error_code"] == "sensitive_provider_output"
    assert blocked["result"] is None and MODEL_SECRET not in blocked["partial"]
    stored = json.dumps(await store.snapshot(SESSION_NAMESPACE, TURN_NAMESPACE), ensure_ascii=False)
    assert MODEL_SECRET not in stored


@pytest.mark.asyncio
async def test_message_containing_configured_secret_is_rejected_without_request(environment):
    _, create = environment
    requests = []
    service = create(lambda request: requests.append(request))
    session = await service.create_session(OWNER)
    with pytest.raises(ChatError) as caught:
        await start_turn(
            service,
            session["session_id"],
            message="不要发送这个密钥：" + MODEL_SECRET,
        )
    assert caught.value.error_code == "sensitive_content" and not requests


@pytest.mark.asyncio
async def test_running_turn_is_failed_safely_on_restart_recovery(environment):
    store, create = environment
    service = create()
    session = await service.create_session(OWNER)
    turn_id = "persisted-running-turn"
    running = {
        "schema_version": TURN_SCHEMA,
        "turn_id": turn_id,
        "session_id": session["session_id"],
        "owner": OWNER,
        "request_hash": "0" * 64,
        "user_message_id": "message",
        "expected_context_epoch": EPOCH,
        "status": "running",
        "progress": "正在生成",
        "partial": "已生成一部分",
        "result": None,
        "error": None,
        "error_code": None,
        "retryable": None,
        "created_at": "2026-09-09T00:00:00Z",
        "started_at": "2026-09-09T00:00:01Z",
        "ended_at": None,
        "provider_calls": 1,
    }
    await store.put(TURN_NAMESPACE, turn_id, running)
    restarted = ProgrammingChatService(
        store, transport=httpx.MockTransport(lambda _: response(b""))
    )
    recovered = await restarted.get_turn(turn_id, OWNER)
    assert recovered["status"] == "failed" and recovered["partial"] == "已生成一部分"
    assert recovered["error_code"] == "service_restarted" and recovered["retryable"]
    await restarted.close()


@pytest.mark.asyncio
async def test_delete_session_removes_history_turn_and_idempotency(environment):
    store, create = environment
    service = create(lambda _: response(answer_stream()))
    session = await service.create_session(OWNER)
    turn = await start_turn(service, session["session_id"], key="delete-key")
    await wait_terminal(service, turn["turn_id"])
    assert await service.delete_session(session["session_id"], OWNER) == {
        "session_id": session["session_id"],
        "deleted": True,
    }
    for namespace in (SESSION_NAMESPACE, TURN_NAMESPACE, IDEMPOTENCY_NAMESPACE):
        assert await store.all(namespace) == []
    with pytest.raises(ChatError) as caught:
        await service.get_session(session["session_id"], OWNER)
    assert caught.value.status == 404


@pytest.mark.asyncio
async def test_delete_active_session_cancels_stream_before_removing_records(environment):
    store, create = environment
    stream = GatedStream()
    service = create(
        lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
    )
    session = await service.create_session(OWNER)
    await start_turn(service, session["session_id"], key="active-delete")
    await asyncio.wait_for(stream.first_sent.wait(), 1)
    await service.delete_session(session["session_id"], OWNER)
    assert stream.closed and stream.cancelled
    for namespace in (SESSION_NAMESPACE, TURN_NAMESPACE, IDEMPOTENCY_NAMESPACE):
        assert await store.all(namespace) == []


@pytest.mark.asyncio
async def test_timeout_is_total_and_closes_stream(environment, monkeypatch):
    _, create = environment
    stream = GatedStream()
    service = create(
        lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
    )
    monkeypatch.setattr(chat_module, "TURN_TIMEOUT_SECONDS", 0.03)
    session = await service.create_session(OWNER)
    turn = await start_turn(service, session["session_id"])
    final = await wait_terminal(service, turn["turn_id"])
    assert final["status"] == "failed" and final["error_code"] == "chat_timeout"
    assert final["retryable"] and stream.closed and stream.cancelled


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "error_code"),
    [
        (b"data: not-json\n\n", "provider_protocol_error"),
        (delta("没有结束"), "provider_stream_incomplete"),
        (b"data: [DONE]\n\n", "provider_stream_incomplete"),
    ],
)
async def test_malformed_or_incomplete_stream_fails_closed(environment, body, error_code):
    _, create = environment
    service = create(lambda _: response(body))
    session = await service.create_session(OWNER)
    turn = await start_turn(service, session["session_id"])
    final = await wait_terminal(service, turn["turn_id"])
    assert final["status"] == "failed" and final["result"] is None
    assert final["error_code"] == error_code and final["retryable"]


@pytest.mark.asyncio
async def test_stream_and_output_limits_fail_closed(environment, monkeypatch):
    _, create = environment
    monkeypatch.setattr(chat_module, "MAX_OUTPUT_BYTES", 8)
    service = create(lambda _: response(answer_stream("回答明显超过八个字节")))
    session = await service.create_session(OWNER)
    turn = await start_turn(service, session["session_id"])
    final = await wait_terminal(service, turn["turn_id"])
    assert final["error_code"] == "provider_output_too_large" and final["result"] is None

    monkeypatch.setattr(chat_module, "MAX_STREAM_BYTES", 32)
    second = create(lambda _: response(b"data: " + b"x" * 100))
    second_session = await second.create_session("second-owner")
    second_turn = await second.create_turn(
        second_session["session_id"],
        "second-owner",
        "解释队列",
        expected_context_epoch=EPOCH,
        context=context(),
        config=model_config(),
        idempotency_key="wire-limit",
    )
    blocked = await wait_terminal(second, second_turn["turn_id"], "second-owner")
    assert blocked["error_code"] == "provider_stream_too_large"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_url",
    [
        "http://models.example",
        "https://127.0.0.1",
        "https://localhost",
        "https://user:password@models.example",
        "https://models.example?secret=value",
    ],
)
async def test_unsafe_provider_config_is_rejected_without_request(environment, provider_url):
    _, create = environment
    requests = []
    service = create(lambda request: requests.append(request))
    session = await service.create_session(OWNER)
    with pytest.raises(ChatError) as caught:
        await start_turn(
            service,
            session["session_id"],
            config={**model_config(), "provider_url": provider_url},
        )
    assert caught.value.error_code == "invalid_model_config" and not requests


def test_context_contract_requires_complete_unique_catalog_and_finite_scores():
    invalid = context()
    invalid["problems"] = invalid["problems"][:1]
    with pytest.raises(ChatError) as caught:
        normalize_programming_context(invalid)
    assert caught.value.error_code == "invalid_chat_context"
    invalid = context()
    invalid["summary"]["pass_rate"] = float("nan")
    with pytest.raises(ChatError):
        normalize_programming_context(invalid)

    empty = context()
    empty["summary"].update(
        catalog_problem_count=0,
        submission_count=0,
        earned_score=0,
        available_score=0,
        attempted_count=0,
        passed_count=0,
        pass_rate=None,
    )
    empty["problems"] = []
    assert normalize_programming_context(empty)["summary"]["pass_rate"] is None

    unrated = context()
    unrated["problems"][0]["difficulty_id"] = None
    assert normalize_programming_context(unrated)["problems"][0]["difficulty_id"] is None


def test_persistence_schema_constants_are_stable():
    assert SESSION_SCHEMA.endswith(".v1") and TURN_SCHEMA.endswith(".v1")
    assert IDEMPOTENCY_SCHEMA.endswith(".v1") and CONTEXT_SCHEMA.endswith(".v1")
