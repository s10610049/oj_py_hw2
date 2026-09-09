"""Registration, sign-in, profile and role management."""

import streamlit as st

from frontend.client import APIError, resource
from frontend.common import (
    ROLE_LABELS,
    api,
    clear_session,
    data_table,
    mutation,
    notice,
    show_error,
    user,
)
from frontend.styles import auth_identity


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
        st.session_state["_auth_error"] = "用户名需 3—40 个字符，且不能全部为空白。"
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
            st.session_state["_auth_error"] = "请先输入有效的用户名。"
        elif not password:
            st.session_state["_auth_error"] = "请输入密码。"
        elif mode == "register" and len(password) < 6:
            st.session_state["_auth_error"] = "密码至少需要 6 个字符。"
        elif mode == "register" and password != repeated:
            st.session_state["_auth_error"] = "两次密码不一致，请重新输入。"
        else:
            path = "/api/auth/login" if mode == "login" else "/api/users/"
            with st.spinner("正在登录…" if mode == "login" else "正在创建账户…"):
                result = api().request("POST", path, json={"username": name, "password": password})
            if mode == "login":
                st.session_state["_user"] = result
                for key in list(st.session_state):
                    if key.startswith("_auth_"):
                        st.session_state.pop(key, None)
                notice("欢迎回来。")
            else:
                st.session_state["_auth_mode"] = "login"
                st.session_state["_auth_step"] = "password"
                st.session_state["login_username"] = name
                st.session_state["_auth_notice"] = "账户已创建。输入密码，开始练习。"
    except APIError as exc:
        # The client also redacts secrets; keep even a misbehaving provider's
        # message out of persisted UI state before displaying an auth error.
        message = exc.message
        for secret in (password, repeated):
            if secret:
                message = message.replace(secret, "[已隐藏]")
        if mode == "login" and exc.status == 401:
            message = "用户名或密码不正确，请重试。"
        elif exc.status == 0:
            message = f"连接暂不可用，请稍后重试。{message}"
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
    st.html(
        '<div class="oj-auth-brand"><span class="oj-auth-symbol" aria-hidden="true">'
        "{ }</span><span>编程练习室</span></div>"
    )
    with st.container(key=f"auth_stage_{mode}_{step}"):
        titles = {
            ("login", "identity"): "登录",
            ("login", "password"): "欢迎回来",
            ("register", "identity"): "创建账户",
            ("register", "password"): "设置密码",
        }
        st.title(titles[(mode, step)])
        st.caption("继续你的编程练习。" if mode == "login" else "从一次清晰的思考开始。")
        step_number = 1 if step == "identity" else 2
        step_label = "用户名" if step == "identity" else "密码"
        st.html(
            '<p class="oj-auth-step" role="status" aria-live="polite">'
            f"第 {step_number} 步，共 2 步 · {step_label}</p>"
        )
        if step == "password":
            with st.container(
                key="auth_identity_row", horizontal=True, vertical_alignment="center"
            ):
                auth_identity(st.session_state.get("_auth_name", ""))
                st.button(
                    "更换用户名",
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
                    "用户名" if mode == "login" else "新用户名",
                    help="3—40 个字符，使用你的编程练习室用户名。",
                    key=f"{mode}_username",
                    autocomplete="username",
                    max_chars=40,
                )
            else:
                st.text_input(
                    "密码" if mode == "login" else "设置密码",
                    type="password",
                    help="至少 6 个字符" if mode == "register" else None,
                    key=f"{mode}_password",
                    autocomplete="current-password" if mode == "login" else "new-password",
                )
                if mode == "register":
                    st.text_input(
                        "再次输入密码",
                        type="password",
                        key="register_repeat",
                        autocomplete="new-password",
                    )
            if st.session_state.get("_auth_error"):
                st.error(st.session_state["_auth_error"])
            label = "下一步" if step == "identity" else ("登录" if mode == "login" else "创建账户")
            st.form_submit_button(
                label,
                key="auth_continue",
                type="primary",
                width="stretch",
                on_click=_auth_continue if step == "identity" else _auth_submit,
            )
        st.button(
            "创建账户" if mode == "login" else "返回登录",
            key="auth_switch_mode",
            type="tertiary",
            on_click=_auth_move,
            args=("register" if mode == "login" else "login",),
        )
    st.html('<p class="oj-auth-footer">阅读 · 编写 · 验证，每一步都算数。</p>')


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
    st.title("账户")
    profile = api().request("GET", f"/api/users/{resource(user()['user_id'])}")
    st.subheader(profile["username"])
    st.caption(
        f"{ROLE_LABELS.get(profile['role'], profile['role'])} · 加入于 {profile['join_time']}"
    )
    a, b = st.columns(2)
    a.metric("代码提交", profile["submit_count"])
    b.metric("已通过题目", profile["resolve_count"])
    st.caption(f"用户编号：{profile['user_id']}")
    st.divider()
    if st.button("退出登录", key="account_logout"):
        logout()
    with st.expander("阅读与字体"):
        st.write(
            "英文、中文与代码分别使用本地 Manrope、Noto Sans SC 与 JetBrains Mono。"
            "中文覆盖官方本次字体分片字集，缺字自动使用系统字体，不依赖 Google 外网。"
            "可使用浏览器缩放调整阅读大小。"
        )


def users_page():
    st.subheader("用户与权限")
    page = st.number_input("用户列表页码", min_value=1, value=1, step=1)
    data = api().request("GET", "/api/users/", params={"page": page, "page_size": 20})
    st.caption(f"共 {data['total']} 位用户")
    records = data["users"]
    if records:
        data_table(
            [
                {
                    "用户编号": x["user_id"],
                    "用户名": x["username"],
                    "角色": ROLE_LABELS.get(x["role"], x["role"]),
                    "加入日期": x["join_time"],
                    "提交": x["submit_count"],
                    "通过题目": x["resolve_count"],
                }
                for x in records
            ],
        )
        lookup = {x["user_id"]: x for x in records}
        with st.form("role_form", border=False):
            selected = st.selectbox(
                "选择用户", list(lookup), format_func=lambda x: f"{lookup[x]['username']} · {x}"
            )
            role = st.selectbox("调整为", list(ROLE_LABELS), format_func=ROLE_LABELS.get)
            confirmed = st.checkbox("我已确认所选用户及新的权限")
            submit = st.form_submit_button("更新角色", type="primary")
        if submit:
            if not confirmed:
                st.error("请先确认用户及权限。")
            else:
                ok, _ = mutation(
                    "PUT", f"/api/users/{resource(selected)}/role", json={"role": role}
                )
                if ok:
                    notice("用户角色已更新。")
                    st.rerun()
    else:
        st.info("本页暂无用户。")
    with st.expander("创建管理员账户"):
        with st.form("new_admin_form", border=False):
            name = st.text_input("管理员用户名")
            password = st.text_input("管理员密码", type="password", key="admin_password")
            submit = st.form_submit_button("创建管理员")
        if submit:
            ok, _ = mutation(
                "POST", "/api/users/admin", json={"username": name, "password": password}
            )
            if ok:
                st.session_state["_clear_secrets"] = True
                notice("管理员账户已创建。")
                st.rerun()
