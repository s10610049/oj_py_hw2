"""Versioned, additive problem-statement translation contracts.

The canonical problem remains Chinese and judge data is never translated.  A
translation is accepted only when it covers every prose field and matches the
current source digest; stale or missing records fall back explicitly instead
of silently presenting a mixed-language statement.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from oj.common import APIError
from oj.schemas import text_field

CONTENT_SCHEMA = "oj.problem-content.v2"
LEGACY_CONTENT_SCHEMA = "oj.problem-content.v1"
TRANSLATION_SCHEMA = "oj.problem-translation.v1"
SUPPORTED_LOCALES = ("zh-CN", "en")
TRANSLATABLE_FIELDS = (
    "title",
    "description",
    "input_description",
    "output_description",
    "constraints",
    "hint",
)
TRANSLATION_SOURCES = {"manual", "import", "ai", "seed"}

_CJK = tuple(
    (start, end)
    for start, end in (
        (0x3400, 0x4DBF),
        (0x4E00, 0x9FFF),
        (0xF900, 0xFAFF),
        (0x20000, 0x2FA1F),
    )
)


def _contains_cjk(value: str) -> bool:
    return any(start <= ord(character) <= end for character in value for start, end in _CJK)


def normalize_locale(value: Any) -> str:
    """Accept only the two public locale identifiers and common exact aliases."""

    if value is None or value == "":
        return "zh-CN"
    if not isinstance(value, str):
        raise APIError(400, "Invalid locale")
    aliases = {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "zh-CN": "zh-CN",
        "en": "en",
        "en-us": "en",
        "en-US": "en",
    }
    locale = aliases.get(value.strip())
    if locale is None:
        raise APIError(400, "Unsupported locale")
    return locale


def source_digest(problem: Mapping[str, Any]) -> str:
    """Hash only prose that can make an existing translation stale."""

    projection = {field: problem.get(field, "") for field in TRANSLATABLE_FIELDS}
    try:
        encoded = json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError) as error:
        raise APIError(500, "Problem content is unavailable") from error
    return hashlib.sha256(encoded).hexdigest()


def validate_translation(value: Any) -> dict[str, str]:
    """Validate one complete, English-only prose translation without judge fields."""

    if not isinstance(value, Mapping):
        raise APIError(400, "Translation must be an object")
    unsupported = set(value) - set(TRANSLATABLE_FIELDS)
    if unsupported:
        raise APIError(400, "Translation contains unsupported fields")
    result = {}
    for field in TRANSLATABLE_FIELDS:
        result[field] = text_field(
            value.get(field, ""),
            f"translation.{field}",
            minimum=0 if field == "hint" else 1,
        )
        if _contains_cjk(result[field]):
            raise APIError(400, f"Translation field {field} must be English")
    return result


def make_translation_record(
    problem: Mapping[str, Any],
    content: Any,
    *,
    locale: str = "en",
    source: str,
    updated_at: str,
) -> dict[str, Any]:
    """Create a persistence-ready record tied to the canonical prose digest."""

    locale = normalize_locale(locale)
    if locale != "en":
        raise APIError(400, "Only English translations are stored")
    if source not in TRANSLATION_SOURCES:
        raise APIError(400, "Invalid translation source")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise APIError(400, "Invalid translation timestamp")
    problem_id = problem.get("id")
    if not isinstance(problem_id, str) or not problem_id:
        raise APIError(500, "Problem content is unavailable")
    return {
        "schema_version": TRANSLATION_SCHEMA,
        "problem_id": problem_id,
        "locale": locale,
        "source_digest": source_digest(problem),
        "source": source,
        "updated_at": updated_at,
        "fields": validate_translation(content),
    }


def translation_key(problem_id: str, locale: str = "en") -> str:
    locale = normalize_locale(locale)
    if locale != "en" or not isinstance(problem_id, str) or not problem_id:
        raise APIError(400, "Invalid translation key")
    return f"{problem_id}:{locale}"


def localized_content(
    problem: Mapping[str, Any],
    locale: str,
    record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a complete display projection without cross-language fallback.

    ``oj.problem-content.v2`` deliberately fails closed for English.  When the
    English record is missing, stale, or malformed, every prose field is empty
    and ``resolved_locale`` is ``None``.  Canonical Chinese remains available
    through an explicit ``locale=zh-CN`` request, but is never masqueraded as
    English content.
    """

    locale = normalize_locale(locale)
    digest = source_digest(problem)
    canonical = {field: str(problem.get(field, "")) for field in TRANSLATABLE_FIELDS}
    if locale == "zh-CN":
        return {
            "schema_version": CONTENT_SCHEMA,
            "requested_locale": locale,
            "resolved_locale": "zh-CN",
            "status": "ready",
            "fallback": False,
            "source_digest": digest,
            "fields": canonical,
        }

    state = "missing"
    translated = None
    if isinstance(record, Mapping):
        if record.get("source_digest") != digest:
            state = "stale"
        elif (
            record.get("schema_version") == TRANSLATION_SCHEMA
            and record.get("problem_id") == problem.get("id")
            and record.get("locale") == "en"
        ):
            try:
                translated = validate_translation(record.get("fields"))
            except APIError:
                translated = None
    if translated is not None:
        return {
            "schema_version": CONTENT_SCHEMA,
            "requested_locale": "en",
            "resolved_locale": "en",
            "status": "ready",
            "fallback": False,
            "source_digest": digest,
            "fields": translated,
        }
    return {
        "schema_version": CONTENT_SCHEMA,
        "requested_locale": "en",
        "resolved_locale": None,
        "status": state,
        "fallback": False,
        "source_digest": digest,
        "fields": {field: "" for field in TRANSLATABLE_FIELDS},
    }


def embedded_english_translation(value: Any) -> dict[str, str] | None:
    """Read the optional additive ``translations.en`` field from an input body."""

    if not isinstance(value, Mapping) or "translations" not in value:
        return None
    translations = value.get("translations")
    if not isinstance(translations, Mapping) or set(translations) != {"en"}:
        raise APIError(400, "Invalid translations")
    return validate_translation(translations["en"])
