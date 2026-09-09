"""Programming chat component tests never contact a model provider."""

from copy import deepcopy
import inspect
import re
import time

import pytest
from streamlit.testing.v1 import AppTest

from frontend.chat import (
    ChatUIContractError,
    SESSION_SCHEMA,
    STATUS_SCHEMA,
    STYLE_HOOKS,
    TURN_SCHEMA,
    chat_copy,
    context_epoch,
    programming_focus,
    send_turn,
    session_detail,
    turn_payload,
    workspace_focus,
    _retryable_input,
    _widget_suffix,
)
from frontend.client import APIError

INTRODUCTION = (
    "你好，我是你的编程助手。我可以结合当前题目、代码、提交记录和评测结果，帮你理解题意、"
    "定位错误、梳理算法并改进代码。直接告诉我你卡在哪里。"
)
INTRODUCTION_EN = (
    "Hi, I’m your programming assistant. I can use the current problem, code you share, "
    "submission history, and judge results to help you understand the task, diagnose errors, "
    "structure an algorithm, and improve your code. Tell me where you’re stuck."
)

EPOCH = "a" * 64
OTHER_EPOCH = "b" * 64


def _session(locale="zh-CN", session_id="session-1"):
    introduction = INTRODUCTION if locale == "zh-CN" else INTRODUCTION_EN
    return {
        "schema_version": SESSION_SCHEMA,
        "session_id": session_id,
        "title": "新会话" if locale == "zh-CN" else "New chat",
        "locale": locale,
        "created_at": "2026-09-09T00:00:00Z",
        "updated_at": "2026-09-09T00:00:00Z",
        "last_context_epoch": None,
        "revision": 1,
        "messages": [
            {
                "message_id": f"intro-{session_id}",
                "role": "assistant",
                "content": introduction,
                "created_at": "2026-09-09T00:00:00Z",
                "turn_id": None,
            }
        ],
    }


def _turn(session_id="session-1", status="pending", partial=""):
    result = partial if status == "completed" else None
    return {
        "schema_version": TURN_SCHEMA,
        "turn_id": "turn-1",
        "session_id": session_id,
        "user_message_id": "user-message-1",
        "expected_context_epoch": EPOCH,
        "status": status,
        "progress": "working",
        "partial": partial,
        "result": result,
        "error": None if status != "failed" else "private backend wording",
        "error_code": "provider_connection_failed" if status == "failed" else None,
        "retryable": True if status == "failed" else None,
        "created_at": "2026-09-09T00:00:01Z",
        "started_at": None,
        "ended_at": None,
        "provider_calls": 0,
    }


class FakeChatAPI:
    def __init__(self):
        self.calls = []
        self.sessions = []
        self.turn = None
        self.failure = None
        self.epoch = EPOCH
        self.private_status = {
            "schema_version": STATUS_SCHEMA,
            "context_epoch": self.epoch,
            "scope": {"user_id": "another-user"},
            "items": [
                {
                    "problem_id": "P1",
                    "source_code": "SECRET_OTHER_USER_CODE",
                    "testcases": ["SECRET_HIDDEN_CASE"],
                }
            ],
        }

    def _summary(self, session):
        return {
            key: deepcopy(value)
            for key, value in session.items()
            if key not in {"messages", "revision", "last_context_epoch"}
        } | {"message_count": len(session["messages"])}

    def request(self, method, path, *, json=None, content=None, headers=None, params=None):
        self.calls.append((method, path, deepcopy(json), deepcopy(params)))
        if self.failure and (method, path) == self.failure[:2]:
            raise APIError(*self.failure[2:])
        if (method, path) == ("GET", "/api/chat/sessions/"):
            return [self._summary(session) for session in reversed(self.sessions)]
        if (method, path) == ("POST", "/api/chat/sessions/"):
            session = _session(json["locale"], f"session-{len(self.sessions) + 1}")
            self.sessions.append(session)
            return deepcopy(session)
        if method == "GET" and re.fullmatch(r"/api/chat/sessions/[^/]+", path):
            session_id = path.rsplit("/", 1)[-1]
            return deepcopy(
                next(item for item in self.sessions if item["session_id"] == session_id)
            )
        if method == "DELETE" and re.fullmatch(r"/api/chat/sessions/[^/]+", path):
            session_id = path.rsplit("/", 1)[-1]
            self.sessions = [item for item in self.sessions if item["session_id"] != session_id]
            self.turn = None
            return {"session_id": session_id, "deleted": True}
        if (method, path) == ("GET", "/api/me/problem-statuses/"):
            value = deepcopy(self.private_status)
            value["context_epoch"] = self.epoch
            return value
        match = re.fullmatch(r"/api/chat/sessions/([^/]+)/turns/", path)
        if match and method == "GET":
            return [] if self.turn is None else [deepcopy(self.turn)]
        if match and method == "POST":
            session_id = match.group(1)
            self.turn = _turn(session_id)
            for session in self.sessions:
                if session["session_id"] == session_id:
                    session["messages"].append(
                        {
                            "message_id": "user-message-1",
                            "role": "user",
                            "content": json["message"],
                            "created_at": "2026-09-09T00:00:01Z",
                            "turn_id": self.turn["turn_id"],
                        }
                    )
                    session["revision"] += 1
                    break
            return deepcopy(self.turn)
        match = re.fullmatch(r"/api/chat/sessions/([^/]+)/turns/([^/]+)", path)
        if match and method == "GET":
            return deepcopy(self.turn)
        if match and method == "DELETE":
            self.turn = {**self.turn, "status": "cancelled"}
            return deepcopy(self.turn)
        raise AssertionError((method, path, json))


def _component(client, locale, focus=None):
    from frontend.chat import chat_assistant

    chat_assistant(client=client, locale=locale, focus=focus)


def _app(client, locale="zh-CN", focus=None):
    return AppTest.from_function(_component, args=(client, locale, focus), default_timeout=6).run()


def _dynamic_locale_component(client):
    import streamlit as st

    from frontend.chat import chat_assistant

    chat_assistant(client=client, locale=st.session_state.get("_test_locale", "zh-CN"))


def test_send_turn_uses_exact_routes_real_epoch_and_opaque_key_only():
    fake = FakeChatAPI()
    sent = send_turn(fake, "session-1", "  请解释这个错误  ")

    assert sent["status"] == "pending"
    assert [call[:2] for call in fake.calls] == [
        ("GET", "/api/me/problem-statuses/"),
        ("POST", "/api/chat/sessions/session-1/turns/"),
    ]
    payload = fake.calls[-1][2]
    assert payload == {
        "message": "请解释这个错误",
        "expected_context_epoch": EPOCH,
        "idempotency_key": payload["idempotency_key"],
    }
    assert re.fullmatch(r"chat-ui-[0-9a-f]{32}", payload["idempotency_key"])
    rendered = repr(payload)
    for forbidden in (
        "another-user",
        "user_id",
        "role",
        "source_code",
        "SECRET_OTHER_USER_CODE",
        "SECRET_HIDDEN_CASE",
        "testcases",
    ):
        assert forbidden not in rendered


def test_workspace_focus_is_current_page_only_and_never_projects_identity():
    state = {
        "_user": {"user_id": "never-send-me", "role": "admin"},
        "_problem_mode": "detail",
        "_problem_id": "DEMO-001",
        "code_DEMO-001": "print(input())\n",
        "_submission_id": "submission-owned-by-server-check",
        "_submission_submission-owned-by-server-check": {"code": "stale secret"},
    }
    assert workspace_focus("题库", state) == {
        "page": "problems",
        "problem_id": "DEMO-001",
        "draft_code": "print(input())\n",
    }
    assert workspace_focus("提交记录", state) == {
        "page": "submissions",
        "selected_submission_id": "submission-owned-by-server-check",
    }
    assert workspace_focus("成绩总览", state) == {"page": "analytics"}
    assert workspace_focus("智能命题", state) == {"page": "authoring"}
    assert workspace_focus("账户", state) == {"page": "account"}
    assert workspace_focus("管理工作区", state) == {"page": "admin"}
    assert workspace_focus("unknown", state) is None
    assert workspace_focus("题库", {**state, "_problem_mode": "list"}) == {"page": "problems"}
    rendered = repr([workspace_focus(page, state) for page in ("题库", "提交记录")])
    assert "never-send-me" not in rendered and "stale secret" not in rendered


def test_focus_contract_rejects_extra_fields_or_unbound_and_oversized_drafts():
    with pytest.raises(ChatUIContractError):
        programming_focus({"page": "problems", "user_id": "do-not-trust"})
    with pytest.raises(ChatUIContractError):
        programming_focus({"page": "problems", "draft_code": "print(1)"})
    with pytest.raises(ChatUIContractError) as caught:
        programming_focus({"page": "problems", "problem_id": "P1", "draft_code": "汉" * 22_000})
    assert caught.value.status == 413


def test_component_forwards_exact_problem_focus_without_cross_page_state():
    fake = FakeChatAPI()
    fake.sessions.append(_session())
    focus = {
        "page": "problems",
        "problem_id": "DEMO-001",
        "draft_code": "value = int(input())\nprint(value * 2)\n",
    }
    at = _app(fake, focus=focus)
    at.button(key="chat_launcher_button").click().run()
    next(item for item in at.text_area if item.key.startswith("chat_draft_")).set_value(
        "帮我检查边界情况"
    )
    next(item for item in at.button if item.label == "发送").click().run()

    assert not at.exception
    payload = next(
        call[2]
        for call in fake.calls
        if call[:2] == ("POST", "/api/chat/sessions/session-1/turns/")
    )
    assert payload["focus"] == focus
    assert set(payload) == {
        "message",
        "expected_context_epoch",
        "idempotency_key",
        "focus",
    }


@pytest.mark.parametrize("status", [0, 500, 502, 503])
def test_ambiguous_send_retry_reuses_epoch_and_idempotency_key(status):
    fake = FakeChatAPI()
    session_id = f"ambiguous-{status}"
    path = f"/api/chat/sessions/{session_id}/turns/"
    fake.failure = ("POST", path, status, "synthetic ambiguous response")
    with pytest.raises(APIError):
        send_turn(
            fake,
            session_id,
            "保留这条消息",
            focus={"page": "problems", "problem_id": "P1", "draft_code": "first"},
        )
    first_payload = deepcopy(fake.calls[-1][2])

    fake.epoch = OTHER_EPOCH
    with pytest.raises(APIError):
        send_turn(
            fake,
            session_id,
            "保留这条消息",
            focus={"page": "submissions", "selected_submission_id": "changed"},
        )
    second_payload = fake.calls[-1][2]

    assert first_payload == second_payload
    assert first_payload["expected_context_epoch"] == EPOCH
    assert first_payload["focus"] == {
        "page": "problems",
        "problem_id": "P1",
        "draft_code": "first",
    }
    assert sum(call[:2] == ("GET", "/api/me/problem-statuses/") for call in fake.calls) == 1


def test_multibyte_wire_limit_is_rejected_before_progress_request_and_shown_as_413():
    fake = FakeChatAPI()
    with pytest.raises(ChatUIContractError) as caught:
        send_turn(fake, "session-1", "汉" * 7_000)
    assert caught.value.status == 413 and fake.calls == []

    fake.sessions.append(_session())
    at = _app(fake)
    at.button(key="chat_launcher_button").click().run()
    calls_before = len(fake.calls)
    next(item for item in at.text_area if item.key.startswith("chat_draft_")).set_value(
        "汉" * 7_000
    )
    next(item for item in at.button if item.label == "发送").click().run()
    assert not at.exception
    assert len(fake.calls) == calls_before
    assert any("消息过长" in item.value for item in at.error)


def test_context_and_payload_contracts_fail_closed():
    with pytest.raises(ChatUIContractError):
        context_epoch({"schema_version": STATUS_SCHEMA, "context_epoch": "not-an-epoch"})
    with pytest.raises(ChatUIContractError):
        turn_payload("x", EPOCH, "bad\nkey")
    unsafe = _session()
    unsafe["messages"][0]["role"] = "system"
    with pytest.raises(ChatUIContractError):
        session_detail(unsafe)


@pytest.mark.parametrize(
    ("locale", "launcher", "intro", "new_label"),
    [
        ("zh-CN", "AI 编程助手", INTRODUCTION, "新建会话"),
        ("en", "AI coding assistant", INTRODUCTION_EN, "New chat"),
    ],
)
def test_drawer_creates_one_persistent_intro_and_has_bilingual_controls(
    locale, launcher, intro, new_label
):
    fake = FakeChatAPI()
    at = _app(fake, locale)
    assert not at.exception
    assert at.button(key="chat_launcher_button").label == launcher
    assert fake.calls == []

    at.button(key="chat_launcher_button").click().run()
    assert not at.exception
    avatar_markup = "\n".join(item.proto.body for item in at.get("html"))
    assert 'src="app/static/brand/ai-chat-avatar.png"' in avatar_markup
    assert ">AI<" not in avatar_markup
    assert at.button(key="chat_new_session").label == new_label
    assert at.button(key="chat_show_history")
    assert at.button(key="chat_toggle_fullscreen")
    assert at.button(key="chat_close")

    at.button(key="chat_new_session").click().run()
    assert not at.exception
    assert [item.value for item in at.markdown].count(intro) == 1
    assert len(fake.sessions) == 1
    assert fake.sessions[0]["messages"][0]["content"] == intro
    at.run()
    assert [item.value for item in at.markdown].count(intro) == 1
    assert len(fake.sessions) == 1
    assert any(
        call[:3] == ("POST", "/api/chat/sessions/", {"locale": locale}) for call in fake.calls
    )


def test_immediate_failure_keeps_selected_history_and_input():
    fake = FakeChatAPI()
    fake.sessions.append(_session())
    at = _app(fake)
    at.button(key="chat_launcher_button").click().run()
    assert not at.exception
    draft = next(item for item in at.text_area if item.key.startswith("chat_draft_"))
    draft.set_value("我的输入必须保留")
    fake.failure = ("POST", "/api/chat/sessions/session-1/turns/", 500, "private failure")
    next(item for item in at.button if item.label == "发送").click().run()

    assert not at.exception and at.error
    kept = next(item for item in at.text_area if item.key.startswith("chat_draft_"))
    assert kept.value == "我的输入必须保留"
    assert [item.value for item in at.markdown].count(INTRODUCTION) == 1
    assert at.session_state["_chat_selected_session"] == "session-1"
    assert not any("private failure" in item.value for item in at.error)


def test_pending_turn_shows_original_loading_and_real_stop_control():
    fake = FakeChatAPI()
    fake.sessions.append(_session())
    at = _app(fake)
    at.button(key="chat_launcher_button").click().run()
    draft = next(item for item in at.text_area if item.key.startswith("chat_draft_"))
    draft.set_value("如何判断循环不变量？")
    next(item for item in at.button if item.label == "发送").click().run()

    assert not at.exception
    loading = "\n".join(
        item.proto.body for item in at.get("html") if "oj-chat-loading" in item.proto.body
    )
    assert "正在定位关键问题" in loading
    assert "正在梳理可行思路" in loading
    assert "正在核对复杂度" in loading
    assert any(item.label == "停止回答" for item in at.button)
    assert any(item.value == "如何判断循环不变量？" for item in at.markdown)
    assert any(call[:2] == ("GET", "/api/chat/sessions/session-1") for call in fake.calls)
    assert (
        sum(call[:2] == ("POST", "/api/chat/sessions/session-1/turns/") for call in fake.calls) == 1
    )
    assert at.session_state["_chat_sessions"][0]["message_count"] == 2

    fake.turn = _turn(status="completed", partial="循环不变量在每次迭代前后都应成立。")
    fake.sessions[0]["messages"].append(
        {
            "message_id": "assistant-message-1",
            "role": "assistant",
            "content": fake.turn["result"],
            "created_at": "2026-09-09T00:00:02Z",
            "turn_id": "turn-1",
        }
    )
    fake.sessions[0]["revision"] += 1
    at.run()
    completed_draft = next(item for item in at.text_area if item.key.startswith("chat_draft_"))
    assert completed_draft.value == ""
    assert [item.value for item in at.markdown].count(fake.turn["result"]) == 1
    assert at.session_state["_chat_sessions"][0]["message_count"] == 3


def test_accepted_send_keeps_user_bubble_when_immediate_detail_refresh_fails():
    fake = FakeChatAPI()
    fake.sessions.append(_session())
    at = _app(fake)
    at.button(key="chat_launcher_button").click().run()
    draft = next(item for item in at.text_area if item.key.startswith("chat_draft_"))
    draft.set_value("这条已接受的消息必须立即出现")
    fake.failure = ("GET", "/api/chat/sessions/session-1", 503, "temporary")
    next(item for item in at.button if item.label == "发送").click().run()

    assert not at.exception
    assert [item.value for item in at.markdown].count("这条已接受的消息必须立即出现") == 1
    assert at.session_state["_chat_sessions"][0]["message_count"] == 2


def test_reopen_recovers_failed_partial_from_session_and_turn_routes():
    fake = FakeChatAPI()
    session = _session()
    session["messages"].append(
        {
            "message_id": "user-message-1",
            "role": "user",
            "content": "保留失败前的上下文",
            "created_at": "2026-09-09T00:00:01Z",
            "turn_id": "turn-1",
        }
    )
    session["revision"] = 2
    fake.sessions.append(session)
    fake.turn = _turn(status="failed", partial="先检查边界，再缩小状态范围。")

    at = _app(fake)
    at.button(key="chat_launcher_button").click().run()

    assert not at.exception
    rendered = [item.value for item in at.markdown]
    assert rendered.count("保留失败前的上下文") == 1
    assert rendered.count("先检查边界，再缩小状态范围。") == 1
    assert any("输入已保留" in item.value for item in at.error)
    assert ("GET", "/api/chat/sessions/session-1", None, None) in fake.calls
    assert ("GET", "/api/chat/sessions/session-1/turns/", None, None) in fake.calls
    recovered = next(item for item in at.text_area if item.key.startswith("chat_draft_"))
    assert recovered.value == "保留失败前的上下文"


def test_forbidden_poll_clears_authenticated_chat_state_and_stops_drawer():
    fake = FakeChatAPI()
    fake.sessions.append(_session())
    at = AppTest.from_function(_component, args=(fake, "zh-CN"), default_timeout=6)
    at.session_state["_user"] = {"user_id": "owner-1", "role": "user"}
    at.run()
    at.button(key="chat_launcher_button").click().run()
    draft = next(item for item in at.text_area if item.key.startswith("chat_draft_"))
    draft.set_value("触发活动回答")
    next(item for item in at.button if item.label == "发送").click().run()
    fake.failure = (
        "GET",
        "/api/chat/sessions/session-1/turns/turn-1",
        403,
        "account banned",
    )
    at.run()

    assert not at.exception
    assert "_user" not in at.session_state
    assert "_chat_drawer_open" not in at.session_state
    assert "_chat_session_cache" not in at.session_state


def test_missing_active_turn_becomes_terminal_and_stops_polling():
    fake = FakeChatAPI()
    fake.sessions.append(_session())
    at = _app(fake)
    at.button(key="chat_launcher_button").click().run()
    next(item for item in at.text_area if item.key.startswith("chat_draft_")).set_value(
        "任务丢失后保留输入"
    )
    next(item for item in at.button if item.label == "发送").click().run()
    detail_path = "/api/chat/sessions/session-1/turns/turn-1"
    calls_before_missing = sum(call[:2] == ("GET", detail_path) for call in fake.calls)
    fake.failure = ("GET", detail_path, 404, "missing")

    at.run()
    calls_after_terminal = sum(call[:2] == ("GET", detail_path) for call in fake.calls)
    at.run()

    assert not at.exception
    assert calls_after_terminal == calls_before_missing + 1
    assert sum(call[:2] == ("GET", detail_path) for call in fake.calls) == calls_after_terminal
    assert "session-1" not in at.session_state["_chat_turns"]
    assert not any(item.label == "停止回答" for item in at.button)
    assert len(at.error) == 1
    restored = next(item for item in at.text_area if item.key.startswith("chat_draft_"))
    assert restored.value == "任务丢失后保留输入"


def test_async_failure_reenables_preserved_draft_and_stops_active_ui():
    fake = FakeChatAPI()
    fake.sessions.append(_session())
    at = _app(fake)
    at.button(key="chat_launcher_button").click().run()
    draft = next(item for item in at.text_area if item.key.startswith("chat_draft_"))
    draft.set_value("失败后仍要保留")
    next(item for item in at.button if item.label == "发送").click().run()
    assert any(item.label == "停止回答" for item in at.button)

    fake.turn = _turn(status="failed", partial="已收到的部分回答")
    at.run()

    assert not at.exception
    restored = next(item for item in at.text_area if item.key.startswith("chat_draft_"))
    assert restored.value == "失败后仍要保留" and not restored.disabled
    assert not any(item.label == "停止回答" for item in at.button)
    assert any("输入已保留" in item.value for item in at.error)


def test_retry_restore_only_uses_the_latest_turn_not_an_older_failure():
    turns = [
        {"turn_id": "turn-old", "user_message_id": "user-old", "status": "failed"},
        {"turn_id": "turn-new", "user_message_id": "user-new", "status": "completed"},
    ]
    messages = [
        {"message_id": "user-old", "turn_id": "turn-old", "role": "user", "content": "old"},
        {"message_id": "user-new", "turn_id": "turn-new", "role": "user", "content": "new"},
    ]
    assert _retryable_input(turns, messages) is None

    turns[-1]["status"] = "failed"
    assert _retryable_input(turns, messages) == "new"


def test_history_fullscreen_and_close_controls_preserve_the_selected_session():
    fake = FakeChatAPI()
    fake.sessions.append(_session())
    at = _app(fake)
    at.button(key="chat_launcher_button").click().run()
    at.button(key="chat_show_history").click().run()
    assert not at.exception and at.session_state["_chat_drawer_view"] == "history"
    assert at.button(key="chat_history_back")

    at.button(key="chat_toggle_fullscreen").click().run()
    assert not at.exception and at.session_state["_chat_drawer_fullscreen"] is True
    assert at.session_state["_chat_selected_session"] == "session-1"
    at.button(key="chat_close").click().run()
    assert at.session_state["_chat_drawer_open"] is True
    assert "is-closing" in "\n".join(item.proto.body for item in at.get("html"))
    time.sleep(0.2)
    at.run()
    assert not at.exception and at.session_state["_chat_drawer_open"] is False
    assert at.button(key="chat_launcher_button")


def test_locale_switch_filters_histories_and_never_reuses_other_language_session():
    fake = FakeChatAPI()
    fake.sessions.extend(
        [
            _session("zh-CN", "session-zh"),
            _session("en", "session-en"),
        ]
    )
    at = AppTest.from_function(_dynamic_locale_component, args=(fake,), default_timeout=6)
    at.session_state["_test_locale"] = "zh-CN"
    at.run()
    at.button(key="chat_launcher_button").click().run()
    assert at.session_state["_chat_selected_session"] == "session-zh"
    assert [item["session_id"] for item in at.session_state["_chat_sessions"]] == ["session-zh"]

    at.session_state["_test_locale"] = "en"
    at.run()
    assert at.session_state["_chat_selected_session"] == "session-en"
    assert [item["session_id"] for item in at.session_state["_chat_sessions"]] == ["session-en"]
    rendered = " ".join(item.value for item in at.markdown)
    assert INTRODUCTION_EN in rendered
    assert INTRODUCTION not in rendered


def test_history_can_confirm_delete_and_then_create_below_the_retention_cap():
    fake = FakeChatAPI()
    fake.sessions.extend([_session(session_id="session-1"), _session(session_id="session-2")])
    at = _app(fake)
    at.button(key="chat_launcher_button").click().run()
    at.button(key="chat_show_history").click().run()

    suffix = _widget_suffix("session-1")
    at.button(key=f"chat_delete_{suffix}").click().run()
    assert any("删除这段会话" in item.value for item in at.warning)
    at.button(key=f"chat_delete_yes_{suffix}").click().run()

    assert not at.exception
    assert [item["session_id"] for item in fake.sessions] == ["session-2"]
    assert ("DELETE", "/api/chat/sessions/session-1", None, None) in fake.calls
    assert "session-1" not in at.session_state["_chat_session_cache"]


def test_copy_and_hooks_are_strict_and_do_not_claim_direct_code_changes():
    assert set(STYLE_HOOKS) == {
        "launcher",
        "drawer",
        "drawer_fullscreen",
        "toolbar",
        "history",
        "conversation",
        "messages",
        "composer",
        "loading",
    }
    assert set(chat_copy("zh-CN")) == set(chat_copy("en"))
    chinese = " ".join(chat_copy("zh-CN").values())
    english = " ".join(chat_copy("en").values())
    assert "直接修改" not in chinese and "直接改代码" not in chinese
    assert re.search(r"[\u4e00-\u9fff]", english) is None
    assert (
        "edit your files" not in english.lower()
        and "modify your code directly" not in english.lower()
    )


def test_pathhub_drawer_loading_and_responsive_css_contract_is_complete():
    import frontend.chat as chat_module
    from frontend.styles import CSS

    for selector in (
        ".st-key-chat_launcher",
        ".oj-chat-drawer-marker",
        ".st-key-chat_drawer_fullscreen",
        ".st-key-chat_history_panel",
        ".st-key-chat_messages",
        ".st-key-chat_composer",
        ".oj-chat-avatar-slot img",
        ".oj-chat-loading-spinner",
        ".oj-chat-loading-phrase:nth-child(3)",
        ".oj-chat-stream-cursor",
    ):
        assert selector in CSS
    assert "rgba(7,18,13,.30)" in CSS
    assert "width:min(480px,100vw)" in CSS
    assert "width:100vw" in CSS and "height:100dvh" in CSS
    assert "position:fixed!important;inset:0!important;width:100vw!important" in CSS
    assert "700ms" in CSS and "2.1s" in CSS and "animation-delay:1.4s" in CSS
    assert "200ms" in CSS and "@starting-style" in CSS
    assert "transition:width 200ms" in CSS and "oj-chat-exit 200ms" in CSS
    assert "@media (max-width:640px)" in CSS
    reduced = CSS.split("@media (prefers-reduced-motion:reduce)", 1)[1]
    assert "oj-chat-loading-spinner" in reduced and "animation:none" in reduced
    assert '[data-testid="stDialog"]:has(.oj-chat-drawer-marker)' in reduced
    assert "linear-gradient" not in CSS
    assert 'background:url("app/static/brand/ai-chat-avatar.png")' in CSS
    assert ":material/smart_toy:" not in inspect.getsource(chat_module)


def test_escape_and_backdrop_dismissal_use_the_same_exit_transition():
    import inspect
    import frontend.chat as chat_module

    source = inspect.getsource(chat_module.chat_assistant)
    assert "on_dismiss=_begin_close_drawer" in source
    assert "on_dismiss=_close_drawer" not in source
