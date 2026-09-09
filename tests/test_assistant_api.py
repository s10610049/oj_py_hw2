import asyncio

import httpx
import pytest

from oj.main import create_app

MODEL_CONFIG = {
    "provider_url": "https://models.example/v1",
    "model": "example-model",
    "api_key": "synthetic-assistant-route-key",
    "input_price": 1,
    "output_price": 2,
    "price_unit": 1_000_000,
    "currency": "USD",
}


class WaitingStream(httpx.AsyncByteStream):
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __aiter__(self):
        self.started.set()
        await self.release.wait()
        yield b"data: [DONE]\n\n"


def provider(_request):
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=WaitingStream(),
    )


async def register_and_login(client, username):
    credentials = {"username": username, "password": "synthetic-password"}
    assert (await client.post("/api/users/", json=credentials)).status_code == 200
    assert (await client.post("/api/auth/login", json=credentials)).status_code == 200


@pytest.mark.asyncio
async def test_authoring_and_chat_routes_are_owner_scoped_and_cancellable(tmp_path):
    app = create_app(tmp_path / "assistant-api.sqlite3", bcrypt_rounds=4, ai_config=MODEL_CONFIG)
    async with app.router.lifespan_context(app):
        app.state.ai._transport = httpx.MockTransport(provider)
        app.state.chat._transport = httpx.MockTransport(provider)
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://test") as alice,
            httpx.AsyncClient(transport=transport, base_url="http://test") as bob,
        ):
            await register_and_login(alice, "alice")
            await register_and_login(bob, "bob")

            options = (await alice.get("/api/ai/authoring-options/")).json()["data"]
            assert len(options["difficulties"]) == 8
            assert len(options["knowledge_points"]) >= 200

            started = await alice.post(
                "/api/ai/authoring-sessions/",
                json={
                    "idempotency_key": "initial-1",
                    "request": {
                        "requirement": "设计一道有向图判环题",
                        "knowledge_point_ids": ["graph.topological-sort"],
                        "difficulty_id": "luogu.4",
                        "free_prompt": "输入规模应覆盖线性复杂度边界。",
                        "attachments": [],
                    },
                },
            )
            assert started.status_code == 200
            session = started.json()["data"]
            session_id = session["session_id"]
            assert session["current_revision"] == 1

            denied = await bob.get(f"/api/ai/authoring-sessions/{session_id}")
            assert denied.status_code == 403
            cancelled = await alice.delete(f"/api/ai/authoring-sessions/{session_id}/active-task")
            assert cancelled.status_code == 200
            assert cancelled.json()["data"]["status"] == "cancelled"

            chat = await alice.post("/api/chat/sessions/", json={"locale": "en"})
            assert chat.status_code == 200
            chat_data = chat.json()["data"]
            assert chat_data["locale"] == "en"
            assert chat_data["messages"][0]["content"].startswith("Hi")
            chat_id = chat_data["session_id"]

            hidden = await bob.get(f"/api/chat/sessions/{chat_id}")
            assert hidden.status_code == 404
            statuses = (await alice.get("/api/me/problem-statuses/")).json()["data"]
            turn = await alice.post(
                f"/api/chat/sessions/{chat_id}/turns/",
                json={
                    "message": "How should I detect a cycle?",
                    "expected_context_epoch": statuses["context_epoch"],
                    "idempotency_key": "turn-1",
                },
            )
            assert turn.status_code == 200
            turn_id = turn.json()["data"]["turn_id"]
            stopped = await alice.delete(f"/api/chat/sessions/{chat_id}/turns/{turn_id}")
            assert stopped.status_code == 200
            assert stopped.json()["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_chat_stale_epoch_returns_structured_retryable_error(tmp_path):
    app = create_app(tmp_path / "chat-epoch.sqlite3", bcrypt_rounds=4, ai_config=MODEL_CONFIG)
    async with app.router.lifespan_context(app):
        app.state.chat._transport = httpx.MockTransport(provider)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await register_and_login(client, "epoch-user")
            chat_id = (await client.post("/api/chat/sessions/", json={"locale": "zh-CN"})).json()[
                "data"
            ]["session_id"]
            result = await client.post(
                f"/api/chat/sessions/{chat_id}/turns/",
                json={
                    "message": "讲一下二分答案",
                    "expected_context_epoch": "0" * 64,
                    "idempotency_key": "stale",
                },
            )
            assert result.status_code == 409
            assert result.json()["data"] == {
                "error_code": "context_epoch_mismatch",
                "retryable": True,
            }
