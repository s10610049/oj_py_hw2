"""Knowledge-point registry quality and API-boundary validation."""

import pytest

from shared.knowledge import (
    KNOWLEDGE_CATEGORIES,
    KNOWLEDGE_POINTS,
    KNOWLEDGE_VERSION,
    knowledge_point,
    resolve_knowledge_points,
)


def test_registry_has_more_than_two_hundred_real_unique_bilingual_points():
    assert KNOWLEDGE_VERSION == "programming-knowledge-2026-09.v1"
    assert len(KNOWLEDGE_POINTS) >= 200
    assert len({item["id"] for item in KNOWLEDGE_POINTS}) == len(KNOWLEDGE_POINTS)
    assert len({item["zh-CN"] for item in KNOWLEDGE_POINTS}) == len(KNOWLEDGE_POINTS)
    assert len({item["en"] for item in KNOWLEDGE_POINTS}) == len(KNOWLEDGE_POINTS)
    categories = {item["id"] for item in KNOWLEDGE_CATEGORIES}
    assert len(categories) >= 10
    assert all(item["category_id"] in categories for item in KNOWLEDGE_POINTS)
    assert all(item["zh-CN"].strip() and item["en"].strip() for item in KNOWLEDGE_POINTS)


def test_resolution_uses_stable_ids_deduplicates_and_preserves_order():
    selected = resolve_knowledge_points(
        ["graph.topological-sort", "engineering.deadlock", "graph.topological-sort"]
    )
    assert [item["id"] for item in selected] == [
        "graph.topological-sort",
        "engineering.deadlock",
    ]
    assert knowledge_point("engineering.deadlock")["zh-CN"] == "死锁分析"
    assert knowledge_point("不存在") is None


@pytest.mark.parametrize(
    "value",
    ["graph.topological-sort", ["missing"], [1], ["graph.dfs"] * 51],
)
def test_resolution_rejects_unknown_wrong_type_and_excessive_inputs(value):
    with pytest.raises(ValueError):
        resolve_knowledge_points(value)
