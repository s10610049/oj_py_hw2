"""REST boundary and real Streamlit AppTest behavior; no paid model calls."""

from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
import toml
from streamlit.testing.v1 import AppTest

from frontend.client import APIClient, APIError
from frontend.forms import optional_number, parse_cases, problem_payload

ROOT = Path(__file__).resolve().parents[1]
USER = {
    "user_id": "u1",
    "username": "student",
    "role": "user",
    "join_time": "2026-09-09",
    "submit_count": 2,
    "resolve_count": 1,
}
PROBLEM = {
    "id": "sum",
    "title": "两数之和",
    "description": "计算两个整数的和。",
    "input_description": "两个整数",
    "output_description": "它们的和",
    "constraints": "绝对值不超过一千",
    "samples": [{"input": "1 2\n", "output": "3\n"}],
    "testcases": [{"input": "-1 1\n", "output": "0\n"}],
    "hint": "注意负数",
    "source": "自建",
    "author": "",
    "tags": ["基础"],
    "difficulty": "入门",
    "time_limit": None,
    "memory_limit": None,
    "public_cases": False,
}
CONFIG = {
    "provider_url": "https://api.example.com/v1",
    "model": "test-model",
    "api_key_configured": True,
    "input_price": None,
    "output_price": None,
    "price_unit": 1_000_000,
    "currency": "CNY",
}


class FakeAPI:
    def __init__(self, role="user"):
        self.calls = []
        self.profile = {**USER, "role": role}
        self.problems = [deepcopy(PROBLEM)]
        self.failure = None
        self.closed = False
        self.task = {
            "task_id": "t1",
            "status": "running",
            "progress": "正在生成题面",
            "result": None,
            "error": None,
            "usage": {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "cost": None,
                "source": "unavailable",
                "currency": "CNY",
            },
            "elapsed_seconds": 12,
        }
        self.submission = {
            "submission_id": "s1",
            "status": "success",
            "score": 0,
            "counts": 10,
            "compile_info": {"result": "error", "message": "compiler: expected semicolon"},
            "run_info": None,
            "error_info": None,
            "code": "bad code",
            "problem_id": "sum",
            "language": "cpp",
            "created_at": "2026-09-09",
        }
        self.log = {"score": 0, "counts": 10}

    def close(self):
        self.closed = True

    def request(self, method, path, *, json=None, params=None):
        self.calls.append((method, path, deepcopy(json), deepcopy(params)))
        if self.failure and (method, path) == self.failure[:2]:
            raise APIError(*self.failure[2:])
        if path == "/api/auth/login":
            return deepcopy(self.profile)
        if path == "/api/auth/logout":
            return None
        if path == "/api/users/" and method == "POST":
            return deepcopy(self.profile)
        if path.startswith("/api/users/") and path.endswith("/role"):
            return {"user_id": "u1", "role": json["role"]}
        if path == "/api/users/":
            return {"total": 1, "users": [deepcopy(self.profile)]}
        if path.startswith("/api/users/"):
            return deepcopy(self.profile)
        if path == "/api/problems/":
            if method == "POST":
                self.problems.append(deepcopy(json))
                return {"id": json["id"]}
            return deepcopy(self.problems)
        if path.startswith("/api/problems/"):
            if method == "PUT":
                return {"id": path.rsplit("/", 1)[-1]}
            if method == "DELETE":
                self.problems = []
                return {"id": "sum"}
            return deepcopy(next(p for p in self.problems if p["id"] == path.rsplit("/", 1)[-1]))
        if path == "/api/languages/":
            return {"name": ["python", "cpp"]}
        if path == "/api/submissions/":
            if method == "POST":
                return {"submission_id": "s1", "status": "pending"}
            return {"total": 1, "submissions": [deepcopy(self.submission)]}
        if path.endswith("/log"):
            return deepcopy(self.log)
        if path.endswith("/rejudge"):
            self.submission["status"] = "pending"
            return {"submission_id": "s1", "status": "pending"}
        if path.startswith("/api/submissions/"):
            return deepcopy(self.submission)
        if path == "/api/ai/model-config":
            return deepcopy(CONFIG)
        if path.endswith("/cancel"):
            self.task["status"] = "cancelled"
            return deepcopy(self.task)
        if path.startswith("/api/ai/problem-tasks"):
            return deepcopy(self.task)
        if path == "/api/logs/access/":
            return []
        raise AssertionError((method, path))


def app(fake, *, logged_in=True, page=None, **state):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=8)
    at.session_state["_api"] = fake
    if logged_in:
        at.session_state["_user"] = deepcopy(fake.profile)
    if page:
        at.session_state["navigation"] = page
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def button(at, label):
    return next(item for item in at.button if item.label == label)


def text_input(at, label):
    return next(item for item in at.text_input if item.label == label)


def block_paths(at, key):
    """Positional delta paths matter in addition to a container's stable ID."""
    found = []

    def walk(node, path):
        if getattr(getattr(node, "proto", None), "id", "").endswith("-" + key):
            found.append(path)
        for index, child in getattr(node, "children", {}).items():
            walk(child, path + (index,))

    walk(at.main, ())
    return found


def auth_password_step(at, *, register=False, name="student"):
    if register:
        at.button(key="auth_switch_mode").click().run()
    mode = "register" if register else "login"
    at.text_input(key=f"{mode}_username").set_value(name)
    button(at, "下一步").click().run()
    assert not at.exception
    return at


def test_http_cookie_isolation_and_envelope():
    cookies = []

    def handler(request):
        cookies.append(request.headers.get("cookie", ""))
        return httpx.Response(
            200,
            json={"code": 200, "msg": "ok", "data": {"user_id": "u1"}},
            headers={"set-cookie": "oj_session=session-one; Path=/"},
        )

    a = APIClient("http://test", transport=httpx.MockTransport(handler))
    b = APIClient("http://test", transport=httpx.MockTransport(handler))
    a.request("POST", "/api/auth/login", json={"username": "test", "password": "secret"})
    a.request("GET", "/api/users/u1")
    b.request("GET", "/api/users/u1")
    assert cookies == ["", "oj_session=session-one", ""]
    a.close()
    b.close()


@pytest.mark.parametrize(
    "status,body",
    [
        (200, {"code": 400, "msg": "bad", "data": None}),
        (200, []),
        (200, {"code": True, "msg": "bad", "data": None}),
    ],
)
def test_invalid_response_fails_closed(status, body):
    client = APIClient(
        "http://test", transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    )
    with pytest.raises(APIError, match="格式"):
        client.request("GET", "/api/problems/")
    client.close()


def test_http_error_masks_secret_and_401_clears_cookie():
    client = APIClient(
        "http://test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                401, json={"code": 401, "msg": "bad secret-value", "data": None}
            )
        ),
    )
    client.http.cookies.set("oj_session", "old")
    with pytest.raises(APIError) as exc:
        client.request("POST", "/api/auth/login", json={"password": "secret-value"})
    assert "secret-value" not in str(exc.value)
    assert not client.http.cookies
    client.close()


def test_problem_missing_limits_and_whitespace():
    values = {
        **PROBLEM,
        "tags_text": "图, 边界",
        "samples_json": '[{"input":" 1\\n","output":"\\n"}]',
        "testcases_json": '[{"input":"","output":""}]',
        "time_limit_text": "",
        "memory_limit_text": "256",
    }
    result = problem_payload(values)
    assert result["time_limit"] is None
    assert result["memory_limit"] == 256
    assert result["samples"][0]["input"] == " 1\n"
    assert result["tags"] == ["图", "边界"]


@pytest.mark.parametrize("text", ["[]", "{}", '[{"input":1,"output":"x"}]', "bad"])
def test_invalid_cases(text):
    with pytest.raises(ValueError):
        parse_cases(text, "测试点")


@pytest.mark.parametrize("text", ["nan", "inf", "-1", "0"])
def test_invalid_limits(text):
    with pytest.raises(ValueError):
        optional_number(text, "时间")


def test_login_failure_stays_visible_and_login_succeeds():
    fake = FakeAPI()
    fake.failure = ("POST", "/api/auth/login", 401, "Invalid username or password")
    at = auth_password_step(app(fake, logged_in=False))
    at.text_input(key="login_password").set_value("testpassword")
    button(at, "登录").click().run()
    assert not at.exception
    assert at.error
    assert at.session_state["_auth_name"] == "student"
    assert at.text_input(key="login_password").value == ""
    assert at.text_input(key="login_password").proto.set_value
    assert at.text_input(key="login_password").proto.value == ""
    fake.failure = None
    at.text_input(key="login_password").set_value("testpassword")
    button(at, "登录").click().run()
    assert not at.exception
    assert at.title[0].value == "题库"
    assert "_user" in at.session_state
    assert "login_password" not in at.session_state
    assert not any(key.startswith("_auth_") for key in at.session_state.filtered_state)


def test_registration_mismatch_does_not_call_api():
    fake = FakeAPI()
    at = auth_password_step(app(fake, logged_in=False), register=True, name="learner")
    at.text_input(key="register_password").set_value("abcdef")
    at.text_input(key="register_repeat").set_value("different")
    button(at, "创建账户").click().run()
    assert at.error and not at.exception
    assert not any(c[:2] == ("POST", "/api/users/") for c in fake.calls)
    assert at.text_input(key="register_password").value == ""
    assert at.text_input(key="register_repeat").value == ""
    assert at.text_input(key="register_password").proto.set_value
    assert at.text_input(key="register_repeat").proto.set_value


@pytest.mark.parametrize("name", ["", "ab", "   "])
def test_auth_identity_validation_never_probes_account(name):
    fake = FakeAPI()
    at = app(fake, logged_in=False)
    assert [item.label for item in at.text_input] == ["用户名"]
    at.text_input(key="login_username").set_value(name)
    button(at, "下一步").click().run()
    assert not at.exception and at.error
    assert at.text_input(key="login_username").value == name
    assert fake.calls == []


def test_auth_back_preserves_name_and_discards_password():
    fake = FakeAPI()
    at = auth_password_step(app(fake, logged_in=False), name="learner")
    at.text_input(key="login_password").set_value("temporary-secret")
    at.button(key="auth_back").click().run()
    assert not at.exception
    assert at.text_input(key="login_username").value == "learner"
    assert "login_password" not in at.session_state
    button(at, "下一步").click().run()
    assert at.text_input(key="login_password").value == ""
    assert fake.calls == []


def test_auth_switch_clears_passwords_errors_and_uses_single_form():
    fake = FakeAPI()
    at = auth_password_step(app(fake, logged_in=False))
    at.text_input(key="login_password").set_value("temporary-secret")
    at.session_state["_auth_error"] = "Old failure"
    at.button(key="auth_switch_mode").click().run()
    assert not at.exception and not at.error
    assert [item.label for item in at.text_input] == ["新用户名"]
    assert "login_password" not in at.session_state
    assert len(at.get("form")) == 1
    at.button(key="auth_switch_mode").click().run()
    assert [item.label for item in at.text_input] == ["用户名"]
    assert fake.calls == []


def test_registration_success_returns_to_password_login_without_auto_login():
    fake = FakeAPI()
    at = auth_password_step(app(fake, logged_in=False), register=True, name="new_learner")
    at.text_input(key="register_password").set_value("new-secret")
    at.text_input(key="register_repeat").set_value("new-secret")
    button(at, "创建账户").click().run()
    assert not at.exception and at.success
    assert "_user" not in at.session_state
    assert at.session_state["_auth_mode"] == "login"
    assert at.session_state["_auth_name"] == "new_learner"
    assert at.text_input(key="login_password").value == ""
    assert "register_password" not in at.session_state
    assert "register_repeat" not in at.session_state
    assert fake.calls == [
        ("POST", "/api/users/", {"username": "new_learner", "password": "new-secret"}, None)
    ]


@pytest.mark.parametrize("password", ["", "abc"])
def test_registration_short_password_clears_secret_without_api(password):
    fake = FakeAPI()
    at = auth_password_step(app(fake, logged_in=False), register=True)
    at.text_input(key="register_password").set_value(password)
    at.text_input(key="register_repeat").set_value(password)
    button(at, "创建账户").click().run()
    assert not at.exception and at.error
    assert fake.calls == []
    assert at.text_input(key="register_password").value == ""
    assert at.text_input(key="register_repeat").value == ""


@pytest.mark.parametrize("register", [False, True])
def test_auth_network_error_redacts_and_clears_secret_without_losing_step(register):
    fake = FakeAPI()
    mode = "register" if register else "login"
    path = "/api/users/" if register else "/api/auth/login"
    fake.failure = ("POST", path, 0, "offline: temporary-secret")
    at = auth_password_step(app(fake, logged_in=False), register=register)
    at.text_input(key=f"{mode}_password").set_value("temporary-secret")
    if register:
        at.text_input(key="register_repeat").set_value("temporary-secret")
    at.button(key="auth_continue").click().run()
    assert not at.exception and at.error
    assert "temporary-secret" not in at.error[0].value
    assert "temporary-secret" not in at.session_state["_auth_error"]
    assert at.session_state["_auth_name"] == "student"
    assert at.session_state["_auth_step"] == "password"
    assert at.text_input(key=f"{mode}_password").value == ""
    assert at.text_input(key=f"{mode}_password").proto.set_value
    assert at.text_input(key=f"{mode}_password").proto.value == ""
    assert "_user" not in at.session_state


@pytest.mark.parametrize(
    "api_message,expected",
    [
        ("Account is banned", "账户已被禁用，请联系管理员。"),
        ("Another permission failure", "Another permission failure"),
    ],
)
def test_login_ban_translation_preserves_other_permission_errors(api_message, expected):
    fake = FakeAPI()
    fake.failure = ("POST", "/api/auth/login", 403, api_message)
    at = auth_password_step(app(fake, logged_in=False))
    at.text_input(key="login_password").set_value("temporary-secret")
    at.button(key="auth_continue").click().run()
    assert not at.exception and at.error[0].value == expected
    assert at.text_input(key="login_password").value == ""
    assert "_user" not in at.session_state


def test_auth_styles_are_scoped_reduced_motion_and_keyboard_safe():
    from frontend.styles import CSS

    assert ".st-key-auth_shell {max-width:100%" in CSS
    assert "@media (max-width:480px)" in CSS
    assert "min-height:44px" in CSS
    assert "button:focus-visible" in CSS
    assert "220ms" in CSS and "translateY(6px)" in CSS
    reduced = CSS.split("@media (prefers-reduced-motion:reduce)")[1]
    assert "st-key-auth_stage_" in reduced and "animation:none;opacity:1;transform:none" in reduced
    assert "st-key-workspace_nav button" in reduced and "transition:none;" in reduced
    assert "pointer-events:none" not in CSS and "visibility:hidden" not in CSS


def test_auth_native_form_enter_labels_and_password_autocomplete():
    at = app(FakeAPI(), logged_in=False)
    assert at.get("form")[0].proto.form.enter_to_submit
    name = at.text_input(key="login_username").proto
    assert name.autocomplete == "username"
    assert name.label_visibility.value == 0  # Streamlit VISIBLE; never placeholder-only.
    auth_password_step(at)
    password = at.text_input(key="login_password").proto
    assert password.type == password.PASSWORD
    assert password.autocomplete == "current-password"
    assert password.label_visibility.value == 0
    assert password.form_id == "auth_form"
    at.button(key="auth_switch_mode").click().run()
    at.text_input(key="register_username").set_value("learner")
    button(at, "下一步").click().run()
    assert not at.exception
    # Already in register mode after the switch; its fields use new-password.
    for key in ("register_password", "register_repeat"):
        field = at.text_input(key=key).proto
        assert field.type == field.PASSWORD
        assert field.autocomplete == "new-password"
        assert field.form_id == "auth_form"


def test_sidebar_native_icon_navigation_reaches_all_user_pages_without_mutation():
    fake = FakeAPI()
    at = app(fake)
    assert not at.sidebar.radio
    assert [item.key for item in at.sidebar.button] == [
        "nav_problems",
        "nav_submissions",
        "nav_authoring",
        "nav_account",
        "sidebar_logout",
    ]
    assert at.button(key="nav_problems").proto.help == "当前页面"
    for key, page in (
        ("nav_submissions", "提交记录"),
        ("nav_account", "账户"),
        ("nav_authoring", "智能命题"),
        ("nav_problems", "题库"),
    ):
        assert at.button(key=key).proto.icon.startswith(":material/")
        at.button(key=key).click().run()
        assert not at.exception
        assert at.session_state["navigation"] == page
        assert at.button(key=key).proto.help == "当前页面"
    assert all(call[0] == "GET" for call in fake.calls)
    assert any(call[1] == "/api/ai/model-config" for call in fake.calls)
    assert any(call[1] == "/api/submissions/" for call in fake.calls)


def test_sidebar_admin_entry_and_role_downgrade_fall_back_safely():
    fake = FakeAPI("admin")
    at = app(fake)
    at.button(key="nav_admin").click().run()
    assert not at.exception
    assert at.session_state["navigation"] == "管理工作区"
    fake.profile["role"] = "user"
    at.run()
    assert not at.exception
    assert "nav_admin" not in [item.key for item in at.sidebar.button]
    assert at.session_state["navigation"] == "题库"


def test_workspace_outer_and_current_route_slots_stay_stable_on_rerun():
    at = app(FakeAPI())

    def block_id(suffix):
        return next(
            block.proto.id
            for block in at.get("flex_container")
            if block.proto.id.endswith("-" + suffix)
        )

    outer = block_id("workspace_shell")
    route = block_id("route_content_problems")
    nav = block_id("workspace_nav")
    nav_item = block_id("nav_item_submissions")
    nav_button = at.button(key="nav_submissions").proto.id
    at.run()
    assert block_id("workspace_shell") == outer
    assert block_id("route_content_problems") == route
    assert block_id("workspace_nav") == nav
    at.button(key="nav_submissions").click().run()
    assert block_id("workspace_shell") == outer
    assert block_id("workspace_nav") == nav
    assert block_id("nav_item_submissions") == nav_item
    assert at.button(key="nav_submissions").proto.id == nav_button
    assert block_id("route_content_submissions") != route


@pytest.mark.parametrize(
    "logged_in,key", [(True, "workspace_shell"), (False, "auth_stage_login_identity")]
)
def test_notice_does_not_shift_main_or_auth_delta_paths(logged_in, key):
    at = app(FakeAPI(), logged_in=logged_in, _notice="已保存测试记录。")
    before = block_paths(at, key)
    assert len(before) == 1 and not at.exception
    assert [item.proto.body for item in at.get("toast")] == ["已保存测试记录。"]
    assert at.get("toast")[0].proto.duration == 10
    at.run()
    assert not at.exception
    assert not at.get("toast")
    assert block_paths(at, key) == before


def test_ai_save_submit_completion_return_keeps_single_fixed_route():
    fake = FakeAPI("admin")
    fake.task.update(status="completed", result=deepcopy(PROBLEM))
    at = app(fake, page="智能命题", _ai_task=deepcopy(fake.task))
    outer_path = block_paths(at, "workspace_shell")
    at.text_input(key="ai_draft_t1_new_id").set_value("ai_saved")
    button(at, "保存到题库").click().run()
    assert not at.exception
    assert block_paths(at, "workspace_shell") == outer_path
    assert len(block_paths(at, "route_content_problems")) == 1
    fake.submission.update(status="pending", problem_id="ai_saved")
    at.text_area(key="code_ai_saved").set_value("print(3)")
    button(at, "提交代码").click().run()
    assert not at.exception
    assert block_paths(at, "workspace_shell") == outer_path
    fake.submission.update(status="success", score=10)
    at.run()  # The pending fragment requests an app rerun on terminal status.
    assert not at.exception
    at.button(key="nav_problems").click().run()
    assert not at.exception
    assert block_paths(at, "workspace_shell") == outer_path
    assert len(block_paths(at, "route_content_problems")) == 1
    assert [item.label for item in at.tabs].count("编程") == 1


def test_sidebar_content_alignment_rule_does_not_target_main_buttons():
    from frontend.styles import CSS

    assert ".st-key-workspace_nav button > div {justify-content:flex-start;" in CSS
    assert ".st-key-workspace_shell button > div" not in CSS
    assert ".st-key-auth_shell button > div" not in CSS


def test_sidebar_identity_html_escapes_server_supplied_name():
    fake = FakeAPI()
    fake.profile["username"] = '<img src=x onerror="bad()">'
    at = app(fake)
    rendered = next(
        item.proto.body
        for item in at.get("html")
        if 'class="oj-sidebar-profile"' in item.proto.body
    )
    assert "&lt;img" in rendered and "<img" not in rendered


def test_ai_polling_keeps_static_mark_separate_from_elapsed_status_and_phrase():
    fake = FakeAPI()
    at = app(fake, page="智能命题", _ai_task=deepcopy(fake.task))
    assert not at.exception

    def markup(marker):
        return next(item.proto.body for item in at.get("html") if marker in item.proto.body)

    mark = markup('class="oj-mark"')
    title = markup('class="oj-loading-title"')
    phrase = markup('class="oj-loading-note oj-phrase"')
    assert "已耗时" not in mark and "aria-hidden" in mark
    assert "正在生成题面" in title and "已耗时" not in title
    fake.task["elapsed_seconds"] = 13
    at.run()
    assert not at.exception
    assert markup('class="oj-mark"') == mark
    assert markup('class="oj-loading-title"') == title
    assert markup('class="oj-loading-note oj-phrase"') == phrase
    assert "13 秒" in markup('class="oj-loading-note">已耗时')


def test_pathhub_theme_preserves_every_local_font_face():
    theme = toml.loads((ROOT / ".streamlit/config.toml").read_text(encoding="utf-8"))["theme"]
    assert theme["primaryColor"] == "#1A6B4A"
    assert theme["backgroundColor"] == "#F5F5F7"
    assert theme["sidebar"]["backgroundColor"] == "#FBFBFD"
    assert "http" not in theme["font"]
    assert len(theme["fontFaces"]) == 103
    noto = [face for face in theme["fontFaces"] if face["family"] == "Noto Sans SC"]
    manifest = json.loads(
        (ROOT / "static/fonts/NotoSansSC-manifest.json").read_text(encoding="utf-8")
    )
    assert len(noto) == len(manifest["faces"]) == 101
    for face, source in zip(noto, manifest["faces"]):
        assert face["url"] == "app/static/fonts/" + source["file"]
        assert face["unicodeRange"] == source["range"]
        assert face["weight"] == "400 600"


def test_pathhub_motion_and_layout_contract_is_bounded_and_reducible():
    from frontend.styles import CSS

    assert "--oj-primary:#1A6B4A" in CSS and "--oj-primary-soft:#EBF5F0" in CSS
    assert "#1765D1" not in CSS
    assert "min-height:640px" in CSS and "min-height:460px" in CSS
    assert "@media (max-width:1100px)" in CSS
    assert ":has(> .st-key-auth_story)" in CSS
    assert ".st-key-sidebar_account {margin-top:auto" in CSS
    assert "180ms" in CSS and "220ms" in CSS and "translateY(1px)" in CSS
    reduced = CSS.split("@media (prefers-reduced-motion:reduce)")[1]
    assert "st-key-route_content_" in reduced and "st-key-auth_stage_" in reduced
    assert "st-key-workspace_nav button" in reduced and "transform:none;" in reduced
    assert "transition:none;" in reduced


def test_narrow_auth_hides_story_layout_wrapper_and_expands_only_form_wrapper():
    from frontend.styles import CSS

    # A0's 390px DOM evidence: the two direct stLayoutWrapper siblings own the
    # flex widths; hiding only their inner story leaves an empty first column.
    narrow = CSS.split("@media (max-width:1100px) {", 1)[1].split("@media", 1)[0]
    wrapper = '.st-key-auth_composition > [data-testid="stLayoutWrapper"]'
    assert wrapper + ":has(> .st-key-auth_story) {" in narrow
    story_rule = narrow.split(wrapper + ":has(> .st-key-auth_story) {", 1)[1].split("}", 1)[0]
    assert story_rule.strip() == "display:none;"
    assert wrapper + ":has(> .st-key-auth_shell) {" in narrow
    form_rule = narrow.split(wrapper + ":has(> .st-key-auth_shell) {", 1)[1].split("}", 1)[0]
    for declaration in ("flex:1 1 100%;", "width:100%;", "min-width:0;", "max-width:100%;"):
        assert declaration in form_rule
    assert "display:none" not in form_rule
    assert narrow.count("display:none") == 1
    assert ".st-key-workspace_shell" not in narrow


def test_catalog_open_button_keeps_readable_action_column_and_native_label():
    at = app(FakeAPI())
    assert not at.exception
    action = next(
        column
        for column in at.get("column")
        if any(item.key == "open_sum" for item in column.button)
    )
    # 1024px with sidebar leaves too little room at the former 1/9 share.
    # Reserve 1/6 of the row; native Streamlit columns still stack on mobile.
    assert action.weight == pytest.approx(1 / 6)
    assert action.button(key="open_sum").label == "打开"
    action.button(key="open_sum").click().run()
    assert not at.exception and at.title[0].value == PROBLEM["title"]


@pytest.mark.parametrize("mode", ["detail", "edit"])
def test_deleted_selected_problem_can_return_to_catalog_and_clear_stale_selection(mode):
    fake = FakeAPI()
    at = app(fake, _problem_mode=mode, _problem_id="sum")
    assert not at.exception
    fake.failure = ("GET", "/api/problems/sum", 404, "Problem not found")
    fake.problems = [{**deepcopy(PROBLEM), "id": "remaining", "title": "另一道题"}]
    at.run()
    assert not at.exception and at.error
    assert button(at, "← 返回题库")
    # Switching away must not remove the recovery path when the stale request
    # fails again; this reproduces the independent review's sidebar sequence.
    at.button(key="nav_account").click().run()
    at.button(key="nav_problems").click().run()
    assert not at.exception and at.error
    button(at, "← 返回题库").click().run()
    assert not at.exception and not at.error
    assert at.session_state["_problem_mode"] == "list"
    assert at.session_state["_problem_id"] is None
    assert any(call[:2] == ("GET", "/api/problems/") for call in fake.calls)
    at.button(key="open_remaining").click().run()
    assert not at.exception and at.title[0].value == "另一道题"


@pytest.mark.parametrize("status", [0, 403, 500])
def test_problem_load_errors_remain_visible_and_recoverable_without_fake_success(status):
    fake = FakeAPI()
    fake.failure = ("GET", "/api/problems/sum", status, "Synthetic load failure")
    at = app(fake, _problem_mode="detail", _problem_id="sum")
    assert not at.exception and at.error
    assert not at.success and not at.tabs
    assert at.session_state["_problem_mode"] == "detail"
    assert at.session_state["_problem_id"] == "sum"
    assert button(at, "重新加载")
    button(at, "← 返回题库").click().run()
    assert not at.exception and not at.error
    assert at.session_state["_problem_mode"] == "list"
    assert at.session_state["_problem_id"] is None


def test_user_can_edit_but_cannot_delete():
    at = app(FakeAPI(), _problem_mode="detail", _problem_id="sum")
    assert not at.exception
    assert button(at, "编辑题目")
    assert not any(item.label == "删除题目" for item in at.button)
    assert not at.sidebar.radio
    assert "管理工作区" not in [item.label for item in at.sidebar.button]


def test_problem_create_sends_all_fields():
    fake = FakeAPI()
    at = app(fake, _problem_mode="new")
    assert not at.exception
    at.text_input(key="new_problem_id").set_value("new_sum")
    at.text_input(key="new_problem_title").set_value("新的两数之和")
    for field in ("description", "input_description", "output_description", "constraints"):
        at.text_area(key=f"new_problem_{field}").set_value(PROBLEM[field])
    button(at, "保存题目").click().run()
    assert not at.exception
    created = next(c[2] for c in fake.calls if c[:2] == ("POST", "/api/problems/"))
    assert set(created) == {
        "id",
        "title",
        "description",
        "input_description",
        "output_description",
        "constraints",
        "hint",
        "source",
        "author",
        "difficulty",
        "tags",
        "samples",
        "testcases",
        "time_limit",
        "memory_limit",
    }
    assert created["time_limit"] is None and created["memory_limit"] is None
    assert at.title[0].value == "新的两数之和"


def test_code_submission_preserves_code_and_displays_compile_error():
    fake = FakeAPI()
    at = app(fake, _problem_mode="detail", _problem_id="sum")
    code = "  print(1)\n\n"
    at.text_area(key="code_sum").set_value(code)
    button(at, "提交代码").click().run()
    assert not at.exception
    sent = next(c[2] for c in fake.calls if c[:2] == ("POST", "/api/submissions/"))
    assert sent["code"] == code
    assert any("expected semicolon" in item.value for item in at.code)
    button(at, "查询评测日志").click().run()
    assert not at.exception
    assert any("未公开" in item.value for item in at.info)


def test_admin_role_management_and_delete_require_confirmation():
    fake = FakeAPI("admin")
    at = app(fake, page="管理工作区")
    assert not at.exception
    button(at, "更新角色").click().run()
    assert at.error
    assert not any(c[1].endswith("/role") for c in fake.calls)
    at.checkbox[0].check()
    button(at, "更新角色").click().run()
    assert any(c[:2] == ("PUT", "/api/users/u1/role") for c in fake.calls)
    at = app(fake, _problem_mode="detail", _problem_id="sum")
    assert button(at, "删除题目").disabled


def test_ai_start_reference_and_real_cancel():
    fake = FakeAPI()
    at = app(fake, page="智能命题")
    assert not at.exception
    at.text_area(key="ai_requirement").set_value("有向图判环，检查自环和不连通图")
    text_input(at, "知识点").set_value("拓扑排序")
    text_input(at, "参考题号（可选）").set_value("sum")
    button(at, "生成题目").click().run()
    assert not at.exception
    sent = next(c[2] for c in fake.calls if c[:2] == ("POST", "/api/ai/problem-tasks/"))
    assert sent["problem_id"] == "sum" and "拓扑排序" in sent["requirement"]
    assert button(at, "生成题目").disabled
    button(at, "停止生成").click().run()
    assert not at.exception
    assert any(c[:2] == ("PUT", "/api/ai/problem-tasks/t1/cancel") for c in fake.calls)
    assert any("已取消" in item.value for item in at.info)
    assert not any(c[:2] == ("POST", "/api/problems/") for c in fake.calls)


def test_ai_completed_draft_is_editable_before_save():
    fake = FakeAPI()
    fake.task.update(status="completed", result=deepcopy(PROBLEM))
    at = app(fake, page="智能命题", _ai_task=deepcopy(fake.task))
    assert not at.exception
    assert not any(c[:2] == ("POST", "/api/problems/") for c in fake.calls)
    at.text_input(key="ai_draft_t1_new_id").set_value("ai_new")
    at.text_input(key="ai_draft_t1_new_title").set_value("人工校订的题目")
    button(at, "保存到题库").click().run()
    assert not at.exception
    sent = next(c[2] for c in fake.calls if c[:2] == ("POST", "/api/problems/"))
    assert sent["title"] == "人工校订的题目"


def test_429_preserves_code_and_no_success_navigation():
    fake = FakeAPI()
    fake.failure = ("POST", "/api/submissions/", 429, "At most 3 submissions per minute")
    at = app(fake, _problem_mode="detail", _problem_id="sum")
    at.text_area(key="code_sum").set_value("print(3)")
    button(at, "提交代码").click().run()
    assert not at.exception and at.error
    assert at.text_area(key="code_sum").value == "print(3)"
    assert at.title[0].value == "两数之和"


def test_logout_discards_private_session_data():
    fake = FakeAPI()
    at = app(fake, _ai_task=deepcopy(fake.task), _log_s1={"details": [{"id": 1}]})
    button(at, "退出登录").click().run()
    assert not at.exception
    assert fake.closed
    assert "_user" not in at.session_state
    assert "_ai_task" not in at.session_state
    assert "_log_s1" not in at.session_state


def test_fonts_are_small_woff2_with_licenses():
    for font, license_file in (
        ("Manrope-latin.woff2", "OFL-manrope.txt"),
        ("JetBrainsMono-latin.woff2", "OFL-jetbrainsmono.txt"),
    ):
        path = ROOT / "static" / "fonts" / font
        assert path.read_bytes()[:4] == b"wOF2"
        assert path.stat().st_size < 100_000
        assert "SIL OPEN FONT LICENSE" in (path.parent / license_file).read_text(encoding="utf-8")


def test_model_configuration_sends_prices_without_reading_key():
    fake = FakeAPI()
    at = app(fake, page="智能命题")
    assert at.text_input(key="ai_api_key").value == ""
    text_input(at, "模型名称").set_value("another-model")
    text_input(at, "输入单价（未知留空）").set_value("2.5")
    text_input(at, "输出单价（未知留空）").set_value("5")
    button(at, "保存模型配置").click().run()
    assert not at.exception
    payload = next(c[2] for c in fake.calls if c[:2] == ("PUT", "/api/ai/model-config"))
    assert payload["model"] == "another-model"
    assert payload["input_price"] == 2.5 and payload["output_price"] == 5
    assert payload["api_key"] == ""  # Backend retains it only for the same provider.
    assert at.text_input(key="ai_api_key").value == ""


def test_live_task_completion_stops_gets_and_preserves_editable_draft():
    fake = FakeAPI()
    at = app(fake, page="智能命题", _ai_task=deepcopy(fake.task))
    assert not at.exception
    fake.task.update(status="completed", result=deepcopy(PROBLEM))
    at.run()
    assert not at.exception
    assert any("生成完成" in item.value for item in at.success)
    previous_gets = sum(c[:2] == ("GET", "/api/ai/problem-tasks/t1") for c in fake.calls)
    at.run()
    assert sum(c[:2] == ("GET", "/api/ai/problem-tasks/t1") for c in fake.calls) == previous_gets
    assert at.text_input(key="ai_draft_t1_new_title")


def test_ai_update_locks_target_id_and_calls_put():
    fake = FakeAPI()
    fake.task.update(status="completed", result={**deepcopy(PROBLEM), "id": "different"})
    at = app(fake, page="智能命题", _ai_task=deepcopy(fake.task))
    at.radio(key="ai_save_mode_t1").set_value("更新已有题目").run()
    assert not at.exception
    assert at.text_input(key="ai_draft_t1_sum_id").disabled
    assert at.text_input(key="ai_draft_t1_sum_id").value == "sum"
    at.checkbox[0].check()
    button(at, "保存到题库").click().run()
    assert not at.exception
    payload = next(c[2] for c in fake.calls if c[:2] == ("PUT", "/api/problems/sum"))
    assert payload["id"] == "sum"


def test_cancel_conflict_does_not_fabricate_cancelled_state():
    fake = FakeAPI()
    fake.failure = ("PUT", "/api/ai/problem-tasks/t1/cancel", 409, "Task has ended")
    at = app(fake, page="智能命题", _ai_task=deepcopy(fake.task))
    button(at, "停止生成").click().run()
    assert not at.exception and at.error
    assert at.session_state["_ai_task"]["status"] == "running"
    assert not any("已取消" in item.value for item in at.info)


def test_network_failure_keeps_real_last_task_state():
    fake = FakeAPI()
    fake.failure = ("GET", "/api/ai/problem-tasks/t1", 0, "连接不可用")
    at = app(fake, page="智能命题", _ai_task=deepcopy(fake.task))
    assert not at.exception and at.error
    assert at.session_state["_ai_task"]["status"] == "running"
    assert not at.success


def test_estimated_usage_explains_method_and_small_cost_is_not_rounded_to_zero():
    fake = FakeAPI()
    fake.task.update(status="cancelled")
    fake.task["usage"] = {
        "input_tokens": 1,
        "output_tokens": 1,
        "total_tokens": 2,
        "cost": 0.00000001,
        "currency": "CNY",
        "source": "estimated",
        "incomplete": True,
        "note": "按 UTF-8 字节数 / 3 粗估",
    }
    at = app(fake, page="智能命题", _ai_task=deepcopy(fake.task))
    assert not at.exception
    assert any("UTF-8" in item.value for item in at.caption)
    cost = next(item for item in at.metric if item.label == "估算费用")
    assert cost.value.startswith("1e-08")


def test_submission_list_and_account_use_backend_data():
    fake = FakeAPI()
    at = app(fake, page="提交记录")
    assert not at.exception
    assert any(
        c[:2] == ("GET", "/api/submissions/") and c[3]["user_id"] == "u1" for c in fake.calls
    )
    button(at, "打开提交").click().run()
    assert not at.exception and at.title[0].value == "提交详情"
    at = app(fake, page="账户")
    assert not at.exception
    assert next(item for item in at.metric if item.label == "代码提交").value == "2"


def test_data_table_escapes_every_cell(monkeypatch):
    from frontend.common import data_table

    rendered = []
    monkeypatch.setattr("frontend.common.st.html", rendered.append)
    data_table([{"<script>": "<img src=x onerror=alert(1)>"}])
    assert "<script>" not in rendered[0]
    assert "<img" not in rendered[0]
    assert "&lt;script&gt;" in rendered[0]


def test_permission_failure_does_not_render_private_log():
    fake = FakeAPI()
    fake.failure = ("GET", "/api/submissions/s1/log", 403, "Log is private")
    at = app(fake, page="提交记录", _submission_id="s1")
    button(at, "查询评测日志").click().run()
    assert not at.exception and at.error
    assert "_log_s1" not in at.session_state
