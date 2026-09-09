"""Persistent revision state machine for iterative AI problem authoring.

This domain layer owns no HTTP routes and no model client.  It coordinates an
injected persistent store with injected ``start/get/cancel`` callbacks so that
each user action creates a distinct, auditable AI task.  Uploaded attachment
bytes are deliberately outside this contract: only immutable id/hash
references may enter a session.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import sys
from typing import Any
import uuid

from oj.common import APIError
from shared.knowledge import KNOWLEDGE_VERSION, knowledge_point
from shared.taxonomy import TAXONOMY_VERSION, difficulty_by_id

SESSION_SCHEMA = "oj.authoring-session.v1"
REQUEST_SCHEMA = "oj.authoring-request.v1"
PROMPT_SCHEMA = "oj.authoring-revision-request.v1"
SESSION_NAMESPACE = "authoring_sessions"
IDEMPOTENCY_NAMESPACE = "authoring_session_idempotency"

ACTIVE_TASK_STATUSES = {"pending", "running"}
TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled", "service_restarted"}
AI_TASK_STATUSES = ACTIVE_TASK_STATUSES | (TERMINAL_TASK_STATUSES - {"service_restarted"})

MAX_REQUIREMENT_CHARS = 20_000
MAX_FREE_PROMPT_CHARS = 10_000
MAX_IMPROVEMENT_CHARS = 10_000
MAX_PROMPT_BYTES = 100_000
MAX_KNOWLEDGE_POINTS = 50
MAX_ATTACHMENTS = 8

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

StartTask = Callable[[str, str, tuple[Mapping[str, str], ...]], Awaitable[Mapping[str, Any]]]
GetTask = Callable[[str, str], Awaitable[Mapping[str, Any]]]
CancelTask = Callable[[str, str], Awaitable[Mapping[str, Any]]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_text(value: Any, field: str, *, maximum: int, required: bool) -> str:
    if not isinstance(value, str):
        raise APIError(400, f"Invalid {field}")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(value) > maximum or (required and not value):
        raise APIError(400, f"Invalid {field}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise APIError(400, f"Invalid {field}") from None
    return value


def _canonical_json(value: Any, *, status: int = 400, message: str = "Invalid value") -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError, RecursionError) as exc:
        raise APIError(status, message) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _owner(value: Any) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise APIError(400, "Invalid session owner")
    return value


def _idempotency_key(value: Any) -> str:
    return _safe_text(value, "idempotency_key", maximum=200, required=True)


def _key_digest(owner_id: str, key: str) -> str:
    return hashlib.sha256(f"{owner_id}\x00{key}".encode("utf-8")).hexdigest()


def _expected_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise APIError(400, "Invalid expected_revision")
    return value


def _attachment_references(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_ATTACHMENTS:
        raise APIError(400, "Invalid attachments")
    result: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"attachment_id", "sha256"}:
            raise APIError(400, "Invalid attachment reference")
        attachment_id, sha256 = item.get("attachment_id"), item.get("sha256")
        if not isinstance(attachment_id, str) or not _IDENTIFIER.fullmatch(attachment_id):
            raise APIError(400, "Invalid attachment reference")
        if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
            raise APIError(400, "Invalid attachment reference")
        if attachment_id in seen_ids:
            raise APIError(400, "Duplicate attachment reference")
        seen_ids.add(attachment_id)
        result.append({"attachment_id": attachment_id, "sha256": sha256})
    return result


def normalize_request(value: Any) -> dict[str, Any]:
    """Validate a structured request without accepting display labels as ids."""

    if not isinstance(value, Mapping):
        raise APIError(400, "Authoring request must be an object")
    allowed = {
        "requirement",
        "knowledge_point_ids",
        "difficulty_id",
        "free_prompt",
        "attachments",
    }
    if set(value) - allowed:
        raise APIError(400, "Authoring request contains unsupported fields")
    requirement = _safe_text(
        value.get("requirement"),
        "requirement",
        maximum=MAX_REQUIREMENT_CHARS,
        required=True,
    )
    free_prompt = _safe_text(
        value.get("free_prompt", ""),
        "free_prompt",
        maximum=MAX_FREE_PROMPT_CHARS,
        required=False,
    )
    point_ids = value.get("knowledge_point_ids", [])
    if not isinstance(point_ids, list) or len(point_ids) > MAX_KNOWLEDGE_POINTS:
        raise APIError(400, "Invalid knowledge_point_ids")
    if any(not isinstance(item, str) for item in point_ids):
        raise APIError(400, "Invalid knowledge_point_ids")
    if len(set(point_ids)) != len(point_ids):
        raise APIError(400, "Duplicate knowledge point")
    points = []
    for point_id in point_ids:
        item = knowledge_point(point_id)
        if item is None:
            raise APIError(400, "Unknown knowledge point")
        points.append(
            {
                "id": str(item["id"]),
                "zh-CN": str(item["zh-CN"]),
                "en": str(item["en"]),
            }
        )
    difficulty_id = value.get("difficulty_id")
    if not isinstance(difficulty_id, str):
        raise APIError(400, "Unknown difficulty")
    difficulty = difficulty_by_id(difficulty_id)
    if difficulty is None:
        raise APIError(400, "Unknown difficulty")
    return {
        "schema_version": REQUEST_SCHEMA,
        "requirement": requirement,
        "knowledge_taxonomy_version": KNOWLEDGE_VERSION,
        "knowledge_points": points,
        "difficulty_taxonomy_version": TAXONOMY_VERSION,
        "difficulty": {
            "id": str(difficulty["id"]),
            "zh-CN": str(difficulty["zh-CN"]),
            "en": str(difficulty["en"]),
        },
        "free_prompt": free_prompt,
        "attachments": _attachment_references(value.get("attachments")),
    }


def _normalize_task(value: Any, *, expected_task_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise APIError(502, "AI task returned invalid state")
    task_id = value.get("task_id")
    status = value.get("status")
    if not isinstance(task_id, str) or not _IDENTIFIER.fullmatch(task_id):
        raise APIError(502, "AI task returned invalid state")
    if expected_task_id is not None and task_id != expected_task_id:
        raise APIError(502, "AI task identity changed")
    if status not in AI_TASK_STATUSES:
        raise APIError(502, "AI task returned invalid state")
    result = value.get("result")
    if result is not None and not isinstance(result, Mapping):
        raise APIError(502, "AI task returned invalid result")
    if status == "completed" and result is None:
        raise APIError(502, "AI task completed without a result")
    progress = value.get("progress", "")
    error = value.get("error")
    error_code = value.get("error_code")
    error_detail = value.get("error_detail")
    for item in (progress, error, error_code, error_detail):
        if item is not None and (not isinstance(item, str) or len(item) > 2_000):
            raise APIError(502, "AI task returned invalid state")
    retryable = value.get("retryable")
    if retryable is not None and not isinstance(retryable, bool):
        raise APIError(502, "AI task returned invalid state")
    provider_calls = value.get("provider_calls", 0)
    if (
        isinstance(provider_calls, bool)
        or not isinstance(provider_calls, int)
        or provider_calls < 0
    ):
        raise APIError(502, "AI task returned invalid usage")
    elapsed = value.get("elapsed_seconds", 0.0)
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(elapsed)
        or elapsed < 0
    ):
        raise APIError(502, "AI task returned invalid state")
    usage = value.get("usage", {})
    if not isinstance(usage, Mapping):
        raise APIError(502, "AI task returned invalid usage")
    task = {
        "task_id": task_id,
        "status": status,
        "progress": progress or "",
        "result": copy.deepcopy(dict(result)) if result is not None else None,
        "error": error,
        "error_code": error_code,
        "retryable": retryable,
        "error_detail": error_detail,
        "provider_calls": provider_calls,
        "usage": copy.deepcopy(dict(usage)),
        "elapsed_seconds": float(elapsed),
    }
    encoded = _canonical_json(task, status=502, message="AI task returned invalid state")
    if len(encoded.encode("utf-8")) > 600_000:
        raise APIError(502, "AI task state exceeds the size limit")
    return task


def _prompt(
    session: Mapping[str, Any] | None,
    *,
    operation: str,
    request: Mapping[str, Any],
    improvement: str | None = None,
) -> tuple[str, dict[str, Any]]:
    original = request if session is None else session["original_request"]
    payload: dict[str, Any] = {
        "schema_version": PROMPT_SCHEMA,
        "operation": operation,
        "original_request": original,
        "current_request": request,
    }
    instruction = "请完整生成一道可判题的标准算法题，并严格保持结构化请求中的原始意图。"
    if operation == "replace_requirements":
        instruction = "请按更新后的要求重新完整命题，同时保留未被更新内容否定的原始意图。"
    elif operation == "refine_draft":
        if session is None or session.get("latest_success_revision") is None:
            raise APIError(409, "No successful draft is available")
        successful = session["revisions"][session["latest_success_revision"] - 1]
        payload["latest_successful_draft"] = successful["task"]["result"]
        payload["improvement"] = improvement
        payload["refinement_history"] = [
            {
                "revision": revision["revision"],
                "improvement": revision["improvement"],
                "status": revision["task"]["status"],
            }
            for revision in session["revisions"]
            if revision["operation"] == "refine_draft"
        ]
        instruction = "请依据改进意见整改上一成功草稿，返回完整题目，且不得丢失原始命题意图。"
    serialized = _canonical_json(payload)
    prompt = f"{instruction}\n结构化命题请求：\n{serialized}"
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise APIError(400, "Authoring revision context is too long")
    return prompt, payload


def _task_usage(revisions: list[Mapping[str, Any]]) -> dict[str, Any]:
    records = [revision["task"] for revision in revisions]
    usages = [task.get("usage", {}) for task in records]
    result: dict[str, Any] = {
        "revision_count": len(revisions),
        "provider_calls": sum(task.get("provider_calls", 0) for task in records),
        "incomplete": any(bool(usage.get("incomplete", False)) for usage in usages),
    }
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        values = [usage.get(field) for usage in usages]
        if any(
            value is None or isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            result[field] = None
        else:
            result[field] = sum(values)
    costs = [usage.get("cost") for usage in usages]
    try:
        if any(
            value is None
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in costs
        ):
            raise InvalidOperation
        total = sum((Decimal(str(value)) for value in costs), Decimal(0))
        result["cost"] = min(float(total), sys.float_info.max)
    except (InvalidOperation, ValueError, OverflowError):
        result["cost"] = None
        result["incomplete"] = True
    currencies = sorted(
        {str(usage["currency"]) for usage in usages if usage.get("currency") not in (None, "")}
    )
    result["currency"] = (
        currencies[0] if len(currencies) == 1 else ("mixed" if currencies else None)
    )
    return result


class AuthoringSessionService:
    """Coordinate persistent owner-only authoring revisions and real AI tasks."""

    def __init__(
        self,
        store: Any,
        *,
        start_task: StartTask,
        get_task: GetTask,
        cancel_task: CancelTask,
        clock: Callable[[], str] | None = None,
        id_factory: Callable[[], str] | None = None,
    ):
        self.store = store
        self.start_task = start_task
        self.get_task = get_task
        self.cancel_task = cancel_task
        self.clock = clock or _now
        self.id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._create_lock = asyncio.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._session_locks.setdefault(session_id, asyncio.Lock())

    @staticmethod
    def _validate_session_id(session_id: Any) -> str:
        if not isinstance(session_id, str) or not _IDENTIFIER.fullmatch(session_id):
            raise APIError(404, "Authoring session not found")
        return session_id

    async def _load(self, session_id: str, owner_id: str) -> dict[str, Any]:
        value = await self.store.get(SESSION_NAMESPACE, session_id)
        if value is None:
            raise APIError(404, "Authoring session not found")
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != SESSION_SCHEMA
            or value.get("session_id") != session_id
            or not isinstance(value.get("revisions"), list)
        ):
            raise APIError(500, "Authoring session data is unavailable")
        if value.get("owner_id") != owner_id:
            raise APIError(403, "Permission denied")
        return value

    @staticmethod
    def _latest_success(session: Mapping[str, Any]) -> tuple[int | None, Any]:
        revision_number = session.get("latest_success_revision")
        if not isinstance(revision_number, int) or not 1 <= revision_number <= len(
            session["revisions"]
        ):
            return None, None
        return revision_number, session["revisions"][revision_number - 1]["task"]["result"]

    def _public(self, session: Mapping[str, Any]) -> dict[str, Any]:
        revision_number, draft = self._latest_success(session)
        return copy.deepcopy(
            {
                "schema_version": SESSION_SCHEMA,
                "session_id": session["session_id"],
                "owner_id": session["owner_id"],
                "created_at": session["created_at"],
                "updated_at": session["updated_at"],
                "status": session["revisions"][-1]["task"]["status"],
                "current_revision": session["current_revision"],
                "latest_success_revision": revision_number,
                "draft": draft,
                "original_request": session["original_request"],
                "current_request": session["current_request"],
                "revisions": session["revisions"],
                "cumulative_usage": _task_usage(session["revisions"]),
            }
        )

    @staticmethod
    def _fingerprint(operation: str, expected: int | None, payload: Any) -> str:
        return _digest({"operation": operation, "expected_revision": expected, "payload": payload})

    @staticmethod
    def _revision(
        *,
        number: int,
        parent: int | None,
        operation: str,
        request: Mapping[str, Any],
        improvement: str | None,
        prompt: str,
        task: Mapping[str, Any],
        timestamp: str,
    ) -> dict[str, Any]:
        return {
            "revision": number,
            "parent_revision": parent,
            "operation": operation,
            "request": copy.deepcopy(dict(request)),
            "improvement": improvement,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "created_at": timestamp,
            "updated_at": timestamp,
            "task": copy.deepcopy(dict(task)),
        }

    @staticmethod
    def _mark_success(session: dict[str, Any], revision: Mapping[str, Any]) -> None:
        if revision["task"]["status"] == "completed":
            session["latest_success_revision"] = revision["revision"]

    async def _compensate_started(self, task: Mapping[str, Any], owner_id: str) -> None:
        if task["status"] not in ACTIVE_TASK_STATUSES:
            return
        try:
            await self.cancel_task(task["task_id"], owner_id)
        except Exception:
            pass

    async def initial(
        self,
        owner_id: str,
        request: Any,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        owner_id = _owner(owner_id)
        normalized = normalize_request(request)
        key = _idempotency_key(idempotency_key)
        key_hash = _key_digest(owner_id, key)
        fingerprint = self._fingerprint("initial", None, normalized)
        prompt, _ = _prompt(None, operation="initial", request=normalized)
        async with self._create_lock:
            existing = await self.store.get(IDEMPOTENCY_NAMESPACE, key_hash)
            if existing is not None:
                if not isinstance(existing, Mapping) or existing.get("fingerprint") != fingerprint:
                    raise APIError(409, "Idempotency key was already used")
                session = await self._load(str(existing.get("session_id")), owner_id)
                return self._public(session)
            session_id = self._validate_session_id(self.id_factory())
            if await self.store.get(SESSION_NAMESPACE, session_id) is not None:
                raise APIError(500, "Authoring session id collision")
            started = _normalize_task(
                await self.start_task(
                    owner_id,
                    prompt,
                    tuple(copy.deepcopy(normalized["attachments"])),
                )
            )
            timestamp = self.clock()
            revision = self._revision(
                number=1,
                parent=None,
                operation="initial",
                request=normalized,
                improvement=None,
                prompt=prompt,
                task=started,
                timestamp=timestamp,
            )
            session = {
                "schema_version": SESSION_SCHEMA,
                "session_id": session_id,
                "owner_id": owner_id,
                "created_at": timestamp,
                "updated_at": timestamp,
                "current_revision": 1,
                "latest_success_revision": None,
                "original_request": normalized,
                "current_request": normalized,
                "revisions": [revision],
                "_idempotency": {key_hash: {"fingerprint": fingerprint, "revision": 1}},
            }
            self._mark_success(session, revision)
            index = {
                "session_id": session_id,
                "owner_id": owner_id,
                "fingerprint": fingerprint,
                "revision": 1,
            }
            try:
                await self.store.write_batch(
                    puts=[
                        (SESSION_NAMESPACE, session_id, session),
                        (IDEMPOTENCY_NAMESPACE, key_hash, index),
                    ]
                )
            except Exception:
                await self._compensate_started(started, owner_id)
                raise
            return self._public(session)

    async def get(self, session_id: str, owner_id: str) -> dict[str, Any]:
        session_id, owner_id = self._validate_session_id(session_id), _owner(owner_id)
        async with self._lock(session_id):
            return self._public(await self._load(session_id, owner_id))

    async def _sync_current(self, session: dict[str, Any]) -> bool:
        revision = session["revisions"][-1]
        current = revision["task"]
        if current["status"] not in ACTIVE_TASK_STATUSES:
            return False
        fresh = _normalize_task(
            await self.get_task(current["task_id"], session["owner_id"]),
            expected_task_id=current["task_id"],
        )
        if fresh == current:
            return False
        revision["task"] = fresh
        timestamp = self.clock()
        revision["updated_at"] = timestamp
        session["updated_at"] = timestamp
        self._mark_success(session, revision)
        return True

    async def poll(self, session_id: str, owner_id: str) -> dict[str, Any]:
        session_id, owner_id = self._validate_session_id(session_id), _owner(owner_id)
        async with self._lock(session_id):
            session = await self._load(session_id, owner_id)
            if await self._sync_current(session):
                await self.store.put(SESSION_NAMESPACE, session_id, session)
            return self._public(session)

    @staticmethod
    def _idempotent_revision(session: Mapping[str, Any], key_hash: str, fingerprint: str) -> bool:
        record = session.get("_idempotency", {}).get(key_hash)
        if record is None:
            return False
        if not isinstance(record, Mapping) or record.get("fingerprint") != fingerprint:
            raise APIError(409, "Idempotency key was already used")
        return True

    async def _cancel_current(self, session: dict[str, Any]) -> None:
        revision = session["revisions"][-1]
        current = revision["task"]
        if current["status"] not in ACTIVE_TASK_STATUSES:
            return
        try:
            cancelled = _normalize_task(
                await self.cancel_task(current["task_id"], session["owner_id"]),
                expected_task_id=current["task_id"],
            )
        except APIError as error:
            if error.status != 409:
                raise
            cancelled = _normalize_task(
                await self.get_task(current["task_id"], session["owner_id"]),
                expected_task_id=current["task_id"],
            )
            if cancelled["status"] in ACTIVE_TASK_STATUSES:
                raise error
        revision["task"] = cancelled
        timestamp = self.clock()
        revision["updated_at"] = timestamp
        session["updated_at"] = timestamp
        self._mark_success(session, revision)
        await self.store.put(SESSION_NAMESPACE, session["session_id"], session)

    async def _append(
        self,
        session: dict[str, Any],
        *,
        operation: str,
        request: Mapping[str, Any],
        improvement: str | None,
        expected_revision: int,
        key_hash: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        if self._idempotent_revision(session, key_hash, fingerprint):
            return self._public(session)
        if session["current_revision"] != expected_revision:
            raise APIError(409, "Authoring session revision conflict")
        if await self._sync_current(session):
            await self.store.put(SESSION_NAMESPACE, session["session_id"], session)
        prompt, _ = _prompt(
            session,
            operation=operation,
            request=request,
            improvement=improvement,
        )
        await self._cancel_current(session)
        started = _normalize_task(
            await self.start_task(
                session["owner_id"],
                prompt,
                tuple(copy.deepcopy(request["attachments"])),
            )
        )
        number = expected_revision + 1
        timestamp = self.clock()
        revision = self._revision(
            number=number,
            parent=expected_revision,
            operation=operation,
            request=request,
            improvement=improvement,
            prompt=prompt,
            task=started,
            timestamp=timestamp,
        )
        session["current_revision"] = number
        session["current_request"] = copy.deepcopy(dict(request))
        session["updated_at"] = timestamp
        session["revisions"].append(revision)
        session.setdefault("_idempotency", {})[key_hash] = {
            "fingerprint": fingerprint,
            "revision": number,
        }
        self._mark_success(session, revision)
        try:
            await self.store.put(SESSION_NAMESPACE, session["session_id"], session)
        except Exception:
            await self._compensate_started(started, session["owner_id"])
            raise
        return self._public(session)

    async def replace_requirements(
        self,
        session_id: str,
        owner_id: str,
        request: Any,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        session_id, owner_id = self._validate_session_id(session_id), _owner(owner_id)
        async with self._lock(session_id):
            session = await self._load(session_id, owner_id)
            normalized = normalize_request(request)
            expected = _expected_revision(expected_revision)
            key_hash = _key_digest(owner_id, _idempotency_key(idempotency_key))
            fingerprint = self._fingerprint("replace_requirements", expected, normalized)
            return await self._append(
                session,
                operation="replace_requirements",
                request=normalized,
                improvement=None,
                expected_revision=expected,
                key_hash=key_hash,
                fingerprint=fingerprint,
            )

    async def refine_draft(
        self,
        session_id: str,
        owner_id: str,
        improvement: Any,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        session_id, owner_id = self._validate_session_id(session_id), _owner(owner_id)
        async with self._lock(session_id):
            session = await self._load(session_id, owner_id)
            normalized_improvement = _safe_text(
                improvement,
                "improvement",
                maximum=MAX_IMPROVEMENT_CHARS,
                required=True,
            )
            expected = _expected_revision(expected_revision)
            key_hash = _key_digest(owner_id, _idempotency_key(idempotency_key))
            fingerprint = self._fingerprint(
                "refine_draft", expected, {"improvement": normalized_improvement}
            )
            if self._idempotent_revision(session, key_hash, fingerprint):
                return self._public(session)
            if session["current_revision"] != expected:
                raise APIError(409, "Authoring session revision conflict")
            if await self._sync_current(session):
                await self.store.put(SESSION_NAMESPACE, session_id, session)
            if session.get("latest_success_revision") is None:
                raise APIError(409, "No successful draft is available")
            return await self._append(
                session,
                operation="refine_draft",
                request=session["current_request"],
                improvement=normalized_improvement,
                expected_revision=expected,
                key_hash=key_hash,
                fingerprint=fingerprint,
            )

    async def recover_after_restart(self) -> int:
        """Seal orphaned active revisions without deleting any task history."""

        async with self._create_lock:
            sessions = await self.store.all(SESSION_NAMESPACE)
            timestamp = self.clock()
            puts = []
            changed = 0
            for session in sessions:
                if not isinstance(session, dict) or session.get("schema_version") != SESSION_SCHEMA:
                    continue
                revisions = session.get("revisions")
                if not isinstance(revisions, list) or not revisions:
                    continue
                revision = revisions[-1]
                task = revision.get("task", {})
                if task.get("status") not in ACTIVE_TASK_STATUSES:
                    continue
                task.update(
                    {
                        "status": "service_restarted",
                        "progress": "The authoring service restarted before this task finished.",
                        "error": "The authoring task was interrupted by a service restart.",
                        "error_code": "service_restarted",
                        "retryable": True,
                    }
                )
                revision["updated_at"] = timestamp
                session["updated_at"] = timestamp
                puts.append((SESSION_NAMESPACE, session["session_id"], session))
                changed += 1
            if puts:
                await self.store.write_batch(puts=puts)
            return changed


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "AuthoringSessionService",
    "IDEMPOTENCY_NAMESPACE",
    "PROMPT_SCHEMA",
    "REQUEST_SCHEMA",
    "SESSION_NAMESPACE",
    "SESSION_SCHEMA",
    "TERMINAL_TASK_STATUSES",
    "normalize_request",
]
