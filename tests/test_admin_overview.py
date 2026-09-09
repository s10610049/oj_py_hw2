"""Contract and permission tests for the administrator cohort overview."""

from copy import deepcopy

import httpx
import pytest

from oj.main import create_app
from oj.progress import (
    ADMIN_LEARNING_OVERVIEW_SCHEMA,
    build_admin_learning_overview,
    problem_version_digest,
)
from shared.taxonomy import normalize_difficulty

PROBLEM = {
    "id": "cohort-sum",
    "title": "Cohort sum",
    "description": "Add two integers.",
    "input_description": "Two integers",
    "output_description": "Their sum",
    "constraints": "Small integers",
    "hint": "",
    "source": "test",
    "author": "test",
    "difficulty": "入门",
    "tags": ["implementation"],
    "samples": [{"input": "1 2", "output": "3"}],
    "testcases": [
        {"input": "1 2", "output": "3"},
        {"input": "-1 1", "output": "0"},
    ],
    "public_cases": False,
}


def submission(identifier, user_id, score, *, detail="AC", compile_error=False):
    return {
        "submission_id": identifier,
        "user_id": user_id,
        "problem_id": PROBLEM["id"],
        "language": "cpp" if compile_error else "python",
        "code": "SECRET SOURCE",
        "created_at": f"2026-09-10T00:00:0{identifier[-1]}+00:00",
        "status": "success",
        "score": score,
        "counts": 20,
        "revision": 1,
        "problem_version": problem_version_digest(PROBLEM),
        "compile_info": (
            {"result": "error", "message": "SECRET COMPILER DETAIL"}
            if compile_error
            else {"result": "success", "message": ""}
        ),
        "details": [{"result": detail, "input": "SECRET CASE"}],
    }


def users():
    return [
        {
            "user_id": "1",
            "username": "admin",
            "role": "admin",
            "join_time": "2026-09-01",
            "password_hash": "SECRET HASH",
        },
        {
            "user_id": "2",
            "username": "alice",
            "role": "user",
            "join_time": "2026-09-02",
        },
        {
            "user_id": "3",
            "username": "bob",
            "role": "user",
            "join_time": "2026-09-03",
        },
        {
            "user_id": "4",
            "username": "disabled-demo",
            "role": "banned",
            "join_time": "2026-09-04",
        },
    ]


def test_admin_overview_reuses_personal_metrics_and_exposes_only_aggregates():
    records = [
        submission("s1", "2", 20),
        submission("s2", "2", 0, compile_error=True),
        submission("s3", "3", 10, detail="WA"),
        submission("s4", "3", 0, detail="WA"),
    ]
    result = build_admin_learning_overview(
        users(),
        [PROBLEM],
        records,
        difficulty_normalizer=normalize_difficulty,
        generated_at="2026-09-10T00:01:00+00:00",
    )
    assert result["schema_version"] == ADMIN_LEARNING_OVERVIEW_SCHEMA
    assert [row["username"] for row in result["users"]] == [
        "admin",
        "alice",
        "bob",
        "disabled-demo",
    ]
    alice = result["users"][1]
    assert alice["submission_count"] == 2
    assert alice["attempted_count"] == alice["passed_count"] == 1
    assert alice["earned_score"] == alice["available_score"] == 20
    assert alice["score_rate"] == alice["pass_rate"] == 1
    assert {row["id"]: row["count"] for row in alice["submission_outcomes"]}["compile_error"] == 1
    bob = result["users"][2]
    assert bob["earned_score"] == 10 and bob["score_rate"] == 0.5
    assert bob["pass_rate"] == 0
    disabled = result["users"][3]
    assert disabled["account_status"] == "disabled"
    assert disabled["submission_count"] == disabled["attempted_count"] == 0
    rendered = str(result)
    assert "SECRET" not in rendered
    assert result["summary"] == {
        "account_count": 4,
        "active_count": 3,
        "disabled_count": 1,
        "learner_count": 2,
        "engaged_count": 2,
        "submission_count": 4,
        "attempted_count": 2,
        "passed_count": 1,
        "earned_score": 30,
        "available_score": 80,
        "score_rate": 0.375,
        "pass_rate": 0.5,
    }


@pytest.fixture
def anyio_backend():
    return "asyncio"


def response_data(response, expected=200):
    assert response.status_code == expected, response.text
    body = response.json()
    assert body["code"] == expected and set(body) == {"code", "msg", "data"}
    return body["data"]


@pytest.mark.anyio
async def test_admin_overview_route_is_admin_only_and_does_not_leak_submission_data(tmp_path):
    app = create_app(tmp_path / "admin-overview.sqlite3", bcrypt_rounds=4, ai_config={})
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://test") as admin,
            httpx.AsyncClient(transport=transport, base_url="http://test") as learner,
            httpx.AsyncClient(transport=transport, base_url="http://test") as anonymous,
        ):
            response_data(await anonymous.get("/api/admin/learning-overview/"), 401)
            response_data(
                await admin.post(
                    "/api/auth/login",
                    json={"username": "admin", "password": "admintestpassword"},
                )
            )
            created = response_data(
                await learner.post(
                    "/api/users/",
                    json={"username": "cohort-user", "password": "fixture-password"},
                )
            )
            response_data(
                await learner.post(
                    "/api/auth/login",
                    json={"username": "cohort-user", "password": "fixture-password"},
                )
            )
            response_data(await learner.get("/api/admin/learning-overview/"), 403)
            response_data(await admin.post("/api/problems/", json=deepcopy(PROBLEM)))
            stored = await app.state.store.get("problems", PROBLEM["id"])
            record = submission("s1", created["user_id"], 20)
            record["problem_version"] = problem_version_digest(stored)
            await app.state.store.put("submissions", record["submission_id"], record)

            overview = response_data(await admin.get("/api/admin/learning-overview/"))
            learner_row = next(
                row for row in overview["users"] if row["user_id"] == created["user_id"]
            )
            assert learner_row["passed_count"] == 1
            assert learner_row["submission_count"] == 1
            rendered = str(overview)
            assert "SECRET SOURCE" not in rendered
            assert "SECRET CASE" not in rendered
            assert "password" not in rendered.lower()
