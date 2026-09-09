"""Streamlit app entry and role-aware routing."""

import streamlit as st

from frontend.accounts import account_page, authentication, logout
from frontend.admin import admin_page
from frontend.ai_page import ai_page
from frontend.analytics import analytics_page
from frontend.chat import chat_assistant, workspace_focus
from frontend.client import APIError, resource
from frontend.common import api, clear_session, go, is_admin, show_error, user
from frontend.i18n import other_locale, role_label, set_locale, t
from frontend.problems import problems_page
from frontend.styles import (
    active_navigation,
    auth_story,
    inject,
    sidebar_brand,
    sidebar_profile,
    workspace_header,
    workspace_identity,
)
from frontend.submissions import submissions_page

NAV_ITEMS = {
    "题库": ("problems", ":material/menu_book:", "nav.problems"),
    "提交记录": ("submissions", ":material/terminal:", "nav.submissions"),
    "成绩总览": ("analytics", ":material/monitoring:", "nav.analytics"),
    "智能命题": ("authoring", ":material/auto_awesome:", "nav.authoring"),
    "账户": ("account", ":material/person:", "nav.account"),
    "管理工作区": ("admin", ":material/manage_accounts:", "nav.admin"),
}


def _navigation_button(page, selected):
    slug, icon, label_key = NAV_ITEMS[page]
    label = t(label_key)
    with st.container(key=f"nav_item_{slug}"):
        st.button(
            label,
            key=f"nav_{slug}",
            icon=icon,
            type="tertiary",
            width="stretch",
            help=t("nav.current") if page == selected else t("nav.open", page=label),
            on_click=go,
            args=(page,),
        )


def _sidebar(selected, profile):
    with st.sidebar:
        with st.container(key="workspace_nav", gap="small"):
            sidebar_brand()
            active_navigation(NAV_ITEMS[selected][0])
            with st.container(key="sidebar_links", gap=None):
                st.html(f'<p class="oj-nav-group">{t("nav.group.learning")}</p>')
                _navigation_button("题库", selected)
                _navigation_button("提交记录", selected)
                _navigation_button("成绩总览", selected)
                st.html(f'<p class="oj-nav-group">{t("nav.group.creation")}</p>')
                _navigation_button("智能命题", selected)
                if is_admin():
                    st.html(f'<p class="oj-nav-group">{t("nav.group.admin")}</p>')
                    _navigation_button("管理工作区", selected)
            with st.container(key="sidebar_account", gap="small"):
                sidebar_profile(profile["username"], role_label(profile["role"]))
                _navigation_button("账户", selected)
                if st.button(
                    t("action.logout"),
                    key="sidebar_logout",
                    icon=":material/logout:",
                    type="tertiary",
                    width="stretch",
                ):
                    logout()


def _toggle_language():
    set_locale(other_locale())
    # A toast already mounted in the browser can survive a Streamlit rerun for
    # its full client-side duration. Hide that stale-language node on this one
    # rerun so the workspace never appears half translated.
    st.session_state["_hide_toasts_once"] = True
    # Never retain transient copy in the language it was originally rendered in.
    for key in (
        "_notice",
        "_auth_error",
        "_auth_notice",
        "login_password",
        "register_password",
        "register_repeat",
        "admin_password",
    ):
        st.session_state.pop(key, None)
    # A password widget would otherwise be mounted again during the same rerun
    # and Streamlit would recreate its session key. Return to the identity step
    # while retaining only the already-entered, non-secret account name.
    if st.session_state.get("_auth_step") == "password":
        mode = st.session_state.get("_auth_mode", "login")
        st.session_state[f"{mode}_username"] = st.session_state.get("_auth_name", "")
        st.session_state["_auth_step"] = "identity"


def _language_control():
    with st.container(key="language_control"):
        st.button(
            t("language.switch"),
            key="language_switch",
            icon=":material/language:",
            type="tertiary",
            help=t("language.switch_help"),
            on_click=_toggle_language,
        )


def main():
    st.set_page_config(page_title=t("app.title"), page_icon=":material/code:", layout="wide")
    inject()
    if st.session_state.pop("_clear_secrets", False):
        for key in (
            "login_password",
            "register_password",
            "register_repeat",
            "admin_password",
            "ai_api_key",
        ):
            st.session_state.pop(key, None)
    # Keys do not replace positional delta paths. Always reserve one locked
    # slot: conditional info/toast calls here would shift the fragment shell.
    notice_slot = st.empty()
    pending_notice = st.session_state.pop("_notice", None)
    if pending_notice:
        notice_slot.toast(pending_notice, duration="long")
    elif st.session_state.pop("_hide_toasts_once", False):
        notice_slot.html(
            '<style data-oj-toast-language-reset="true">'
            '[data-testid="stToastContainer"]{display:none!important}'
            "</style>"
        )
    if not user():
        with st.container(
            key="auth_language_bar",
            horizontal=True,
            horizontal_alignment="right",
        ):
            _language_control()
        with st.container(key="auth_layout", horizontal=True, horizontal_alignment="center"):
            with st.container(
                key="auth_composition", horizontal=True, wrap=False, gap=None, width=920
            ):
                with st.container(key="auth_story", width=440):
                    auth_story()
                with st.container(key="auth_shell", width=480):
                    authentication()
        return
    try:
        profile = api().request("GET", f"/api/users/{resource(user()['user_id'])}")
        if profile.get("role") != user().get("role"):
            # Drop previously authorized privileged data after a role change.
            for key in list(st.session_state):
                if key.startswith(("_log_", "_submission_")):
                    st.session_state.pop(key, None)
        st.session_state["_user"] = profile
    except APIError as exc:
        if exc.status in (401, 403):
            clear_session(t("session.expired"))
            st.rerun()
        show_error(exc)
        if st.button(t("action.retry_connection")):
            st.rerun()
        return
    pages = {
        "题库": problems_page,
        "提交记录": submissions_page,
        "成绩总览": analytics_page,
        "智能命题": ai_page,
        "账户": account_page,
    }
    if is_admin():
        pages["管理工作区"] = admin_page
    requested = st.session_state.pop("_next_navigation", None)
    if requested in pages:
        st.session_state["navigation"] = requested
    elif st.session_state.get("navigation") not in pages:
        st.session_state["navigation"] = "题库"
    selected = st.session_state["navigation"]
    _sidebar(selected, profile)
    # Stable outer shell stays mounted during normal reruns and fragment polling.
    # Only a changed route gets a different entry animation; there is no delay.
    with st.container(key="workspace_shell"):
        with st.container(
            key="workspace_commandbar",
            horizontal=True,
            horizontal_alignment="right",
            vertical_alignment="center",
            gap="small",
            wrap=True,
        ):
            with st.container(key="workspace_header_slot", width="stretch"):
                workspace_header(t(NAV_ITEMS[selected][2]))
            with st.container(
                key="workspace_actions",
                horizontal=True,
                horizontal_alignment="right",
                vertical_alignment="center",
                gap="small",
                wrap=True,
                width="content",
            ):
                workspace_identity(profile["username"], role_label(profile["role"]))
                _language_control()
                chat_assistant(focus=workspace_focus(selected, st.session_state))
        with st.container(key=f"route_content_{NAV_ITEMS[selected][0]}"):
            try:
                pages[selected]()
            except APIError as exc:
                if exc.status == 401:
                    clear_session(t("session.login_expired"))
                    st.rerun()
                show_error(exc)
                if st.button(t("action.reload"), key="retry_page"):
                    st.rerun()


if __name__ == "__main__":
    main()
