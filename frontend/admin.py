"""Administrative workspace shares the same API permissions and visual system."""

from collections.abc import Mapping

import streamlit as st

from frontend.accounts import users_page
from frontend.admin_analytics import admin_overview_page
from frontend.common import api, data_table, go, is_admin
from frontend.i18n import t


def audit_table_rows(records, locale_code=None):
    result = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, Mapping):
            continue
        action = record.get("action", "")
        action_label = (
            t("admin.audit_action.view_logs", locale_code)
            if action == "view_logs"
            else t("admin.audit_action.other", locale_code)
        )
        result.append(
            {
                t("admin.audit_column.user", locale_code): record.get("user_id", ""),
                t("admin.audit_column.problem", locale_code): record.get("problem_id", ""),
                t("admin.audit_column.action", locale_code): action_label,
                t("admin.audit_column.time", locale_code): record.get("time", ""),
                t("admin.audit_column.status", locale_code): record.get("status", ""),
            }
        )
    return result


def admin_page():
    if not is_admin():
        st.error(t("admin.forbidden"))
        return
    st.title(t("admin.title"))
    overview, users, audit, links = st.tabs(
        [
            t("admin.tab.overview"),
            t("admin.tab.users"),
            t("admin.tab.audit"),
            t("admin.tab.judge"),
        ]
    )
    with overview:
        admin_overview_page()
    with users:
        users_page()
    with audit:
        st.subheader(t("admin.tab.audit"))
        with st.form("audit_filters", border=False):
            a, b = st.columns(2)
            owner = a.text_input(t("admin.audit_owner"))
            problem = b.text_input(t("admin.audit_problem"))
            page = st.number_input(t("admin.audit_page"), min_value=1, value=1, step=1)
            submitted = st.form_submit_button(t("admin.audit_query"))
        if submitted:
            params = {"page": page, "page_size": 50}
            if owner.strip():
                params["user_id"] = owner.strip()
            if problem.strip():
                params["problem_id"] = problem.strip()
            records = api().request("GET", "/api/logs/access/", params=params)
            if records:
                data_table(audit_table_rows(records))
            else:
                st.info(t("admin.audit_empty"))
    with links:
        st.write(t("admin.judge_note"))
        st.button(
            t("admin.manage_problems"),
            on_click=go,
            args=("题库",),
            kwargs={"_problem_mode": "list"},
        )
        st.button(
            t("admin.manage_rejudge"),
            on_click=go,
            args=("提交记录",),
            kwargs={"_submission_id": None},
        )
