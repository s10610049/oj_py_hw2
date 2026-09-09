"""Personal learning analytics rendered from one privacy-safe API payload.

The module intentionally knows only ``oj.learning-stats.v1``.  It never asks
for submissions, source code, judge details or test cases separately.  HTML
helpers are pure so chart geometry and escaping can be verified without a
running Streamlit server.
"""

from __future__ import annotations

import html
import math
from datetime import date
from typing import Any, Mapping

import streamlit as st

from frontend.common import api
from shared.taxonomy import difficulty_from_id

SCHEMA_VERSION = "oj.learning-stats.v1"
OUTCOME_ORDER = ("pending", "judge_error", "zero_score", "partial", "full")
STATE_ORDER = ("unattempted", "pending", "failed", "partial", "passed", "outdated")

_COPY = {
    "zh-CN": {
        "title": "学习统计",
        "caption": "从每次尝试中，看见稳定增长。",
        "partial": "部分统计数据格式异常，已安全省略。",
        "invalid": "统计数据暂时无法读取，请稍后再试。",
        "score": "累计得分",
        "passed": "已通过",
        "attempted_submissions": "尝试 / 提交",
        "pass_rate": "通过率",
        "problems": "题",
        "times": "次",
        "timeline": "累计最佳得分",
        "timeline_note": "按日期展示当前版本题目的累计最佳得分",
        "no_timeline": "完成一次判题后，这里会出现成长曲线。",
        "difficulty": "难度掌握",
        "outcomes": "提交结果",
        "knowledge": "知识点掌握",
        "problem_detail": "逐题表现",
        "no_data": "暂无可展示的数据",
        "no_problems": "题库中暂无题目。",
        "attempt_passed": "{passed} / {attempted} 题通过",
        "score_pair": "{earned} / {available} 分",
        "rate_unknown": "暂无尝试",
        "problem": "题目",
        "status": "状态",
        "best": "最佳得分",
        "difficulty_col": "难度",
        "tags": "知识点",
        "unrated": "未分级",
        "untagged": "未标注",
        "timeline_title": "累计最佳得分折线图",
        "timeline_desc": "共 {count} 个日期的数据，从 {first} 到 {last}。",
        "tooltip": "{date}，累计 {score} 分，提交 {submissions} 次",
    },
    "en": {
        "title": "Learning analytics",
        "caption": "See steady progress in every attempt.",
        "partial": "Some malformed statistics were safely omitted.",
        "invalid": "Statistics are temporarily unavailable. Please try again.",
        "score": "Total score",
        "passed": "Passed",
        "attempted_submissions": "Attempted / submissions",
        "pass_rate": "Pass rate",
        "problems": "problems",
        "times": "times",
        "timeline": "Cumulative best score",
        "timeline_note": "Best cumulative score on current problem versions by date",
        "no_timeline": "Your progress curve appears after a judged submission.",
        "difficulty": "Difficulty mastery",
        "outcomes": "Submission outcomes",
        "knowledge": "Knowledge mastery",
        "problem_detail": "Problem performance",
        "no_data": "No data to display",
        "no_problems": "There are no problems in the catalog.",
        "attempt_passed": "{passed} / {attempted} passed",
        "score_pair": "{earned} / {available} points",
        "rate_unknown": "Not attempted",
        "problem": "Problem",
        "status": "Status",
        "best": "Best score",
        "difficulty_col": "Difficulty",
        "tags": "Topics",
        "unrated": "Unrated",
        "untagged": "Untagged",
        "timeline_title": "Cumulative best score line chart",
        "timeline_desc": "{count} dates from {first} to {last}.",
        "tooltip": "{date}: {score} cumulative points, {submissions} submissions",
    },
}

_OUTCOME_LABELS = {
    "zh-CN": {
        "pending": "判题中",
        "judge_error": "评测异常",
        "zero_score": "未得分",
        "partial": "部分得分",
        "full": "满分",
    },
    "en": {
        "pending": "Pending",
        "judge_error": "Judge error",
        "zero_score": "No score",
        "partial": "Partial",
        "full": "Full score",
    },
}

_STATE_LABELS = {
    "zh-CN": {
        "unattempted": "未尝试",
        "pending": "判题中",
        "failed": "未通过",
        "partial": "部分通过",
        "passed": "已通过",
        "outdated": "题目已更新",
    },
    "en": {
        "unattempted": "Not attempted",
        "pending": "Pending",
        "failed": "Not passed",
        "partial": "Partially passed",
        "passed": "Passed",
        "outdated": "Problem updated",
    },
}


def _locale_code(locale: Any) -> str:
    return "en" if str(locale or "").lower().startswith("en") else "zh-CN"


def _text(value: Any, fallback: str = "") -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value > 10**15:
        return None
    if isinstance(value, int):
        return value
    if not math.isfinite(value):
        return None
    return int(value) if value.is_integer() else value


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None or float(number).is_integer() is False:
        return None
    return int(number)


def _rate(value: Any) -> float | None:
    number = _number(value)
    if number is None or number > 1:
        return None
    return float(number)


def _format_number(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "—"
    if isinstance(number, int):
        return f"{number:,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_rate(value: Any) -> str:
    rate = _rate(value)
    if rate is None:
        return "—"
    percentage = rate * 100
    return f"{int(percentage)}%" if percentage.is_integer() else f"{percentage:.1f}%"


def _safe_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _localized_difficulty(difficulty_id: Any, label: Any, locale: str) -> tuple[str, str]:
    """Return a display label and a controlled design-token class."""

    if isinstance(difficulty_id, str):
        try:
            projection = difficulty_from_id(difficulty_id, locale)
            return str(projection["label"]), str(projection["color_token"])
        except ValueError:
            pass
    return _text(label, _COPY[locale]["unrated"]), "difficulty-neutral"


def _normalize_timeline(value: Any) -> tuple[list[dict[str, Any]], int]:
    issues = 0
    rows: dict[str, dict[str, Any]] = {}
    for raw in _list_of_mappings(value):
        day = _safe_date(raw.get("date"))
        score = _number(raw.get("cumulative_score"))
        submissions = _integer(raw.get("submissions"))
        completed = _integer(raw.get("completed"))
        delta = _number(raw.get("best_score_delta"))
        if None in {day, score, submissions, completed, delta} or day in rows:
            issues += 1
            continue
        rows[str(day)] = {
            "date": day,
            "cumulative_score": score,
            "submissions": submissions,
            "completed": completed,
            "best_score_delta": delta,
        }
    ordered = [rows[key] for key in sorted(rows)]
    if any(
        float(current["cumulative_score"]) < float(previous["cumulative_score"])
        for previous, current in zip(ordered, ordered[1:])
    ):
        return [], issues + 1
    return ordered, issues


def normalize_stats(payload: Any, locale: str = "zh-CN") -> dict[str, Any] | None:
    """Create a bounded, display-only view model from the versioned payload.

    Unknown fields are dropped deliberately.  This is the privacy boundary that
    prevents accidental rendering of source code or judge-only fields.
    """

    locale = _locale_code(locale)
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        return None

    issues = 0
    scope_raw = payload.get("scope")
    kpis_raw = payload.get("kpis")
    if not isinstance(scope_raw, Mapping):
        scope_raw = {}
        issues += 1
    if not isinstance(kpis_raw, Mapping):
        kpis_raw = {}
        issues += 1

    def integer(mapping: Mapping[str, Any], key: str) -> int:
        nonlocal issues
        result = _integer(mapping.get(key))
        if result is None:
            issues += 1
            return 0
        return result

    def number(mapping: Mapping[str, Any], key: str) -> int | float:
        nonlocal issues
        result = _number(mapping.get(key))
        if result is None:
            issues += 1
            return 0
        return result

    attempted = integer(kpis_raw, "attempted_count")
    passed = integer(kpis_raw, "passed_count")
    supplied_rate = _rate(kpis_raw.get("pass_rate"))
    if supplied_rate is None and attempted:
        supplied_rate = min(passed / attempted, 1)
        issues += 1
    elif supplied_rate is None and kpis_raw.get("pass_rate") is not None:
        issues += 1

    timeline, timeline_issues = _normalize_timeline(payload.get("timeline"))
    issues += timeline_issues

    outcomes_by_id: dict[str, int] = {}
    for raw in _list_of_mappings(payload.get("submission_outcomes")):
        outcome_id = raw.get("id")
        count = _integer(raw.get("count"))
        if outcome_id not in OUTCOME_ORDER or count is None or outcome_id in outcomes_by_id:
            issues += 1
            continue
        outcomes_by_id[str(outcome_id)] = count
    issues += sum(outcome not in outcomes_by_id for outcome in OUTCOME_ORDER)

    difficulties = []
    for raw in _list_of_mappings(payload.get("difficulty")):
        label, token = _localized_difficulty(
            raw.get("difficulty_id"), raw.get("difficulty_label"), locale
        )
        row_attempted = _integer(raw.get("attempted"))
        row_passed = _integer(raw.get("passed"))
        earned = _number(raw.get("earned_score"))
        available = _number(raw.get("available_score"))
        row_rate = _rate(raw.get("rate"))
        if None in {row_attempted, row_passed, earned, available}:
            issues += 1
            continue
        difficulties.append(
            {
                "id": raw.get("difficulty_id") if token != "difficulty-neutral" else None,
                "label": label,
                "token": token,
                "attempted": row_attempted,
                "passed": row_passed,
                "earned": earned,
                "available": available,
                "rate": row_rate,
            }
        )
    difficulty_order = {f"luogu.{index}": index for index in range(1, 9)}
    difficulties.sort(
        key=lambda row: (difficulty_order.get(row["id"], 999), row["label"].casefold())
    )

    knowledge = []
    for raw in _list_of_mappings(payload.get("knowledge_points")):
        tag = _text(raw.get("tag"))
        row_attempted = _integer(raw.get("attempted"))
        row_passed = _integer(raw.get("passed"))
        earned = _number(raw.get("earned_score"))
        available = _number(raw.get("available_score"))
        row_rate = _rate(raw.get("rate"))
        if not tag or None in {row_attempted, row_passed, earned, available}:
            issues += 1
            continue
        knowledge.append(
            {
                "tag": tag,
                "attempted": row_attempted,
                "passed": row_passed,
                "earned": earned,
                "available": available,
                "rate": row_rate,
            }
        )
    knowledge.sort(key=lambda row: (-row["attempted"], row["tag"].casefold()))

    problems = []
    seen_problem_ids = set()
    for raw in _list_of_mappings(payload.get("problems")):
        problem_id = _text(raw.get("problem_id"))
        title = _text(raw.get("title"))
        state = raw.get("state")
        best_score = _number(raw.get("best_score"))
        available_score = _number(raw.get("available_score"))
        if (
            not problem_id
            or not title
            or state not in STATE_ORDER
            or best_score is None
            or available_score is None
            or problem_id in seen_problem_ids
        ):
            issues += 1
            continue
        seen_problem_ids.add(problem_id)
        difficulty_label, difficulty_token = _localized_difficulty(
            raw.get("difficulty_id"), raw.get("difficulty_label"), locale
        )
        raw_tags = raw.get("tags")
        tags = []
        if isinstance(raw_tags, list):
            for candidate in raw_tags:
                tag = _text(candidate)
                if tag and tag.casefold() not in {item.casefold() for item in tags}:
                    tags.append(tag)
        elif raw_tags is not None:
            issues += 1
        problems.append(
            {
                "id": problem_id,
                "title": title,
                "state": state,
                "best": best_score,
                "available": available_score,
                "difficulty": difficulty_label,
                "difficulty_token": difficulty_token,
                "tags": tags,
            }
        )

    expected_lists = (
        "submission_outcomes",
        "timeline",
        "difficulty",
        "knowledge_points",
        "problems",
    )
    issues += sum(not isinstance(payload.get(key), list) for key in expected_lists)

    catalog_count = integer(scope_raw, "catalog_problem_count")
    submission_count = integer(scope_raw, "submission_count")
    earned_score = number(kpis_raw, "earned_score")
    available_score = number(kpis_raw, "available_score")

    return {
        "issues": issues,
        "scope": {
            "catalog": catalog_count,
            "submissions": submission_count,
        },
        "kpis": {
            "earned": earned_score,
            "available": available_score,
            "attempted": attempted,
            "passed": passed,
            "pass_rate": supplied_rate,
        },
        "timeline": timeline,
        "outcomes": [
            {"id": outcome, "count": outcomes_by_id.get(outcome, 0)} for outcome in OUTCOME_ORDER
        ],
        "difficulty": difficulties,
        "knowledge": knowledge,
        "problems": problems,
    }


def kpi_html(stats: Mapping[str, Any], locale: str = "zh-CN") -> str:
    """Return the compact KPI row."""

    locale = _locale_code(locale)
    copy = _COPY[locale]
    kpis = stats["kpis"]
    scope = stats["scope"]
    items = (
        (
            copy["score"],
            f"{_format_number(kpis['earned'])} / {_format_number(kpis['available'])}",
            "",
        ),
        (copy["passed"], _format_number(kpis["passed"]), copy["problems"]),
        (
            copy["attempted_submissions"],
            f"{_format_number(kpis['attempted'])} / {_format_number(scope['submissions'])}",
            f"{copy['problems']} / {copy['times']}",
        ),
        (copy["pass_rate"], _format_rate(kpis["pass_rate"]), ""),
    )
    cards = "".join(
        "<article class='oj-analytics-kpi'>"
        f"<span class='oj-analytics-kpi-label'>{html.escape(label)}</span>"
        f"<strong class='oj-analytics-kpi-value'>{html.escape(value)}</strong>"
        f"<span class='oj-analytics-kpi-unit'>{html.escape(unit)}</span>"
        "</article>"
        for label, value, unit in items
    )
    return (
        f"<section class='oj-analytics-kpis' aria-label='{html.escape(copy['title'])}'>"
        f"{cards}</section>"
    )


def timeline_svg(timeline: Any, locale: str = "zh-CN") -> str:
    """Render an accessible, dependency-free cumulative-score line chart."""

    locale = _locale_code(locale)
    copy = _COPY[locale]
    rows, _ = _normalize_timeline(timeline)
    if not rows:
        return (
            "<div class='oj-chart-empty' role='status'>" f"{html.escape(copy['no_timeline'])}</div>"
        )

    width, height = 760, 240
    left, right, top, bottom = 54, 18, 18, 38
    plot_width = width - left - right
    plot_height = height - top - bottom
    baseline = top + plot_height
    values = [float(row["cumulative_score"]) for row in rows]
    actual_max = max(values)
    scale_max = max(actual_max, 1.0)

    points = []
    for index, row in enumerate(rows):
        x = left + (plot_width / 2 if len(rows) == 1 else index * plot_width / (len(rows) - 1))
        y = top + (scale_max - float(row["cumulative_score"])) / scale_max * plot_height
        points.append((x, y, row))

    line_path = " ".join(
        ("M" if index == 0 else "L") + f" {x:.2f} {y:.2f}" for index, (x, y, _) in enumerate(points)
    )
    area_path = (
        f"M {points[0][0]:.2f} {baseline:.2f} "
        + " ".join(f"L {x:.2f} {y:.2f}" for x, y, _ in points)
        + f" L {points[-1][0]:.2f} {baseline:.2f} Z"
    )
    grid = "".join(
        f"<line x1='{left}' y1='{top + step * plot_height / 4:.2f}' "
        f"x2='{width - right}' y2='{top + step * plot_height / 4:.2f}'/>"
        for step in range(5)
    )
    circles = "".join(
        f"<circle cx='{x:.2f}' cy='{y:.2f}' r='4' tabindex='0'>"
        "<title>"
        + html.escape(
            copy["tooltip"].format(
                date=row["date"],
                score=_format_number(row["cumulative_score"]),
                submissions=row["submissions"],
            )
        )
        + "</title></circle>"
        for x, y, row in points
    )
    first, last = rows[0]["date"], rows[-1]["date"]
    description = copy["timeline_desc"].format(count=len(rows), first=first, last=last)
    max_label = _format_number(actual_max)
    return (
        "<div class='oj-chart oj-timeline' role='region' "
        f"aria-label='{html.escape(copy['timeline'])}'>"
        f"<svg viewBox='0 0 {width} {height}' role='img' preserveAspectRatio='xMidYMid meet' "
        "width='100%' height='240' "
        "aria-labelledby='oj-timeline-title oj-timeline-desc'>"
        f"<title id='oj-timeline-title'>{html.escape(copy['timeline_title'])}</title>"
        f"<desc id='oj-timeline-desc'>{html.escape(description)}</desc>"
        f"<g class='oj-timeline-grid' stroke='#dce5e0' stroke-width='1' "
        f"aria-hidden='true'>{grid}</g>"
        f"<path class='oj-timeline-area' d='{area_path}' fill='#e9f4ef'/>"
        f"<path class='oj-timeline-line' d='{line_path}' fill='none' stroke='#187a55' "
        "stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>"
        f"<g class='oj-timeline-points' fill='#187a55'>{circles}</g>"
        f"<g class='oj-timeline-axis' aria-hidden='true'><text x='{left - 8}' y='{top + 5}' "
        f"text-anchor='end'>{html.escape(max_label)}</text>"
        f"<text x='{left - 8}' y='{baseline + 4}' text-anchor='end'>0</text>"
        f"<text x='{left}' y='{height - 10}'>{html.escape(first)}</text>"
        f"<text x='{width - right}' y='{height - 10}' text-anchor='end'>{html.escape(last)}</text>"
        "</g></svg></div>"
    )


def breakdown_html(stats: Mapping[str, Any], kind: str, locale: str = "zh-CN") -> str:
    """Render difficulty, outcome or knowledge rows with accessible bars."""

    locale = _locale_code(locale)
    copy = _COPY[locale]
    if kind == "outcomes":
        rows = stats["outcomes"]
        heading = copy["outcomes"]
        maximum = max((row["count"] for row in rows), default=0)
        prepared = [
            {
                "label": _OUTCOME_LABELS[locale][row["id"]],
                "token": f"outcome-{row['id']}",
                "percentage": row["count"] / maximum if maximum else 0,
                "meta": f"{_format_number(row['count'])} {copy['times']}",
            }
            for row in rows
        ]
    elif kind == "difficulty":
        rows = stats["difficulty"]
        heading = copy["difficulty"]
        prepared = [
            {
                "label": row["label"],
                "token": row["token"],
                "percentage": row["rate"] or 0,
                "meta": (
                    copy["attempt_passed"].format(
                        passed=_format_number(row["passed"]),
                        attempted=_format_number(row["attempted"]),
                    )
                    if row["rate"] is not None
                    else copy["rate_unknown"]
                ),
            }
            for row in rows
        ]
    elif kind == "knowledge":
        rows = stats["knowledge"]
        heading = copy["knowledge"]
        prepared = [
            {
                "label": row["tag"],
                "token": "knowledge-mastery",
                "percentage": row["rate"] or 0,
                "meta": (
                    copy["attempt_passed"].format(
                        passed=_format_number(row["passed"]),
                        attempted=_format_number(row["attempted"]),
                    )
                    if row["rate"] is not None
                    else copy["rate_unknown"]
                ),
            }
            for row in rows
        ]
    else:
        raise ValueError("unsupported analytics breakdown")

    for row in prepared:
        row["width"] = max(0.0, min(float(row["percentage"]), 1.0)) * 100

    if not prepared:
        body = f"<p class='oj-chart-empty'>{html.escape(copy['no_data'])}</p>"
    else:
        body = "".join(
            "<div class='oj-bar-row' "
            f"aria-label='{html.escape(row['label'] + ", " + row['meta'], quote=True)}'>"
            "<div class='oj-bar-meta'>"
            f"<span class='oj-difficulty-token {row['token']}'>{html.escape(row['label'])}</span>"
            f"<span>{html.escape(row['meta'])}</span></div>"
            "<div class='oj-bar-track' aria-hidden='true'>"
            f"<span class='oj-bar-fill {row['token']}' "
            f"style='width:{row['width']:.2f}%'></span>"
            "</div></div>"
            for row in prepared
        )
    return (
        f"<section class='oj-panel oj-panel-{kind}' aria-label='{html.escape(heading)}'>"
        f"<h3>{html.escape(heading)}</h3><div class='oj-bar-list'>{body}</div></section>"
    )


def problems_table_html(stats: Mapping[str, Any], locale: str = "zh-CN") -> str:
    """Render the allow-listed per-problem projection as a semantic table."""

    locale = _locale_code(locale)
    copy = _COPY[locale]
    rows = stats["problems"]
    if not rows:
        return f"<div class='oj-chart-empty' role='status'>{html.escape(copy['no_problems'])}</div>"

    rendered_rows = []
    for row in rows:
        state = str(row["state"])
        tags = " · ".join(row["tags"]) or copy["untagged"]
        rendered_rows.append(
            "<tr>"
            f"<th scope='row'><span class='oj-problem-id'>{html.escape(row['id'])}</span>"
            f"<span class='oj-problem-title'>{html.escape(row['title'])}</span></th>"
            f"<td><span class='oj-state-token state-{state}'>"
            f"{html.escape(_STATE_LABELS[locale][state])}</span></td>"
            f"<td class='oj-number'>{html.escape(_format_number(row['best']))} / "
            f"{html.escape(_format_number(row['available']))}</td>"
            f"<td><span class='oj-difficulty-token {row['difficulty_token']}'>"
            f"{html.escape(row['difficulty'])}</span></td>"
            f"<td class='oj-problem-tags'>{html.escape(tags)}</td>"
            "</tr>"
        )
    headings = (copy["problem"], copy["status"], copy["best"], copy["difficulty_col"], copy["tags"])
    header = "".join(f"<th scope='col'>{html.escape(item)}</th>" for item in headings)
    return (
        "<div class='oj-analytics-table-wrap' tabindex='0' role='region' "
        f"aria-label='{html.escape(copy['problem_detail'])}'>"
        "<table class='oj-analytics-table'><caption class='oj-sr-only'>"
        f"{html.escape(copy['problem_detail'])}</caption><thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(rendered_rows)}</tbody></table></div>"
    )


def dashboard_fragments(payload: Any, locale: str = "zh-CN") -> dict[str, str] | None:
    """Pure composition helper used by Streamlit and tests."""

    locale = _locale_code(locale)
    stats = normalize_stats(payload, locale)
    if stats is None:
        return None
    return {
        "kpis": kpi_html(stats, locale),
        "timeline": timeline_svg(stats["timeline"], locale),
        "difficulty": breakdown_html(stats, "difficulty", locale),
        "outcomes": breakdown_html(stats, "outcomes", locale),
        "knowledge": breakdown_html(stats, "knowledge", locale),
        "problems": problems_table_html(stats, locale),
        "issues": str(stats["issues"]),
    }


def _current_locale() -> str:
    try:
        return _locale_code(st.session_state.get("_locale", "zh-CN"))
    except Exception:
        return "zh-CN"


def analytics_page() -> None:
    """Render the page using exactly one learning-statistics request."""

    locale = _current_locale()
    copy = _COPY[locale]
    st.title(copy["title"])
    st.caption(copy["caption"])
    payload = api().request("GET", "/api/me/learning-stats/")
    fragments = dashboard_fragments(payload, locale)
    if fragments is None:
        st.error(copy["invalid"])
        return
    if int(fragments["issues"]):
        st.warning(copy["partial"])

    st.html(fragments["kpis"])
    st.subheader(copy["timeline"])
    st.caption(copy["timeline_note"])
    st.html(fragments["timeline"])
    st.html(
        "<div class='oj-analytics-grid oj-analytics-grid-two'>"
        + fragments["difficulty"]
        + fragments["outcomes"]
        + "</div>"
    )
    st.html(fragments["knowledge"])
    st.subheader(copy["problem_detail"])
    st.html(fragments["problems"])


__all__ = (
    "SCHEMA_VERSION",
    "analytics_page",
    "breakdown_html",
    "dashboard_fragments",
    "kpi_html",
    "normalize_stats",
    "problems_table_html",
    "timeline_svg",
)
