"""Permanent regressions for independently reproduced async lifecycle defects."""

import asyncio
import json
import sqlite3
import threading

import httpx
import pytest
import pytest_asyncio

from oj.main import create_app

PROBLEM = {
    "id": "race",
    "title": "Lifecycle",
    "description": "test",
    "input_description": "none",
    "output_description": "one",
    "constraints": "none",
    "samples": [{"input": "", "output": "1"}],
    "testcases": [{"input": "", "output": "1"}],
}
JUDGMENT = {
    "status": "success",
    "score": 10,
    "counts": 10,
    "details": [],
    "compile_info": None,
    "run_info": None,
    "error_info": None,
}


@pytest_asyncio.fixture
async def context(tmp_path):
    app = create_app(tmp_path / "state.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            assert (
                await client.post(
                    "/api/auth/login", json={"username": "admin", "password": "admintestpassword"}
                )
            ).status_code == 200
            assert (await client.post("/api/problems/", json=PROBLEM)).status_code == 200
            yield client, app


async def submit(client):
    result = await client.post(
        "/api/submissions/", json={"problem_id": "race", "language": "python", "code": "print(1)"}
    )
    assert result.status_code == 200
    return result.json()["data"]["submission_id"]


@pytest.mark.asyncio
async def test_reset_waits_for_cancelled_sqlite_write(context, monkeypatch):
    client, app = context
    ready, release = threading.Event(), threading.Event()
    connect = sqlite3.connect

    class BlockedWrite(sqlite3.Connection):
        def execute(self, sql, args=()):
            if (
                sql.startswith("INSERT INTO documents")
                and args[0] == "submissions"
                and json.loads(args[2])["status"] == "success"
            ):
                ready.set()
                assert release.wait(5)
            return super().execute(sql, args)

    monkeypatch.setattr(
        "oj.store.sqlite3.connect",
        lambda *args, **kwargs: connect(*args, factory=BlockedWrite, **kwargs),
    )

    async def instant(*args):
        return JUDGMENT

    monkeypatch.setattr("oj.judge.judge_submission", instant)
    await submit(client)
    assert await asyncio.to_thread(ready.wait, 3)
    resetting = asyncio.create_task(client.post("/api/reset/"))
    try:
        await asyncio.sleep(0.08)
        assert not resetting.done(), "reset must await the in-flight write transaction"
    finally:
        release.set()
    assert (await resetting).status_code == 200
    assert await app.state.store.all("submissions") == []
    await asyncio.sleep(0.05)
    assert await app.state.store.all("submissions") == []


@pytest.mark.asyncio
async def test_concurrent_rejudges_have_no_untracked_workers(context, monkeypatch):
    client, app = context
    active = set()

    async def waiting(*args):
        current = asyncio.current_task()
        active.add(current)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.02)
            raise
        finally:
            active.discard(current)

    monkeypatch.setattr("oj.judge.judge_submission", waiting)
    key = await submit(client)
    await asyncio.sleep(0.02)
    results = await asyncio.gather(
        *[client.put(f"/api/submissions/{key}/rejudge") for _ in range(2)]
    )
    assert all(r.status_code == 200 for r in results)
    await asyncio.sleep(0.02)
    assert len(active) == len(app.state.jobs) == 1
    assert (await client.post("/api/reset/")).status_code == 200
    assert not active and not app.state.jobs


@pytest.mark.asyncio
async def test_missing_rejudge_dependency_does_not_cancel_original(context, monkeypatch):
    client, app = context
    release = asyncio.Event()

    async def waiting(*args):
        await release.wait()
        return JUDGMENT

    monkeypatch.setattr("oj.judge.judge_submission", waiting)
    key = await submit(client)
    assert (await client.delete("/api/problems/race")).status_code == 200
    assert (await client.put(f"/api/submissions/{key}/rejudge")).status_code == 404
    assert key in app.state.jobs and not app.state.jobs[key].done()
    release.set()
    await asyncio.gather(*app.state.jobs.values())
    assert (await app.state.store.get("submissions", key))["status"] == "success"


@pytest.mark.asyncio
async def test_reset_invalidates_authenticated_delayed_body(context):
    client, app = context
    ready, release = asyncio.Event(), asyncio.Event()

    async def delayed_body():
        ready.set()
        await release.wait()
        yield json.dumps({**PROBLEM, "id": "late"}).encode()

    creating = asyncio.create_task(client.post("/api/problems/", content=delayed_body()))
    await ready.wait()
    resetting = asyncio.create_task(client.post("/api/reset/"))
    assert (await asyncio.wait_for(resetting, 1)).status_code == 200
    release.set()
    assert (await creating).status_code == 401
    assert await app.state.store.all("problems") == []


@pytest.mark.asyncio
async def test_slow_anonymous_upload_does_not_block_ai_cancel(context, monkeypatch):
    client, app = context
    ready, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def slow_body():
        ready.set()
        await release.wait()
        yield b"{}"

    async def cancel(*args):
        cancelled.set()
        return {"status": "cancelled"}

    monkeypatch.setattr(app.state.ai, "cancel", cancel)
    uploading = asyncio.create_task(client.post("/api/users/", content=slow_body()))
    try:
        await ready.wait()
        result = await asyncio.wait_for(client.put("/api/ai/problem-tasks/test/cancel"), 1)
        assert result.status_code == 200 and cancelled.is_set()
        assert not uploading.done()
    finally:
        release.set()
        await uploading


@pytest.mark.asyncio
async def test_slow_model_configuration_does_not_block_cancel_or_reset(context, monkeypatch):
    client, app = context
    ready, release = asyncio.Event(), asyncio.Event()

    async def configure(*args):
        ready.set()
        await release.wait()
        return {"model": "discarded-old-generation"}

    async def cancel(*args):
        return {"status": "cancelled"}

    monkeypatch.setattr(app.state.ai, "configure", configure)
    monkeypatch.setattr(app.state.ai, "cancel", cancel)
    configuring = asyncio.create_task(client.put("/api/ai/model-config", json={}))
    try:
        await ready.wait()
        assert (
            await asyncio.wait_for(client.put("/api/ai/problem-tasks/test/cancel"), 1)
        ).status_code == 200
        assert (await asyncio.wait_for(client.post("/api/reset/"), 1)).status_code == 200
    finally:
        release.set()
    assert (await configuring).status_code == 409


@pytest.mark.parametrize("field", ["title", "description", "constraints"])
@pytest.mark.asyncio
async def test_unpaired_surrogate_is_bad_request(context, field):
    client, _ = context
    raw = json.dumps({**PROBLEM, field: "\ud800"}, ensure_ascii=True).encode()
    result = await client.post("/api/problems/", content=raw)
    assert result.status_code == 400


@pytest.mark.asyncio
async def test_deep_json_is_bad_request(context):
    client, _ = context
    raw = b'{"unused":' + b"[" * 10000 + b"0" + b"]" * 10000 + b"}"
    result = await client.post("/api/users/", content=raw)
    assert result.status_code == 400


@pytest.mark.asyncio
async def test_visibility_exact_message(context):
    client, _ = context
    result = await client.put("/api/problems/race/log_visibility", json={"public_cases": True})
    assert result.json() == {
        "code": 200,
        "msg": "log visibility updated",
        "data": {"problem_id": "race", "public_cases": True},
    }
