"""Administrator-only account performance comparison.

The page consumes one allow-listed aggregate contract.  It never downloads
submission source, judge details or hidden problem data to build its charts.
"""

from __future__ import annotations

import html
import math
from collections.abc import Mapping
from typing import Any

import streamlit as st

from frontend.common import api
from frontend.i18n import locale, role_label

SCHEMA_VERSION = "oj.admin-learning-overview.v1"
ROLES = ("admin", "user", "banned")
ACCOUNT_STATUSES = ("active", "disabled")
OUTCOME_IDS = (
    "pending",
    "accepted",
    "partial",
    "wrong_answer",
    "compile_error",
    "time_limit",
    "memory_limit",
    "runtime_error",
    "judge_error",
)

_COPY = {
    "zh-CN": {
        "title": "全员学习概览",
        "caption": "统一查看账号状态与学习表现，快速发现需要支持的学习者。",
        "invalid": "全员统计暂时无法读取，请稍后再试。",
        "accounts": "账号总数",
        "engaged": "已开始练习",
        "submissions": "代码提交",
        "pass_rate": "总体通过率",
        "people": "人",
        "times": "次",
        "comparison": "用户表现对比",
        "comparison_note": "得分率按当前题库总分计算；通过率按已尝试题目计算。",
        "score_rate": "得分率",
        "problem_pass_rate": "通过率",
        "no_activity": "尚无可比较的学习记录。",
        "accounts_title": "账号列表",
        "account_search": "搜索账号",
        "account_search_placeholder": "输入用户名",
        "role_filter": "角色筛选",
        "status_filter": "账号状态",
        "all_roles": "全部角色",
        "all_statuses": "全部状态",
        "no_account_matches": "没有符合当前筛选条件的账号。",
        "username": "账号",
        "role": "角色",
        "status": "状态",
        "joined": "加入日期",
        "submission_count": "提交",
        "attempted": "尝试题目",
        "passed": "通过题目",
        "score": "累计得分",
        "active": "正常",
        "disabled": "已禁用",
        "not_available": "—",
        "outcomes": "提交结果分布",
        "outcomes_note": "每一行代表该账号全部提交的判题结果构成。",
        "pending": "等待",
        "accepted": "AC",
        "partial": "部分通过",
        "wrong_answer": "WA",
        "compile_error": "CE",
        "time_limit": "TLE",
        "memory_limit": "MLE",
        "runtime_error": "RE",
        "judge_error": "评测异常",
    },
    "en": {
        "title": "Cohort overview",
        "caption": "Review account status and learning performance in one place.",
        "invalid": "Cohort statistics are temporarily unavailable. Try again later.",
        "accounts": "Accounts",
        "engaged": "Started learning",
        "submissions": "Submissions",
        "pass_rate": "Overall pass rate",
        "people": "people",
        "times": "times",
        "comparison": "User performance comparison",
        "comparison_note": (
            "Score rate uses the current catalog total; pass rate uses attempted problems."
        ),
        "score_rate": "Score rate",
        "problem_pass_rate": "Pass rate",
        "no_activity": "No learning activity is available for comparison yet.",
        "accounts_title": "Account list",
        "account_search": "Search accounts",
        "account_search_placeholder": "Enter a username",
        "role_filter": "Role",
        "status_filter": "Account status",
        "all_roles": "All roles",
        "all_statuses": "All statuses",
        "no_account_matches": "No accounts match the current filters.",
        "username": "Account",
        "role": "Role",
        "status": "Status",
        "joined": "Joined",
        "submission_count": "Submissions",
        "attempted": "Attempted",
        "passed": "Passed",
        "score": "Total score",
        "active": "Active",
        "disabled": "Disabled",
        "not_available": "—",
        "outcomes": "Submission outcome mix",
        "outcomes_note": "Each row shows the verdict mix across all submissions for an account.",
        "pending": "Pending",
        "accepted": "AC",
        "partial": "Partial",
        "wrong_answer": "WA",
        "compile_error": "CE",
        "time_limit": "TLE",
        "memory_limit": "MLE",
        "runtime_error": "RE",
        "judge_error": "Judge error",
    },
}


def _locale_code(value: Any) -> str:
    return "en" if str(value).lower().startswith("en") else "zh-CN"


def _text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _number(value: Any, *, integer: bool = False) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    if integer and not isinstance(value, int):
        return None
    return value


def _rate(value: Any) -> float | None:
    if value is None:
        return None
    number = _number(value)
    if number is None or number > 1:
        raise ValueError("rate must be null or between zero and one")
    return float(number)


def _same_rate(actual: float | None, numerator: int | float, denominator: int | float) -> bool:
    expected = None if denominator == 0 else float(numerator / denominator)
    if expected is None:
        return actual is None
    return actual is not None and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)


def _outcomes(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    counts = {}
    for row in value:
        if not isinstance(row, Mapping):
            return None
        outcome_id = row.get("id")
        count = _number(row.get("count"), integer=True)
        if outcome_id not in OUTCOME_IDS or count is None or outcome_id in counts:
            return None
        counts[outcome_id] = count
    if set(counts) != set(OUTCOME_IDS):
        return None
    return [{"id": outcome, "count": counts[outcome]} for outcome in OUTCOME_IDS]


def normalize_overview(payload: Any) -> dict[str, Any] | None:
    """Validate and reduce the admin API payload to a display-only view model."""

    try:
        if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
            return None
        generated_at = _text(payload.get("generated_at"))
        if generated_at is None or payload.get("timezone") != "UTC":
            return None
        raw_summary = payload.get("summary")
        raw_users = payload.get("users")
        aggregate_outcomes = _outcomes(payload.get("submission_outcomes"))
        if (
            not isinstance(raw_summary, Mapping)
            or not isinstance(raw_users, list)
            or aggregate_outcomes is None
        ):
            return None

        users = []
        seen = set()
        for raw in raw_users:
            if not isinstance(raw, Mapping):
                return None
            user_id = _text(raw.get("user_id"))
            username = _text(raw.get("username"))
            join_time = _text(raw.get("join_time"))
            role = raw.get("role")
            status = raw.get("account_status")
            integers = {
                key: _number(raw.get(key), integer=True)
                for key in ("submission_count", "attempted_count", "passed_count")
            }
            numbers = {key: _number(raw.get(key)) for key in ("earned_score", "available_score")}
            if (
                user_id is None
                or username is None
                or join_time is None
                or user_id in seen
                or role not in ROLES
                or status not in ACCOUNT_STATUSES
                or (status == "disabled") != (role == "banned")
                or None in integers.values()
                or None in numbers.values()
            ):
                return None
            if (
                integers["passed_count"] > integers["attempted_count"]
                or integers["attempted_count"] > integers["submission_count"]
                or numbers["earned_score"] > numbers["available_score"]
            ):
                return None
            score_rate = _rate(raw.get("score_rate"))
            pass_rate = _rate(raw.get("pass_rate"))
            outcomes = _outcomes(raw.get("submission_outcomes"))
            if (
                not _same_rate(score_rate, numbers["earned_score"], numbers["available_score"])
                or not _same_rate(pass_rate, integers["passed_count"], integers["attempted_count"])
                or outcomes is None
            ):
                return None
            if sum(row["count"] for row in outcomes) != integers["submission_count"]:
                return None
            seen.add(user_id)
            users.append(
                {
                    "id": user_id,
                    "username": username,
                    "join_time": join_time,
                    "role": role,
                    "status": status,
                    **integers,
                    **numbers,
                    "score_rate": score_rate,
                    "pass_rate": pass_rate,
                    "outcomes": outcomes,
                }
            )

        integer_summary = {
            key: _number(raw_summary.get(key), integer=True)
            for key in (
                "account_count",
                "active_count",
                "disabled_count",
                "learner_count",
                "engaged_count",
                "submission_count",
                "attempted_count",
                "passed_count",
            )
        }
        number_summary = {
            key: _number(raw_summary.get(key)) for key in ("earned_score", "available_score")
        }
        if None in integer_summary.values() or None in number_summary.values():
            return None
        score_rate = _rate(raw_summary.get("score_rate"))
        pass_rate = _rate(raw_summary.get("pass_rate"))
        expected = {
            "account_count": len(users),
            "active_count": sum(row["status"] == "active" for row in users),
            "disabled_count": sum(row["status"] == "disabled" for row in users),
            "learner_count": sum(row["role"] == "user" for row in users),
            "engaged_count": sum(row["attempted_count"] > 0 for row in users),
            "submission_count": sum(row["submission_count"] for row in users),
            "attempted_count": sum(row["attempted_count"] for row in users),
            "passed_count": sum(row["passed_count"] for row in users),
            "earned_score": sum(row["earned_score"] for row in users),
            "available_score": sum(row["available_score"] for row in users),
        }
        if integer_summary != {key: expected[key] for key in integer_summary}:
            return None
        if any(
            not math.isclose(float(number_summary[key]), float(expected[key]))
            for key in number_summary
        ):
            return None
        if not _same_rate(
            score_rate, number_summary["earned_score"], number_summary["available_score"]
        ) or not _same_rate(
            pass_rate, integer_summary["passed_count"], integer_summary["attempted_count"]
        ):
            return None
        expected_outcomes = {outcome: 0 for outcome in OUTCOME_IDS}
        for row in users:
            for outcome in row["outcomes"]:
                expected_outcomes[outcome["id"]] += outcome["count"]
        if aggregate_outcomes != [
            {"id": outcome, "count": expected_outcomes[outcome]} for outcome in OUTCOME_IDS
        ]:
            return None
        return {
            "generated_at": generated_at,
            "summary": {
                **integer_summary,
                **number_summary,
                "score_rate": score_rate,
                "pass_rate": pass_rate,
            },
            "outcomes": aggregate_outcomes,
            "users": users,
        }
    except (OverflowError, TypeError, ValueError, ZeroDivisionError):
        return None


def _format_number(value: int | float) -> str:
    number = float(value)
    return f"{int(number):,}" if number.is_integer() else f"{number:,.1f}"


def _format_rate(value: float | None, copy: Mapping[str, str]) -> str:
    return copy["not_available"] if value is None else f"{value * 100:.0f}%"


def filter_account_rows(
    users: list[Mapping[str, Any]],
    username_query: str = "",
    role: str = "all",
    status: str = "all",
) -> list[Mapping[str, Any]]:
    """Return account rows matching the local, display-only filters.

    Filtering deliberately does not consider submission activity, so an idle
    account remains visible whenever its username, role and status match.
    """

    query = str(username_query or "").strip().casefold()
    role_filter = role if role in ("all", *ROLES) else "all"
    status_filter = status if status in ("all", *ACCOUNT_STATUSES) else "all"
    return [
        row
        for row in users
        if (not query or query in row["username"].casefold())
        and (role_filter == "all" or row["role"] == role_filter)
        and (status_filter == "all" or row["status"] == status_filter)
    ]


def kpis_html(view: Mapping[str, Any], locale_code: str = "zh-CN") -> str:
    locale_code = _locale_code(locale_code)
    copy = _COPY[locale_code]
    summary = view["summary"]
    items = (
        (copy["accounts"], _format_number(summary["account_count"]), copy["people"]),
        (copy["engaged"], _format_number(summary["engaged_count"]), copy["people"]),
        (copy["submissions"], _format_number(summary["submission_count"]), copy["times"]),
        (copy["pass_rate"], _format_rate(summary["pass_rate"], copy), ""),
    )
    cards = "".join(
        "<article class='oj-admin-kpi'>"
        f"<span>{html.escape(label)}</span><strong>{html.escape(value)}</strong>"
        f"<small>{html.escape(unit)}</small></article>"
        for label, value, unit in items
    )
    return (
        f"<section class='oj-admin-kpis' aria-label='{html.escape(copy['title'], quote=True)}'>"
        f"{cards}</section>"
    )


def comparison_html(view: Mapping[str, Any], locale_code: str = "zh-CN") -> str:
    locale_code = _locale_code(locale_code)
    copy = _COPY[locale_code]
    users = sorted(
        view["users"],
        key=lambda row: (
            -(row["score_rate"] if row["score_rate"] is not None else -1),
            -(row["pass_rate"] if row["pass_rate"] is not None else -1),
            row["username"].casefold(),
            row["id"],
        ),
    )
    rows = []
    for row in users:
        score = row["score_rate"] or 0
        passed = row["pass_rate"] or 0
        label = row["username"]
        meta = role_label(row["role"], locale_code)
        rows.append(
            "<div class='oj-admin-compare-row'>"
            "<div class='oj-admin-compare-person'>"
            f"<strong>{html.escape(label)}</strong><span>{html.escape(meta)}</span></div>"
            "<div class='oj-admin-compare-bars'>"
            f"<div aria-label='{html.escape(copy['score_rate'], quote=True)} "
            f"{html.escape(_format_rate(row['score_rate'], copy), quote=True)}'>"
            f"<span class='oj-admin-bar score' style='width:{score * 100:.2f}%'></span></div>"
            f"<div aria-label='{html.escape(copy['problem_pass_rate'], quote=True)} "
            f"{html.escape(_format_rate(row['pass_rate'], copy), quote=True)}'>"
            f"<span class='oj-admin-bar pass' style='width:{passed * 100:.2f}%'></span></div>"
            "</div><div class='oj-admin-compare-values'>"
            f"<span>{html.escape(_format_rate(row['score_rate'], copy))}</span>"
            f"<span>{html.escape(_format_rate(row['pass_rate'], copy))}</span></div></div>"
        )
    body = "".join(rows) or f"<p class='oj-chart-empty'>{html.escape(copy['no_activity'])}</p>"
    return (
        "<section class='oj-admin-comparison' role='region' "
        f"aria-label='{html.escape(copy['comparison'], quote=True)}'>"
        "<header><div>"
        f"<h3>{html.escape(copy['comparison'])}</h3>"
        f"<p>{html.escape(copy['comparison_note'])}</p></div>"
        "<div class='oj-admin-legend'>"
        f"<span class='score'>{html.escape(copy['score_rate'])}</span>"
        f"<span class='pass'>{html.escape(copy['problem_pass_rate'])}</span></div></header>"
        f"<div class='oj-admin-comparison-scroll'>{body}</div></section>"
    )


def outcomes_html(view: Mapping[str, Any], locale_code: str = "zh-CN") -> str:
    locale_code = _locale_code(locale_code)
    copy = _COPY[locale_code]
    visible_outcomes = tuple(
        outcome
        for outcome in OUTCOME_IDS
        if any(
            next(item["count"] for item in row["outcomes"] if item["id"] == outcome)
            for row in view["users"]
        )
    )
    legend = "".join(
        f"<span class='outcome-{outcome}'>{html.escape(copy[outcome])}</span>"
        for outcome in visible_outcomes
    )
    rows = []
    for row in view["users"]:
        counts = {item["id"]: item["count"] for item in row["outcomes"]}
        total = row["submission_count"]
        segments = "".join(
            f"<span class='outcome-{outcome}' style='width:{counts[outcome] / total * 100:.2f}%' "
            f"title='{html.escape(copy[outcome], quote=True)}: {counts[outcome]}'></span>"
            for outcome in visible_outcomes
            if total and counts[outcome]
        )
        if not segments:
            segments = "<span class='outcome-empty'></span>"
        rows.append(
            "<div class='oj-admin-outcome-row'>"
            f"<strong>{html.escape(row['username'])}</strong>"
            f"<div class='oj-admin-outcome-track'>{segments}</div>"
            f"<span>{_format_number(total)}</span></div>"
        )
    return (
        "<section class='oj-admin-outcomes' role='region' "
        f"aria-label='{html.escape(copy['outcomes'], quote=True)}'><header><div>"
        f"<h3>{html.escape(copy['outcomes'])}</h3>"
        f"<p>{html.escape(copy['outcomes_note'])}</p></div>"
        f"<div class='oj-admin-outcome-legend'>{legend}</div></header>"
        f"<div class='oj-admin-outcomes-scroll'>{''.join(rows)}</div></section>"
    )


def accounts_table_html(view: Mapping[str, Any], locale_code: str = "zh-CN") -> str:
    locale_code = _locale_code(locale_code)
    copy = _COPY[locale_code]
    headings = (
        copy["username"],
        copy["role"],
        copy["status"],
        copy["joined"],
        copy["submission_count"],
        copy["attempted"],
        copy["passed"],
        copy["score"],
        copy["score_rate"],
        copy["problem_pass_rate"],
    )
    rows = []
    for row in view["users"]:
        status = copy[row["status"]]
        rows.append(
            "<tr>"
            f"<th scope='row'><strong>{html.escape(row['username'])}</strong>"
            f"<small>{html.escape(row['id'])}</small></th>"
            f"<td>{html.escape(role_label(row['role'], locale_code))}</td>"
            f"<td><span class='oj-account-status {row['status']}'>{html.escape(status)}</span></td>"
            f"<td>{html.escape(row['join_time'])}</td>"
            f"<td class='oj-number'>{_format_number(row['submission_count'])}</td>"
            f"<td class='oj-number'>{_format_number(row['attempted_count'])}</td>"
            f"<td class='oj-number'>{_format_number(row['passed_count'])}</td>"
            f"<td class='oj-number'>{_format_number(row['earned_score'])} / "
            f"{_format_number(row['available_score'])}</td>"
            f"<td class='oj-number'>{html.escape(_format_rate(row['score_rate'], copy))}</td>"
            f"<td class='oj-number'>{html.escape(_format_rate(row['pass_rate'], copy))}</td>"
            "</tr>"
        )
    if not rows:
        return (
            "<div class='oj-chart-empty oj-admin-account-empty' role='status'>"
            f"{html.escape(copy['no_account_matches'])}</div>"
        )
    header = "".join(f"<th scope='col'>{html.escape(item)}</th>" for item in headings)
    body = "".join(rows)
    return (
        "<div class='oj-admin-account-table-wrap' tabindex='0' role='region' "
        f"aria-label='{html.escape(copy['accounts_title'], quote=True)}'>"
        "<table class='oj-admin-account-table'><caption class='oj-sr-only'>"
        f"{html.escape(copy['accounts_title'])}</caption><thead><tr>{header}</tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def overview_fragments(payload: Any, locale_code: str = "zh-CN") -> dict[str, str] | None:
    view = normalize_overview(payload)
    if view is None:
        return None
    return {
        "kpis": kpis_html(view, locale_code),
        "comparison": comparison_html(view, locale_code),
        "outcomes": outcomes_html(view, locale_code),
        "accounts": accounts_table_html(view, locale_code),
    }


def admin_overview_page() -> None:
    locale_code = _locale_code(locale())
    copy = _COPY[locale_code]
    st.subheader(copy["title"])
    st.caption(copy["caption"])
    view = normalize_overview(api().request("GET", "/api/admin/learning-overview/"))
    if view is None:
        st.error(copy["invalid"])
        return
    fragments = {
        "kpis": kpis_html(view, locale_code),
        "comparison": comparison_html(view, locale_code),
        "outcomes": outcomes_html(view, locale_code),
    }
    st.html(fragments["kpis"])
    st.html(
        "<div class='oj-admin-chart-grid'>"
        + fragments["comparison"]
        + fragments["outcomes"]
        + "</div>"
    )
    st.subheader(copy["accounts_title"])
    search_column, role_column, status_column = st.columns([2, 1, 1], gap="small")
    username_query = search_column.text_input(
        copy["account_search"],
        placeholder=copy["account_search_placeholder"],
        key="admin_account_search",
    )
    role = role_column.selectbox(
        copy["role_filter"],
        ("all", *ROLES),
        format_func=lambda value: (
            copy["all_roles"] if value == "all" else role_label(value, locale_code)
        ),
        key="admin_account_role_filter",
    )
    status = status_column.selectbox(
        copy["status_filter"],
        ("all", *ACCOUNT_STATUSES),
        format_func=lambda value: copy["all_statuses"] if value == "all" else copy[value],
        key="admin_account_status_filter",
    )
    filtered_users = filter_account_rows(view["users"], username_query, role, status)
    st.html(accounts_table_html({"users": filtered_users}, locale_code))


__all__ = (
    "SCHEMA_VERSION",
    "accounts_table_html",
    "admin_overview_page",
    "comparison_html",
    "filter_account_rows",
    "kpis_html",
    "normalize_overview",
    "outcomes_html",
    "overview_fragments",
)
