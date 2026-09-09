"""Problem catalog, complete editor and programming workspace."""

import hashlib
import html
from collections.abc import Mapping

import streamlit as st

from frontend.client import APIError, resource
from frontend.common import api, go, is_admin, mutation, notice
from frontend.forms import problem_form
from shared.taxonomy import DIFFICULTIES, normalize_difficulty

STATUS_SCHEMA = "oj.problem-status.v1"
_PROBLEM_STATES = {"unattempted", "pending", "failed", "partial", "passed", "outdated"}
_OUTCOMES = {
    "pending",
    "accepted",
    "wrong_answer",
    "partial",
    "compile_error",
    "time_limit",
    "memory_limit",
    "runtime_error",
    "judge_error",
}
_DIFFICULTY_TOKENS = {item["color_token"] for item in DIFFICULTIES} | {"difficulty-neutral"}

_STATE_PRESENTATION = {
    "zh-CN": {
        "unattempted": ("未尝试", "status-unattempted"),
        "pending": ("判题中", "status-pending"),
        "failed": ("未通过", "status-failed"),
        "partial": ("部分通过", "status-partial"),
        "passed": ("已通过", "status-ac"),
        "outdated": ("题目已更新", "status-outdated"),
        "unavailable": ("状态暂缺", "status-unavailable"),
    },
    "en": {
        "unattempted": ("Not attempted", "status-unattempted"),
        "pending": ("Pending", "status-pending"),
        "failed": ("Not passed", "status-failed"),
        "partial": ("Partially passed", "status-partial"),
        "passed": ("Accepted", "status-ac"),
        "outdated": ("Problem updated", "status-outdated"),
        "unavailable": ("Status unavailable", "status-unavailable"),
    },
}

_OUTCOME_PRESENTATION = {
    "zh-CN": {
        "pending": ("判题中", "status-pending"),
        "accepted": ("已通过", "status-ac"),
        "wrong_answer": ("答案错误", "status-failed"),
        "partial": ("部分通过", "status-partial"),
        "compile_error": ("编译错误", "status-compile"),
        "time_limit": ("运行超时", "status-timeout"),
        "memory_limit": ("内存超限", "status-memory"),
        "runtime_error": ("运行错误", "status-runtime"),
        "judge_error": ("评测异常", "status-judge-error"),
    },
    "en": {
        "pending": ("Pending", "status-pending"),
        "accepted": ("Accepted", "status-ac"),
        "wrong_answer": ("Wrong answer", "status-failed"),
        "partial": ("Partially passed", "status-partial"),
        "compile_error": ("Compile error", "status-compile"),
        "time_limit": ("Time limit", "status-timeout"),
        "memory_limit": ("Memory limit", "status-memory"),
        "runtime_error": ("Runtime error", "status-runtime"),
        "judge_error": ("Judge error", "status-judge-error"),
    },
}

_LEGACY_DIFFICULTIES = {
    "easy": {"zh-CN": "旧制 · 简单", "en": "Legacy · Easy"},
    "medium": {"zh-CN": "旧制 · 中等", "en": "Legacy · Medium"},
    "hard": {"zh-CN": "旧制 · 困难", "en": "Legacy · Hard"},
    "基础": {"zh-CN": "旧制 · 基础", "en": "Legacy · Basic"},
    "进阶": {"zh-CN": "旧制 · 进阶", "en": "Legacy · Advanced"},
    "困难": {"zh-CN": "旧制 · 困难", "en": "Legacy · Difficult"},
}


def _locale_code(locale=None):
    if locale is None:
        locale = st.session_state.get("_locale", "zh-CN")
    return "en" if str(locale).lower().startswith("en") else "zh-CN"


def difficulty_projection(raw, locale="zh-CN"):
    """Map exact Luogu labels to color tokens; keep legacy labels neutral."""

    locale = _locale_code(locale)
    projection = normalize_difficulty(str(raw or ""), locale)
    if projection["recognized"]:
        return {
            "id": projection["id"],
            "label": projection["label"],
            "token": projection["color_token"],
            "recognized": True,
        }
    original = str(raw or "").strip()
    legacy = _LEGACY_DIFFICULTIES.get(original.casefold()) or _LEGACY_DIFFICULTIES.get(original)
    return {
        "id": None,
        "label": legacy[locale] if legacy else ("未分级" if locale == "zh-CN" else "Unrated"),
        "token": "difficulty-neutral",
        "recognized": False,
    }


def problem_status_index(payload):
    """Return an allow-listed problem status index, or ``None`` on bad schema."""

    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != STATUS_SCHEMA
        or not isinstance(payload.get("items"), list)
    ):
        return None
    result = {}
    for raw in payload["items"]:
        if not isinstance(raw, Mapping):
            continue
        problem_id = raw.get("problem_id")
        state = raw.get("state")
        if (
            not isinstance(problem_id, str)
            or not problem_id.strip()
            or problem_id in result
            or state not in _PROBLEM_STATES
        ):
            continue
        terminal = raw.get("latest_terminal")
        terminal_status = terminal.get("status") if isinstance(terminal, Mapping) else None
        outcome = raw.get("latest_outcome")
        result[problem_id] = {
            "state": state,
            "latest_outcome": outcome if outcome in _OUTCOMES else None,
            "terminal_error": terminal_status == "error",
        }
    return result


def _status_presentation(status, locale):
    locale = _locale_code(locale)
    if not isinstance(status, Mapping):
        return _STATE_PRESENTATION[locale]["unavailable"]
    state = status.get("state")
    # Current-version lifecycle states take priority over historical verdicts.
    if state in {"unattempted", "pending", "outdated"}:
        return _STATE_PRESENTATION[locale][state]
    outcome = status.get("latest_outcome")
    if outcome in _OUTCOMES:
        return _OUTCOME_PRESENTATION[locale][outcome]
    if status.get("terminal_error"):
        return _OUTCOME_PRESENTATION[locale]["judge_error"]
    return _STATE_PRESENTATION[locale].get(state, _STATE_PRESENTATION[locale]["unavailable"])


def problem_badges_html(difficulty, status, locale="zh-CN"):
    """Render two small, escaped badges without exposing raw status records."""

    locale = _locale_code(locale)
    label, status_class = _status_presentation(status, locale)
    if not isinstance(difficulty, Mapping):
        difficulty = {}
    difficulty_label = difficulty.get("label")
    if not isinstance(difficulty_label, str) or not difficulty_label:
        difficulty_label = "未分级" if locale == "zh-CN" else "Unrated"
    difficulty_token = difficulty.get("token")
    if difficulty_token not in _DIFFICULTY_TOKENS:
        difficulty_token = "difficulty-neutral"
    status_prefix = "提交状态" if locale == "zh-CN" else "Submission status"
    difficulty_prefix = "难度" if locale == "zh-CN" else "Difficulty"
    return (
        "<div class='oj-catalog-badges'>"
        f"<span class='oj-status-token {status_class}' aria-label='"
        f"{html.escape(status_prefix + ': ' + label, quote=True)}'>{html.escape(label)}</span>"
        f"<span class='oj-difficulty-token {difficulty_token}' aria-label='"
        f"{html.escape(difficulty_prefix + ': ' + difficulty_label, quote=True)}'>"
        f"{html.escape(difficulty_label)}</span></div>"
    )


def _difficulty_filter(rows, locale):
    present = {row[1]["id"] for row in rows if row[1]["recognized"]}
    has_neutral = any(not row[1]["recognized"] for row in rows)
    options = ["all"] + [item["id"] for item in DIFFICULTIES if item["id"] in present]
    if has_neutral:
        options.append("neutral")
    labels = {"all": "全部难度" if locale == "zh-CN" else "All difficulties"}
    labels.update({item["id"]: item[locale] for item in DIFFICULTIES})
    labels["neutral"] = "未分级" if locale == "zh-CN" else "Unrated"
    return options, labels


def catalog():
    locale = _locale_code()
    st.title("题库")
    st.caption("从一个问题开始，把解题思路变成可运行的程序。")
    top, action = st.columns([4, 1])
    search = top.text_input(
        "搜索题目", placeholder="题名、题号或知识点", label_visibility="collapsed"
    )
    action.button(
        "新增题目", type="primary", on_click=go, args=("题库",), kwargs={"_problem_mode": "new"}
    )
    client = api()
    all_problems = client.request("GET", "/api/problems/")
    status_message = None
    try:
        statuses = problem_status_index(client.request("GET", "/api/me/problem-statuses/"))
        if statuses is None:
            statuses = {}
            status_message = (
                "提交状态数据暂不可用，题库仍可正常浏览。"
                if locale == "zh-CN"
                else "Submission status is unavailable; the catalog remains usable."
            )
    except APIError as exc:
        if exc.status == 401:
            raise
        statuses = {}
        status_message = (
            "提交状态暂时无法加载，题库仍可正常浏览。"
            if locale == "zh-CN"
            else "Submission status could not be loaded; the catalog remains usable."
        )
    rows = [
        (problem, difficulty_projection(problem.get("difficulty"), locale))
        for problem in all_problems
    ]
    options, option_labels = _difficulty_filter(rows, locale)
    difficulty = st.selectbox(
        "难度" if locale == "zh-CN" else "Difficulty",
        options,
        format_func=option_labels.get,
    )
    if status_message:
        st.caption(status_message)
    query = search.casefold().strip()
    filtered = [
        (p, projection)
        for p, projection in rows
        if (
            not query
            or query in " ".join([p["id"], p["title"], " ".join(p.get("tags") or [])]).casefold()
        )
        and (
            difficulty == "all"
            or projection["id"] == difficulty
            or difficulty == "neutral"
            and not projection["recognized"]
        )
    ]
    st.caption(f"{len(filtered)} 道题目")
    if not filtered:
        st.info("暂无匹配题目。可调整搜索条件，或新增一道题目。")
        return
    pages = max(1, (len(filtered) + 11) // 12)
    signature = (search, difficulty)
    if st.session_state.get("_catalog_filter") != signature:
        st.session_state["catalog_page"] = 1
        st.session_state["_catalog_filter"] = signature
    st.session_state["catalog_page"] = min(st.session_state.get("catalog_page", 1), pages)
    page = st.number_input("题库页码", min_value=1, max_value=pages, step=1, key="catalog_page")
    for problem, projection in filtered[(page - 1) * 12 : page * 12]:
        row_key = hashlib.sha256(problem["id"].encode("utf-8")).hexdigest()[:12]
        with st.container(key=f"catalog_problem_{row_key}"):
            title, meta, action = st.columns([6, 1.5, 1.5], vertical_alignment="center")
            title.write(problem["title"])
            title.caption(
                problem["id"]
                + (" · " + " / ".join(problem.get("tags") or []) if problem.get("tags") else "")
            )
            meta.html(problem_badges_html(projection, statuses.get(problem["id"]), locale))
            action.button(
                "打开",
                key=f"open_{problem['id']}",
                on_click=go,
                args=("题库",),
                kwargs={"_problem_mode": "detail", "_problem_id": problem["id"]},
            )


def render_statement(problem):
    with st.container(key="problem_prose"):
        for field, label in (
            ("description", "题目描述"),
            ("input_description", "输入格式"),
            ("output_description", "输出格式"),
            ("constraints", "数据范围"),
        ):
            st.subheader(label)
            st.markdown(problem.get(field, ""))
        st.subheader("样例")
        for index, sample in enumerate(problem.get("samples", []), 1):
            left, right = st.columns(2)
            left.caption(f"输入 {index}")
            left.code(sample["input"], language="text")
            right.caption(f"输出 {index}")
            right.code(sample["output"], language="text")
        if problem.get("hint"):
            st.subheader("提示")
            st.markdown(problem["hint"])
        with st.expander(f"测试数据 · {len(problem.get('testcases', []))} 组"):
            for index, case in enumerate(problem.get("testcases", []), 1):
                st.caption(f"测试点 {index}")
                left, right = st.columns(2)
                left.code(case["input"], language="text")
                right.code(case["output"], language="text")


def code_submission(problem):
    st.subheader("编写并提交")
    names = api().request("GET", "/api/languages/")["name"]
    if not names:
        st.warning("当前暂无可用编程语言，请联系管理员。")
        return
    with st.form("submission_form", border=False):
        language = st.selectbox("编程语言", names)
        st.caption("使用标准输入输出，提交完整程序。代码中的空格与换行将原样发送。")
        with st.container(key="code_editor"):
            code = st.text_area("代码", height=360, key=f"code_{problem['id']}")
        submit = st.form_submit_button("提交代码", type="primary")
    if submit:
        if not code.strip():
            st.error("请先填写代码。")
            return
        ok, result = mutation(
            "POST",
            "/api/submissions/",
            json={"problem_id": problem["id"], "language": language, "code": code},
        )
        if ok:
            go("提交记录", _submission_id=result["submission_id"])
            notice("代码已提交，正在等待评测。")
            st.rerun()


def problem_detail(problem):
    st.title(problem["title"])
    localized_difficulty = difficulty_projection(problem.get("difficulty"), _locale_code())
    time_limit = (
        f"{problem['time_limit']} 秒" if problem.get("time_limit") is not None else "随语言配置"
    )
    memory = (
        f"{problem['memory_limit']} MB" if problem.get("memory_limit") is not None else "随语言配置"
    )
    st.caption(
        f"{problem['id']} · {localized_difficulty['label']} · 时间 {time_limit} · 内存 {memory}"
    )
    if problem.get("source") or problem.get("author"):
        st.caption(
            f"来源：{problem.get('source') or '未标注'} · 作者：{problem.get('author') or '未标注'}"
        )
    st.button("编辑题目", on_click=go, args=("题库",), kwargs={"_problem_mode": "edit"})
    statement, program = st.tabs(["题目", "编程"])
    with statement:
        render_statement(problem)
    with program:
        code_submission(problem)
    if is_admin():
        with st.expander("题目管理"):
            visibility = st.checkbox(
                "向登录用户公开逐测试点评测日志", value=bool(problem.get("public_cases"))
            )
            if st.button("保存日志可见性"):
                ok, _ = mutation(
                    "PUT",
                    f"/api/problems/{resource(problem['id'])}/log_visibility",
                    json={"public_cases": visibility},
                )
                if ok:
                    notice("日志可见性已更新。")
                    st.rerun()
            st.divider()
            confirmed = st.checkbox(f"确认删除题目 {problem['id']}；已有记录不会因此重新评测")
            if st.button("删除题目", disabled=not confirmed):
                ok, _ = mutation("DELETE", f"/api/problems/{resource(problem['id'])}")
                if ok:
                    go("题库", _problem_mode="list", _problem_id=None)
                    notice("题目已删除。")
                    st.rerun()


def problems_page():
    mode = st.session_state.get("_problem_mode", "list")
    if mode == "list":
        catalog()
        return
    # Keep recovery available before fetching a selected problem: another
    # session may have deleted it. Returning also discards the stale identity.
    st.button(
        "← 返回题库",
        on_click=go,
        args=("题库",),
        kwargs={"_problem_mode": "list", "_problem_id": None},
    )
    problem = None
    if mode in ("detail", "edit"):
        problem = api().request("GET", f"/api/problems/{resource(st.session_state['_problem_id'])}")
    if mode == "detail":
        problem_detail(problem)
        return
    st.title("编辑题目" if problem else "新增题目")
    st.caption("完整填写题面与测试数据。保存后仍可继续编辑。")
    payload = problem_form(
        problem,
        prefix=f"edit_{problem['id']}" if problem else "new_problem",
        locked_id=problem["id"] if problem else None,
    )
    if payload:
        path = f"/api/problems/{resource(problem['id'])}" if problem else "/api/problems/"
        ok, _ = mutation("PUT" if problem else "POST", path, json=payload)
        if ok:
            go("题库", _problem_mode="detail", _problem_id=payload["id"])
            notice("题目已保存。")
            st.rerun()
