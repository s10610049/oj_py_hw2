"""Problem APIs expose complete locale projections without changing judge fields."""

import httpx
import pytest

from oj.main import create_app

PROBLEM = {
    "id": "BILINGUAL",
    "title": "两数之和",
    "description": "计算两个整数的和。",
    "input_description": "输入两个整数。",
    "output_description": "输出它们的和。",
    "constraints": "绝对值不超过十亿。",
    "hint": "使用加法。",
    "source": "原创",
    "author": "课程组",
    "difficulty": "入门",
    "tags": ["数学"],
    "samples": [{"input": "1 2", "output": "3"}],
    "testcases": [{"input": "SECRET_INPUT", "output": "SECRET_OUTPUT"}],
    "time_limit": 1,
    "memory_limit": 128,
}
ENGLISH = {
    "title": "A + B",
    "description": "Add two integers.",
    "input_description": "Read two integers.",
    "output_description": "Print their sum.",
    "constraints": "Absolute values are at most one billion.",
    "hint": "Use addition.",
}


async def login(client):
    response = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "admintestpassword"}
    )
    assert response.status_code == 200


def checked(response, status=200):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == status
    return body["data"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_problem_locale_projection_translation_update_and_staleness(tmp_path):
    app = create_app(tmp_path / "translations.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await login(client)
            checked(await client.post("/api/problems/", json=PROBLEM))

            fallback = checked(await client.get("/api/problems/BILINGUAL", params={"locale": "en"}))
            assert fallback["content"]["status"] == "missing"
            assert fallback["content"]["resolved_locale"] == "zh-CN"
            assert "SECRET_INPUT" not in str(fallback["content"])

            ready = checked(
                await client.put("/api/problems/BILINGUAL/translations/en", json=ENGLISH)
            )
            assert ready["status"] == "ready" and ready["fields"]["title"] == "A + B"
            listing = checked(await client.get("/api/problems/", params={"locale": "en"}))
            assert listing[0]["title"] == PROBLEM["title"]
            assert listing[0]["content"]["fields"]["title"] == "A + B"

            changed = {**PROBLEM, "description": "新的中文题意。"}
            checked(await client.put("/api/problems/BILINGUAL", json=changed))
            stale = checked(await client.get("/api/problems/BILINGUAL", params={"locale": "en"}))
            assert stale["content"]["status"] == "stale"
            assert stale["content"]["fields"]["description"] == "新的中文题意。"

            checked(await client.delete("/api/problems/BILINGUAL/translations/en"))
            assert (
                checked(await client.get("/api/problems/BILINGUAL", params={"locale": "en"}))[
                    "content"
                ]["status"]
                == "missing"
            )


@pytest.mark.anyio
async def test_embedded_translation_is_atomic_and_locale_is_validated(tmp_path):
    app = create_app(tmp_path / "embedded.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await login(client)
            checked(
                await client.post(
                    "/api/problems/", json={**PROBLEM, "translations": {"en": ENGLISH}}
                )
            )
            content = checked(
                await client.get("/api/problems/BILINGUAL", params={"locale": "en-US"})
            )["content"]
            assert content["resolved_locale"] == "en"
            checked(await client.get("/api/problems/", params={"locale": "fr"}), 400)

            invalid = {
                **PROBLEM,
                "id": "INVALID-TRANSLATION",
                "translations": {"en": {"title": "Only a title"}},
            }
            checked(await client.post("/api/problems/", json=invalid), 400)
            assert await app.state.store.get("problems", "INVALID-TRANSLATION") is None
