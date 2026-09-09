"""REST boundary and real Streamlit AppTest behavior; no paid model calls."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import httpx
import pytest
import toml
from streamlit.testing.v1 import AppTest

from frontend.admin import audit_table_rows
from frontend.client import APIClient, APIError
from frontend.forms import (
    difficulty_option_label,
    difficulty_options,
    manual_authoring_request,
    optional_number,
    parse_cases,
    problem_payload,
)
from frontend.problems import (
    _import_binding,
    _safe_import_preview,
    _validate_luogu_metadata,
    difficulty_projection,
    localized_problem,
    problem_badges_html,
    problem_status_index,
)

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
ENGLISH_PROBLEM = {
    **deepcopy(PROBLEM),
    "translations": {
        "en": {
            "title": "A + B",
            "description": "Add two integers.",
            "input_description": "Read two integers.",
            "output_description": "Print their sum.",
            "constraints": "Absolute values are at most one thousand.",
            "hint": "Mind negative values.",
        }
    },
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
PROBLEM_STATUSES = {
    "schema_version": "oj.problem-status.v1",
    "context_epoch": "test-epoch",
    "generated_at": "2026-09-09T12:00:00+00:00",
    "items": [
        {
            "problem_id": "sum",
            "title": "两数之和",
            "current_problem_version": "version-1",
            "state": "passed",
            "latest_outcome": "accepted",
            "latest_pending": None,
            "best": None,
            "latest_terminal": {"status": "success"},
            "historical_best": None,
            "version_unknown": False,
            "code": "SECRET_STATUS_CODE",
            "details": [{"input": "SECRET_STATUS_CASE"}],
        }
    ],
}
LEARNING_STATS = {
    "schema_version": "oj.learning-stats.v1",
    "context_epoch": "test-epoch",
    "generated_at": "2026-09-09T12:00:00+00:00",
    "scope": {
        "user_id": "u1",
        "catalog_problem_count": 1,
        "submission_count": 2,
        "orphan_submission_count": 0,
        "version_unknown_count": 0,
        "timezone": "UTC",
    },
    "kpis": {
        "earned_score": 10,
        "available_score": 10,
        "attempted_count": 1,
        "passed_count": 1,
        "pass_rate": 1.0,
    },
    "submission_outcomes": [
        {"id": "pending", "count": 0},
        {"id": "judge_error", "count": 0},
        {"id": "zero_score", "count": 1},
        {"id": "partial", "count": 0},
        {"id": "full", "count": 1},
    ],
    "timeline": [
        {
            "date": "2026-09-09",
            "submissions": 2,
            "completed": 2,
            "best_score_delta": 10,
            "cumulative_score": 10,
        }
    ],
    "difficulty": [
        {
            "difficulty_id": "luogu.1",
            "difficulty_label": "入门",
            "attempted": 1,
            "passed": 1,
            "earned_score": 10,
            "available_score": 10,
            "rate": 1.0,
        }
    ],
    "knowledge_points": [
        {
            "tag": "基础",
            "attempted": 1,
            "passed": 1,
            "earned_score": 10,
            "available_score": 10,
            "rate": 1.0,
        }
    ],
    "problems": [
        {
            "problem_id": "sum",
            "title": "两数之和",
            "state": "passed",
            "available_score": 10,
            "best_score": 10,
            "difficulty_id": "luogu.1",
            "difficulty_label": "入门",
            "tags": ["基础"],
        }
    ],
}


class FakeAPI:
    def __init__(self, role="user"):
        self.calls = []
        self.profile = {**USER, "role": role}
        self.problems = [deepcopy(PROBLEM)]
        self.failure = None
        self.closed = False
        self.raw_calls = []
        self.translations = {}
        self.attachments = []
        self.attachment_tamper = None
        self.audit_records = []
        self.import_expires = "2099-09-09T01:00:00+00:00"
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
        self.problem_statuses = deepcopy(PROBLEM_STATUSES)
        self.learning_stats = deepcopy(LEARNING_STATS)
        self.authoring_session = None

    def close(self):
        self.closed = True

    def _localized(self, problem, requested):
        requested = "en" if str(requested).startswith("en") else "zh-CN"
        translation = self.translations.get(problem["id"])
        status = "ready" if requested == "zh-CN" or translation else "missing"
        selected_fields = (
            problem if requested == "zh-CN" else translation if status == "ready" else {}
        )
        fields = {
            key: selected_fields.get(key, "")
            for key in (
                "title",
                "description",
                "input_description",
                "output_description",
                "constraints",
                "hint",
            )
        }
        return {
            **deepcopy(problem),
            "content": {
                "schema_version": "oj.problem-content.v2",
                "requested_locale": requested,
                "resolved_locale": requested if status == "ready" else None,
                "status": status,
                "fallback": False,
                "source_digest": "test-digest",
                "fields": fields,
            },
        }

    def request(self, method, path, *, json=None, content=None, headers=None, params=None):
        self.calls.append((method, path, deepcopy(json), deepcopy(params)))
        if content is not None:
            self.raw_calls.append(
                (method, path, bytes(content), deepcopy(params), deepcopy(headers))
            )
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
            return [
                self._localized(problem, (params or {}).get("locale")) for problem in self.problems
            ]
        if path == "/api/me/problem-statuses/":
            return deepcopy(self.problem_statuses)
        if path == "/api/me/learning-stats/":
            return deepcopy(self.learning_stats)
        if path == "/api/admin/learning-overview/":
            outcomes = [
                {"id": name, "count": 1 if name in {"accepted", "wrong_answer"} else 0}
                for name in (
                    "pending",
                    "accepted",
                    "partial",
                    "wrong_answer",
                    "compile_error",
                    "time_limit",
                    "memory_limit",
                    "runtime_error",
                    "judge_error",
                )
            ]
            return {
                "schema_version": "oj.admin-learning-overview.v1",
                "generated_at": "2026-09-09T12:00:00+00:00",
                "timezone": "UTC",
                "summary": {
                    "account_count": 1,
                    "active_count": 1,
                    "disabled_count": 0,
                    "learner_count": int(self.profile["role"] == "user"),
                    "engaged_count": 1,
                    "submission_count": 2,
                    "attempted_count": 1,
                    "passed_count": 1,
                    "earned_score": 10,
                    "available_score": 10,
                    "score_rate": 1.0,
                    "pass_rate": 1.0,
                },
                "submission_outcomes": outcomes,
                "users": [
                    {
                        "user_id": self.profile["user_id"],
                        "username": self.profile["username"],
                        "role": self.profile["role"],
                        "account_status": "active",
                        "join_time": self.profile["join_time"],
                        "submission_count": 2,
                        "attempted_count": 1,
                        "passed_count": 1,
                        "earned_score": 10,
                        "available_score": 10,
                        "score_rate": 1.0,
                        "pass_rate": 1.0,
                        "submission_outcomes": outcomes,
                    }
                ],
            }
        if path == "/api/attachments/":
            if method == "POST":
                record = {
                    "schema_version": "oj.attachment.v1",
                    "attachment_id": f"a{len(self.attachments) + 1}",
                    "filename": params["filename"],
                    "media_type": params["media_type"],
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "status": "ready",
                    "kind": "image" if params["filename"].endswith(".png") else "text",
                    "capabilities": {
                        "text": not params["filename"].endswith(".png"),
                        "vision": False,
                    },
                    "preview": {"text": "safe preview"},
                    "warning_codes": [],
                    "created_at": "2026-09-09T00:00:00+00:00",
                    "expires_at": "2099-09-09T01:00:00+00:00",
                }
                if self.attachment_tamper == "size":
                    record["size_bytes"] += 1
                elif self.attachment_tamper == "sha256":
                    record["sha256"] = "f" * 64
                self.attachments.append(record)
                return deepcopy(record)
            return deepcopy(self.attachments)
        if path.startswith("/api/attachments/") and method == "DELETE":
            attachment_id = path.rsplit("/", 1)[-1]
            self.attachments = [
                item for item in self.attachments if item["attachment_id"] != attachment_id
            ]
            return {"attachment_id": attachment_id}
        if path.startswith("/api/attachments/") and method == "GET":
            attachment_id = path.rsplit("/", 1)[-1]
            return deepcopy(
                next(item for item in self.attachments if item["attachment_id"] == attachment_id)
            )
        if path == "/api/problem-imports/uploads/":
            self.import_upload_sha = hashlib.sha256(content).hexdigest()
            return {
                "schema_version": "oj.problem-import-upload.v1",
                "upload_id": "upload-1",
                "filename": params["filename"],
                "size_bytes": len(content),
                "sha256": self.import_upload_sha,
                "expires_at": self.import_expires,
            }
        if path == "/api/problem-imports/previews/":
            return {
                "schema_version": "oj.problem-import-preview.v1",
                "preview_id": "preview-1",
                "archive_sha256": self.import_upload_sha,
                "source_format": json["source_format"],
                "expires_at": self.import_expires,
                "problem": {"id": "IMPORTED", "title": "导入题目"},
                "cases": {"samples": 1, "testcases": 2},
                "limits": {"time_limit": 1, "memory_limit": 128},
                "warnings": [],
                "missing_fields": [],
                "conflict": {"exists": False, "current_digest": None},
                "can_commit": True,
            }
        if path == "/api/problem-imports/previews/preview-1/commit":
            self.problems.append({**deepcopy(PROBLEM), "id": "IMPORTED", "title": "导入题目"})
            return {"id": "IMPORTED"}
        if path.endswith("/translations/en"):
            problem_id = path.split("/")[3]
            if method == "PUT":
                self.translations[problem_id] = deepcopy(json)
                return {"status": "ready", "fields": deepcopy(json)}
            self.translations.pop(problem_id, None)
            return {"problem_id": problem_id, "locale": "en"}
        if path.startswith("/api/problems/"):
            if method == "PUT":
                return {"id": path.rsplit("/", 1)[-1]}
            if method == "DELETE":
                self.problems = []
                return {"id": "sum"}
            found = next(p for p in self.problems if p["id"] == path.rsplit("/", 1)[-1])
            return self._localized(found, (params or {}).get("locale"))
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
        if path == "/api/ai/authoring-sessions/" and method == "POST":
            request = deepcopy(json["request"])
            self.authoring_session = {
                "schema_version": "oj.authoring-session.v1",
                "session_id": "manual-session-1",
                "owner_id": "u1",
                "status": "running",
                "current_revision": 1,
                "latest_success_revision": None,
                "draft": None,
                "original_request": request,
                "current_request": request,
                "revisions": [
                    {
                        "revision": 1,
                        "operation": "initial",
                        "request": request,
                        "task": {
                            "task_id": "manual-task-1",
                            "status": "running",
                            "progress": "正在接收模型生成内容",
                            "progress_percent": 35,
                            "result": None,
                            "error": None,
                            "error_code": None,
                        },
                    }
                ],
            }
            return deepcopy(self.authoring_session)
        if path == "/api/ai/authoring-sessions/manual-session-1" and method == "GET":
            return deepcopy(self.authoring_session)
        if path.endswith("/active-task") and method == "DELETE":
            self.authoring_session["status"] = "cancelled"
            self.authoring_session["revisions"][-1]["task"]["status"] = "cancelled"
            self.authoring_session["revisions"][-1]["task"]["progress_percent"] = 10
            return deepcopy(self.authoring_session)
        if path.endswith("/cancel"):
            self.task["status"] = "cancelled"
            return deepcopy(self.task)
        if path.startswith("/api/ai/problem-tasks"):
            return deepcopy(self.task)
        if path == "/api/logs/access/":
            return deepcopy(self.audit_records)
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


def attachment_projection(index=1, *, size_bytes=20, content=b"reference text"):
    return {
        "schema_version": "oj.attachment.v1",
        "attachment_id": f"a{index}",
        "filename": f"note-{index}.txt",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": size_bytes,
        "media_type": "text/plain",
        "kind": "text",
        "capabilities": {"text": True, "vision": False},
        "preview": {"text": "safe preview", "width": None, "height": None},
        "warning_codes": [],
        "expires_at": "2099-09-09T01:00:00+00:00",
    }


def finish_manual_authoring(fake, draft, *, status="completed"):
    fake.authoring_session["status"] = status
    task = fake.authoring_session["revisions"][-1]["task"]
    task["status"] = status
    task["progress"] = status
    task["progress_percent"] = 100 if status == "completed" else 35
    if status == "completed":
        task["result"] = deepcopy(draft)
        fake.authoring_session["draft"] = deepcopy(draft)
        fake.authoring_session["latest_success_revision"] = 1
    else:
        task["result"] = None
        task["error"] = "Synthetic provider failure"
        task["error_code"] = "provider_unavailable"


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


def test_difficulty_choices_keep_stored_value_without_duplicate_localized_labels():
    options = difficulty_options("Beginner")
    labels = [difficulty_option_label(value, "en") for value in options]

    assert options[0] == "入门"
    assert labels[0] == "Beginner"
    assert len(labels) == len(set(labels)) == 8


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
        ("Another permission failure", "请稍后重试；若问题持续，请联系管理员。"),
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


def test_framework_toolbar_is_minimal_and_only_exact_right_controls_are_hidden():
    from frontend.styles import CSS

    config = toml.loads((ROOT / ".streamlit/config.toml").read_text(encoding="utf-8"))
    assert config["client"]["toolbarMode"] == "minimal"
    assert 'header [data-testid="stToolbar"]' in CSS
    assert 'header [data-testid="stAppDeployButton"]' in CSS
    assert "#MainMenu" in CSS
    assert '[data-testid="stSidebarCollapseButton"]' not in CSS
    assert "header {display:none" not in CSS


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
        "nav_analytics",
        "nav_authoring",
        "nav_account",
        "sidebar_logout",
    ]
    assert at.button(key="nav_problems").proto.help == "当前页面"
    for key, page in (
        ("nav_submissions", "提交记录"),
        ("nav_analytics", "成绩总览"),
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
    assert any(call[1] == "/api/me/learning-stats/" for call in fake.calls)


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


def test_language_switch_updates_shell_pages_and_problem_request_together():
    fake = FakeAPI()
    at = app(fake)

    assert at.button(key="language_switch").label == "English"
    at.button(key="language_switch").click().run()

    assert not at.exception
    assert at.session_state["_locale"] == "en"
    assert at.title[0].value == "Problems"
    assert at.button(key="language_switch").label == "中文"
    assert at.button(key="nav_problems").label == "Problems"
    assert at.button(key="nav_submissions").label == "Submissions"
    assert any('data-oj-toast-language-reset="true"' in item.proto.body for item in at.get("html"))
    assert any(
        call[:2] == ("GET", "/api/problems/") and call[3] == {"locale": "en"} for call in fake.calls
    )
    at.button(key="nav_account").click().run()
    assert not at.exception and at.title[0].value == "Account"


def test_language_choice_survives_logout_and_authentication_is_consistent():
    fake = FakeAPI()
    at = app(fake, _locale="en")

    at.button(key="sidebar_logout").click().run()

    assert not at.exception and at.session_state["_locale"] == "en"
    assert at.title[0].value == "Sign in"
    assert at.text_input(key="login_username").label == "Username"
    assert at.button(key="auth_continue").label == "Next"


def test_language_switch_clears_every_password_state_without_changing_identity():
    fake = FakeAPI()
    at = auth_password_step(app(fake, logged_in=False), name="learner")
    at.text_input(key="login_password").set_value("temporary-secret")
    at.session_state["register_password"] = "register-secret"
    at.session_state["register_repeat"] = "register-secret"
    at.session_state["admin_password"] = "admin-secret"

    at.button(key="language_switch").click().run()

    assert not at.exception and at.session_state["_locale"] == "en"
    for key in ("login_password", "register_password", "register_repeat", "admin_password"):
        assert key not in at.session_state
    assert at.session_state["_auth_name"] == "learner"
    assert at.session_state["_auth_step"] == "identity"
    assert at.text_input(key="login_username").value == "learner"


def test_analytics_navigation_renders_one_private_statistics_payload():
    fake = FakeAPI()

    at = app(fake, page="成绩总览")

    assert not at.exception
    assert at.title[0].value == "学习统计"
    assert sum(call[:2] == ("GET", "/api/me/learning-stats/") for call in fake.calls) == 1
    bodies = [item.proto.body for item in at.get("html")]
    assert any("oj-analytics-kpis" in body for body in bodies)
    assert any("oj-analytics-table" in body for body in bodies)


def test_catalog_uses_one_status_snapshot_for_multiple_problems_and_hides_private_fields():
    fake = FakeAPI()
    fake.problems.extend(
        [
            {**deepcopy(PROBLEM), "id": "legacy", "title": "旧难度", "difficulty": "medium"},
            {**deepcopy(PROBLEM), "id": "advanced", "title": "进阶题", "difficulty": "提高"},
        ]
    )
    fake.problem_statuses["items"].extend(
        [
            {
                "problem_id": "legacy",
                "state": "failed",
                "latest_outcome": "compile_error",
                "latest_terminal": {"status": "success"},
            },
            {
                "problem_id": "advanced",
                "state": "partial",
                "latest_outcome": "time_limit",
                "latest_terminal": {"status": "success"},
            },
        ]
    )

    at = app(fake)

    assert not at.exception
    assert sum(call[:2] == ("GET", "/api/me/problem-statuses/") for call in fake.calls) == 1
    assert not any(call[1].startswith("/api/submissions") for call in fake.calls)
    bodies = "".join(item.proto.body for item in at.get("html"))
    assert "status-ac" in bodies and "status-compile" in bodies and "status-timeout" in bodies
    assert "difficulty-red" in bodies and "difficulty-green" in bodies
    assert "SECRET_STATUS_CODE" not in bodies
    assert "SECRET_STATUS_CASE" not in bodies


@pytest.mark.parametrize(
    ("outcome", "css_class", "zh_label"),
    [
        ("accepted", "status-ac", "已通过"),
        ("wrong_answer", "status-failed", "答案错误"),
        ("partial", "status-partial", "部分通过"),
        ("compile_error", "status-compile", "编译错误"),
        ("time_limit", "status-timeout", "运行超时"),
        ("memory_limit", "status-memory", "内存超限"),
        ("runtime_error", "status-runtime", "运行错误"),
        ("judge_error", "status-judge-error", "评测异常"),
        ("pending", "status-pending", "判题中"),
    ],
)
def test_catalog_verdict_badges_have_bounded_semantic_colors(outcome, css_class, zh_label):
    source = deepcopy(PROBLEM_STATUSES)
    state = "passed" if outcome == "accepted" else "partial" if outcome == "partial" else "failed"
    if outcome == "pending":
        state = "pending"
    source["items"][0].update(state=state, latest_outcome=outcome)
    if outcome == "judge_error":
        source["items"][0]["latest_terminal"] = {"status": "error"}
    status = problem_status_index(source)["sum"]

    rendered = problem_badges_html(difficulty_projection("入门"), status)

    assert css_class in rendered
    assert zh_label in rendered


def test_problem_status_projection_is_versioned_allow_list_and_badges_escape_input():
    source = deepcopy(PROBLEM_STATUSES)
    projected = problem_status_index(source)

    assert projected == {
        "sum": {
            "state": "passed",
            "latest_outcome": "accepted",
            "terminal_error": False,
            "has_pending": False,
        }
    }
    assert problem_status_index({"schema_version": "future", "items": []}) is None
    rendered = problem_badges_html(
        {"label": "<img src=x onerror=alert(1)>", "token": "x' onclick='alert(1)"},
        projected["sum"],
    )
    assert "<img" not in rendered and "onclick" not in rendered
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "difficulty-neutral" in rendered


def test_pending_current_attempt_and_outdated_problem_keep_honest_lifecycle_labels():
    source = deepcopy(PROBLEM_STATUSES)
    source["items"][0].update(state="passed", latest_outcome="pending")
    source["items"][0]["latest_pending"] = {"submission_id": "new"}
    pending = problem_status_index(source)["sum"]
    rendered = problem_badges_html(difficulty_projection("入门"), pending)
    assert "已通过" in rendered and "新提交判题中" in rendered
    assert rendered.count("status-pending") == 1

    source["items"][0].update(state="outdated", latest_outcome="accepted")
    outdated = problem_status_index(source)["sum"]
    rendered = problem_badges_html(difficulty_projection("入门"), outdated)
    assert "status-outdated" in rendered and "题目已更新" in rendered


def test_known_legacy_difficulties_project_to_canonical_luogu_labels():
    assert difficulty_projection("medium", "zh-CN") == {
        "id": "luogu.4",
        "label": "普及+/提高-",
        "token": "difficulty-green",
        "recognized": True,
    }
    assert difficulty_projection("基础", "en") == {
        "id": "luogu.2",
        "label": "Novice−",
        "token": "difficulty-orange",
        "recognized": True,
    }
    assert difficulty_projection("自定义难度", "en")["label"] == "Unrated"
    assert difficulty_projection("custom", "zh-CN")["label"] == "未分级"
    assert difficulty_projection("提高", "en")["label"] == "Intermediate"


@pytest.mark.parametrize("status", [0, 403, 500])
def test_catalog_status_failure_degrades_without_losing_the_problem_list(status):
    fake = FakeAPI()
    fake.failure = ("GET", "/api/me/problem-statuses/", status, "private backend failure")

    at = app(fake)

    assert not at.exception and at.title[0].value == "题库"
    assert at.button(key="open_sum")
    assert any("题库仍可正常浏览" in item.value for item in at.caption)
    bodies = "".join(item.proto.body for item in at.get("html"))
    assert "状态暂缺" in bodies and "private backend failure" not in bodies


def test_progress_styles_are_responsive_accessible_and_reduced_motion_safe():
    from frontend.styles import CSS

    for selector in (
        ".oj-analytics-kpis",
        ".oj-analytics-grid-two",
        ".oj-analytics-table-wrap",
        ".oj-catalog-badges",
        ".status-ac",
        ".status-compile",
        ".status-timeout",
        ".state-passed",
        ".state-outdated",
        ".difficulty-red",
        ".difficulty-purple",
        ".difficulty-neutral",
    ):
        assert selector in CSS
    assert "@media (max-width:860px)" in CSS
    assert "@media (max-width:480px)" in CSS
    reduced = CSS.split("@media (prefers-reduced-motion:reduce)", 1)[1]
    assert "st-key-catalog_problem_" in reduced and "transform:none" in reduced
    assert "linear-gradient" not in CSS


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
    ("page", "role"),
    [
        ("题库", "user"),
        ("提交记录", "user"),
        ("成绩总览", "user"),
        ("智能命题", "user"),
        ("账户", "user"),
        ("管理工作区", "admin"),
    ],
)
def test_authenticated_workspace_has_exactly_one_global_chat_launcher(page, role):
    at = app(FakeAPI(role), page=page)

    assert not at.exception
    assert len([item for item in at.button if item.key == "chat_launcher_button"]) == 1


def test_logged_out_authentication_never_mounts_chat_launcher():
    at = app(FakeAPI(), logged_in=False)

    assert not at.exception
    assert not [item for item in at.button if item.key == "chat_launcher_button"]


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
    fake.task.update(status="completed", result=deepcopy(ENGLISH_PROBLEM))
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
    elapsed = markup('class="oj-loading-note">已耗时')
    assert "13 秒" in elapsed
    assert "4 分钟" not in elapsed and "四分钟" not in elapsed


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


def test_green_visual_hierarchy_is_semantic_and_restrained():
    from frontend.styles import CSS

    assert "--oj-border-accent:#BDD7C8" in CSS
    assert "--oj-surface-tint:#F7FBF8" in CSS
    assert '.st-key-workspace_shell [data-testid="stForm"]' in CSS
    assert '.st-key-workspace_shell [data-testid="stMetric"]' in CSS
    assert '.st-key-workspace_shell [data-testid="stExpander"]' in CSS
    assert ".st-key-problem_prose" in CSS and "border-left:2px" in CSS
    assert "linear-gradient" not in CSS


def test_narrow_auth_hides_story_layout_wrapper_and_expands_only_form_wrapper():
    from frontend.styles import CSS

    assert ".st-key-auth_composition {max-width:100%;margin-inline:auto!important" in CSS
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


def test_problem_translation_projection_and_explicit_missing_fallback():
    fake = FakeAPI()
    fake.translations["sum"] = {
        "title": "A + B",
        "description": "Add two integers.",
        "input_description": "Read two integers.",
        "output_description": "Print their sum.",
        "constraints": "Absolute values are at most one thousand.",
        "hint": "Mind negative values.",
    }
    at = app(fake, _locale="en", _problem_mode="detail", _problem_id="sum")
    assert not at.exception and at.title[0].value == "A + B"
    assert not any("No English translation" in item.value for item in at.warning)
    assert not any("自建" in item.value for item in at.caption)
    assert any("1 optional metadata item" in item.value for item in at.caption)
    assert any(
        call[:2] == ("GET", "/api/problems/sum") and call[3] == {"locale": "en"}
        for call in fake.calls
    )

    missing = app(FakeAPI(), _locale="en", _problem_mode="detail", _problem_id="sum")
    assert not missing.exception
    assert missing.title[0].value == "Problem sum · English translation unavailable"
    assert PROBLEM["title"] not in str(missing)
    assert any("No English translation" in item.value for item in missing.warning)


def test_english_catalog_hides_untranslated_tags_instead_of_mixing_languages():
    fake = FakeAPI()
    fake.translations["sum"] = {
        "title": "A + B",
        "description": "Add two integers.",
        "input_description": "Read two integers.",
        "output_description": "Print their sum.",
        "constraints": "Absolute values are at most one thousand.",
        "hint": "",
    }
    at = app(fake, _locale="en")

    assert not at.exception
    assert not any("基础" in item.value for item in at.caption)
    assert any("1 optional metadata item" in item.value for item in at.caption)


def test_english_problem_editor_preserves_unknown_difficulty_and_marks_original_fields():
    fake = FakeAPI()
    fake.problems[0]["difficulty"] = "custom 难度"
    at = app(fake, _locale="en", _problem_mode="edit", _problem_id="sum")

    difficulty = at.selectbox(key="edit_sum_difficulty")
    assert not at.exception and difficulty.value == "custom 难度"
    assert "Original difficulty · custom 难度" in difficulty.options
    assert at.text_input(key="edit_sum_source").label == "Original source"
    assert at.text_input(key="edit_sum_tags").label == "Original tags (comma-separated)"
    assert any("original Chinese statement" in item.value for item in at.caption)

    button(at, "Save problem").click().run()
    updated = next(call[2] for call in fake.calls if call[:2] == ("PUT", "/api/problems/sum"))
    assert updated["difficulty"] == "custom 难度"


def test_malformed_or_stale_translation_never_claims_ready():
    raw = deepcopy(PROBLEM)
    raw["content"] = {
        "schema_version": "oj.problem-content.v1",
        "requested_locale": "en",
        "resolved_locale": "zh-CN",
        "status": "stale",
        "fallback": True,
        "fields": {
            field: raw.get(field, "")
            for field in (
                "title",
                "description",
                "input_description",
                "output_description",
                "constraints",
                "hint",
            )
        },
    }
    projected, warning = localized_problem(raw, "en")
    assert projected["title"] == "Problem sum · English translation unavailable"
    assert projected["description"] == ""
    assert warning == "translation.fallback_stale"

    raw["content"]["fields"].pop("description")
    _, warning = localized_problem(raw, "en")
    assert warning == "translation.fallback_missing"


def test_complete_english_translation_uses_dedicated_prose_only_route():
    fake = FakeAPI()
    at = app(fake, _problem_mode="detail", _problem_id="sum")
    translation = {
        "title": "A + B",
        "description": "Add two integers.",
        "input_description": "Read two integers.",
        "output_description": "Print their sum.",
        "constraints": "Absolute values are at most one thousand.",
        "hint": "",
    }
    at.text_input(key="translation_sum_title").set_value(translation["title"])
    for field in (
        "description",
        "input_description",
        "output_description",
        "constraints",
        "hint",
    ):
        at.text_area(key=f"translation_sum_{field}").set_value(translation[field])
    button(at, "保存英文译文").click().run()

    assert not at.exception
    assert any(
        call[:3] == ("PUT", "/api/problems/sum/translations/en", translation) for call in fake.calls
    )
    assert "samples" not in fake.translations["sum"]


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


def test_manual_payload_can_persist_complete_english_without_copying_judge_data():
    values = {
        **PROBLEM,
        "id": "BILINGUAL-MANUAL",
        "tags_text": "整数运算",
        "samples_json": '[{"input":"1 2\\n","output":"3\\n"}]',
        "testcases_json": '[{"input":"-1 1\\n","output":"0\\n"}]',
        "time_limit_text": "1",
        "memory_limit_text": "128",
        "translations_en": ENGLISH_PROBLEM["translations"]["en"],
    }

    payload = problem_payload(values)

    assert payload["translations"] == ENGLISH_PROBLEM["translations"]
    assert set(payload["translations"]["en"]) == {
        "title",
        "description",
        "input_description",
        "output_description",
        "constraints",
        "hint",
    }
    assert "samples" not in payload["translations"]["en"]
    assert payload["testcases"] == [{"input": "-1 1\n", "output": "0\n"}]


def test_problem_zip_import_is_raw_preview_then_explicit_commit():
    fake = FakeAPI()
    at = app(fake, _problem_mode="new")
    at.file_uploader(key="problem_import_file").upload(
        "problem.zip", b"PK\x03\x04fake archive", "application/zip"
    ).run()
    button(at, "上传并生成预览").click().run()

    assert not at.exception
    assert fake.raw_calls == [
        (
            "POST",
            "/api/problem-imports/uploads/",
            b"PK\x03\x04fake archive",
            {"filename": "problem.zip", "media_type": "application/zip"},
            None,
        )
    ]
    assert any(call[:2] == ("POST", "/api/problem-imports/previews/") for call in fake.calls)
    assert any("样例 1 组" in item.value for item in at.caption)
    preview_copy = "\n".join(item.value for item in at.caption)
    assert "文件：problem.zip" in preview_copy
    assert "格式：标准 OJ 题目包" in preview_copy
    assert "题面语言：仅中文（未附英文译文）" in preview_copy
    assert "时间 1 秒" in preview_copy and "内存 128 MB" in preview_copy
    assert hashlib.sha256(b"PK\x03\x04fake archive").hexdigest() in preview_copy
    assert "预览有效至：2099-09-09" in preview_copy
    assert "服务端可提交：是" in preview_copy

    button(at, "确认导入题库").click().run()
    assert not at.exception
    assert any(
        call[:2] == ("POST", "/api/problem-imports/previews/preview-1/commit")
        and call[2] == {"overwrite": False}
        for call in fake.calls
    )


def test_import_binding_covers_archive_name_format_and_luogu_metadata():
    class Upload:
        def __init__(self, name, value):
            self.name = name
            self.value = value

        def getvalue(self):
            return self.value

    archive = Upload("problem.zip", b"first")
    baseline = _import_binding(archive, "luogu-flat-v1", {"title": "one"})

    assert baseline != _import_binding(
        Upload("renamed.zip", b"first"), "luogu-flat-v1", {"title": "one"}
    )
    assert baseline != _import_binding(
        Upload("problem.zip", b"second"), "luogu-flat-v1", {"title": "one"}
    )
    assert baseline != _import_binding(archive, "native-v1", {"title": "one"})
    assert baseline != _import_binding(archive, "luogu-flat-v1", {"title": "two"})
    assert set(baseline) == {
        "filename",
        "archive_sha256",
        "source_format",
        "metadata_sha256",
    }


def test_changed_import_file_or_format_immediately_invalidates_old_preview():
    fake = FakeAPI()
    at = app(fake, _problem_mode="new")
    at.file_uploader(key="problem_import_file").upload(
        "problem.zip", b"PK\x03\x04first", "application/zip"
    ).run()
    button(at, "上传并生成预览").click().run()
    assert "_problem_import_preview" in at.session_state

    at.file_uploader(key="problem_import_file").upload(
        "replacement.zip", b"PK\x03\x04second", "application/zip"
    ).run()
    assert "_problem_import_preview" not in at.session_state
    assert not any(item.label == "确认导入题库" for item in at.button)
    assert any("已改变" in item.value for item in at.info)

    button(at, "上传并生成预览").click().run()
    assert "_problem_import_preview" in at.session_state
    at.radio(key="problem_import_format").set_value("luogu-flat-v1").run()
    assert "_problem_import_preview" not in at.session_state
    assert not any(item.label == "确认导入题库" for item in at.button)


def test_failed_repreview_cannot_leave_the_previous_preview_committable():
    fake = FakeAPI()
    at = app(fake, _problem_mode="new")
    at.file_uploader(key="problem_import_file").upload(
        "problem.zip", b"PK\x03\x04first", "application/zip"
    ).run()
    button(at, "上传并生成预览").click().run()
    assert "_problem_import_preview" in at.session_state

    fake.failure = (
        "POST",
        "/api/problem-imports/previews/",
        422,
        "SECRET backend parser text",
    )
    button(at, "上传并生成预览").click().run()

    assert not at.exception and at.error
    assert "_problem_import_preview" not in at.session_state
    assert not any(item.label == "确认导入题库" for item in at.button)
    assert "SECRET" not in at.error[0].value


def test_expired_import_preview_is_visible_but_never_committable():
    fake = FakeAPI()
    fake.import_expires = "2000-01-01T00:00:00+00:00"
    at = app(fake, _problem_mode="new")
    at.file_uploader(key="problem_import_file").upload(
        "problem.zip", b"PK\x03\x04expired", "application/zip"
    ).run()
    button(at, "上传并生成预览").click().run()

    assert not at.exception
    assert any("已过期" in item.value for item in at.error)
    assert button(at, "确认导入题库").disabled
    assert not any(call[1].endswith("/commit") for call in fake.calls)


def test_import_preview_projection_drops_statement_and_case_content():
    raw = {
        "schema_version": "oj.problem-import-preview.v1",
        "preview_id": "preview-safe",
        "archive_sha256": "a" * 64,
        "source_format": "native-v1",
        "expires_at": "2099-09-09T00:00:00+00:00",
        "problem": {
            "id": "SAFE",
            "title": "<script>alert(1)</script>",
            "description": "SECRET STATEMENT",
            "testcases": [{"input": "SECRET CASE"}],
        },
        "cases": {"samples": 1, "testcases": 2},
        "limits": {"time_limit": 1, "memory_limit": 128},
        "warnings": [{"code": "TRANSLATION_MISSING", "message": "SECRET MESSAGE"}],
        "missing_fields": [],
        "conflict": {"exists": False, "current_digest": None},
        "can_commit": True,
    }
    binding = {
        "filename": "problem.zip",
        "archive_sha256": "a" * 64,
        "source_format": "native-v1",
        "metadata_sha256": "b" * 64,
    }
    preview = _safe_import_preview(raw, filename="problem.zip", binding=binding)
    assert set(preview["problem"]) == {"id", "title"}
    assert "SECRET" not in str(preview)
    assert preview["warnings"] == ["TRANSLATION_MISSING"]
    assert preview["binding"] == binding

    malformed = deepcopy(raw)
    malformed["missing_fields"] = ["private_backend_field"]
    assert _safe_import_preview(malformed, filename="problem.zip", binding=binding) is None
    malformed = deepcopy(raw)
    malformed["expires_at"] = "not-a-time"
    assert _safe_import_preview(malformed, filename="problem.zip", binding=binding) is None
    assert _safe_import_preview(raw, filename="other.zip", binding=binding) is None


def test_luogu_import_metadata_is_strict_and_keeps_case_archive_separate():
    metadata = _validate_luogu_metadata(
        {
            "id": "P1000",
            "title": "A+B Problem",
            "description": "Add two values.",
            "input_description": "Two integers.",
            "output_description": "Their sum.",
            "constraints": "Small integers.",
            "samples_json": '[{"input":"1 2","output":"3"}]',
            "difficulty": "入门",
            "tags": "math, implementation",
            "source": "Luogu",
            "author": "Course",
            "hint": "",
        }
    )
    assert metadata["id"] == "P1000"
    assert metadata["samples"] == [{"input": "1 2", "output": "3"}]
    assert metadata["tags"] == ["math", "implementation"]
    assert "testcases" not in metadata


def test_manual_authoring_uploads_text_and_marks_image_metadata_only():
    fake = FakeAPI()
    at = app(fake, _problem_mode="new")
    at.file_uploader(key="manual_new_problem_attachment_files").set_value(
        [
            ("note.txt", b"reference text", "text/plain"),
            ("diagram.png", b"fake image", "image/png"),
        ]
    ).run()
    button(at, "解析所选附件").click().run()

    assert not at.exception
    assert len([call for call in fake.raw_calls if call[1] == "/api/attachments/"]) == 2
    assert len(at.session_state["_manual_new_problem_attachments"]) == 2
    assert any("图片仅校验并记录尺寸" in item.value for item in at.caption)
    captions = "\n".join(item.value for item in at.caption)
    assert "文本 · text/plain · 14 B" in captions
    assert "图片 · image/png · 10 B" in captions


def test_manual_attachment_limit_includes_existing_records_before_upload():
    fake = FakeAPI()
    existing = [
        attachment_projection(
            index,
            size_bytes=10 * 1024 * 1024,
            content=f"existing-{index}".encode(),
        )
        for index in range(1, 4)
    ]
    at = app(
        fake,
        _problem_mode="new",
        _manual_new_problem_attachments=existing,
    )
    at.file_uploader(key="manual_new_problem_attachment_files").set_value(
        [("additional.txt", b"x" * (3 * 1024 * 1024), "text/plain")]
    ).run()
    button(at, "解析所选附件").click().run()

    assert not at.exception
    assert any("总大小不能超过 32 MiB" in item.value for item in at.error)
    assert not any(call[1] == "/api/attachments/" for call in fake.raw_calls)
    assert at.session_state["_manual_new_problem_attachments"] == existing


@pytest.mark.parametrize("tamper", ["size", "sha256"])
def test_attachment_response_is_rechecked_and_invalid_temporary_record_is_deleted(tamper):
    fake = FakeAPI()
    fake.attachment_tamper = tamper
    at = app(fake, _problem_mode="new")
    at.text_input(key="new_problem_title").set_value("附件失败也要保留的草稿")
    at.file_uploader(key="manual_new_problem_attachment_files").set_value(
        [("note.txt", b"reference", "text/plain")]
    ).run()
    button(at, "解析所选附件").click().run()

    assert not at.exception and at.error
    assert at.text_input(key="new_problem_title").value == "附件失败也要保留的草稿"
    assert at.session_state["_manual_new_problem_attachments"] == []
    assert fake.attachments == []
    assert any(call[:2] == ("DELETE", "/api/attachments/a1") for call in fake.calls)


def test_saved_manual_problem_deletes_temporary_references_without_publishing_them():
    fake = FakeAPI()
    reference = attachment_projection()
    fake.attachments = [deepcopy(reference)]
    at = app(
        fake,
        _problem_mode="new",
        _manual_new_problem_attachments=[deepcopy(reference)],
    )
    at.text_input(key="new_problem_id").set_value("with-reference")
    at.text_input(key="new_problem_title").set_value("附件不公开")
    for field in ("description", "input_description", "output_description", "constraints"):
        at.text_area(key=f"new_problem_{field}").set_value(PROBLEM[field])
    button(at, "保存题目").click().run()

    created = next(call[2] for call in fake.calls if call[:2] == ("POST", "/api/problems/"))
    assert "attachments" not in created
    assert "_manual_new_problem_attachments" not in at.session_state
    assert any(call[:2] == ("DELETE", "/api/attachments/a1") for call in fake.calls)


def test_abandoning_manual_problem_deletes_temporary_references_and_preview():
    fake = FakeAPI()
    reference = attachment_projection()
    fake.attachments = [deepcopy(reference)]
    at = app(
        fake,
        _problem_mode="new",
        _manual_new_problem_attachments=[deepcopy(reference)],
    )
    at.session_state["_problem_import_preview"] = {"preview_id": "stale"}
    button(at, "← 返回题库").click().run()

    assert not at.exception
    assert "_manual_new_problem_attachments" not in at.session_state
    assert "_problem_import_preview" not in at.session_state
    assert any(call[:2] == ("DELETE", "/api/attachments/a1") for call in fake.calls)
    assert at.session_state["_problem_mode"] == "list"


def test_manual_attachment_handoff_carries_only_identity_and_digest_to_ai():
    fake = FakeAPI()
    at = app(fake, _problem_mode="new")
    content = b"reference"
    digest = hashlib.sha256(content).hexdigest()
    at.file_uploader(key="manual_new_problem_attachment_files").set_value(
        [("note.txt", content, "text/plain")]
    ).run()
    button(at, "解析所选附件").click().run()
    button(at, "转入 AI 智能命题").click().run()

    assert not at.exception
    assert at.session_state["navigation"] == "智能命题"
    assert at.session_state["_ai_handoff_attachments"] == [
        {"attachment_id": "a1", "sha256": digest}
    ]
    assert "_manual_new_problem_attachments" not in at.session_state
    assert not any(call[:2] == ("DELETE", "/api/attachments/a1") for call in fake.calls)
    assert not any(call[:2] == ("POST", "/api/problems/") for call in fake.calls)


def test_manual_and_import_uploaders_declare_server_aligned_browser_limits():
    at = app(FakeAPI(), _problem_mode="new")

    manual = at.file_uploader(key="manual_new_problem_attachment_files")
    archive = at.file_uploader(key="problem_import_file")
    assert manual.proto.max_upload_size_mb == 10
    assert archive.proto.max_upload_size_mb == 16


def test_manual_authoring_request_contains_current_draft_and_locked_reference():
    snapshot = {
        "id": "sum",
        "title": "当前标题",
        "description": "当前题面",
        "input_description": "输入",
        "output_description": "输出",
        "constraints": "约束",
        "samples_json": '[{"input":"1 2","output":"3"}]',
        "testcases_json": '[{"input":"2 3","output":"5"}]',
        "hint": "提示",
        "source": "课堂",
        "author": "Teacher",
        "difficulty": "普及-",
        "tags_text": "图论, graph.topological-sort",
        "time_limit_text": "2",
        "memory_limit_text": "256",
    }
    reference = {"attachment_id": "a1", "sha256": "a" * 64}
    built = manual_authoring_request(
        snapshot,
        [reference],
        "补齐边界情况",
        locked_id="sum",
    )

    assert built["difficulty_id"] == "luogu.2"
    assert built["reference_problem_id"] == "sum"
    assert built["attachments"] == [reference]
    assert "当前标题" in built["requirement"]
    assert "补齐边界情况" in built["requirement"]
    assert built["knowledge_point_ids"] == ["graph.topological-sort"]
    assert "图论" in built["free_prompt"]


def test_manual_ai_organizes_in_place_then_refills_without_saving():
    fake = FakeAPI()
    reference = attachment_projection()
    fake.attachments = [deepcopy(reference)]
    at = app(
        fake,
        _problem_mode="new",
        _manual_new_problem_attachments=[deepcopy(reference)],
    )
    at.text_input(key="new_problem_id").set_value("manual-id")
    at.text_input(key="new_problem_title").set_value("人工草稿标题")
    at.text_area(key="new_problem_description").set_value("人工草稿题面")
    at.text_area(key="new_problem_input_description").set_value("人工输入")
    at.text_area(key="new_problem_output_description").set_value("人工输出")
    at.text_area(key="new_problem_constraints").set_value("人工约束")
    at.text_input(key="new_problem_tags").set_value("图论")
    at.text_area(key="new_problem_manual_ai_instruction").set_value("补齐边界样例")
    button(at, "AI 整理 / 补全").click().run()

    created = next(
        call[2] for call in fake.calls if call[:2] == ("POST", "/api/ai/authoring-sessions/")
    )
    assert created["request"]["attachments"] == [
        {"attachment_id": reference["attachment_id"], "sha256": reference["sha256"]}
    ]
    assert "人工草稿标题" in created["request"]["requirement"]
    assert "补齐边界样例" in created["request"]["requirement"]
    assert created["idempotency_key"].startswith("ui-manual-organize-")
    assert not any(call[:2] == ("POST", "/api/problems/") for call in fake.calls)

    organized = {
        **deepcopy(PROBLEM),
        "id": "ai-generated-id",
        "title": "AI 整理后的标题",
        "description": "AI 整理后的完整题面",
        "difficulty": "普及+/提高-",
    }
    finish_manual_authoring(fake, organized)
    at.run()

    assert not at.exception
    assert at.text_input(key="new_problem_id").value == "manual-id"
    assert at.text_input(key="new_problem_title").value == "AI 整理后的标题"
    assert at.text_area(key="new_problem_description").value == "AI 整理后的完整题面"
    assert at.selectbox(key="new_problem_difficulty").value == "普及+/提高-"
    assert at.session_state["_manual_new_problem_attachments"] == [reference]
    assert any("请继续编辑和审核" in item.value for item in at.success)
    assert not any(call[:2] == ("POST", "/api/problems/") for call in fake.calls)


def test_manual_ai_failure_and_concurrent_edit_never_silently_clear_or_overwrite():
    fake = FakeAPI()
    at = app(fake, _problem_mode="new")
    at.text_input(key="new_problem_id").set_value("preserved-id")
    at.text_input(key="new_problem_title").set_value("原始标题")
    at.text_area(key="new_problem_description").set_value("原始题面")
    button(at, "AI 整理 / 补全").click().run()

    finish_manual_authoring(fake, None, status="failed")
    at.run()
    assert not at.exception
    assert at.text_input(key="new_problem_title").value == "原始标题"
    assert at.text_area(key="new_problem_description").value == "原始题面"
    assert any("当前表单和附件均已保留" in item.value for item in at.error)

    button(at, "AI 整理 / 补全").click().run()
    at.text_input(key="new_problem_title").set_value("生成期间人工修改").run()
    finish_manual_authoring(
        fake,
        {**deepcopy(PROBLEM), "id": "other", "title": "AI 新标题"},
    )
    at.run()
    assert at.text_input(key="new_problem_title").value == "生成期间人工修改"
    assert any("表单内容发生过变化" in item.value for item in at.warning)
    button(at, "应用 AI 草稿到表单").click().run()
    assert at.text_input(key="new_problem_title").value == "AI 新标题"
    assert at.text_input(key="new_problem_id").value == "preserved-id"


def test_existing_problem_ai_refill_keeps_locked_identity_and_uses_reference():
    fake = FakeAPI()
    at = app(fake, _problem_mode="edit", _problem_id="sum")
    at.text_input(key="edit_sum_title").set_value("待整理标题")
    button(at, "AI 整理 / 补全").click().run()
    created = next(
        call[2] for call in fake.calls if call[:2] == ("POST", "/api/ai/authoring-sessions/")
    )
    assert created["request"]["reference_problem_id"] == "sum"

    finish_manual_authoring(
        fake,
        {**deepcopy(PROBLEM), "id": "forbidden-replacement", "title": "整理后标题"},
    )
    at.run()
    assert not at.exception
    assert at.text_input(key="edit_sum_id").disabled
    assert at.text_input(key="edit_sum_id").value == "sum"
    assert at.text_input(key="edit_sum_title").value == "整理后标题"
    assert not any(call[:2] == ("PUT", "/api/problems/sum") for call in fake.calls)


def test_leaving_manual_editor_cancels_page_local_ai_task():
    fake = FakeAPI()
    at = app(fake, _problem_mode="new")
    at.text_input(key="new_problem_title").set_value("尚未保存的题目")
    button(at, "AI 整理 / 补全").click().run()
    button(at, "← 返回题库").click().run()

    assert not at.exception
    assert at.session_state["_problem_mode"] == "list"
    assert "_manual_ai_session_new_problem" not in at.session_state
    assert any(
        call[:2]
        == (
            "DELETE",
            "/api/ai/authoring-sessions/manual-session-1/active-task",
        )
        for call in fake.calls
    )


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


def test_admin_audit_projection_localizes_headers_and_drops_unapproved_fields():
    record = {
        "user_id": "u1",
        "problem_id": "sum",
        "action": "view_logs",
        "time": "2026-09-09T12:00:00+00:00",
        "status": "200",
        "details": "SECRET CASE DATA",
    }
    english = audit_table_rows([record], "en")
    assert english == [
        {
            "Accessing user ID": "u1",
            "Problem ID": "sum",
            "Action": "View judge log",
            "Access time": "2026-09-09T12:00:00+00:00",
            "Result": "200",
        }
    ]
    assert "SECRET" not in str(english)
    assert list(audit_table_rows([record], "zh-CN")[0]) == [
        "访问用户编号",
        "题号",
        "操作",
        "访问时间",
        "结果",
    ]


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
    assert button(at, "重新发送").disabled
    assert not button(at, "编辑要求").disabled
    button(at, "停止生成").click().run()
    assert not at.exception
    assert any(c[:2] == ("PUT", "/api/ai/problem-tasks/t1/cancel") for c in fake.calls)
    assert any("已取消" in item.value for item in at.info)
    assert not any(c[:2] == ("POST", "/api/problems/") for c in fake.calls)


def test_ai_completed_draft_is_editable_before_save():
    fake = FakeAPI()
    fake.task.update(status="completed", result=deepcopy(ENGLISH_PROBLEM))
    at = app(fake, page="智能命题", _ai_task=deepcopy(fake.task))
    assert not at.exception
    assert not any(c[:2] == ("POST", "/api/problems/") for c in fake.calls)
    at.text_input(key="ai_draft_t1_new_id").set_value("ai_new")
    at.text_input(key="ai_draft_t1_new_title").set_value("人工校订的题目")
    button(at, "保存到题库").click().run()
    assert not at.exception
    sent = next(c[2] for c in fake.calls if c[:2] == ("POST", "/api/problems/"))
    assert sent["title"] == "人工校订的题目"
    assert sent["translations"] == ENGLISH_PROBLEM["translations"]


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
    fake.task.update(status="completed", result=deepcopy(ENGLISH_PROBLEM))
    at.run()
    assert not at.exception
    assert any("生成完成" in item.value for item in at.success)
    previous_gets = sum(c[:2] == ("GET", "/api/ai/problem-tasks/t1") for c in fake.calls)
    at.run()
    assert sum(c[:2] == ("GET", "/api/ai/problem-tasks/t1") for c in fake.calls) == previous_gets
    assert at.text_input(key="ai_draft_t1_new_title")


def test_ai_update_locks_target_id_and_calls_put():
    fake = FakeAPI()
    fake.task.update(status="completed", result={**deepcopy(ENGLISH_PROBLEM), "id": "different"})
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


def test_estimated_usage_keeps_compact_metrics_without_verbose_accounting_copy():
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
    captions = "\n".join(item.value for item in at.caption)
    for forbidden in (
        "UTF-8",
        "统计来源",
        "费用不代表最终账单",
        "统计尚不完整",
        "单价未完整配置",
        "费用 =",
    ):
        assert forbidden not in captions
    assert [item.label for item in at.metric] == [
        "输入 Token",
        "输出 Token",
        "总 Token",
        "估算费用",
    ]
    cost = next(item for item in at.metric if item.label == "估算费用")
    assert cost.value.startswith("≈ 1e-08")


def test_removed_ai_timeout_and_account_font_copy_do_not_render_or_remain_in_sources():
    fake = FakeAPI()
    at = app(fake, page="智能命题")
    rendered = "\n".join(
        [item.value for item in at.caption] + [item.label for item in at.get("expander")]
    )
    assert "4 分钟" not in rendered and "四分钟" not in rendered

    at = app(fake, page="账户")
    assert "阅读与字体" not in [item.label for item in at.get("expander")]

    sources = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("frontend/ai_page.py", "frontend/accounts.py", "frontend/styles.py")
    )
    for forbidden in (
        "后台异步处理，最长 4 分钟",
        "最长 4 分钟",
        "最多四分钟",
        "阅读与字体",
        "统计来源：",
        "费用不代表最终账单",
        "统计尚不完整",
        "单价未完整配置",
    ):
        assert forbidden not in sources


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
