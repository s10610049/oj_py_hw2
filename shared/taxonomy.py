"""Stable difficulty taxonomy and display-only localization helpers.

The stored course ``difficulty`` field remains free text.  Only exact labels in
this registry are normalized; legacy values such as ``medium`` or ``基础`` are
deliberately left neutral instead of being guessed into a Luogu level.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TAXONOMY_VERSION = "luogu-2026-09.v1"

DIFFICULTIES = (
    {
        "id": "luogu.1",
        "order": 1,
        "zh-CN": "入门",
        "en": "Beginner",
        "color_token": "difficulty-red",
    },
    {
        "id": "luogu.2",
        "order": 2,
        "zh-CN": "普及-",
        "en": "Novice−",
        "color_token": "difficulty-orange",
    },
    {
        "id": "luogu.3",
        "order": 3,
        "zh-CN": "普及",
        "en": "Novice",
        "color_token": "difficulty-yellow",
    },
    {
        "id": "luogu.4",
        "order": 4,
        "zh-CN": "普及+/提高-",
        "en": "Novice+ / Intermediate−",
        "color_token": "difficulty-green",
    },
    {
        "id": "luogu.5",
        "order": 5,
        "zh-CN": "提高",
        "en": "Intermediate",
        "color_token": "difficulty-cyan",
    },
    {
        "id": "luogu.6",
        "order": 6,
        "zh-CN": "提高+/省选-",
        "en": "Intermediate+ / Provincial−",
        "color_token": "difficulty-blue",
    },
    {
        "id": "luogu.7",
        "order": 7,
        "zh-CN": "省选/NOI-",
        "en": "Provincial / NOI−",
        "color_token": "difficulty-purple",
    },
    {
        "id": "luogu.8",
        "order": 8,
        "zh-CN": "NOI/NOI+/CTS",
        "en": "NOI / NOI+ / CTS",
        "color_token": "difficulty-black",
    },
)

_BY_ID = {item["id"]: item for item in DIFFICULTIES}
_BY_EXACT_LABEL = {
    str(item[label]).casefold(): item for item in DIFFICULTIES for label in ("zh-CN", "en")
}


def difficulty_by_id(difficulty_id: str) -> Mapping[str, Any] | None:
    """Return immutable registry data by canonical id, or ``None``."""

    return _BY_ID.get(str(difficulty_id))


def normalize_difficulty(raw: str, locale: str = "zh-CN") -> dict[str, Any]:
    """Normalize only registered exact labels into a safe display projection."""

    if locale not in {"zh-CN", "en"}:
        raise ValueError("unsupported locale")
    text = str(raw or "").strip()
    item = _BY_EXACT_LABEL.get(text.casefold())
    if item is None:
        return {
            "id": None,
            "raw": text,
            "label": text or ("未分级" if locale == "zh-CN" else "Unrated"),
            "order": 999,
            "color_token": "difficulty-neutral",
            "recognized": False,
            "taxonomy_version": TAXONOMY_VERSION,
        }
    return {
        "id": item["id"],
        "raw": text,
        "label": item[locale],
        "order": item["order"],
        "color_token": item["color_token"],
        "recognized": True,
        "taxonomy_version": TAXONOMY_VERSION,
    }


def difficulty_from_id(difficulty_id: str, locale: str = "zh-CN") -> dict[str, Any]:
    """Validate a structured selection and return its localized projection."""

    item = difficulty_by_id(difficulty_id)
    if item is None:
        raise ValueError("unknown difficulty id")
    return normalize_difficulty(str(item["zh-CN"]), locale)
