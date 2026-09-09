"""Shared rendering and session state helpers; no backend imports."""

import html

import streamlit as st

from frontend.client import APIClient, APIError
from frontend.i18n import api_error_message, locale, t


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


def clear_session(message=None):
    current = st.session_state.get("_api")
    selected_locale = locale()
    if current:
        current.close()
    st.session_state.clear()
    st.session_state["_locale"] = selected_locale
    st.session_state["_notice"] = message or t("session.logged_out")


def show_error(exc):
    labels = {
        0: "error.connection",
        400: "error.input",
        401: "error.auth",
        403: "error.permission",
        404: "error.not_found",
        409: "error.conflict",
        429: "error.rate_limit",
        500: "error.server",
        502: "error.response",
    }
    separator = "：" if locale() == "zh-CN" else ": "
    st.error(
        t(labels.get(exc.status, "error.generic")) + separator + api_error_message(exc.message)
    )


def poll_error(exc):
    if exc.status == 401:
        clear_session(t("session.login_expired"))
        st.rerun(scope="app")
    show_error(exc)
    st.caption(t("poll.preserved"))


def score_text(record):
    if record.get("score") is None or record.get("counts") is None:
        return t("score.pending")
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
        '<div class="oj-table-scroll" tabindex="0" role="region" aria-label="'
        + html.escape(t("table.aria"), quote=True)
        + '">'
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
            clear_session(t("session.login_expired"))
            st.rerun()
        show_error(exc)
        return False, None
