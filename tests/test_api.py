"""Course contracts and TA clarifications exercised through the ASGI boundary."""

import asyncio
import inspect
from copy import deepcopy

import httpx
import pytest
import pytest_asyncio

from oj.main import create_app

PROBLEM = {
    "id": "sum",
    "title": "整数求和",
    "description": "计算两个整数的和。",
    "input_description": "两个整数",
    "output_description": "它们的和",
    "constraints": "绝对值不超过十亿",
    "samples": [{"input": "1 2", "output": "3"}],
    "testcases": [{"input": "1 2", "output": "3"}, {"input": "-5 4", "output": "-1"}],
}


@pytest_asyncio.fixture
async def api(tmp_path):
    app = create_app(tmp_path / "db.sqlite3", bcrypt_rounds=4, ai_config={})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c, app


async def login(client, name="admin", password="admintestpassword"):
    result = await client.post("/api/auth/login", json={"username": name, "password": password})
    assert result.status_code == 200, result.text
    return result.json()["data"]


async def register(client, name="alice", password="password123"):
    r = await client.post("/api/users/", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def check(r, code=200):
    assert r.status_code == code, r.text
    body = r.json()
    assert body["code"] == code
    assert set(body) == {"code", "msg", "data"}
    if code != 200:
        assert body["data"] is None
    return body["data"]


async def settled(client, key):
    for _ in range(150):
        result = check(await client.get(f"/api/submissions/{key}"))
        if result["status"] != "pending":
            return result
        await asyncio.sleep(0.04)
    pytest.fail("Judge did not finish within integration timeout")


@pytest.mark.asyncio
async def test_all_business_endpoints_are_async(api):
    _, app = api
    for route in app.routes:
        if route.path.startswith("/api/"):
            assert inspect.iscoroutinefunction(route.endpoint), route.path


@pytest.mark.asyncio
async def test_authentication_cookie_and_unicode_password(api):
    c, app = api
    check(await c.post("/api/users/", json={"username": "ab", "password": "123456"}), 400)
    long_password = "安全密码" * 40
    user = await register(c, password=long_password)
    assert user["submit_count"] == user["resolve_count"] == 0
    assert "password" not in str(user)
    stored = await app.state.store.get("users", user["user_id"])
    assert stored["password_hash"].startswith("$2b$")
    assert long_password not in str(stored)
    await login(c, "alice", long_password)
    check(await c.get(f"/api/users/{user['user_id']}"))
    check(await c.get("/api/users/1"), 403)
    check(await c.post("/api/auth/logout"))
    check(await c.get("/api/problems/"), 401)
    check(await c.post("/api/auth/logout"), 401)
    check(await c.post("/api/auth/login", json={"username": "alice", "password": "bad"}), 401)
    check(await c.post("/api/auth/login", json={"username": "none", "password": "bad"}), 401)
    check(await c.post("/api/users/", json={"username": "alice", "password": "123456"}), 400)


@pytest.mark.asyncio
async def test_auth_role_then_validation_priority(api):
    c, _ = api
    check(await c.post("/api/problems/", content="bad-json"), 401)
    check(await c.put("/api/users/missing/role", content="bad-json"), 401)
    user = await register(c)
    await login(c, "alice", "password123")
    check(await c.put("/api/users/missing/role", content="bad-json"), 403)
    check(await c.delete("/api/problems/missing"), 403)
    check(await c.get("/api/users/?page=bad"), 403)
    check(await c.get("/api/submissions/?user_id=someone&page=bad"), 403)
    await login(c)
    check(await c.put("/api/users/missing/role", json={"role": "invalid"}), 400)
    check(await c.put("/api/users/missing/role", json={"role": "user"}), 404)
    await login(c, "alice", "password123")
    cookie = c.cookies.get("oj_session")
    c.cookies.clear()
    await login(c)
    check(await c.put(f"/api/users/{user['user_id']}/role", json={"role": "banned"}))
    c.cookies.clear()
    c.cookies.set("oj_session", cookie)
    check(await c.get("/api/problems/"), 403)
    check(
        await c.post("/api/auth/login", json={"username": "alice", "password": "password123"}), 403
    )


@pytest.mark.asyncio
async def test_problem_crud_defaults_permissions_and_persistence(api):
    c, app = api
    await register(c)
    await login(c, "alice", "password123")
    assert check(await c.get("/api/problems/")) == []
    assert check(await c.post("/api/problems/", json=PROBLEM)) == {"id": "sum"}
    check(await c.post("/api/problems/", json=PROBLEM), 409)
    item = check(await c.get("/api/problems/sum"))
    assert item["testcases"] == PROBLEM["testcases"]
    assert item["hint"] == item["source"] == item["difficulty"] == ""
    assert item["tags"] == []
    assert item["time_limit"] is item["memory_limit"] is None
    await register(c, "bob")
    await login(c, "bob", "password123")
    edited = {**PROBLEM, "title": "普通用户可改题", "time_limit": 0.5}
    check(await c.put("/api/problems/sum", json=edited))
    assert (await app.state.store.get("problems", "sum"))["title"] == edited["title"]
    check(await c.put("/api/problems/missing", json=edited), 400)
    check(await c.put("/api/problems/missing", json={**edited, "id": "missing"}), 404)
    check(await c.delete("/api/problems/sum"), 403)
    await login(c)
    check(await c.delete("/api/problems/sum"))
    check(await c.get("/api/problems/sum"), 404)


@pytest.mark.parametrize("field", list(PROBLEM))
@pytest.mark.asyncio
async def test_every_required_problem_field(api, field):
    c, _ = api
    await login(c)
    invalid = deepcopy(PROBLEM)
    invalid.pop(field)
    check(await c.post("/api/problems/", json=invalid), 400)
    invalid[field] = 123
    check(await c.post("/api/problems/", json=invalid), 400)
    assert check(await c.get("/api/problems/")) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "../../secrets"},
        {"samples": [{"input": 1, "output": "1"}]},
        {"testcases": []},
        {"time_limit": 0},
        {"time_limit": "1"},
        {"memory_limit": True},
        {"memory_limit": 1.5},
        {"tags": "bad"},
    ],
)
@pytest.mark.asyncio
async def test_invalid_problem_fields(api, changes):
    c, _ = api
    await login(c)
    check(await c.post("/api/problems/", json={**PROBLEM, **changes}), 400)


@pytest.mark.asyncio
async def test_users_pagination_and_admin_creation(api):
    c, _ = api
    await login(c)
    created = check(
        await c.post("/api/users/admin", json={"username": "manager", "password": "123456"})
    )
    assert created["role"] == "admin"
    check(await c.post("/api/users/admin", json={"username": "manager", "password": "123456"}), 400)
    assert check(await c.get("/api/users/"))["total"] == 2
    assert len(check(await c.get("/api/users/?page_size=1"))["users"]) == 1
    assert len(check(await c.get("/api/users/?page=3&page_size=1"))["users"]) == 0
    for query in ("page=1", "page=0&page_size=2", "page_size=0", "page_size=x"):
        check(await c.get("/api/users/?" + query), 400)


@pytest.mark.asyncio
async def test_real_judge_logs_six_permissions_and_rejudge(api):
    c, _ = api
    alice = await register(c)
    await register(c, "bob")
    await login(c, "alice", "password123")
    check(await c.post("/api/problems/", json=PROBLEM))
    pending = check(
        await c.post(
            "/api/submissions/",
            json={
                "problem_id": "sum",
                "language": "python",
                "code": "a,b=map(int,input().split());print(a+b)",
            },
        )
    )
    assert pending["status"] == "pending"
    key = pending["submission_id"]
    done = await settled(c, key)
    assert done["status"] == "success"
    assert done["score"] == done["counts"] == 20
    assert "details" not in done
    info = check(await c.get(f"/api/users/{alice['user_id']}"))
    assert info["submit_count"] == info["resolve_count"] == 1
    private = check(await c.get(f"/api/submissions/{key}/log"))
    assert private == {"score": 20, "counts": 20}
    check(await c.put(f"/api/submissions/{key}/rejudge"), 403)
    await login(c, "bob", "password123")
    check(await c.get(f"/api/submissions/{key}"), 403)
    check(await c.get(f"/api/submissions/{key}/log"), 403)
    assert check(await c.get("/api/submissions/?problem_id=sum"))["total"] == 0
    await login(c)
    assert len(check(await c.get(f"/api/submissions/{key}/log"))["details"]) == 2
    check(await c.put("/api/problems/sum/log_visibility", json={"public_cases": True}))
    assert len(check(await c.get(f"/api/submissions/{key}/log"))["details"]) == 2
    for who in ("alice", "bob"):
        await login(c, who, "password123")
        public = check(await c.get(f"/api/submissions/{key}/log"))
        assert len(public["details"]) == 2
        assert not {"code", "compile_info", "error_info"} & public.keys()
    check(await c.get(f"/api/submissions/{key}"), 403)
    await login(c)
    audit = check(await c.get("/api/logs/access/"))
    assert {r["status"] for r in audit} == {"200", "403"}
    assert all(r["action"] == "view_logs" for r in audit)
    changed = {**PROBLEM, "testcases": [{"input": "1 2", "output": "4"}]}
    check(await c.put("/api/problems/sum", json=changed))
    assert check(await c.get(f"/api/submissions/{key}"))["score"] == 20
    assert check(await c.put(f"/api/submissions/{key}/rejudge"))["submission_id"] == key
    rejudged = await settled(c, key)
    assert rejudged["score"] == 0 and rejudged["counts"] == 10
    info = check(await c.get(f"/api/users/{alice['user_id']}"))
    assert info["submit_count"] == 1 and info["resolve_count"] == 0


@pytest.mark.asyncio
async def test_rate_limit_error_priority_and_queries(api, monkeypatch):
    c, _ = api
    await login(c)
    check(await c.post("/api/problems/", json=PROBLEM))
    value = {"problem_id": "sum", "language": "python", "code": "print(0)"}
    for _ in range(3):
        check(await c.post("/api/submissions/", json=value))
    check(await c.post("/api/submissions/", json=value), 429)
    check(await c.post("/api/submissions/", json={**value, "problem_id": "missing"}), 429)
    check(await c.post("/api/submissions/", json={**value, "code": None}), 400)
    records = check(await c.get("/api/submissions/?problem_id=sum&page_size=2"))
    assert records["total"] == 3 and len(records["submissions"]) == 2
    for query in ("", "user_id=1&page=1", "user_id=1&status=AC"):
        check(await c.get("/api/submissions/?" + query), 400)


@pytest.mark.asyncio
async def test_global_language_registration_and_use(api):
    c, _ = api
    await register(c)
    await login(c, "alice", "password123")
    lang = {
        "name": "python_extra",
        "file_ext": ".py",
        "run_cmd": "python3 {src}",
        "time_limit": 1,
        "memory_limit": 128,
    }
    check(await c.post("/api/languages/", json=lang))
    check(await c.post("/api/problems/", json=PROBLEM))
    await login(c)
    assert "python_extra" in check(await c.get("/api/languages/"))["name"]
    key = check(
        await c.post(
            "/api/submissions/",
            json={
                "problem_id": "sum",
                "language": "python_extra",
                "code": "print(sum(map(int,input().split())))",
            },
        )
    )["submission_id"]
    evaluated = await settled(c, key)
    assert evaluated["score"] == 20, evaluated


@pytest.mark.asyncio
async def test_reset_clears_state_and_sessions(api):
    c, _ = api
    await register(c)
    await login(c, "alice", "password123")
    check(await c.post("/api/reset/"), 403)
    await login(c)
    check(await c.post("/api/problems/", json=PROBLEM))
    old = c.cookies.get("oj_session")
    check(await c.post("/api/reset/"))
    c.cookies.set("oj_session", old)
    check(await c.get("/api/problems/"), 401)
    c.cookies.clear()
    await login(c)
    assert check(await c.get("/api/problems/")) == []
    assert check(await c.get("/api/users/"))["total"] == 1


@pytest.mark.asyncio
async def test_database_survives_application_restart(tmp_path):
    path = tmp_path / "persistent.sqlite3"
    for stage in range(2):
        app = create_app(path, bcrypt_rounds=4, ai_config={})
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as c:
                await login(c)
                if stage == 0:
                    check(await c.post("/api/problems/", json=PROBLEM))
                else:
                    assert check(await c.get("/api/problems/sum"))["title"] == PROBLEM["title"]
