"""FastAPI course API. Start with: uvicorn oj.main:app --host 127.0.0.1."""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
from dotenv import dotenv_values
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from oj.common import APIError, response
from oj.schemas import identifier, paginate, pagination, text_field, validate_problem
from oj.store import Store

COOKIE = "oj_session"
SESSION_SECONDS = 24 * 3600


def new_id():
    return uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def password_bytes(password):
    # bcrypt's 72-byte limit must not silently truncate long/unicode passwords.
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


async def body_object(request):
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 8_000_000:
            raise APIError(400, "Request body is too large")
    try:
        value = json.loads(chunks)
    except (ValueError, UnicodeError):
        raise APIError(400, "Invalid JSON body") from None
    if not isinstance(value, dict):
        raise APIError(400, "JSON body must be an object")
    return value


def credentials(value):
    username = text_field(value.get("username"), "username", minimum=3, maximum=40)
    password = text_field(value.get("password"), "password", minimum=6, maximum=1024)
    return username, password


def load_ai_config():
    # Called by the server, never returned to the UI or emitted in logs.
    config = {**dotenv_values(Path(__file__).resolve().parent.parent / ".env"), **os.environ}
    key = config.get("DEEPSEEK_API_KEY")
    if not key:
        return None
    return {
        "provider_url": config.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": config.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "api_key": key,
        "input_price": None,
        "output_price": None,
        "price_unit": 1_000_000,
        "currency": "CNY",
    }


def create_app(database_path=None, *, bcrypt_rounds=12, ai_config=None):
    store = Store(database_path or os.environ.get("OJ_DATABASE", "runtime/oj.sqlite3"))
    mutation = asyncio.Lock()
    jobs = {}
    recent_submissions = {}

    async def initialize_defaults():
        if not await store.all("users"):
            hashed = await asyncio.to_thread(
                bcrypt.hashpw, password_bytes("admintestpassword"), bcrypt.gensalt(bcrypt_rounds)
            )
            await store.put(
                "users",
                "1",
                {
                    "user_id": "1",
                    "username": "admin",
                    "role": "admin",
                    "join_time": datetime.now().strftime("%Y-%m-%d"),
                    "password_hash": hashed.decode("ascii"),
                },
            )
        for language in (
            {"name": "python", "file_ext": ".py", "run_cmd": "python3 {src}"},
            {
                "name": "cpp",
                "file_ext": ".cpp",
                "compile_cmd": "g++ -std=c++14 -O2 {src} -o {exe}",
                "run_cmd": "{exe}",
            },
        ):
            if not await store.get("languages", language["name"]):
                await store.put("languages", language["name"], language)

    async def cancel_jobs():
        running = list(jobs.values())
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        jobs.clear()

    @asynccontextmanager
    async def lifespan(application):
        from oj.ai import AIService

        await store.initialize()
        await initialize_defaults()
        for submission in await store.all("submissions"):
            if submission["status"] == "pending":
                submission.update(status="error", error_info="评测被服务重启中断，请重新评测")
                await store.put("submissions", submission["submission_id"], submission)
        application.state.ai = AIService(
            default_config=load_ai_config() if ai_config is None else ai_config or None
        )
        yield
        await cancel_jobs()
        await application.state.ai.close()

    application = FastAPI(title="OJ · 编程练习室", version="1.0.0", lifespan=lifespan)
    application.state.store = store
    application.state.jobs = jobs

    @application.exception_handler(APIError)
    async def expected_error(request, exc):
        return response(None, exc.message, exc.status)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return response(None, "Invalid request parameters", 400)

    @application.exception_handler(HTTPException)
    async def http_error(request, exc):
        return response(
            None,
            "Request not found" if exc.status_code == 404 else "Request failed",
            exc.status_code,
        )

    @application.exception_handler(Exception)
    async def unexpected_error(request, exc):
        # Do not leak database paths, submitted code, provider responses or secrets.
        return response(None, "Internal server error", 500)

    async def current_user(request: Request):
        token = request.cookies.get(COOKIE)
        session = await store.get("sessions", token) if token else None
        if not session or session["expires_at"] <= time.time():
            raise APIError(401, "Login required")
        user = await store.get("users", session["user_id"])
        if not user:
            raise APIError(401, "Login required")
        if user["role"] == "banned":
            raise APIError(403, "Account is banned")
        return user

    async def administrator(user=Depends(current_user)):
        if user["role"] != "admin":
            raise APIError(403, "Administrator permission required")
        return user

    def own_or_admin(user, user_id):
        if user["user_id"] != user_id and user["role"] != "admin":
            raise APIError(403, "Permission denied")

    async def public_user(user):
        submissions = [s for s in await store.all("submissions") if s["user_id"] == user["user_id"]]
        resolved = {
            s["problem_id"]
            for s in submissions
            if s["status"] == "success"
            and s.get("counts", 0) > 0
            and s.get("score") == s.get("counts")
        }
        return {
            **{k: user[k] for k in ("user_id", "username", "role", "join_time")},
            "submit_count": len(submissions),
            "resolve_count": len(resolved),
        }

    async def add_user(value, role):
        username, password = credentials(value)
        async with mutation:
            if any(u["username"] == username for u in await store.all("users")):
                raise APIError(400, "Username already exists")
            hashed = await asyncio.to_thread(
                bcrypt.hashpw, password_bytes(password), bcrypt.gensalt(bcrypt_rounds)
            )
            user = {
                "user_id": new_id(),
                "username": username,
                "role": role,
                "join_time": datetime.now().strftime("%Y-%m-%d"),
                "password_hash": hashed.decode("ascii"),
            }
            await store.put("users", user["user_id"], user)
        return response(
            await public_user(user), "success" if role == "admin" else "register success"
        )

    @application.get("/api/health")
    async def health():
        return response({"status": "ok", "version": "1.0.0"})

    @application.post("/api/users/")
    async def register(request: Request):
        return await add_user(await body_object(request), "user")

    @application.post("/api/users/admin")
    async def register_admin(request: Request, user=Depends(administrator)):
        return await add_user(await body_object(request), "admin")

    @application.post("/api/auth/login")
    async def login(request: Request):
        value = await body_object(request)
        username = text_field(value.get("username"), "username", maximum=40)
        password = text_field(value.get("password"), "password", maximum=1024)
        user = next((u for u in await store.all("users") if u["username"] == username), None)
        # Same expensive hash check for unknown users reduces username timing leakage.
        hashed = user["password_hash"] if user else (await store.get("users", "1"))["password_hash"]
        matched = await asyncio.to_thread(bcrypt.checkpw, password_bytes(password), hashed.encode())
        if not user or not matched:
            raise APIError(401, "Invalid username or password")
        if user["role"] == "banned":
            raise APIError(403, "Account is banned")
        token = secrets.token_urlsafe(32)
        async with mutation:
            old = request.cookies.get(COOKIE)
            if old:
                await store.delete("sessions", old)
            await store.put(
                "sessions",
                token,
                {"user_id": user["user_id"], "expires_at": time.time() + SESSION_SECONDS},
            )
        result = response({k: user[k] for k in ("user_id", "username", "role")}, "login success")
        result.set_cookie(
            COOKIE,
            token,
            max_age=SESSION_SECONDS,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return result

    @application.post("/api/auth/logout")
    async def logout(request: Request, user=Depends(current_user)):
        await store.delete("sessions", request.cookies[COOKIE])
        result = response(None, "logout success")
        result.delete_cookie(COOKIE)
        return result

    @application.get("/api/users/")
    async def users(request: Request, user=Depends(administrator)):
        limits = pagination(request.query_params)
        records = await store.all("users")
        return response(
            {
                "total": len(records),
                "users": [await public_user(u) for u in paginate(records, limits)],
            }
        )

    @application.get("/api/users/{user_id}")
    async def user_info(user_id: str, user=Depends(current_user)):
        own_or_admin(user, user_id)
        record = await store.get("users", user_id)
        if not record:
            raise APIError(404, "User not found")
        return response(await public_user(record))

    @application.put("/api/users/{user_id}/role")
    async def change_role(user_id: str, request: Request, user=Depends(administrator)):
        value = await body_object(request)
        role = value.get("role")
        if role not in ("admin", "user", "banned"):
            raise APIError(400, "Invalid role")
        async with mutation:
            record = await store.get("users", user_id)
            if not record:
                raise APIError(404, "User not found")
            record["role"] = role
            await store.put("users", user_id, record)
            await store.put(
                "role_audit",
                new_id(),
                {"actor": user["user_id"], "user_id": user_id, "role": role, "time": now()},
            )
        return response({"user_id": user_id, "role": role}, "role updated")

    @application.get("/api/problems/")
    async def problems(user=Depends(current_user)):
        return response(
            [
                {k: p.get(k, "") for k in ("id", "title", "difficulty", "tags", "source")}
                for p in await store.all("problems")
            ]
        )

    @application.post("/api/problems/")
    async def add_problem(request: Request, user=Depends(current_user)):
        problem = validate_problem(await body_object(request))
        async with mutation:
            if await store.get("problems", problem["id"]):
                raise APIError(409, "Problem already exists")
            await store.put("problems", problem["id"], {**problem, "public_cases": False})
        return response({"id": problem["id"]}, "add success")

    @application.get("/api/problems/{problem_id}")
    async def problem_info(problem_id: str, user=Depends(current_user)):
        record = await store.get("problems", problem_id)
        if not record:
            raise APIError(404, "Problem not found")
        return response(record)

    @application.put("/api/problems/{problem_id}")
    async def edit_problem(problem_id: str, request: Request, user=Depends(current_user)):
        problem = validate_problem(await body_object(request))
        if problem["id"] != problem_id:
            raise APIError(400, "Problem id must match URL")
        async with mutation:
            existing = await store.get("problems", problem_id)
            if not existing:
                raise APIError(404, "Problem not found")
            await store.put(
                "problems",
                problem_id,
                {**problem, "public_cases": existing.get("public_cases", False)},
            )
        return response({"id": problem_id}, "update success")

    @application.delete("/api/problems/{problem_id}")
    async def delete_problem(problem_id: str, user=Depends(administrator)):
        async with mutation:
            if not await store.get("problems", problem_id):
                raise APIError(404, "Problem not found")
            await store.delete("problems", problem_id)
        return response({"id": problem_id}, "delete success")

    @application.get("/api/languages/")
    async def languages(user=Depends(current_user)):
        return response({"name": [record["name"] for record in await store.all("languages")]})

    @application.post("/api/languages/")
    async def add_language(request: Request, user=Depends(current_user)):
        from oj.judge import validate_language

        language = validate_language(await body_object(request))
        async with mutation:
            if await store.get("languages", language["name"]):
                raise APIError(409, "Language already exists")
            await store.put("languages", language["name"], language)
        return response({"name": language["name"]}, "language registered")

    def summary(record, *, detailed=False):
        keys = ["submission_id", "status"]
        if record["status"] == "success":
            keys += ["score", "counts"]
        if detailed:
            keys += [
                "score",
                "counts",
                "compile_info",
                "run_info",
                "error_info",
                "user_id",
                "problem_id",
                "language",
                "created_at",
                "code",
            ]
        else:
            # Additive metadata for meaningful frontend record lists.
            keys += ["user_id", "problem_id", "language", "created_at"]
        return {key: record.get(key) for key in keys}

    async def evaluate(submission, problem, language):
        from oj.judge import judge_submission

        key = submission["submission_id"]
        try:
            result = await judge_submission(problem, language, submission["code"])
        except asyncio.CancelledError:
            raise
        except Exception:
            result = {
                "status": "error",
                "error_info": "Judge infrastructure failed",
                "score": None,
                "counts": None,
                "details": [],
            }
        async with mutation:
            current = await store.get("submissions", key)
            if current and current["revision"] == submission["revision"]:
                await store.put("submissions", key, {**current, **result})

    def launch(submission, problem, language):
        key = submission["submission_id"]
        task = asyncio.create_task(evaluate(submission, problem, language))
        jobs[key] = task

        def done(completed):
            if jobs.get(key) is completed:
                jobs.pop(key, None)

        task.add_done_callback(done)

    @application.post("/api/submissions/")
    async def submit(request: Request, user=Depends(current_user)):
        value = await body_object(request)
        problem_id = identifier(value.get("problem_id"), "problem_id")
        language_name = text_field(value.get("language"), "language", maximum=80)
        code = text_field(value.get("code"), "code", maximum=500_000)
        async with mutation:
            stamp = time.monotonic()
            history = [t for t in recent_submissions.get(user["user_id"], []) if stamp - t < 60]
            if len(history) >= 3:
                raise APIError(429, "At most 3 submissions per minute; please wait")
            problem = await store.get("problems", problem_id)
            language = await store.get("languages", language_name)
            if not problem or not language:
                raise APIError(404, "Problem or language not found")
            submission = {
                "submission_id": new_id(),
                "user_id": user["user_id"],
                "problem_id": problem_id,
                "language": language_name,
                "code": code,
                "created_at": now(),
                "status": "pending",
                "revision": 1,
                "score": None,
                "counts": None,
                "compile_info": None,
                "run_info": None,
                "error_info": None,
                "details": [],
            }
            await store.put("submissions", submission["submission_id"], submission)
            recent_submissions[user["user_id"]] = history + [stamp]
            launch(submission, problem, language)
        return response({"submission_id": submission["submission_id"], "status": "pending"})

    @application.get("/api/submissions/")
    async def submissions(request: Request, user=Depends(current_user)):
        query = request.query_params
        user_id, problem_id = query.get("user_id"), query.get("problem_id")
        if user_id:
            own_or_admin(user, user_id)
        if not user_id and not problem_id:
            raise APIError(400, "user_id or problem_id is required")
        limits = pagination(query)
        status = query.get("status")
        if status is not None and status not in ("pending", "success", "error"):
            raise APIError(400, "Invalid status")
        records = await store.all("submissions")
        if user["role"] != "admin":
            records = [s for s in records if s["user_id"] == user["user_id"]]
        if user_id:
            records = [s for s in records if s["user_id"] == user_id]
        if problem_id:
            records = [s for s in records if s["problem_id"] == problem_id]
        if status:
            records = [s for s in records if s["status"] == status]
        records.reverse()
        return response(
            {"total": len(records), "submissions": [summary(s) for s in paginate(records, limits)]}
        )

    @application.get("/api/submissions/{submission_id}")
    async def submission_info(submission_id: str, user=Depends(current_user)):
        record = await store.get("submissions", submission_id)
        if not record:
            raise APIError(404, "Submission not found")
        own_or_admin(user, record["user_id"])
        return response(summary(record, detailed=True))

    @application.put("/api/submissions/{submission_id}/rejudge")
    async def rejudge(submission_id: str, user=Depends(administrator)):
        old_task = jobs.get(submission_id)
        if old_task:
            old_task.cancel()
            await asyncio.gather(old_task, return_exceptions=True)
        async with mutation:
            record = await store.get("submissions", submission_id)
            if not record:
                raise APIError(404, "Submission not found")
            problem = await store.get("problems", record["problem_id"])
            language = await store.get("languages", record["language"])
            if not problem or not language:
                raise APIError(404, "Problem or language no longer exists")
            record.update(
                status="pending",
                score=None,
                counts=None,
                details=[],
                compile_info=None,
                run_info=None,
                error_info=None,
                revision=record["revision"] + 1,
            )
            await store.put("submissions", submission_id, record)
            launch(record, problem, language)
        return response({"submission_id": submission_id, "status": "pending"}, "rejudge started")

    @application.put("/api/problems/{problem_id}/log_visibility")
    async def visibility(problem_id: str, request: Request, user=Depends(administrator)):
        value = await body_object(request)
        public = value.get("public_cases", False)
        if not isinstance(public, bool):
            raise APIError(400, "public_cases must be a boolean")
        async with mutation:
            problem = await store.get("problems", problem_id)
            if not problem:
                raise APIError(404, "Problem not found")
            problem["public_cases"] = public
            await store.put("problems", problem_id, problem)
        return response({"problem_id": problem_id, "public_cases": public})

    @application.get("/api/submissions/{submission_id}/log")
    async def submission_log(submission_id: str, user=Depends(current_user)):
        record = await store.get("submissions", submission_id)
        if not record:
            raise APIError(404, "Submission not found")
        problem = await store.get("problems", record["problem_id"])
        public = bool(problem and problem.get("public_cases"))
        full = public or user["role"] == "admin"
        allowed = full or record["user_id"] == user["user_id"]
        await store.put(
            "access",
            new_id(),
            {
                "user_id": user["user_id"],
                "problem_id": record["problem_id"],
                "action": "view_logs",
                "time": now(),
                "status": "200" if allowed else "403",
            },
        )
        if not allowed:
            raise APIError(403, "Log is private")
        data = {"score": record.get("score"), "counts": record.get("counts")}
        if full:
            data["details"] = record.get("details", [])
        return response(data)

    @application.get("/api/logs/access/")
    async def access_logs(request: Request, user=Depends(administrator)):
        limits = pagination(request.query_params)
        records = await store.all("access")
        for key in ("user_id", "problem_id"):
            wanted = request.query_params.get(key)
            if wanted:
                records = [r for r in records if r[key] == wanted]
        return response(paginate(list(reversed(records)), limits))

    @application.get("/api/ai/model-config")
    async def get_ai_config(user=Depends(current_user)):
        return response(await application.state.ai.get_config(user["user_id"]))

    @application.put("/api/ai/model-config")
    async def configure_ai(request: Request, user=Depends(current_user)):
        return response(
            await application.state.ai.configure(user["user_id"], await body_object(request))
        )

    @application.post("/api/ai/problem-tasks/")
    async def start_ai(request: Request, user=Depends(current_user)):
        value = await body_object(request)
        requirement = text_field(value.get("requirement"), "requirement", maximum=20_000)
        reference = None
        if value.get("problem_id") is not None:
            problem_id = identifier(value["problem_id"], "problem_id")
            reference = await store.get("problems", problem_id)
            if not reference:
                raise APIError(404, "Reference problem not found")
        return response(await application.state.ai.start(user["user_id"], requirement, reference))

    @application.get("/api/ai/problem-tasks/{task_id}")
    async def ai_status(task_id: str, user=Depends(current_user)):
        return response(
            await application.state.ai.get(task_id, user["user_id"], user["role"] == "admin")
        )

    @application.put("/api/ai/problem-tasks/{task_id}/cancel")
    async def cancel_ai(task_id: str, user=Depends(current_user)):
        return response(
            await application.state.ai.cancel(task_id, user["user_id"], user["role"] == "admin")
        )

    @application.post("/api/reset/")
    async def reset(user=Depends(administrator)):
        from oj.ai import AIService

        await cancel_jobs()
        await application.state.ai.close()
        async with mutation:
            await store.clear()
            recent_submissions.clear()
            await initialize_defaults()
            application.state.ai = AIService(
                default_config=load_ai_config() if ai_config is None else ai_config or None
            )
        result = response(None, "system reset successfully")
        result.delete_cookie(COOKIE)
        return result

    return application


app = create_app()
