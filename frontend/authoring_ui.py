"""Pure projections for the iterative AI-authoring Streamlit page.

The browser-facing layer intentionally consumes the shared, versioned
knowledge and difficulty registries instead of maintaining display aliases of
its own.  Functions in this module do not call Streamlit or the network, which
makes request/idempotency and accounting behavior deterministic to test.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import re
import sys
from typing import Any

from oj.pricing import resolve_pricing
from shared.knowledge import KNOWLEDGE_POINTS
from shared.taxonomy import DIFFICULTIES

ACTIVE = {"pending", "running"}
TERMINAL = {"completed", "cancelled", "failed", "service_restarted"}
MAX_ATTACHMENTS = 8
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_TOTAL_BYTES = 32 * 1024 * 1024

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PROBLEM_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KNOWLEDGE_BY_ID = {str(item["id"]): item for item in KNOWLEDGE_POINTS}
_DIFFICULTY_BY_ID = {str(item["id"]): item for item in DIFFICULTIES}


def locale_code(locale: Any = None) -> str:
    """Collapse supported locale aliases into the two UI locales."""

    return "en" if str(locale or "").lower().startswith("en") else "zh-CN"


def difficulty_options(locale: Any = None) -> tuple[list[str], dict[str, str]]:
    """Return stable Luogu ids and labels in the selected locale."""

    selected = locale_code(locale)
    identifiers = [str(item["id"]) for item in DIFFICULTIES]
    return identifiers, {str(item["id"]): str(item[selected]) for item in DIFFICULTIES}


def knowledge_options() -> list[str]:
    """Return all shared stable ids in registry order."""

    return [str(item["id"]) for item in KNOWLEDGE_POINTS]


def knowledge_label(value: Any, locale: Any = None) -> str:
    """Localize a registry id while leaving a user-created option unchanged."""

    text = str(value)
    item = _KNOWLEDGE_BY_ID.get(text)
    if item is None:
        return text
    return str(item[locale_code(locale)])


def _attachment_references(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("invalid attachments")
    if len(value) > MAX_ATTACHMENTS:
        raise ValueError("too many attachments")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("invalid attachment reference")
        attachment_id = raw.get("attachment_id")
        sha256 = raw.get("sha256")
        if (
            not isinstance(attachment_id, str)
            or not _IDENTIFIER.fullmatch(attachment_id)
            or not isinstance(sha256, str)
            or not _SHA256.fullmatch(sha256)
            or attachment_id in seen
        ):
            raise ValueError("invalid attachment reference")
        seen.add(attachment_id)
        result.append({"attachment_id": attachment_id, "sha256": sha256})
    return result


def build_authoring_request(
    *,
    requirement: Any,
    difficulty_id: Any,
    knowledge_points: Any,
    free_prompt: Any = "",
    reference_problem_id: Any = "",
    attachments: Any = None,
) -> dict[str, Any]:
    """Build the exact public request shape from native widget values."""

    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("empty requirement")
    requirement = requirement.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(requirement) > 20_000:
        raise ValueError("requirement too long")
    if not isinstance(difficulty_id, str) or difficulty_id not in _DIFFICULTY_BY_ID:
        raise ValueError("invalid difficulty")
    if not isinstance(knowledge_points, Sequence) or isinstance(knowledge_points, (str, bytes)):
        raise ValueError("invalid knowledge points")
    if len(knowledge_points) > 50:
        raise ValueError("too many knowledge points")
    normalized_points: list[str] = []
    custom_points: list[str] = []
    seen_points: set[str] = set()
    for raw in knowledge_points:
        if not isinstance(raw, str):
            raise ValueError("invalid knowledge point")
        point = raw.strip()
        if not point or len(point) > 120:
            raise ValueError("invalid knowledge point")
        # Registry ids are preserved exactly; custom text is deliberately not
        # guessed into a taxonomy id.
        identity = point if point in _KNOWLEDGE_BY_ID else point.casefold()
        if identity in seen_points:
            raise ValueError("duplicate knowledge point")
        seen_points.add(identity)
        if point in _KNOWLEDGE_BY_ID:
            normalized_points.append(point)
        else:
            custom_points.append(point)
    if not isinstance(free_prompt, str):
        raise ValueError("invalid free prompt")
    free_prompt = free_prompt.replace("\r\n", "\n").replace("\r", "\n").strip()
    if custom_points:
        custom_context = "Custom knowledge points: " + json.dumps(
            custom_points, ensure_ascii=False, separators=(",", ":")
        )
        free_prompt = "\n".join(part for part in (free_prompt, custom_context) if part)
    if len(free_prompt) > 10_000:
        raise ValueError("free prompt too long")
    if reference_problem_id is None:
        reference = ""
    elif not isinstance(reference_problem_id, str):
        raise ValueError("invalid reference problem id")
    else:
        reference = reference_problem_id.strip()
    if reference and not _PROBLEM_IDENTIFIER.fullmatch(reference):
        raise ValueError("invalid reference problem id")
    result: dict[str, Any] = {
        "requirement": requirement,
        "difficulty_id": difficulty_id,
        "knowledge_point_ids": normalized_points,
        "free_prompt": free_prompt,
        "attachments": _attachment_references(attachments),
    }
    if reference:
        result["reference_problem_id"] = reference
    return result


def request_defaults(value: Any) -> dict[str, Any]:
    """Project either wire request or normalized domain request into widgets."""

    value = value if isinstance(value, Mapping) else {}
    difficulty = value.get("difficulty_id", value.get("difficulty"))
    if isinstance(difficulty, Mapping):
        difficulty = difficulty.get("id")
    if difficulty not in _DIFFICULTY_BY_ID:
        difficulty = DIFFICULTIES[0]["id"]
    raw_points = value.get("knowledge_point_ids", value.get("knowledge_points", []))
    points = []
    if isinstance(raw_points, Sequence) and not isinstance(raw_points, (str, bytes)):
        for raw in raw_points:
            point = raw.get("id") if isinstance(raw, Mapping) else raw
            if isinstance(point, str) and point.strip() and point not in points:
                points.append(point.strip())
    try:
        attachments = _attachment_references(value.get("attachments", []))
    except ValueError:
        attachments = []
    reference = value.get("reference_problem_id", value.get("problem_id", ""))
    return {
        "requirement": str(value.get("requirement") or ""),
        "difficulty": str(difficulty),
        "knowledge_points": points,
        "free_prompt": str(value.get("free_prompt") or ""),
        "reference_problem_id": str(reference or ""),
        "attachments": attachments,
    }


def current_task(session: Any) -> dict[str, Any]:
    """Return a copy-free, read-only projection of the current revision task."""

    if not isinstance(session, Mapping):
        return {}
    revisions = session.get("revisions")
    if isinstance(revisions, Sequence) and not isinstance(revisions, (str, bytes)) and revisions:
        revision = revisions[-1]
        task = revision.get("task") if isinstance(revision, Mapping) else None
        return dict(task) if isinstance(task, Mapping) else {}
    if isinstance(session.get("task"), Mapping):
        return dict(session["task"])
    # Legacy flat task support.
    if isinstance(session.get("task_id"), str):
        return dict(session)
    return {}


def current_status(session: Any) -> str:
    task = current_task(session)
    status = task.get("status")
    return str(status) if isinstance(status, str) else ""


def last_successful_draft(session: Any) -> tuple[dict[str, Any] | None, str]:
    """Return the durable good draft and its task id, even after a failed turn."""

    if not isinstance(session, Mapping):
        return None, "draft"
    draft = session.get("draft")
    revision_number = session.get("latest_success_revision")
    revisions = session.get("revisions")
    task_id = "draft"
    if (
        isinstance(revision_number, int)
        and isinstance(revisions, Sequence)
        and not isinstance(revisions, (str, bytes))
        and 1 <= revision_number <= len(revisions)
    ):
        revision = revisions[revision_number - 1]
        if isinstance(revision, Mapping) and isinstance(revision.get("task"), Mapping):
            task_id = str(revision["task"].get("task_id") or task_id)
    if isinstance(draft, Mapping):
        return dict(draft), task_id
    task = current_task(session)
    if task.get("status") == "completed" and isinstance(task.get("result"), Mapping):
        return dict(task["result"]), str(task.get("task_id") or task_id)
    return None, task_id


def idempotency_key(
    operation: str,
    payload: Mapping[str, Any],
    *,
    session_id: str = "new",
    expected_revision: int | None = None,
) -> str:
    """Derive a stable retry key without storing raw prompt text in UI state."""

    encoded = json.dumps(
        {
            "operation": operation,
            "session_id": session_id,
            "expected_revision": expected_revision,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"ui-{operation}-{hashlib.sha256(encoded).hexdigest()}"


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def finite_usage(
    usage: Any,
    *,
    prompt_text: str = "",
    pricing: Any = None,
) -> dict[str, Any]:
    """Return finite display values while retaining an explicit estimate bit."""

    usage = usage if isinstance(usage, Mapping) else {}
    pricing = pricing if isinstance(pricing, Mapping) else {}
    input_tokens = _nonnegative_integer(usage.get("input_tokens"))
    output_tokens = _nonnegative_integer(usage.get("output_tokens"))
    total_tokens = _nonnegative_integer(usage.get("total_tokens"))
    estimated = (
        input_tokens is None
        or output_tokens is None
        or total_tokens is None
        or bool(usage.get("incomplete", False))
    )
    if input_tokens is None:
        input_tokens = math.ceil(len(str(prompt_text).encode("utf-8")) / 3)
    if output_tokens is None:
        output_tokens = max(0, (total_tokens or 0) - input_tokens)
    if total_tokens is None:
        total_tokens = input_tokens + output_tokens
    cost = _nonnegative_number(usage.get("cost"))
    if cost is None or (estimated and usage.get("source") in {"zero_before_start", "unavailable"}):
        effective = resolve_pricing(dict(pricing))
        input_price = _nonnegative_number(usage.get("input_price"))
        output_price = _nonnegative_number(usage.get("output_price"))
        unit = _nonnegative_number(usage.get("price_unit"))
        if input_price is None:
            input_price = _nonnegative_number(pricing.get("input_price"))
        if output_price is None:
            output_price = _nonnegative_number(pricing.get("output_price"))
        if unit in (None, 0):
            unit = _nonnegative_number(pricing.get("price_unit"))
        if input_price is None:
            input_price = _nonnegative_number(effective.get("input_price"))
        if output_price is None:
            output_price = _nonnegative_number(effective.get("output_price"))
        if unit in (None, 0):
            unit = _nonnegative_number(effective.get("price_unit"))
        cost = (
            (input_tokens * input_price + output_tokens * output_price) / unit
            if input_price is not None and output_price is not None and unit not in (None, 0)
            else 0.0
        )
        estimated = True
    cost = min(float(cost), sys.float_info.max)
    currency = usage.get("currency") or pricing.get("currency") or "USD"
    if not isinstance(currency, str) or not currency.strip():
        currency = "CNY"
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost": cost,
        "currency": currency.strip()[:16],
        "estimated": estimated or usage.get("source") in {"estimated", "mixed"},
    }


__all__ = [
    "ACTIVE",
    "MAX_ATTACHMENTS",
    "MAX_ATTACHMENT_BYTES",
    "MAX_ATTACHMENT_TOTAL_BYTES",
    "TERMINAL",
    "build_authoring_request",
    "current_status",
    "current_task",
    "difficulty_options",
    "finite_usage",
    "idempotency_key",
    "knowledge_label",
    "knowledge_options",
    "last_successful_draft",
    "locale_code",
    "request_defaults",
]
