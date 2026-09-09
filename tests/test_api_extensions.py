"""Additive personal progress APIs without changing the course endpoints."""

from copy import deepcopy

import httpx
import pytest

from oj.main import create_app
from oj.progress import problem_version_digest

PROBLEM = {
    "id": "sum",
    "title": "整数求和",
    "description": "计算两个整数的和。",
    "input_description": "两个整数",
    "output_description": "它们的和",
    "constraints": "绝对值不超过十亿",
    "samples": [{"input": "1 2", "output": "3"}],
    "testcases": [{"input": "1 2", "output": "3"}, {"input": "-5 4", "output": "-1"}],
    "difficulty": "入门",
    "tags": ["数学", "实现"],
}


async def login(client, username="admin", password="admintestpassword"):
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return response.json()["data"]


def data(response, status=200):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == status
    assert set(body) == {"code", "msg", "data"}
    return body["data"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_personal_progress_routes_are_private_consistent_and_additive(tmp_path):
    app = create_app(tmp_path / "progress.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            data(await client.get("/api/me/problem-statuses/"), 401)
            await login(client)
            data(await client.post("/api/problems/", json=PROBLEM))
            admin = data(await client.get("/api/users/1"))

            stored_problem = await app.state.store.get("problems", "sum")
            version = problem_version_digest(stored_problem)
            await app.state.store.put(
                "submissions",
                "mine",
                {
                    "submission_id": "mine",
                    "user_id": admin["user_id"],
                    "problem_id": "sum",
                    "language": "python",
                    "code": "SECRET_CODE",
                    "created_at": "2026-09-09T12:00:00+00:00",
                    "status": "success",
                    "score": 20,
                    "counts": 20,
                    "details": [{"input": "SECRET_CASE"}],
                    "revision": 1,
                    "problem_version": version,
                },
            )
            statuses = data(await client.get("/api/me/problem-statuses/"))
            stats = data(await client.get("/api/me/learning-stats/"))
            assert statuses["context_epoch"] == stats["context_epoch"]
            assert statuses["items"][0]["state"] == "passed"
            assert stats["kpis"] == {
                "earned_score": 20,
                "available_score": 20,
                "attempted_count": 1,
                "passed_count": 1,
                "pass_rate": 1.0,
            }
            rendered = str((statuses, stats))
            assert "SECRET_CODE" not in rendered and "SECRET_CASE" not in rendered
            # The existing course list contract remains available and additive
            # routes do not require or accept a target user id.
            assert data(await client.get("/api/problems/"))[0]["id"] == "sum"
            assert (
                data(await client.get("/api/me/learning-stats/?user_id=someone"))["scope"][
                    "user_id"
                ]
                == admin["user_id"]
            )


@pytest.mark.anyio
async def test_new_submission_captures_problem_version_and_rejudge_refreshes_it(tmp_path):
    app = create_app(tmp_path / "versions.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await login(client)
            data(await client.post("/api/problems/", json=PROBLEM))
            created = data(
                await client.post(
                    "/api/submissions/",
                    json={
                        "problem_id": "sum",
                        "language": "python",
                        "code": "a,b=map(int,input().split());print(a+b)",
                    },
                )
            )
            first = await app.state.store.get("submissions", created["submission_id"])
            assert first["problem_version"] == problem_version_digest(
                await app.state.store.get("problems", "sum")
            )
            assert first["problem_title"] == "整数求和"
            assert first["difficulty_raw"] == "入门"
            assert first["tags_snapshot"] == ["数学", "实现"]

            changed = deepcopy(PROBLEM)
            changed["title"] = "新版求和"
            data(await client.put("/api/problems/sum", json=changed))
            old_version = first["problem_version"]
            data(await client.put(f"/api/submissions/{created['submission_id']}/rejudge"))
            refreshed = await app.state.store.get("submissions", created["submission_id"])
            assert refreshed["problem_version"] != old_version
            assert refreshed["problem_title"] == "新版求和"
            assert refreshed["version_inferred"] is False


@pytest.mark.anyio
async def test_corrupt_progress_timestamp_returns_safe_atomic_500(tmp_path):
    app = create_app(tmp_path / "corrupt.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await login(client)
            data(await client.post("/api/problems/", json=PROBLEM))
            await app.state.store.put(
                "submissions",
                "broken",
                {
                    "submission_id": "broken",
                    "user_id": "1",
                    "problem_id": "sum",
                    "status": "error",
                    "created_at": "not-a-date",
                },
            )
            failure = await client.get("/api/me/learning-stats/")
            assert data(failure, 500) is None
            assert failure.json()["msg"] == "Learning progress could not be calculated"
