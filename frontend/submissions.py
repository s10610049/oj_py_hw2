"""Submission list, live results and explicitly requested authorized logs."""

import streamlit as st

from frontend.client import APIError, resource
from frontend.common import (
    api,
    data_table,
    go,
    is_admin,
    mutation,
    notice,
    poll_error,
    score_text,
    user,
)

STATUS = {"pending": "评测中", "success": "评测完成", "error": "评测异常"}


def render_result(record):
    status = record["status"]
    if status == "pending":
        st.status("代码已接收，正在评测", state="running", type="compact")
    elif status == "error":
        st.error("评测任务异常，请查看错误信息。")
    elif record.get("counts") and record.get("score") == record["counts"]:
        st.success("全部通过 · AC")
    else:
        st.warning("评测完成，尚未全部通过。请查看编译、运行信息或授权日志。")
    st.write("得分：" + score_text(record))
    for key, title in (("compile_info", "编译信息"), ("run_info", "运行结果")):
        value = record.get(key)
        if value:
            st.subheader(title)
            st.write(str(value.get("result", "")))
            if value.get("message"):
                st.code(str(value["message"]), language="text")
    if record.get("error_info"):
        st.subheader("错误信息")
        st.code(str(record["error_info"]), language="text")


def render_log(log):
    st.write("日志得分：" + score_text(log))
    if "details" not in log:
        st.info("本题未公开逐测试点结果；当前权限仅可查看总分。")
    elif not log["details"]:
        st.caption("尚未产生逐测试点结果。")
    else:
        data_table(
            [
                {
                    "测试点": item["id"],
                    "结果": item["result"],
                    "耗时（秒）": item["time"],
                    "内存（MiB）": item["memory"],
                }
                for item in log["details"]
            ],
        )


def submission_detail(submission_id):
    st.button("← 返回提交列表", on_click=go, args=("提交记录",), kwargs={"_submission_id": None})
    st.title("提交详情")
    st.caption(f"提交编号：{submission_id}")
    cache_key = f"_submission_{submission_id}"
    cached = st.session_state.get(cache_key)
    active = not cached or cached.get("status") == "pending"

    @st.fragment(run_every=1 if active else None)
    def panel():
        previous = st.session_state.get(cache_key)
        try:
            current = (
                api().request("GET", f"/api/submissions/{resource(submission_id)}")
                if active or not previous
                else previous
            )
            st.session_state[cache_key] = current
        except APIError as exc:
            poll_error(exc)
            if previous:
                render_result(previous)
            return
        if active and current["status"] != "pending":
            st.rerun(scope="app")
        if current.get("problem_id"):
            st.caption(
                f"题目 {current['problem_id']} · {current.get('language', '')} · "
                f"{current.get('created_at', '')}"
            )
        render_result(current)
        if st.button("刷新评测状态", key=f"refresh_{submission_id}"):
            st.session_state.pop(cache_key, None)
            st.rerun(scope="app")
        if current.get("code") is not None:
            with st.expander("查看本次提交代码"):
                language = "cpp" if current.get("language") == "cpp" else "python"
                st.code(current["code"], language=language)
        st.divider()
        if st.button("查询评测日志", key=f"log_{submission_id}"):
            ok, data = mutation("GET", f"/api/submissions/{resource(submission_id)}/log")
            if ok:
                st.session_state[f"_log_{submission_id}"] = data
        if f"_log_{submission_id}" in st.session_state:
            render_log(st.session_state[f"_log_{submission_id}"])
        if is_admin():
            with st.expander("管理员操作"):
                confirmed = st.checkbox(
                    "重新评测会覆盖本次评测结果", key=f"confirm_rejudge_{submission_id}"
                )
                if st.button("重新评测", disabled=not confirmed, key=f"rejudge_{submission_id}"):
                    ok, _ = mutation("PUT", f"/api/submissions/{resource(submission_id)}/rejudge")
                    if ok:
                        st.session_state.pop(cache_key, None)
                        st.session_state.pop(f"_log_{submission_id}", None)
                        notice("已开始重新评测。")
                        st.rerun(scope="app")

    panel()


def submission_list():
    st.title("提交记录")
    st.caption("每一次提交，都留下可回看的解题轨迹。")
    with st.form("submission_filters", border=False):
        a, b, c = st.columns(3)
        problem_id = a.text_input("题号筛选（可选）")
        status = b.selectbox(
            "评测状态", ["全部"] + list(STATUS), format_func=lambda x: STATUS.get(x, x)
        )
        owner = c.text_input("用户编号", value=user()["user_id"], disabled=not is_admin())
        st.form_submit_button("查询记录", type="primary")
    if not owner.strip() and not problem_id.strip():
        st.info("请填写用户编号或题号。管理员可清空用户编号，查询某题的全部提交。")
        return
    page = st.number_input("提交列表页码", min_value=1, value=1, step=1)
    params = {"page": page, "page_size": 20}
    if owner.strip():
        params["user_id"] = owner.strip()
    if problem_id.strip():
        params["problem_id"] = problem_id.strip()
    if status != "全部":
        params["status"] = status
    result = api().request("GET", "/api/submissions/", params=params)
    st.caption(f"共 {result['total']} 次提交")
    records = result["submissions"]
    if records:
        data_table(
            [
                {
                    "提交编号": x["submission_id"],
                    "题目": x.get("problem_id", ""),
                    "语言": x.get("language", ""),
                    "状态": STATUS.get(x["status"], x["status"]),
                    "得分": score_text(x),
                    "提交时间": x.get("created_at", ""),
                }
                for x in records
            ],
        )
        selected = st.selectbox("选择提交查看详情", [x["submission_id"] for x in records])
        st.button("打开提交", on_click=go, args=("提交记录",), kwargs={"_submission_id": selected})
    else:
        st.info("本页暂无提交记录。")
    with st.expander("通过提交编号查询"):
        value = st.text_input("提交编号", key="direct_submission_id")
        if st.button("查询提交详情", disabled=not value.strip()):
            go("提交记录", _submission_id=value.strip())
            st.rerun()
        if st.button("查询公开日志", disabled=not value.strip()):
            ok, data = mutation("GET", f"/api/submissions/{resource(value.strip())}/log")
            if ok:
                render_log(data)


def submissions_page():
    submission_id = st.session_state.get("_submission_id")
    if submission_id:
        submission_detail(submission_id)
    else:
        submission_list()
