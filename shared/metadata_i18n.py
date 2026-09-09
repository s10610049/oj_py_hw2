"""Fail-closed localization for optional programming-problem metadata.

This module lives in ``shared`` so both the Streamlit display layer and the
provider-context adapter use one reviewed mapping.  Unknown Chinese metadata
is omitted in English mode instead of producing a mixed-language surface.
"""

from __future__ import annotations

from shared.knowledge import KNOWLEDGE_CATEGORIES, KNOWLEDGE_POINTS

_EXTRA_TAGS = {
    "二分查找": "Binary search",
    "二分答案": "Binary search on answer",
    "分段扫描": "Segment scanning",
    "前缀和": "Prefix sums",
    "动态规划": "Dynamic programming",
    "区间合并": "Interval merging",
    "区间调度": "Interval scheduling",
    "去重": "Deduplication",
    "双指针": "Two pointers",
    "取模": "Modulo arithmetic",
    "向上取整": "Ceiling division",
    "因数统计": "Divisor counting",
    "图论": "Graph theory",
    "多关键字": "Multiple sort keys",
    "字符串": "Strings",
    "完全背包": "Unbounded knapsack",
    "并查集": "Disjoint-set union",
    "广度优先搜索": "Breadth-first search",
    "循环": "Loops",
    "拓扑排序": "Topological sorting",
    "排序": "Sorting",
    "数组": "Arrays",
    "整数运算": "Integer arithmetic",
    "入门": "Introductory",
    "图": "Graphs",
    "最短路": "Shortest paths",
    "有向图": "Directed graphs",
    "环检测": "Cycle detection",
    "条件判断": "Conditionals",
    "查询": "Queries",
    "栈": "Stacks",
    "模拟": "Simulation",
    "状态维护": "State tracking",
    "状态转移": "State transitions",
    "计数": "Counting",
    "贪心": "Greedy algorithms",
    "输入输出": "Input and output",
    "边界": "Boundary cases",
    "连通分量": "Connected components",
    "遍历": "Traversal",
    "队列": "Queues",
}
_TAG_TRANSLATIONS = {
    str(item["zh-CN"]).casefold(): str(item["en"])
    for item in (*KNOWLEDGE_CATEGORIES, *KNOWLEDGE_POINTS)
}
_TAG_TRANSLATIONS.update({key.casefold(): value for key, value in _EXTRA_TAGS.items()})

_SOURCE_TRANSLATIONS = {
    "项目原创演示题 · 自建测试数据": "Original project demo · self-authored test data",
    "原创": "Original",
    "AI生成": "AI-generated",
    "AI 生成": "AI-generated",
}
_AUTHOR_TRANSLATIONS = {
    "OJ 项目": "OJ project",
    "课程组": "Course team",
}


def has_cjk(value: str) -> bool:
    """Return whether text includes a CJK unified ideograph."""

    return any("\u3400" <= character <= "\u9fff" for character in value)


def localized_tags(values, locale: str) -> tuple[list[str], int]:
    """Translate curated tags and suppress unknown CJK instead of mixing locales."""

    tags = [str(value).strip() for value in (values or []) if str(value).strip()]
    if locale != "en":
        return tags, 0
    result = []
    missing = 0
    for tag in tags:
        translated = _TAG_TRANSLATIONS.get(tag.casefold())
        if translated:
            result.append(translated)
        elif has_cjk(tag):
            missing += 1
        else:
            result.append(tag)
    return result, missing


def localized_optional_metadata(value, locale: str, kind: str) -> tuple[str, bool]:
    """Translate known source/author values and hide unknown CJK in English mode."""

    text = str(value or "").strip()
    if locale != "en" or not text:
        return text, False
    translations = _SOURCE_TRANSLATIONS if kind == "source" else _AUTHOR_TRANSLATIONS
    translated = translations.get(text)
    if translated:
        return translated, False
    if has_cjk(text):
        return "", True
    return text, False
