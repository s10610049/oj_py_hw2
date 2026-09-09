"""Shared rendering and session state helpers; no backend imports."""

import html

import streamlit as st

from frontend.client import APIClient, APIError

ROLE_LABELS = {"admin": "管理员", "user": "学习者", "banned": "已禁用"}


def api():
    if "_api" not in st.session_state:
        st.session_state["_api"] = APIClient()
    return st.session_state["_api"]


def user():
    return st.session_state.get("_user", {})


def is_admin():
    return user().get("role") == "admin"


def go(page, **state):
    st.session_state["_next_navigation"] = page
    st.session_state.update(state)


def notice(message):
    st.session_state["_notice"] = message


def clear_session(message="已退出登录。"):
    current = st.session_state.get("_api")
    if current:
        current.close()
    st.session_state.clear()
    st.session_state["_notice"] = message


def show_error(exc):
    labels = {
        0: "连接暂不可用",
        400: "请检查输入",
        401: "登录状态已失效",
        403: "无法执行此操作",
        404: "未找到记录",
        409: "记录状态已变化",
        429: "请求过于频繁，请稍后再试",
        500: "服务暂时异常",
        502: "响应异常",
    }
    st.error(f"{labels.get(exc.status, '操作失败')}：{exc.message}")


def poll_error(exc):
    if exc.status == 401:
        clear_session("登录已失效，请重新登录。")
        st.rerun(scope="app")
    show_error(exc)
    st.caption("保留上次已确认状态；连接失败不表示后台任务已停止。")


def score_text(record):
    if record.get("score") is None or record.get("counts") is None:
        return "尚未返回"
    return f"{record['score']} / {record['counts']}"


def data_table(records):
    """Escaped semantic table without an optional NumPy/Arrow native dependency."""
    if not records:
        return
    columns = list(records[0])
    header = "".join(f"<th scope='col'>{html.escape(str(key))}</th>" for key in columns)
    rows = "".join(
        "<tr>"
        + "".join(
            (
                '<td class="oj-number">' + html.escape(str(record.get(key, ""))) + "</td>"
                if isinstance(record.get(key), (int, float)) or key == "得分"
                else "<td>" + html.escape(str(record.get(key, ""))) + "</td>"
            )
            for key in columns
        )
        + "</tr>"
        for record in records
    )
    st.html(
        '<div class="oj-table-scroll" tabindex="0" role="region" aria-label="数据表">'
        '<table class="oj-table"><thead><tr>'
        + header
        + "</tr></thead><tbody>"
        + rows
        + "</tbody></table></div>"
    )


def mutation(method, path, *, json=None):
    """Catch recoverable form errors at the form, so input remains visible."""
    try:
        return True, api().request(method, path, json=json)
    except APIError as exc:
        if exc.status == 401:
            clear_session("登录已失效，请重新登录。")
            st.rerun()
        show_error(exc)
        return False, None
