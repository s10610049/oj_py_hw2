"""Registration, sign-in, profile and role management."""

import streamlit as st

from frontend.client import APIError, resource
from frontend.common import (
    api,
    clear_session,
    data_table,
    mutation,
    notice,
    show_error,
    user,
)
from frontend.i18n import api_error_message, role_label, t
from frontend.styles import auth_brand, auth_identity


def _auth_clear_passwords():
    # Called before widgets are constructed, never cache credentials in flow state.
    for key in ("login_password", "register_password", "register_repeat"):
        st.session_state.pop(key, None)


def _auth_move(mode, step="identity"):
    _auth_clear_passwords()
    st.session_state.pop("_auth_error", None)
    st.session_state.pop("_auth_notice", None)
    if mode == st.session_state.get("_auth_mode", "login"):
        st.session_state[f"{mode}_username"] = st.session_state.get("_auth_name", "")
    else:
        st.session_state.pop("_auth_name", None)
    st.session_state["_auth_mode"] = mode
    st.session_state["_auth_step"] = step


def _auth_continue():
    mode = st.session_state.get("_auth_mode", "login")
    name = st.session_state.get(f"{mode}_username", "")
    st.session_state.pop("_auth_error", None)
    st.session_state.pop("_auth_notice", None)
    _auth_clear_passwords()
    if not 3 <= len(name) <= 40 or not name.strip():
        st.session_state["_auth_error"] = t("auth.username_invalid")
        return
    # This step performs local validation only; it never probes account existence.
    st.session_state["_auth_name"] = name
    st.session_state["_auth_step"] = "password"


def _auth_submit():
    mode = st.session_state.get("_auth_mode", "login")
    name = st.session_state.get("_auth_name", "")
    password = st.session_state.get(f"{mode}_password", "")
    repeated = st.session_state.get("register_repeat", "")
    st.session_state.pop("_auth_error", None)
    st.session_state.pop("_auth_notice", None)
    try:
        if not 3 <= len(name) <= 40 or not name.strip():
            st.session_state["_auth_step"] = "identity"
            st.session_state["_auth_error"] = t("auth.username_required")
        elif not password:
            st.session_state["_auth_error"] = t("auth.password_required")
        elif mode == "register" and len(password) < 6:
            st.session_state["_auth_error"] = t("auth.password_short")
        elif mode == "register" and password != repeated:
            st.session_state["_auth_error"] = t("auth.password_mismatch")
        else:
            path = "/api/auth/login" if mode == "login" else "/api/users/"
            with st.spinner(t("auth.logging_in") if mode == "login" else t("auth.creating")):
                result = api().request("POST", path, json={"username": name, "password": password})
            if mode == "login":
                st.session_state["_user"] = result
                for key in list(st.session_state):
                    if key.startswith("_auth_"):
                        st.session_state.pop(key, None)
                notice(t("notice.welcome"))
            else:
                st.session_state["_auth_mode"] = "login"
                st.session_state["_auth_step"] = "password"
                st.session_state["login_username"] = name
                st.session_state["_auth_notice"] = t("auth.created")
    except APIError as exc:
        # The client also redacts secrets; keep even a misbehaving provider's
        # message out of persisted UI state before displaying an auth error.
        message = exc.message
        for secret in (password, repeated):
            if secret:
                message = message.replace(secret, "[redacted]")
        if mode == "login" and exc.status == 401:
            message = t("auth.invalid_credentials")
        elif mode == "login" and exc.status == 403 and exc.message == "Account is banned":
            message = t("auth.banned")
        elif exc.status == 0:
            message = t("auth.network")
        else:
            message = api_error_message(message)
        st.session_state["_auth_error"] = message
    finally:
        _auth_clear_passwords()
        if st.session_state.get("_auth_error") and st.session_state.get("_auth_step") == "password":
            # Deleting server state alone does not emit TextInput.set_value.
            # Explicitly reset still-mounted fields so the browser clears too.
            st.session_state[f"{mode}_password"] = ""
            if mode == "register":
                st.session_state["register_repeat"] = ""


def authentication():
    mode = st.session_state.get("_auth_mode", "login")
    step = st.session_state.get("_auth_step", "identity")
    auth_brand()
    with st.container(key=f"auth_stage_{mode}_{step}"):
        titles = {
            ("login", "identity"): t("auth.login"),
            ("login", "password"): t("auth.welcome_back"),
            ("register", "identity"): t("auth.create_account"),
            ("register", "password"): t("auth.set_password"),
        }
        st.title(titles[(mode, step)])
        st.caption(t("auth.login_caption") if mode == "login" else t("auth.register_caption"))
        step_number = 1 if step == "identity" else 2
        step_label = t("auth.username") if step == "identity" else t("auth.password")
        st.html(
            '<p class="oj-auth-step" role="status" aria-live="polite">'
            + t("auth.step", step=step_number, label=step_label)
            + "</p>"
        )
        if step == "password":
            with st.container(
                key="auth_identity_row", horizontal=True, vertical_alignment="center"
            ):
                auth_identity(st.session_state.get("_auth_name", ""))
                st.button(
                    t("auth.change_username"),
                    key="auth_back",
                    type="tertiary",
                    on_click=_auth_move,
                    args=(mode,),
                )
        if st.session_state.get("_auth_notice"):
            st.success(st.session_state["_auth_notice"])
        # One native form and a stable submit key preserve normal keyboard/form
        # semantics. No JS focus manipulation, fake inputs or hidden form copies.
        with st.form("auth_form", border=False, enter_to_submit=True):
            if step == "identity":
                st.text_input(
                    t("auth.username") if mode == "login" else t("auth.new_username"),
                    help=t("auth.username_help"),
                    key=f"{mode}_username",
                    autocomplete="username",
                    max_chars=40,
                )
            else:
                st.text_input(
                    t("auth.password") if mode == "login" else t("auth.set_password"),
                    type="password",
                    help=t("auth.password_help") if mode == "register" else None,
                    key=f"{mode}_password",
                    autocomplete="current-password" if mode == "login" else "new-password",
                )
                if mode == "register":
                    st.text_input(
                        t("auth.password_again"),
                        type="password",
                        key="register_repeat",
                        autocomplete="new-password",
                    )
            if st.session_state.get("_auth_error"):
                st.error(st.session_state["_auth_error"])
            label = (
                t("auth.next")
                if step == "identity"
                else (t("auth.login") if mode == "login" else t("auth.create_account"))
            )
            st.form_submit_button(
                label,
                key="auth_continue",
                type="primary",
                width="stretch",
                on_click=_auth_continue if step == "identity" else _auth_submit,
            )
        st.button(
            t("auth.create_account") if mode == "login" else t("auth.back_login"),
            key="auth_switch_mode",
            type="tertiary",
            on_click=_auth_move,
            args=("register" if mode == "login" else "login",),
        )
    st.html('<p class="oj-auth-footer">' + t("auth.footer") + "</p>")


def logout():
    try:
        api().request("POST", "/api/auth/logout")
    except APIError as exc:
        if exc.status != 401:
            show_error(exc)
            return
    clear_session()
    st.rerun()


def account_page():
    st.title(t("account.title"))
    profile = api().request("GET", f"/api/users/{resource(user()['user_id'])}")
    st.subheader(profile["username"])
    st.caption(t("account.joined", role=role_label(profile["role"]), date=profile["join_time"]))
    a, b = st.columns(2)
    a.metric(t("account.submissions"), profile["submit_count"])
    b.metric(t("account.solved"), profile["resolve_count"])
    st.caption(t("account.user_id", user_id=profile["user_id"]))
    st.divider()
    if st.button(t("action.logout"), key="account_logout"):
        logout()


def users_page():
    st.subheader(t("users.title"))
    page = st.number_input(t("users.page"), min_value=1, value=1, step=1)
    data = api().request("GET", "/api/users/", params={"page": page, "page_size": 20})
    st.caption(t("users.total", count=data["total"]))
    records = data["users"]
    if records:
        data_table(
            [
                {
                    t("users.column.id"): x["user_id"],
                    t("users.column.name"): x["username"],
                    t("users.column.role"): role_label(x["role"]),
                    t("users.column.joined"): x["join_time"],
                    t("users.column.submissions"): x["submit_count"],
                    t("users.column.solved"): x["resolve_count"],
                }
                for x in records
            ],
        )
        lookup = {x["user_id"]: x for x in records}
        with st.form("role_form", border=False):
            selected = st.selectbox(
                t("users.select"),
                list(lookup),
                format_func=lambda x: f"{lookup[x]['username']} · {x}",
            )
            role = st.selectbox(
                t("users.role"), ["admin", "user", "banned"], format_func=role_label
            )
            confirmed = st.checkbox(t("users.confirm"))
            submit = st.form_submit_button(t("users.update"), type="primary")
        if submit:
            if not confirmed:
                st.error(t("users.confirm_required"))
            else:
                ok, _ = mutation(
                    "PUT", f"/api/users/{resource(selected)}/role", json={"role": role}
                )
                if ok:
                    notice(t("users.updated"))
                    st.rerun()
    else:
        st.info(t("users.empty"))
    with st.expander(t("users.create_admin")):
        with st.form("new_admin_form", border=False):
            name = st.text_input(t("users.admin_name"))
            password = st.text_input(
                t("users.admin_password"), type="password", key="admin_password"
            )
            submit = st.form_submit_button(t("users.admin_submit"))
        if submit:
            ok, _ = mutation(
                "POST", "/api/users/admin", json={"username": name, "password": password}
            )
            if ok:
                st.session_state["_clear_secrets"] = True
                notice(t("users.admin_created"))
                st.rerun()
