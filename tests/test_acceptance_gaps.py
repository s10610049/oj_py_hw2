"""Bounded course acceptance gaps through real ASGI routes and temporary SQLite.

The judge stub only supplies deterministic list/filter states. AIService remains
real with an injected, gated MockTransport: no DNS, model billing or env loading.
Clock replacement is local to oj.main; asyncio's process-wide clock is untouched.
"""

import asyncio
from contextlib import AsyncExitStack
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import time

import httpx
import pytest
import pytest_asyncio

import oj.main as main_module
from oj.ai import AIService

PROBLEM = {
    "id": "gap-a",
    "title": "独立验收求和",
    "description": "输出两个整数的和。",
    "input_description": "两个整数a和b。",
    "output_description": "输出a+b。",
    "constraints": "-10 <= a,b <= 10",
    "samples": [{"input": "1 2\n", "output": "3\n"}],
    "testcases": [{"input": "1 2\n", "output": "3\n"}],
}
MODEL_CONFIG = {
    "provider_url": "https://acceptance-model.example/v1",
    "model": "synthetic-model",
    "api_key": "synthetic-acceptance-key-not-a-credential",
}
AI_ROUTES = [
    ("GET", "/api/ai/model-config"),
    ("PUT", "/api/ai/model-config"),
    ("POST", "/api/ai/problem-tasks/"),
    ("GET", "/api/ai/problem-tasks/missing"),
    ("PUT", "/api/ai/problem-tasks/missing/cancel"),
]


def checked(response, status=200):
    assert response.status_code == status, response.text
    value = response.json()
    assert set(value) == {"code", "msg", "data"}
    assert value["code"] == status and isinstance(value["msg"], str)
    assert MODEL_CONFIG["api_key"] not in response.text
    if status != 200:
        assert value["data"] is None
    return value["data"]


async def login(client, username="admin", password="admintestpassword"):
    return checked(
        await client.post("/api/auth/login", json={"username": username, "password": password})
    )


@pytest_asyncio.fixture
async def api(tmp_path):
    application = main_module.create_app(
        tmp_path / "acceptance.sqlite3", bcrypt_rounds=4, ai_config={}
    )
    async with application.router.lifespan_context(application), AsyncExitStack() as stack:
        clients = {}
        for name in ("admin", "alice", "bob", "guest"):
            clients[name] = await stack.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
                    base_url="http://acceptance.test",
                )
            )
        users = {"admin": await login(clients["admin"])}
        for name in ("alice", "bob"):
            users[name] = checked(
                await clients[name].post(
                    "/api/users/", json={"username": name, "password": "fixture-password"}
                )
            )
            await login(clients[name], name, "fixture-password")
        for problem_id in ("gap-a", "gap-b"):
            checked(
                await clients["admin"].post("/api/problems/", json={**PROBLEM, "id": problem_id})
            )
        yield SimpleNamespace(app=application, clients=clients, users=users)


@pytest.fixture
def clock(monkeypatch):
    value = SimpleNamespace(wall=time.time(), tick=1000.0)
    # Replacing time.monotonic globally would also alter the event loop clock.
    monkeypatch.setattr(
        main_module, "time", SimpleNamespace(time=lambda: value.wall, monotonic=lambda: value.tick)
    )
    return value


@pytest.fixture
def deterministic_judge(monkeypatch):
    async def judge(problem, language, code):
        if code == "synthetic-error":
            return {"status": "error", "error_info": "Synthetic list-state fixture", "details": []}
        return {
            "status": "success",
            "score": 10,
            "counts": 10,
            "details": [{"testcase_index": 1, "result": "AC", "time": 0.001, "memory": 1}],
            "compile_info": None,
            "run_info": "Synthetic list-state fixture",
            "error_info": None,
        }

    monkeypatch.setattr("oj.judge.judge_submission", judge)


async def submit(api, owner="alice", problem_id="gap-a", code="print(3)", status=200):
    result = checked(
        await api.clients[owner].post(
            "/api/submissions/", json={"problem_id": problem_id, "language": "python", "code": code}
        ),
        status,
    )
    if status == 200:
        assert result["status"] == "pending"
        await asyncio.wait_for(asyncio.gather(*list(api.app.state.jobs.values())), 3)
        return result["submission_id"]
    return None


@pytest.mark.asyncio
async def test_rolling_quota_recovers_one_slot_at_each_60_second_boundary(
    api, clock, deterministic_judge
):
    # Failed requests do not consume quota under the frozen rolling-window contract.
    await submit(api, problem_id="missing", status=404)
    for stamp in (1000.0, 1010.0, 1020.0):
        clock.tick = stamp
        await submit(api)
    for stamp, status in (
        (1059.999, 429),
        (1060.0, 200),
        (1060.001, 429),
        (1070.0, 200),
        (1079.999, 429),
        (1080.0, 200),
    ):
        clock.tick = stamp
        await submit(api, status=status)
    # Quota is per user, not global, and rejected attempts created no submissions.
    await submit(api, owner="bob")
    result = checked(
        await api.clients["admin"].get(
            "/api/submissions/", params={"user_id": api.users["alice"]["user_id"]}
        )
    )
    assert result["total"] == len(result["submissions"]) == 6


@pytest.mark.asyncio
async def test_session_expiry_boundary_blocks_reads_and_writes_until_new_login(api, clock):
    alice = api.clients["alice"]
    await login(alice, "alice", "fixture-password")
    token = alice.cookies.get(main_module.COOKIE)
    session = await api.app.state.store.get("sessions", token)
    assert session["expires_at"] == clock.wall + main_module.SESSION_SECONDS
    clock.wall = session["expires_at"] - 0.001
    checked(await alice.get("/api/problems/"))
    for stamp in (session["expires_at"], session["expires_at"] + 1):
        clock.wall = stamp
        checked(await alice.get("/api/problems/"), 401)
        checked(await alice.post("/api/problems/", content=b"bad-json"), 401)
    assert len(await api.app.state.store.all("problems")) == 2
    await login(alice, "alice", "fixture-password")
    assert alice.cookies.get(main_module.COOKIE) != token
    assert await api.app.state.store.get("sessions", token) is None
    checked(await alice.get("/api/problems/"))


@pytest.mark.asyncio
async def test_submission_second_page_uses_filtered_total_and_newest_first(
    api, clock, deterministic_judge
):
    first = await submit(api)
    clock.tick += 1
    second = await submit(api)
    clock.tick += 1
    await submit(api, problem_id="gap-b")
    clock.tick += 60
    third = await submit(api)
    clock.tick += 1
    await submit(api, code="synthetic-error")
    await submit(api, owner="bob")
    params = {"user_id": api.users["alice"]["user_id"], "problem_id": "gap-a", "status": "success"}
    admin = api.clients["admin"]
    for paging, expected in (
        ({}, [third, second, first]),
        ({"page_size": 2}, [third, second]),
        ({"page": 2, "page_size": 2}, [first]),
        ({"page": 3, "page_size": 2}, []),
    ):
        result = checked(await admin.get("/api/submissions/", params={**params, **paging}))
        assert result["total"] == 3
        assert [item["submission_id"] for item in result["submissions"]] == expected
        assert all(item["status"] == "success" for item in result["submissions"])
    own = checked(await api.clients["bob"].get("/api/submissions/", params={"problem_id": "gap-a"}))
    assert own["total"] == 1 and own["submissions"][0]["user_id"] == api.users["bob"]["user_id"]


@pytest.mark.asyncio
async def test_user_second_page_retains_total_and_stable_registration_order(api):
    admin = api.clients["admin"]
    result = checked(await admin.get("/api/users/", params={"page": 2, "page_size": 2}))
    assert result["total"] == 3
    assert [user["user_id"] for user in result["users"]] == [api.users["bob"]["user_id"]]
    empty = checked(await admin.get("/api/users/", params={"page": 3, "page_size": 2}))
    assert empty == {"total": 3, "users": []}


@pytest.mark.asyncio
async def test_role_audit_persists_actor_target_timestamp_and_each_successful_change(api):
    before = datetime.now(timezone.utc).replace(microsecond=0)
    alice_id, bob_id = (api.users[name]["user_id"] for name in ("alice", "bob"))
    for actor, target, role in (("admin", alice_id, "admin"), ("alice", bob_id, "banned")):
        result = checked(
            await api.clients[actor].put(f"/api/users/{target}/role", json={"role": role})
        )
        assert result == {"user_id": target, "role": role}
        stored = await api.app.state.store.get("users", target)
        assert stored["role"] == role
    after = datetime.now(timezone.utc)
    records = await api.app.state.store.all("role_audit")
    assert len(records) == 2
    for record, expected in zip(
        records,
        (
            {"actor": "1", "user_id": alice_id, "role": "admin"},
            {"actor": alice_id, "user_id": bob_id, "role": "banned"},
        ),
    ):
        assert {key: record[key] for key in expected} == expected
        assert before <= datetime.fromisoformat(record["time"]) <= after
    checked(await api.clients["bob"].put(f"/api/users/{alice_id}/role", json={"role": "user"}), 403)
    checked(
        await api.clients["admin"].put(f"/api/users/{alice_id}/role", json={"role": "invalid"}), 400
    )
    assert await api.app.state.store.all("role_audit") == records


@pytest.mark.asyncio
async def test_access_audit_combines_filters_and_paginates_recorded_allowed_and_denied_reads(
    api, deterministic_judge
):
    first = await submit(api)
    second = await submit(api, problem_id="gap-b")
    before = datetime.now(timezone.utc).replace(microsecond=0)
    reads = [
        ("alice", first, 200),
        ("bob", second, 403),
        ("bob", first, 403),
        ("admin", first, 200),
        ("bob", first, 403),
    ]
    for actor, submission, status in reads:
        checked(await api.clients[actor].get(f"/api/submissions/{submission}/log"), status)
    checked(
        await api.clients["admin"].put(
            "/api/problems/gap-a/log_visibility", json={"public_cases": True}
        )
    )
    for submission, status in ((first, 200), (second, 403), (first, 200)):
        checked(await api.clients["bob"].get(f"/api/submissions/{submission}/log"), status)
    after = datetime.now(timezone.utc)
    admin = api.clients["admin"]
    bob_id = api.users["bob"]["user_id"]
    params = {"user_id": bob_id, "problem_id": "gap-a"}
    matches = checked(await admin.get("/api/logs/access/", params=params))
    assert len(matches) == 4 and [row["status"] for row in matches] == ["200", "200", "403", "403"]
    for row in matches:
        assert {key: row[key] for key in params} == params
        assert row["action"] == "view_logs"
        assert before <= datetime.fromisoformat(row["time"]) <= after
    for paging, expected in (
        ({"page_size": 2}, matches[:2]),
        ({"page": 2, "page_size": 2}, matches[2:]),
        ({"page": 3, "page_size": 2}, []),
    ):
        assert (
            checked(await admin.get("/api/logs/access/", params={**params, **paging})) == expected
        )
    assert len(checked(await admin.get("/api/logs/access/", params={"user_id": bob_id}))) == 6
    assert len(checked(await admin.get("/api/logs/access/", params={"problem_id": "gap-a"}))) == 6
    assert len(checked(await admin.get("/api/logs/access/"))) == 8
    assert (
        checked(await admin.get("/api/logs/access/", params={**params, "problem_id": "missing"}))
        == []
    )
    checked(await api.clients["bob"].get("/api/logs/access/", params={"page": "invalid"}), 403)
    checked(await api.clients["guest"].get("/api/logs/access/", params={"page": "invalid"}), 401)
    for query in ({"page": 1}, {"page": "invalid", "page_size": 2}, {"page_size": 0}):
        checked(await admin.get("/api/logs/access/", params=query), 400)
    assert len(checked(await admin.get("/api/logs/access/"))) == 8


@pytest.mark.asyncio
async def test_log_visibility_error_priority_and_missing_log_have_no_access_records(api):
    path = "/api/problems/missing/log_visibility"
    for actor, status in (("guest", 401), ("bob", 403), ("admin", 400)):
        checked(await api.clients[actor].put(path, json={"public_cases": "yes"}), status)
    checked(await api.clients["admin"].put(path, json={"public_cases": False}), 404)
    for actor, status in (("guest", 401), ("alice", 404), ("admin", 404)):
        checked(await api.clients[actor].get("/api/submissions/missing/log"), status)
    assert await api.app.state.store.all("access") == []


class PausedStream(httpx.AsyncByteStream):
    def __init__(self):
        self.reading = asyncio.Event()
        self.cancelled = False
        self.closed = False

    async def __aiter__(self):
        try:
            yield b'data: {"choices":[{"delta":{"content":"{"}}]}\n\n'
            self.reading.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self):
        self.closed = True


@pytest_asyncio.fixture
async def model_api(api):
    streams = []

    def response(request):
        assert str(request.url) == MODEL_CONFIG["provider_url"] + "/chat/completions"
        assert request.headers["authorization"] == "Bearer " + MODEL_CONFIG["api_key"]
        stream = PausedStream()
        streams.append(stream)
        return httpx.Response(200, stream=stream, headers={"content-type": "text/event-stream"})

    await api.app.state.ai.close()
    service = AIService(transport=httpx.MockTransport(response))
    api.app.state.ai = service
    yield api, streams
    await service.close()


@pytest.mark.parametrize("method,path", AI_ROUTES)
@pytest.mark.asyncio
async def test_ai_http_anonymous_is_401_before_invalid_body_or_missing_resource(
    model_api, method, path
):
    api, streams = model_api
    checked(await api.clients["guest"].request(method, path, content=b"not-json"), 401)
    assert not streams


@pytest.mark.parametrize("method,path", AI_ROUTES)
@pytest.mark.asyncio
async def test_ai_http_banned_session_is_403_before_invalid_body_or_missing_resource(
    model_api, method, path
):
    api, streams = model_api
    checked(
        await api.clients["admin"].put(
            f"/api/users/{api.users['bob']['user_id']}/role", json={"role": "banned"}
        )
    )
    checked(await api.clients["bob"].request(method, path, content=b"not-json"), 403)
    assert not streams


@pytest.mark.asyncio
async def test_ai_http_configuration_is_user_scoped_and_missing_reference_is_404(model_api):
    api, streams = model_api
    alice, bob = api.clients["alice"], api.clients["bob"]
    configured = checked(await alice.put("/api/ai/model-config", json=deepcopy(MODEL_CONFIG)))
    assert configured["model"] == MODEL_CONFIG["model"] and configured["api_key_configured"]
    assert checked(await alice.get("/api/ai/model-config")) == configured
    other = checked(await bob.get("/api/ai/model-config"))
    assert not other["api_key_configured"] and other["model"] != MODEL_CONFIG["model"]
    checked(await alice.put("/api/ai/model-config", content=b"bad-json"), 400)
    checked(await alice.post("/api/ai/problem-tasks/", json={"requirement": ""}), 400)
    checked(
        await alice.post(
            "/api/ai/problem-tasks/", json={"requirement": "入门整数运算", "problem_id": "missing"}
        ),
        404,
    )
    assert not streams and not api.app.state.ai._tasks


@pytest.mark.parametrize("cancel_actor", ["alice", "admin"])
@pytest.mark.asyncio
async def test_ai_http_owner_admin_cancellation_closes_stream_and_terminal_is_409(
    model_api, cancel_actor
):
    api, streams = model_api
    checked(await api.clients["alice"].put("/api/ai/model-config", json=MODEL_CONFIG))
    request = {"requirement": "入门整数运算"}
    if cancel_actor == "admin":
        request["problem_id"] = "gap-a"
    created = checked(await api.clients["alice"].post("/api/ai/problem-tasks/", json=request))
    assert created["status"] == "pending"
    task_id = created["task_id"]
    path = f"/api/ai/problem-tasks/{task_id}"

    # Wait for real HTTP consumption without replacing start/get/cancel or auth.
    async def reading():
        while not streams:
            await asyncio.sleep(0)
        await streams[0].reading.wait()

    await asyncio.wait_for(reading(), 3)
    for name in ("alice", "admin"):
        assert checked(await api.clients[name].get(path))["status"] == "running"
    for name, status in (("guest", 401), ("bob", 403)):
        checked(await api.clients[name].get(path), status)
        checked(await api.clients[name].put(path + "/cancel"), status)
    assert not streams[0].closed
    result = checked(await api.clients[cancel_actor].put(path + "/cancel"))
    assert result["status"] == "cancelled"
    assert streams[0].closed and streams[0].cancelled
    assert api.app.state.ai._tasks[task_id].future.done()
    for name in ("alice", "admin"):
        assert checked(await api.clients[name].get(path))["status"] == "cancelled"
        checked(await api.clients[name].put(path + "/cancel"), 409)
        checked(await api.clients[name].get("/api/ai/problem-tasks/missing"), 404)
        checked(await api.clients[name].put("/api/ai/problem-tasks/missing/cancel"), 404)
    # Ownership still wins over terminal-state disclosure for another normal user.
    checked(await api.clients["bob"].get(path), 403)
    checked(await api.clients["bob"].put(path + "/cancel"), 403)
    assert len(streams) == 1
