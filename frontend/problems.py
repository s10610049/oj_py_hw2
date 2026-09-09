"""Problem catalog, complete editor and programming workspace."""

import streamlit as st

from frontend.client import resource
from frontend.common import api, go, is_admin, mutation, notice
from frontend.forms import problem_form


def catalog():
    st.title("题库")
    st.caption("从一个问题开始，把解题思路变成可运行的程序。")
    top, action = st.columns([4, 1])
    search = top.text_input(
        "搜索题目", placeholder="题名、题号或知识点", label_visibility="collapsed"
    )
    action.button(
        "新增题目", type="primary", on_click=go, args=("题库",), kwargs={"_problem_mode": "new"}
    )
    all_problems = api().request("GET", "/api/problems/")
    levels = sorted({p.get("difficulty") for p in all_problems if p.get("difficulty")})
    difficulty = st.selectbox("难度", ["全部难度"] + levels)
    query = search.casefold().strip()
    filtered = [
        p
        for p in all_problems
        if (
            not query
            or query in " ".join([p["id"], p["title"], " ".join(p.get("tags") or [])]).casefold()
        )
        and (difficulty == "全部难度" or p.get("difficulty") == difficulty)
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
    for problem in filtered[(page - 1) * 12 : page * 12]:
        title, meta, action = st.columns([6, 2, 1])
        title.write(problem["title"])
        title.caption(
            problem["id"]
            + (" · " + " / ".join(problem.get("tags") or []) if problem.get("tags") else "")
        )
        meta.caption(problem.get("difficulty") or "未标难度")
        action.button(
            "打开",
            key=f"open_{problem['id']}",
            on_click=go,
            args=("题库",),
            kwargs={"_problem_mode": "detail", "_problem_id": problem["id"]},
        )
        st.divider()


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
    st.button("← 返回题库", on_click=go, args=("题库",), kwargs={"_problem_mode": "list"})
    st.title(problem["title"])
    time_limit = (
        f"{problem['time_limit']} 秒" if problem.get("time_limit") is not None else "随语言配置"
    )
    memory = (
        f"{problem['memory_limit']} MB" if problem.get("memory_limit") is not None else "随语言配置"
    )
    st.caption(
        f"{problem['id']} · {problem.get('difficulty') or '未标难度'} · 时间 {time_limit} · 内存 {memory}"
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
    problem = None
    if mode in ("detail", "edit"):
        problem = api().request("GET", f"/api/problems/{resource(st.session_state['_problem_id'])}")
    if mode == "detail":
        problem_detail(problem)
        return
    st.button("← 返回题库", on_click=go, args=("题库",), kwargs={"_problem_mode": "list"})
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
