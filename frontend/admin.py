"""Administrative workspace shares the same API permissions and visual system."""

import streamlit as st

from frontend.accounts import users_page
from frontend.common import api, data_table, go, is_admin


def admin_page():
    if not is_admin():
        st.error("此页面仅对管理员开放。")
        return
    st.title("管理工作区")
    users, audit, links = st.tabs(["用户与权限", "日志访问审计", "题目与评测"])
    with users:
        users_page()
    with audit:
        st.subheader("日志访问审计")
        with st.form("audit_filters", border=False):
            a, b = st.columns(2)
            owner = a.text_input("访问用户编号（可选）")
            problem = b.text_input("日志题号（可选）")
            page = st.number_input("审计页码", min_value=1, value=1, step=1)
            submitted = st.form_submit_button("查询访问记录")
        if submitted:
            params = {"page": page, "page_size": 50}
            if owner.strip():
                params["user_id"] = owner.strip()
            if problem.strip():
                params["problem_id"] = problem.strip()
            records = api().request("GET", "/api/logs/access/", params=params)
            if records:
                data_table(records)
            else:
                st.info("没有匹配的访问记录。")
    with links:
        st.write("题目删除与日志可见性在题目详情的管理区操作。重新评测在提交详情中操作。")
        st.button("管理题库", on_click=go, args=("题库",), kwargs={"_problem_mode": "list"})
        st.button(
            "查询与重新评测", on_click=go, args=("提交记录",), kwargs={"_submission_id": None}
        )
