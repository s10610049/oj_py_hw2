"""Streamlit app entry and role-aware routing."""

import streamlit as st

from frontend.accounts import account_page, authentication, logout
from frontend.admin import admin_page
from frontend.ai_page import ai_page
from frontend.client import APIError, resource
from frontend.common import ROLE_LABELS, api, clear_session, go, is_admin, show_error, user
from frontend.problems import problems_page
from frontend.styles import (
    active_navigation,
    auth_story,
    inject,
    sidebar_brand,
    sidebar_profile,
    workspace_header,
)
from frontend.submissions import submissions_page

NAV_ITEMS = {
    "题库": ("problems", ":material/menu_book:"),
    "提交记录": ("submissions", ":material/terminal:"),
    "智能命题": ("authoring", ":material/auto_awesome:"),
    "账户": ("account", ":material/person:"),
    "管理工作区": ("admin", ":material/manage_accounts:"),
}


def _navigation_button(page, selected):
    slug, icon = NAV_ITEMS[page]
    with st.container(key=f"nav_item_{slug}"):
        st.button(
            page,
            key=f"nav_{slug}",
            icon=icon,
            type="tertiary",
            width="stretch",
            help="当前页面" if page == selected else f"打开{page}",
            on_click=go,
            args=(page,),
        )


def _sidebar(selected, profile):
    with st.sidebar:
        with st.container(key="workspace_nav", gap="small"):
            sidebar_brand()
            active_navigation(NAV_ITEMS[selected][0])
            with st.container(key="sidebar_links", gap=None):
                st.html('<p class="oj-nav-group">学习工作台</p>')
                _navigation_button("题库", selected)
                _navigation_button("提交记录", selected)
                st.html('<p class="oj-nav-group">创作工具</p>')
                _navigation_button("智能命题", selected)
                if is_admin():
                    st.html('<p class="oj-nav-group">管理</p>')
                    _navigation_button("管理工作区", selected)
            with st.container(key="sidebar_account", gap="small"):
                sidebar_profile(
                    profile["username"], ROLE_LABELS.get(profile["role"], profile["role"])
                )
                _navigation_button("账户", selected)
                if st.button(
                    "退出登录",
                    key="sidebar_logout",
                    icon=":material/logout:",
                    type="tertiary",
                    width="stretch",
                ):
                    logout()


def main():
    st.set_page_config(page_title="OJ · 编程练习室", page_icon=":material/code:", layout="wide")
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
    if not user():
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
            clear_session("会话已失效或账户不可用，请重新登录。")
            st.rerun()
        show_error(exc)
        if st.button("重试连接"):
            st.rerun()
        return
    pages = {
        "题库": problems_page,
        "提交记录": submissions_page,
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
        workspace_header(selected, ROLE_LABELS.get(profile["role"], profile["role"]))
        with st.container(key=f"route_content_{NAV_ITEMS[selected][0]}"):
            try:
                pages[selected]()
            except APIError as exc:
                if exc.status == 401:
                    clear_session("登录已失效，请重新登录。")
                    st.rerun()
                show_error(exc)
                if st.button("重新加载", key="retry_page"):
                    st.rerun()


if __name__ == "__main__":
    main()
