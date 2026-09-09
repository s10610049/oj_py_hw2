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
from starlette.requests import ClientDisconnect

from oj.authoring_adapter import AuthoringTaskAdapter
from oj.authoring_sessions import AuthoringSessionService
from oj.chat import (
    ChatError,
    ProgrammingChatService,
    build_programming_context,
    build_programming_focus,
    localize_programming_context,
    prepare_programming_focus,
)
from oj.common import APIError, response
from oj.progress import (
    build_admin_learning_overview,
    build_progress_payloads,
    problem_version_digest,
)
from oj.schemas import identifier, paginate, pagination, text_field, validate_problem
from oj.store import Store
from oj.translations import (
    embedded_english_translation,
    localized_content,
    make_translation_record,
    normalize_locale,
    translation_key,
    validate_translation,
)
from shared.knowledge import KNOWLEDGE_CATEGORIES, KNOWLEDGE_POINTS, KNOWLEDGE_VERSION
from shared.taxonomy import (
    DIFFICULTIES,
    TAXONOMY_VERSION,
    migrated_difficulty_label,
    normalize_difficulty,
)

COOKIE = "oj_session"
SESSION_SECONDS = 24 * 3600
ATTACHMENT_TTL_SECONDS = 3600
IMPORT_TTL_SECONDS = 3600
MAX_JSON_BODY_BYTES = 8_000_000
MAX_IMPORT_UPLOAD_BYTES = 16 * 1024 * 1024


def new_id():
    return uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def password_bytes(password):
    # bcrypt's 72-byte limit must not silently truncate long/unicode passwords.
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


async def read_body(request, maximum=MAX_JSON_BODY_BYTES):
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > maximum:
            raise APIError(400, "Request body is too large")
        chunks.extend(chunk)
    return bytes(chunks)


def expires_at(seconds):
    return datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat(timespec="seconds")


async def body_object(request):
    if getattr(request.state, "body_error", None):
        raise request.state.body_error
    chunks = getattr(request.state, "buffered_body", None)
    if chunks is None:
        chunks = await read_body(request)
    try:
        value = json.loads(chunks)
    except (ValueError, UnicodeError, RecursionError):
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
    lifecycle = asyncio.Lock()
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

        # R-044: migrate the project's former three-tier labels to the current
        # Luogu taxonomy.  Difficulty is display metadata, so submissions that
        # exactly matched the old problem version move to the equivalent new
        # digest; already-outdated or unknown versions stay historical.
        snapshot = await store.snapshot("problems", "submissions")
        problem_updates = []
        current_version_updates = {}
        for problem in snapshot["problems"]:
            canonical = migrated_difficulty_label(problem.get("difficulty", ""))
            if canonical is None or canonical == problem.get("difficulty"):
                continue
            old_digest = problem_version_digest(problem)
            updated = {**problem, "difficulty": canonical}
            new_digest = problem_version_digest(updated)
            problem_updates.append(("problems", problem["id"], updated))
            current_version_updates[(problem["id"], old_digest)] = (new_digest, canonical)

        submission_updates = []
        for submission in snapshot["submissions"]:
            updated = None
            version_update = current_version_updates.get(
                (submission.get("problem_id"), submission.get("problem_version"))
            )
            if version_update is not None:
                updated = {**submission, "problem_version": version_update[0]}
            canonical_snapshot = migrated_difficulty_label(submission.get("difficulty_raw", ""))
            if canonical_snapshot is not None:
                updated = {**(updated or submission), "difficulty_raw": canonical_snapshot}
            if updated is not None:
                submission_updates.append(("submissions", submission["submission_id"], updated))

        if problem_updates or submission_updates:
            await store.write_batch(puts=[*problem_updates, *submission_updates])

    async def cancel_jobs():
        running = list(jobs.values())
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        jobs.clear()

    async def install_assistant_services(application):
        from oj.ai import AIService

        ai = AIService(
            default_config=load_ai_config() if ai_config is None else ai_config or None,
            evidence_directory=(
                "runtime/authoring-evidence" if os.environ.get("OJ_AI_EVIDENCE") == "1" else None
            ),
        )
        adapter = AuthoringTaskAdapter(store, ai)
        authoring = AuthoringSessionService(
            store,
            start_task=adapter.start,
            get_task=adapter.get,
            cancel_task=adapter.cancel,
        )
        chat = ProgrammingChatService(store)
        application.state.ai = ai
        application.state.authoring = authoring
        application.state.chat = chat
        await authoring.recover_after_restart()
        await chat.initialize()

    @asynccontextmanager
    async def lifespan(application):
        await store.initialize()
        await initialize_defaults()
        for submission in await store.all("submissions"):
            if submission["status"] == "pending":
                submission.update(status="error", error_info="评测被服务重启中断，请重新评测")
                await store.put("submissions", submission["submission_id"], submission)
        await install_assistant_services(application)
        yield
        await cancel_jobs()
        await application.state.chat.close()
        await application.state.authoring.close()
        await application.state.ai.close()

    application = FastAPI(title="OJ · 编程练习室", version="1.0.0", lifespan=lifespan)
    application.state.store = store
    application.state.jobs = jobs

    @application.middleware("http")
    async def serialize_mutations(request, call_next):
        writes = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if writes:
            # Untrusted/slow uploads must never hold the lifecycle lock. Delay
            # validation errors until AFTER route authentication (401 > 403 > 400).
            try:
                upload_limits = {
                    "/api/attachments/": 10 * 1024 * 1024,
                    "/api/problem-imports/uploads/": MAX_IMPORT_UPLOAD_BYTES,
                }
                request.state.buffered_body = await asyncio.wait_for(
                    read_body(request, upload_limits.get(request.url.path, MAX_JSON_BODY_BYTES)),
                    10,
                )
            except APIError as error:
                request.state.body_error = error
            except (asyncio.TimeoutError, ClientDisconnect):
                request.state.body_error = APIError(400, "Request body incomplete or timed out")
        if request.method == "PUT" and request.url.path == "/api/ai/model-config":
            # DNS/configuration may wait on the network; bind to this service
            # generation instead of blocking unrelated cancellation or reset.
            request.state.ai_service = application.state.ai
            return await call_next(request)
        if (
            writes
            or request.url.path.endswith("/log")
            or request.url.path.startswith("/api/ai/authoring-sessions/")
        ):
            # Authentication happens inside this lock, so a reset invalidates
            # sessions for any delayed upload before it can reach a mutation.
            async with lifecycle:
                return await call_next(request)
        return await call_next(request)

    async def raw_body(request):
        if getattr(request.state, "body_error", None):
            raise request.state.body_error
        buffered = getattr(request.state, "buffered_body", None)
        return buffered if buffered is not None else await read_body(request)

    @application.exception_handler(ChatError)
    async def expected_chat_error(request, exc):
        return response(
            {"error_code": exc.error_code, "retryable": exc.retryable}, exc.message, exc.status
        )

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

    def structured_failure(error, *, status=400):
        data = {"error_code": error.code}
        field = getattr(error, "field", None)
        if field is not None:
            data["field"] = field
        return response(data, error.message, status)

    async def owned_temporary(namespace, key, owner):
        record = await store.get(namespace, key)
        if (
            not record
            or record.get("owner") != owner
            or type(record.get("expires_epoch")) not in (int, float)
            or record["expires_epoch"] <= time.time()
        ):
            raise APIError(404, "Temporary resource not found or expired")
        return record

    async def purge_expired(namespace):
        current = time.time()
        for record in await store.all(namespace):
            if (
                type(record.get("expires_epoch")) in (int, float)
                and record["expires_epoch"] <= current
            ):
                await store.delete(namespace, record["id"])

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

    @application.post("/api/attachments/")
    async def upload_attachment(request: Request, user=Depends(current_user)):
        from oj.attachments import AttachmentError, parse_attachment

        filename = text_field(
            request.query_params.get("filename"), "filename", minimum=1, maximum=255
        )
        media_type = request.query_params.get("media_type") or request.headers.get(
            "content-type", ""
        )
        content = await raw_body(request)
        attachment_id = new_id()
        created = now()
        expires = expires_at(ATTACHMENT_TTL_SECONDS)
        try:
            parsed = await asyncio.to_thread(
                parse_attachment,
                content,
                filename=filename,
                media_type=media_type,
                attachment_id=attachment_id,
                created_at=created,
                expires_at=expires,
                vision_available=False,
            )
        except AttachmentError as error:
            return structured_failure(error)
        await purge_expired("attachments")
        await store.put(
            "attachments",
            attachment_id,
            {
                **parsed.as_dict(),
                "id": attachment_id,
                "owner": user["user_id"],
                "expires_epoch": time.time() + ATTACHMENT_TTL_SECONDS,
                "extracted_text": parsed.extracted_text,
            },
        )
        return response(parsed.as_dict(), "attachment ready")

    @application.get("/api/attachments/")
    async def list_attachments(user=Depends(current_user)):
        records = [
            record
            for record in await store.all("attachments")
            if record.get("owner") == user["user_id"]
            and record.get("expires_epoch", 0) > time.time()
        ]
        records.sort(key=lambda item: (item.get("created_at", ""), item.get("id", "")))
        private = {"id", "owner", "expires_epoch", "extracted_text"}
        return response(
            [{k: v for k, v in record.items() if k not in private} for record in records]
        )

    @application.get("/api/attachments/{attachment_id}")
    async def attachment_info(attachment_id: str, user=Depends(current_user)):
        attachment_id = identifier(attachment_id, "attachment_id")
        record = await owned_temporary("attachments", attachment_id, user["user_id"])
        private = {"id", "owner", "expires_epoch", "extracted_text"}
        return response({k: v for k, v in record.items() if k not in private})

    @application.delete("/api/attachments/{attachment_id}")
    async def delete_attachment(attachment_id: str, user=Depends(current_user)):
        attachment_id = identifier(attachment_id, "attachment_id")
        await owned_temporary("attachments", attachment_id, user["user_id"])
        await store.delete("attachments", attachment_id)
        return response({"attachment_id": attachment_id}, "attachment deleted")

    @application.post("/api/problem-imports/uploads/")
    async def upload_problem_archive(request: Request, user=Depends(current_user)):
        filename = text_field(
            request.query_params.get("filename"), "filename", minimum=1, maximum=255
        )
        media_type = (
            (request.query_params.get("media_type") or request.headers.get("content-type", ""))
            .partition(";")[0]
            .strip()
            .casefold()
        )
        if not filename.casefold().endswith(".zip") or media_type not in {
            "application/zip",
            "application/x-zip-compressed",
        }:
            raise APIError(400, "Problem archive must be a ZIP file")
        content = await raw_body(request)
        if not content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            raise APIError(400, "Problem archive signature is invalid")
        await purge_expired("problem_import_uploads")
        upload_id = new_id()
        created = now()
        expires = expires_at(IMPORT_TTL_SECONDS)
        await store.put(
            "problem_import_uploads",
            upload_id,
            {
                "id": upload_id,
                "owner": user["user_id"],
                "filename": filename,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "created_at": created,
                "expires_at": expires,
                "expires_epoch": time.time() + IMPORT_TTL_SECONDS,
                "raw_base64": base64.b64encode(content).decode("ascii"),
            },
        )
        return response(
            {
                "schema_version": "oj.problem-import-upload.v1",
                "upload_id": upload_id,
                "filename": filename,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "created_at": created,
                "expires_at": expires,
            },
            "archive uploaded",
        )

    @application.post("/api/problem-imports/previews/")
    async def preview_problem_archive(request: Request, user=Depends(current_user)):
        from oj.problem_import import ImportError as ProblemImportError
        from oj.problem_import import parse_problem_archive

        value = await body_object(request)
        upload_id = identifier(value.get("upload_id"), "upload_id")
        source_format = text_field(
            value.get("source_format"), "source_format", minimum=1, maximum=40
        )
        metadata = value.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise APIError(400, "Import metadata must be an object")
        upload = await owned_temporary("problem_import_uploads", upload_id, user["user_id"])
        try:
            archive = base64.b64decode(upload["raw_base64"], validate=True)
        except (KeyError, ValueError):
            raise APIError(500, "Stored problem archive is unavailable") from None
        try:
            if source_format == "luogu-flat-v1":
                import yaml

                parsed = await asyncio.to_thread(
                    parse_problem_archive,
                    archive,
                    source_format=source_format,
                    metadata=metadata,
                    config_loader=yaml.safe_load,
                )
            else:
                parsed = await asyncio.to_thread(
                    parse_problem_archive,
                    archive,
                    source_format=source_format,
                    metadata=metadata,
                )
        except ProblemImportError as error:
            return structured_failure(error)
        problem_id = parsed.problem.get("id")
        existing = await store.get("problems", problem_id) if problem_id else None
        current_digest = problem_version_digest(existing) if existing else None
        preview_id = new_id()
        expiry_epoch = time.time() + IMPORT_TTL_SECONDS
        expiry = datetime.fromtimestamp(expiry_epoch, timezone.utc).isoformat(timespec="seconds")
        public_preview = parsed.make_preview(
            preview_id=preview_id,
            expires_at=expiry,
            conflict_exists=existing is not None,
            current_digest=current_digest,
        )
        await purge_expired("problem_import_previews")
        await store.put(
            "problem_import_previews",
            preview_id,
            {
                "id": preview_id,
                "owner": user["user_id"],
                "upload_id": upload_id,
                "expires_at": expiry,
                "expires_epoch": expiry_epoch,
                "status": "ready",
                "parsed_can_commit": parsed.can_commit,
                "problem": dict(parsed.problem),
                "public_preview": public_preview,
            },
        )
        return response(public_preview, "import preview ready")

    @application.get("/api/problem-imports/previews/{preview_id}")
    async def problem_import_preview(preview_id: str, user=Depends(current_user)):
        preview_id = identifier(preview_id, "preview_id")
        record = await owned_temporary("problem_import_previews", preview_id, user["user_id"])
        if record.get("status") == "committed":
            return response(
                {**record["public_preview"], "status": "committed", "result": record["result"]}
            )
        return response(record["public_preview"])

    @application.post("/api/problem-imports/previews/{preview_id}/commit")
    async def commit_problem_import(preview_id: str, request: Request, user=Depends(current_user)):
        preview_id = identifier(preview_id, "preview_id")
        value = await body_object(request)
        overwrite = value.get("overwrite", False)
        expected_digest = value.get("expected_digest")
        if not isinstance(overwrite, bool) or (
            expected_digest is not None and not isinstance(expected_digest, str)
        ):
            raise APIError(400, "Invalid import confirmation")
        record = await owned_temporary("problem_import_previews", preview_id, user["user_id"])
        if record.get("status") == "committed":
            return response(record["result"], "archive already committed")
        if not record.get("parsed_can_commit"):
            raise APIError(400, "Import preview has missing required fields")
        problem = validate_problem(record.get("problem"))
        embedded = embedded_english_translation(record.get("problem"))
        async with mutation:
            existing = await store.get("problems", problem["id"])
            current_digest = problem_version_digest(existing) if existing else None
            preview_conflict = record["public_preview"].get("conflict", {})
            if existing:
                if not overwrite:
                    raise APIError(409, "Problem already exists; confirm overwrite")
                if (
                    not expected_digest
                    or expected_digest != preview_conflict.get("current_digest")
                    or expected_digest != current_digest
                ):
                    raise APIError(409, "Problem changed after preview; preview again")
            elif expected_digest is not None:
                raise APIError(409, "Problem conflict no longer exists; preview again")
            stored_problem = {
                **problem,
                "public_cases": existing.get("public_cases", False) if existing else False,
            }
            result = {
                "problem_id": problem["id"],
                "problem_version": problem_version_digest(stored_problem),
                "created": existing is None,
                "translation_imported": embedded is not None,
            }
            record = {**record, "status": "committed", "result": result}
            puts = [
                ("problems", problem["id"], stored_problem),
                ("problem_import_previews", preview_id, record),
            ]
            if embedded is not None:
                puts.append(
                    (
                        "problem_translations",
                        translation_key(problem["id"]),
                        make_translation_record(
                            stored_problem,
                            embedded,
                            source="import",
                            updated_at=now(),
                        ),
                    )
                )
            await store.write_batch(
                puts=puts,
                deletes=[("problem_import_uploads", record["upload_id"])],
            )
        return response(result, "problem archive committed")

    @application.get("/api/problems/")
    async def problems(request: Request, user=Depends(current_user)):
        locale = normalize_locale(request.query_params.get("locale"))
        snapshot = await store.snapshot("problems", "problem_translations")
        translations = {
            item.get("problem_id"): item
            for item in snapshot["problem_translations"]
            if item.get("locale") == "en"
        }
        return response(
            [
                {
                    **{
                        key: problem.get(key, "")
                        for key in ("id", "title", "difficulty", "tags", "source")
                    },
                    "content": localized_content(
                        problem, locale, translations.get(problem.get("id"))
                    ),
                }
                for problem in snapshot["problems"]
            ]
        )

    def progress_from_snapshot(snapshot, user):
        try:
            return build_progress_payloads(
                snapshot["problems"],
                snapshot["submissions"],
                user["user_id"],
                difficulty_normalizer=normalize_difficulty,
                generated_at=now(),
            )
        except (TypeError, ValueError, KeyError, OverflowError):
            # Corrupt timestamps or aggregates must fail atomically and must not
            # expose raw stored documents, code or hidden cases.
            raise APIError(500, "Learning progress could not be calculated") from None

    async def personal_progress(user):
        snapshot = await store.snapshot("problems", "submissions")
        return progress_from_snapshot(snapshot, user)

    def localize_statistics_titles(snapshot, statistics, locale):
        """Add a safe display title without changing version-sensitive facts."""

        translations = {
            item.get("problem_id"): item
            for item in snapshot.get("problem_translations", [])
            if item.get("locale") == "en"
        }
        problems_by_id = {problem.get("id"): problem for problem in snapshot.get("problems", [])}
        for row in statistics.get("problems", []):
            problem = problems_by_id.get(row.get("problem_id"))
            if problem is None:
                continue
            content = localized_content(problem, locale, translations.get(problem.get("id")))
            ready = content.get("status") == "ready" and content.get("resolved_locale") == locale
            fields = content.get("fields") if isinstance(content.get("fields"), dict) else {}
            row["display_title"] = str(fields.get("title", "")) if ready else None
            row["title_translation_status"] = str(content.get("status", "missing"))
        statistics["display_locale"] = locale
        return statistics

    @application.get("/api/me/problem-statuses/")
    async def personal_problem_statuses(user=Depends(current_user)):
        statuses, _ = await personal_progress(user)
        return response(statuses)

    @application.get("/api/me/learning-stats/")
    async def personal_learning_stats(request: Request, user=Depends(current_user)):
        locale = normalize_locale(request.query_params.get("locale"))
        snapshot = await store.snapshot("problems", "submissions", "problem_translations")
        _, statistics = progress_from_snapshot(snapshot, user)
        return response(localize_statistics_titles(snapshot, statistics, locale))

    @application.get("/api/admin/learning-overview/")
    async def admin_learning_overview(user=Depends(administrator)):
        snapshot = await store.snapshot("users", "problems", "submissions")
        try:
            overview = build_admin_learning_overview(
                snapshot["users"],
                snapshot["problems"],
                snapshot["submissions"],
                difficulty_normalizer=normalize_difficulty,
                generated_at=now(),
            )
        except (TypeError, ValueError, KeyError, OverflowError):
            # Keep malformed aggregate data behind the same fail-closed privacy
            # boundary as the personal statistics endpoints.
            raise APIError(500, "Administrator overview could not be calculated") from None
        return response(overview)

    @application.post("/api/problems/")
    async def add_problem(request: Request, user=Depends(current_user)):
        value = await body_object(request)
        problem = validate_problem(value)
        embedded = embedded_english_translation(value)
        async with mutation:
            if await store.get("problems", problem["id"]):
                raise APIError(409, "Problem already exists")
            stored_problem = {**problem, "public_cases": False}
            puts = [("problems", problem["id"], stored_problem)]
            if embedded is not None:
                puts.append(
                    (
                        "problem_translations",
                        translation_key(problem["id"]),
                        make_translation_record(
                            stored_problem, embedded, source="manual", updated_at=now()
                        ),
                    )
                )
            await store.write_batch(puts=puts)
        return response({"id": problem["id"]}, "add success")

    @application.get("/api/problems/{problem_id}")
    async def problem_info(problem_id: str, request: Request, user=Depends(current_user)):
        locale = normalize_locale(request.query_params.get("locale"))
        record = await store.get("problems", problem_id)
        if not record:
            raise APIError(404, "Problem not found")
        translation = (
            await store.get("problem_translations", translation_key(problem_id))
            if locale == "en"
            else None
        )
        return response({**record, "content": localized_content(record, locale, translation)})

    @application.put("/api/problems/{problem_id}")
    async def edit_problem(problem_id: str, request: Request, user=Depends(current_user)):
        value = await body_object(request)
        problem = validate_problem(value)
        embedded = embedded_english_translation(value)
        if problem["id"] != problem_id:
            raise APIError(400, "Problem id must match URL")
        async with mutation:
            existing = await store.get("problems", problem_id)
            if not existing:
                raise APIError(404, "Problem not found")
            stored_problem = {
                **problem,
                "public_cases": existing.get("public_cases", False),
            }
            puts = [("problems", problem_id, stored_problem)]
            if embedded is not None:
                puts.append(
                    (
                        "problem_translations",
                        translation_key(problem_id),
                        make_translation_record(
                            stored_problem, embedded, source="manual", updated_at=now()
                        ),
                    )
                )
            await store.write_batch(puts=puts)
        return response({"id": problem_id}, "update success")

    @application.put("/api/problems/{problem_id}/translations/en")
    async def put_problem_translation(
        problem_id: str, request: Request, user=Depends(current_user)
    ):
        value = validate_translation(await body_object(request))
        async with mutation:
            problem = await store.get("problems", problem_id)
            if not problem:
                raise APIError(404, "Problem not found")
            record = make_translation_record(problem, value, source="manual", updated_at=now())
            await store.put("problem_translations", translation_key(problem_id), record)
        return response(localized_content(problem, "en", record), "translation updated")

    @application.delete("/api/problems/{problem_id}/translations/en")
    async def delete_problem_translation(problem_id: str, user=Depends(current_user)):
        if not await store.get("problems", problem_id):
            raise APIError(404, "Problem not found")
        await store.delete("problem_translations", translation_key(problem_id))
        return response({"problem_id": problem_id, "locale": "en"}, "translation deleted")

    @application.delete("/api/problems/{problem_id}")
    async def delete_problem(problem_id: str, user=Depends(administrator)):
        async with mutation:
            if not await store.get("problems", problem_id):
                raise APIError(404, "Problem not found")
            await store.write_batch(
                deletes=[
                    ("problems", problem_id),
                    ("problem_translations", translation_key(problem_id)),
                ]
            )
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
                "problem_version": problem_version_digest(problem),
                "problem_title": problem["title"],
                "difficulty_raw": problem.get("difficulty", ""),
                "tags_snapshot": list(problem.get("tags") or []),
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
        # Validate dependencies before stopping a valid in-flight snapshot.
        record = await store.get("submissions", submission_id)
        if not record:
            raise APIError(404, "Submission not found")
        problem = await store.get("problems", record["problem_id"])
        language = await store.get("languages", record["language"])
        if not problem or not language:
            raise APIError(404, "Problem or language no longer exists")
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
                problem_version=problem_version_digest(problem),
                problem_title=problem["title"],
                difficulty_raw=problem.get("difficulty", ""),
                tags_snapshot=list(problem.get("tags") or []),
                version_inferred=False,
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
        return response(
            {"problem_id": problem_id, "public_cases": public}, "log visibility updated"
        )

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
        service = request.state.ai_service
        result = await service.configure(user["user_id"], await body_object(request))
        if service is not application.state.ai:
            raise APIError(409, "Configuration invalidated by reset; please log in again")
        return response(result)

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

    @application.get("/api/ai/authoring-options/")
    async def authoring_options(user=Depends(current_user)):
        return response(
            {
                "difficulty_taxonomy_version": TAXONOMY_VERSION,
                "difficulties": [dict(item) for item in DIFFICULTIES],
                "knowledge_taxonomy_version": KNOWLEDGE_VERSION,
                "knowledge_categories": [dict(item) for item in KNOWLEDGE_CATEGORIES],
                "knowledge_points": [dict(item) for item in KNOWLEDGE_POINTS],
            }
        )

    @application.post("/api/ai/authoring-sessions/")
    async def start_authoring_session(request: Request, user=Depends(current_user)):
        value = await body_object(request)
        return response(
            await application.state.authoring.initial(
                user["user_id"],
                value.get("request"),
                idempotency_key=value.get("idempotency_key"),
            )
        )

    @application.get("/api/ai/authoring-sessions/{session_id}")
    async def authoring_session_status(session_id: str, user=Depends(current_user)):
        return response(await application.state.authoring.poll(session_id, user["user_id"]))

    @application.post("/api/ai/authoring-sessions/{session_id}/requirements")
    async def replace_authoring_requirements(
        session_id: str, request: Request, user=Depends(current_user)
    ):
        value = await body_object(request)
        return response(
            await application.state.authoring.replace_requirements(
                session_id,
                user["user_id"],
                value.get("request"),
                expected_revision=value.get("expected_revision"),
                idempotency_key=value.get("idempotency_key"),
            )
        )

    @application.post("/api/ai/authoring-sessions/{session_id}/refinements")
    async def refine_authoring_draft(session_id: str, request: Request, user=Depends(current_user)):
        value = await body_object(request)
        improvement = value.get("improvement", value.get("instruction"))
        return response(
            await application.state.authoring.refine_draft(
                session_id,
                user["user_id"],
                improvement,
                expected_revision=value.get("expected_revision"),
                idempotency_key=value.get("idempotency_key"),
                base_revision=value.get("base_revision"),
            )
        )

    @application.delete("/api/ai/authoring-sessions/{session_id}/active-task")
    async def cancel_authoring_task(session_id: str, user=Depends(current_user)):
        return response(
            await application.state.authoring.cancel_active(session_id, user["user_id"])
        )

    @application.get("/api/chat/sessions/")
    async def chat_sessions(user=Depends(current_user)):
        return response(await application.state.chat.list_sessions(user["user_id"]))

    @application.post("/api/chat/sessions/")
    async def create_chat_session(request: Request, user=Depends(current_user)):
        value = await body_object(request)
        locale = normalize_locale(value.get("locale"))
        return response(
            await application.state.chat.create_session(
                user["user_id"], value.get("title"), locale=locale
            )
        )

    @application.get("/api/chat/sessions/{session_id}")
    async def chat_session(session_id: str, user=Depends(current_user)):
        return response(await application.state.chat.get_session(session_id, user["user_id"]))

    @application.delete("/api/chat/sessions/{session_id}")
    async def delete_chat_session(session_id: str, user=Depends(current_user)):
        return response(await application.state.chat.delete_session(session_id, user["user_id"]))

    @application.get("/api/chat/sessions/{session_id}/turns/")
    async def chat_turns(session_id: str, user=Depends(current_user)):
        return response(await application.state.chat.list_turns(session_id, user["user_id"]))

    @application.post("/api/chat/sessions/{session_id}/turns/")
    async def create_chat_turn(session_id: str, request: Request, user=Depends(current_user)):
        value = await body_object(request)
        prepared_focus, focus_digest = prepare_programming_focus(value.get("focus"))
        replayed = await application.state.chat.replay_turn(
            session_id,
            user["user_id"],
            value.get("message"),
            expected_context_epoch=value.get("expected_context_epoch"),
            idempotency_key=value.get("idempotency_key"),
            focus_digest=focus_digest,
        )
        if replayed is not None:
            return response(replayed)

        chat_session = await application.state.chat.get_session(session_id, user["user_id"])
        chat_locale = chat_session.get("locale", "zh-CN")
        translation_snapshot = (
            await store.all("problem_translations") if chat_locale == "en" else []
        )

        # Build one coherent progress/focus handoff.  The final comparison is
        # made while holding the same lock used by problem/submission writers,
        # closing the last race before the turn is accepted.  A single retry
        # absorbs an in-flight judge completion without spinning indefinitely.
        for attempt in range(2):
            snapshot = await store.snapshot("problems", "submissions")
            statuses, statistics = progress_from_snapshot(snapshot, user)
            context = build_programming_context(statuses, statistics)
            context = localize_programming_context(
                context,
                snapshot["problems"],
                translation_snapshot,
                chat_locale,
            )
            focus = build_programming_focus(
                prepared_focus,
                focus_digest,
                snapshot["problems"],
                snapshot["submissions"],
                user["user_id"],
                locale=chat_locale,
                translations=translation_snapshot,
            )
            async with mutation:
                latest = await store.snapshot("problems", "submissions")
                latest_statuses, _ = progress_from_snapshot(latest, user)
                if latest_statuses["context_epoch"] != statuses["context_epoch"]:
                    if attempt == 0:
                        continue
                    raise ChatError(
                        409,
                        "学习进度正在更新，请刷新后重新发送",
                        "context_epoch_mismatch",
                        retryable=True,
                    )
                turn = await application.state.chat.create_turn(
                    session_id,
                    user["user_id"],
                    value.get("message"),
                    expected_context_epoch=value.get("expected_context_epoch"),
                    context=context,
                    config=application.state.ai.private_config(user["user_id"]),
                    idempotency_key=value.get("idempotency_key"),
                    focus=focus,
                )
                return response(turn)

        raise ChatError(
            409,
            "学习进度正在更新，请刷新后重新发送",
            "context_epoch_mismatch",
            retryable=True,
        )

    async def owned_chat_turn(session_id, turn_id, user):
        turn = await application.state.chat.get_turn(turn_id, user["user_id"])
        if turn.get("session_id") != session_id:
            raise ChatError(404, "回答任务不存在", "chat_turn_not_found")
        return turn

    @application.get("/api/chat/sessions/{session_id}/turns/{turn_id}")
    async def chat_turn(session_id: str, turn_id: str, user=Depends(current_user)):
        return response(await owned_chat_turn(session_id, turn_id, user))

    @application.delete("/api/chat/sessions/{session_id}/turns/{turn_id}")
    async def cancel_chat_turn(session_id: str, turn_id: str, user=Depends(current_user)):
        await owned_chat_turn(session_id, turn_id, user)
        return response(await application.state.chat.cancel_turn(turn_id, user["user_id"]))

    @application.post("/api/reset/")
    async def reset(user=Depends(administrator)):
        await cancel_jobs()
        await application.state.chat.close()
        await application.state.authoring.close()
        await application.state.ai.close()
        async with mutation:
            await store.clear()
            recent_submissions.clear()
            await initialize_defaults()
            await install_assistant_services(application)
        result = response(None, "system reset successfully")
        result.delete_cookie(COOKIE)
        return result

    return application


app = create_app()
