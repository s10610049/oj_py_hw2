"""Owner-scoped programming assistant drawer for the authenticated workspace.

The browser sends a user message, a freshly read personal progress epoch, an
idempotency key and, when available, a small current-workspace focus selector.
The API route remains solely responsible for authenticating and safely
projecting the referenced problem or submission before calling the provider.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import html
import re
import time
import uuid

import streamlit as st

from frontend.client import APIError, resource
from frontend.common import api, clear_session, user
from frontend.i18n import normalize_locale

SESSION_SCHEMA = "oj.programming-chat.session.v1"
TURN_SCHEMA = "oj.programming-chat.turn.v1"
STATUS_SCHEMA = "oj.problem-status.v1"
ACTIVE_STATUSES = frozenset({"pending", "running"})
TERMINAL_STATUSES = frozenset({"completed", "cancelled", "failed"})
ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
EPOCH_PATTERN = re.compile(r"[0-9a-f]{64}")
FOCUS_PAGES = frozenset({"problems", "submissions", "analytics", "authoring", "account", "admin"})
FOCUS_FIELDS = frozenset({"page", "problem_id", "draft_code", "selected_submission_id"})
FOCUS_PAGE_BY_NAVIGATION = {
    "题库": "problems",
    "提交记录": "submissions",
    "成绩总览": "analytics",
    "智能命题": "authoring",
    "账户": "account",
    "管理工作区": "admin",
}
MAX_FOCUS_IDENTIFIER_LENGTH = 80
MAX_DRAFT_CODE_BYTES = 64_000

# Stable Streamlit keys double as CSS hooks (``.st-key-<value>``).  The global
# stylesheet can position the launcher and turn the dialog into a right drawer
# without coupling itself to widget-generated class names.
STYLE_HOOKS = {
    "launcher": "chat_launcher",
    "drawer": "chat_drawer",
    "drawer_fullscreen": "chat_drawer_fullscreen",
    "toolbar": "chat_drawer_toolbar",
    "history": "chat_history_panel",
    "conversation": "chat_conversation_panel",
    "messages": "chat_messages",
    "composer": "chat_composer",
    "loading": "chat_loading",
}

OPEN_KEY = "_chat_drawer_open"
FULLSCREEN_KEY = "_chat_drawer_fullscreen"
VIEW_KEY = "_chat_drawer_view"
OWNER_KEY = "_chat_owner"
LOCALE_KEY = "_chat_locale"
SESSIONS_KEY = "_chat_sessions"
SESSIONS_LOADED_KEY = "_chat_sessions_loaded"
SELECTED_KEY = "_chat_selected_session"
SESSION_CACHE_KEY = "_chat_session_cache"
TURNS_KEY = "_chat_turns"
TURN_HISTORY_KEY = "_chat_turn_history"
ATTEMPTS_KEY = "_chat_send_attempts"
CLEAR_DRAFTS_KEY = "_chat_clear_drafts"
PRESERVED_INPUTS_KEY = "_chat_preserved_inputs"
DELETE_PENDING_KEY = "_chat_delete_pending"
CLOSING_KEY = "_chat_drawer_closing_at"
AI_AVATAR_FILE = "static/brand/ai-chat-avatar.png"

_COPY = {
    "zh-CN": {
        "launcher": "AI 编程助手",
        "title": "AI 编程助手",
        "subtitle": "讲清思路，定位问题，逐步推进。",
        "history": "历史会话",
        "back": "返回对话",
        "new": "新建会话",
        "refresh": "刷新历史",
        "delete_session": "删除",
        "delete_confirm": "删除这段会话及其历史？正在生成的回答也会停止。",
        "delete_yes": "确认删除",
        "delete_no": "保留会话",
        "close": "关闭",
        "fullscreen": "全屏",
        "restore": "缩回",
        "empty": "还没有会话。新建后，助手会先简要介绍可提供的帮助。",
        "message_count": "{count} 条消息",
        "input": "描述题意、报错或卡住的步骤",
        "send": "发送",
        "sending": "正在发送",
        "stop": "停止回答",
        "loading_1": "正在定位关键问题",
        "loading_2": "正在梳理可行思路",
        "loading_3": "正在核对复杂度",
        "cancelled": "回答已停止；已收到的内容仍保留。",
        "failed": "本轮回答失败，输入已保留，可以直接重试。",
        "retryable_failed": "本轮回答失败，输入已保留，请重试。",
        "input_required": "请输入要讨论的问题。",
        "connection": "暂时无法连接编程助手，输入和历史已保留。",
        "bad_request": "消息无法发送，请检查内容；输入和历史已保留。",
        "permission": "登录状态或权限已失效。",
        "not_found": "会话已不可用；已加载的历史仍保留。",
        "conflict": "学习进度或会话已变化，请重试；输入已保留。",
        "too_large": "消息过长，请精简后重试；输入已保留。",
        "rate_limit": "发送过于频繁，请稍后重试；输入已保留。",
        "server": "编程助手暂时不可用，输入和历史已保留。",
        "response": "服务响应无法验证，输入和历史已保留。",
        "generic": "操作失败，输入和历史已保留。",
    },
    "en": {
        "launcher": "AI coding assistant",
        "title": "AI coding assistant",
        "subtitle": "Clarify the idea, locate the issue, and move forward step by step.",
        "history": "Chat history",
        "back": "Back to chat",
        "new": "New chat",
        "refresh": "Refresh history",
        "delete_session": "Delete",
        "delete_confirm": "Delete this chat and its history? Any active response will stop.",
        "delete_yes": "Delete chat",
        "delete_no": "Keep chat",
        "close": "Close",
        "fullscreen": "Full screen",
        "restore": "Exit full screen",
        "empty": (
            "No chats yet. Start one and the assistant will briefly introduce how it can help."
        ),
        "message_count": "{count} messages",
        "input": "Describe the problem, error, or step where you are stuck",
        "send": "Send",
        "sending": "Sending",
        "stop": "Stop response",
        "loading_1": "Locating the key issue",
        "loading_2": "Structuring a workable approach",
        "loading_3": "Checking the complexity",
        "cancelled": "The response was stopped. Received content is still available.",
        "failed": "This response failed. Your input is preserved and ready to retry.",
        "retryable_failed": "This response failed. Your input is preserved; please retry.",
        "input_required": "Enter a programming question.",
        "connection": "The assistant is unreachable. Your input and history are preserved.",
        "bad_request": "The message could not be sent. Check it and retry; nothing was lost.",
        "permission": "Your session or permission is no longer valid.",
        "not_found": "This chat is unavailable. Previously loaded history is preserved.",
        "conflict": "Your learning context or chat changed. Retry; your input is preserved.",
        "too_large": "The message is too long. Shorten it and retry; your input is preserved.",
        "rate_limit": "Messages are being sent too quickly. Wait and retry; nothing was lost.",
        "server": "The assistant is temporarily unavailable. Your input and history remain.",
        "response": "The service response could not be verified. Your work is preserved.",
        "generic": "The operation failed. Your input and history are preserved.",
    },
}


class ChatUIContractError(ValueError):
    """The service returned a payload that is unsafe to render or act on."""

    def __init__(self, message, *, status=502):
        self.status = status
        super().__init__(message)


def chat_copy(locale=None):
    """Return the complete copy catalog for exactly one supported locale."""

    return _COPY[normalize_locale(locale)]


def _contract_error():
    return APIError(502, "Chat response did not match the expected contract")


def _identifier(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ChatUIContractError(f"invalid {field}")
    if any(ord(character) < 32 for character in value):
        raise ChatUIContractError(f"invalid {field}")
    return value.strip()


def context_epoch(payload):
    """Project a personal status response to its only outbound chat field."""

    if not isinstance(payload, dict) or payload.get("schema_version") != STATUS_SCHEMA:
        raise ChatUIContractError("invalid personal status schema")
    epoch = payload.get("context_epoch")
    if not isinstance(epoch, str) or EPOCH_PATTERN.fullmatch(epoch) is None:
        raise ChatUIContractError("invalid personal context epoch")
    return epoch


def new_idempotency_key():
    """Create one opaque key for one logical send attempt."""

    return "chat-ui-" + uuid.uuid4().hex


def _normalized_message(message):
    if not isinstance(message, str) or not message.strip():
        raise ChatUIContractError("invalid message", status=400)
    normalized = message.strip()
    try:
        encoded = normalized.encode("utf-8")
    except UnicodeError as error:
        raise ChatUIContractError("invalid message", status=400) from error
    if len(encoded) > 20_000:
        raise ChatUIContractError("message too large", status=413)
    return normalized


def programming_focus(value):
    """Validate and canonically order one non-authoritative UI focus selector."""

    if value is None:
        return None
    if not isinstance(value, Mapping) or not set(value).issubset(FOCUS_FIELDS):
        raise ChatUIContractError("invalid chat focus", status=400)
    page = value.get("page")
    if page not in FOCUS_PAGES:
        raise ChatUIContractError("invalid chat focus page", status=400)
    result = {"page": page}
    for field in ("problem_id", "selected_submission_id"):
        if field not in value:
            continue
        identifier = _identifier(value[field], field)
        if len(identifier) > MAX_FOCUS_IDENTIFIER_LENGTH:
            raise ChatUIContractError("invalid chat focus resource", status=400)
        result[field] = identifier
    if "draft_code" in value:
        draft = value["draft_code"]
        if not isinstance(draft, str) or "problem_id" not in result:
            raise ChatUIContractError("invalid chat draft focus", status=400)
        try:
            size = len(draft.encode("utf-8"))
        except UnicodeError as error:
            raise ChatUIContractError("invalid chat draft focus", status=400) from error
        if size > MAX_DRAFT_CODE_BYTES:
            raise ChatUIContractError("chat draft focus too large", status=413)
        result["draft_code"] = draft
    return result


def workspace_focus(navigation, state):
    """Project only the resources that are visibly selected on the current page."""

    page = FOCUS_PAGE_BY_NAVIGATION.get(navigation)
    if page is None:
        return None
    focus = {"page": page}
    if page == "problems" and state.get("_problem_mode") in {"detail", "edit"}:
        problem_id = state.get("_problem_id")
        if problem_id is not None:
            focus["problem_id"] = problem_id
            draft_key = f"code_{problem_id}"
            if draft_key in state:
                focus["draft_code"] = state[draft_key]
    elif page == "submissions":
        submission_id = state.get("_submission_id")
        if submission_id is not None:
            focus["selected_submission_id"] = submission_id
    # Validation is deliberately deferred until Send. A very large editor
    # draft must not make the surrounding problem page or closed launcher
    # unusable; the composer can surface the bounded 413 error in place.
    return focus


def turn_payload(message, epoch, idempotency_key, focus=None):
    """Build the bounded request accepted by the chat turn route."""

    normalized = _normalized_message(message)
    if not isinstance(epoch, str) or EPOCH_PATTERN.fullmatch(epoch) is None:
        raise ChatUIContractError("invalid personal context epoch")
    key = _identifier(idempotency_key, "idempotency key")
    payload = {
        "message": normalized,
        "expected_context_epoch": epoch,
        "idempotency_key": key,
    }
    selected_focus = programming_focus(focus)
    if selected_focus is not None:
        payload["focus"] = selected_focus
    return payload


def _message(payload):
    if not isinstance(payload, dict):
        raise ChatUIContractError("invalid chat message")
    role = payload.get("role")
    content = payload.get("content")
    if role not in {"assistant", "user"} or not isinstance(content, str):
        raise ChatUIContractError("invalid chat message")
    return {
        "message_id": _identifier(payload.get("message_id"), "message id"),
        "role": role,
        "content": content,
        "created_at": (
            payload.get("created_at") if isinstance(payload.get("created_at"), str) else ""
        ),
        "turn_id": payload.get("turn_id") if isinstance(payload.get("turn_id"), str) else None,
    }


def session_detail(payload, expected_id=None):
    """Validate and reduce a session detail before keeping it in browser state."""

    if not isinstance(payload, dict) or payload.get("schema_version") != SESSION_SCHEMA:
        raise ChatUIContractError("invalid chat session schema")
    session_id = _identifier(payload.get("session_id"), "session id")
    if expected_id is not None and session_id != expected_id:
        raise ChatUIContractError("chat session identity changed")
    locale = payload.get("locale")
    title = payload.get("title")
    messages = payload.get("messages")
    revision = payload.get("revision")
    if locale not in {"zh-CN", "en"} or not isinstance(title, str):
        raise ChatUIContractError("invalid chat session metadata")
    if not isinstance(messages, list) or type(revision) is not int or revision < 1:
        raise ChatUIContractError("invalid chat session history")
    return {
        "schema_version": SESSION_SCHEMA,
        "session_id": session_id,
        "title": title,
        "locale": locale,
        "revision": revision,
        "created_at": (
            payload.get("created_at") if isinstance(payload.get("created_at"), str) else ""
        ),
        "updated_at": (
            payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else ""
        ),
        "last_context_epoch": payload.get("last_context_epoch"),
        "messages": [_message(item) for item in messages],
    }


def session_summaries(payload):
    """Validate the ordered, owner-filtered session list."""

    if not isinstance(payload, list):
        raise ChatUIContractError("invalid chat session list")
    result = []
    seen = set()
    for item in payload:
        if not isinstance(item, dict) or item.get("schema_version") != SESSION_SCHEMA:
            raise ChatUIContractError("invalid chat session summary")
        session_id = _identifier(item.get("session_id"), "session id")
        count = item.get("message_count")
        if session_id in seen or type(count) is not int or count < 0:
            raise ChatUIContractError("invalid chat session summary")
        if item.get("locale") not in {"zh-CN", "en"} or not isinstance(item.get("title"), str):
            raise ChatUIContractError("invalid chat session summary")
        seen.add(session_id)
        result.append(
            {
                "schema_version": SESSION_SCHEMA,
                "session_id": session_id,
                "title": item["title"],
                "locale": item["locale"],
                "updated_at": item.get("updated_at", ""),
                "message_count": count,
            }
        )
    return result


def turn_detail(payload, expected_session=None):
    """Validate and reduce a turn used for polling, cancellation, or recovery."""

    if not isinstance(payload, dict) or payload.get("schema_version") != TURN_SCHEMA:
        raise ChatUIContractError("invalid chat turn schema")
    turn_id = _identifier(payload.get("turn_id"), "turn id")
    session_id = _identifier(payload.get("session_id"), "session id")
    status = payload.get("status")
    if expected_session is not None and session_id != expected_session:
        raise ChatUIContractError("chat turn belongs to another session")
    if status not in ALL_STATUSES:
        raise ChatUIContractError("invalid chat turn status")
    partial = payload.get("partial")
    result = payload.get("result")
    if not isinstance(partial, str) or (result is not None and not isinstance(result, str)):
        raise ChatUIContractError("invalid chat turn output")
    retryable = payload.get("retryable")
    if retryable is not None and not isinstance(retryable, bool):
        raise ChatUIContractError("invalid chat turn retry flag")
    return {
        "schema_version": TURN_SCHEMA,
        "turn_id": turn_id,
        "session_id": session_id,
        "user_message_id": _identifier(payload.get("user_message_id"), "user message id"),
        "expected_context_epoch": context_epoch(
            {
                "schema_version": STATUS_SCHEMA,
                "context_epoch": payload.get("expected_context_epoch"),
            }
        ),
        "status": status,
        "progress": payload.get("progress") if isinstance(payload.get("progress"), str) else "",
        "partial": partial,
        "result": result,
        "error_code": (
            payload.get("error_code") if isinstance(payload.get("error_code"), str) else None
        ),
        "retryable": retryable,
        "created_at": (
            payload.get("created_at") if isinstance(payload.get("created_at"), str) else ""
        ),
    }


def turn_history(payload, expected_session):
    """Validate the ordered turn list used to recover partial terminal output."""

    if not isinstance(payload, list):
        raise ChatUIContractError("invalid chat turn list")
    result = [turn_detail(item, expected_session=expected_session) for item in payload]
    identifiers = [item["turn_id"] for item in result]
    if len(identifiers) != len(set(identifiers)):
        raise ChatUIContractError("duplicate chat turn")
    return result


def _client(value=None):
    return value or api()


def _state_mapping(key):
    value = st.session_state.setdefault(key, {})
    if not isinstance(value, dict):
        value = {}
        st.session_state[key] = value
    return value


def _widget_suffix(value):
    return sha256(str(value).encode("utf-8")).hexdigest()[:14]


def _show_error(error, copy):
    if error.status in {401, 403}:
        clear_session(copy["permission"])
        st.rerun(scope="app")
    labels = {
        0: "connection",
        400: "bad_request",
        403: "permission",
        404: "not_found",
        409: "conflict",
        413: "too_large",
        429: "rate_limit",
        500: "server",
        502: "response",
        503: "server",
    }
    st.error(copy[labels.get(error.status, "generic")])


def _request(client, method, path, *, payload=None):
    try:
        return client.request(method, path, json=payload)
    except APIError:
        raise
    except (ChatUIContractError, KeyError, TypeError, ValueError):
        raise _contract_error() from None


def _load_sessions(client, locale=None):
    try:
        sessions = session_summaries(_request(client, "GET", "/api/chat/sessions/"))
    except ChatUIContractError:
        raise _contract_error() from None
    selected_locale = normalize_locale(
        locale if locale is not None else st.session_state.get("_locale", "zh-CN")
    )
    sessions = [item for item in sessions if item["locale"] == selected_locale]
    st.session_state[SESSIONS_KEY] = sessions
    st.session_state[SESSIONS_LOADED_KEY] = True
    selected = st.session_state.get(SELECTED_KEY)
    identifiers = {item["session_id"] for item in sessions}
    if selected not in identifiers:
        st.session_state[SELECTED_KEY] = sessions[0]["session_id"] if sessions else None
    return sessions


def _sync_session_summary(session):
    """Keep history metadata aligned with the latest canonical/detail state."""

    summary = {
        "schema_version": SESSION_SCHEMA,
        "session_id": session["session_id"],
        "title": session["title"],
        "locale": session["locale"],
        "updated_at": session["updated_at"],
        "message_count": len(session["messages"]),
    }
    previous = st.session_state.get(SESSIONS_KEY, [])
    items = [
        summary,
        *[
            item
            for item in previous
            if isinstance(item, dict) and item.get("session_id") != session["session_id"]
        ],
    ]
    items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    st.session_state[SESSIONS_KEY] = items
    st.session_state[SESSIONS_LOADED_KEY] = True


def _load_session(client, session_id):
    try:
        session = session_detail(
            _request(client, "GET", f"/api/chat/sessions/{resource(session_id)}"),
            expected_id=session_id,
        )
    except ChatUIContractError:
        raise _contract_error() from None
    _state_mapping(SESSION_CACHE_KEY)[session_id] = session
    _sync_session_summary(session)
    _restore_retry_input(session_id, _state_mapping(TURN_HISTORY_KEY).get(session_id, []))
    return session


def _load_turn_history(client, session_id):
    try:
        turns = turn_history(
            _request(
                client,
                "GET",
                f"/api/chat/sessions/{resource(session_id)}/turns/",
            ),
            expected_session=session_id,
        )
    except ChatUIContractError:
        raise _contract_error() from None
    _state_mapping(TURN_HISTORY_KEY)[session_id] = turns
    active = [item for item in turns if item["status"] in ACTIVE_STATUSES]
    if active:
        _state_mapping(TURNS_KEY)[session_id] = active[-1]
    else:
        _state_mapping(TURNS_KEY).pop(session_id, None)
    _restore_retry_input(session_id, turns)
    return turns


def _restore_retry_input(session_id, turns):
    """Recover a failed/cancelled turn's input from its persisted user message."""

    if not isinstance(turns, list):
        return
    session = _state_mapping(SESSION_CACHE_KEY).get(session_id)
    if not isinstance(session, dict):
        return
    messages = session.get("messages")
    if not isinstance(messages, list):
        return
    preserved = _state_mapping(PRESERVED_INPUTS_KEY)
    preserved.pop(session_id, None)
    recovered = _retryable_input(turns, messages)
    if recovered is not None:
        preserved[session_id] = recovered


def _retryable_input(turns, messages):
    """Return only the newest failed/cancelled input from ordered history."""

    if not isinstance(turns, list) or not isinstance(messages, list) or not turns:
        return None
    # The server returns turns in creation order.  A failed historical turn must
    # not repopulate the composer after a newer retry has completed.
    turn = turns[-1]
    if not isinstance(turn, dict) or turn.get("status") not in {"failed", "cancelled"}:
        return None
    for message in reversed(messages):
        if (
            isinstance(message, dict)
            and message.get("role") == "user"
            and (
                message.get("message_id") == turn.get("user_message_id")
                or message.get("turn_id") == turn.get("turn_id")
            )
            and isinstance(message.get("content"), str)
            and message["content"].strip()
        ):
            return message["content"]
    return None


def _create_session(client, locale):
    try:
        session = session_detail(
            _request(client, "POST", "/api/chat/sessions/", payload={"locale": locale})
        )
    except ChatUIContractError:
        raise _contract_error() from None
    session_id = session["session_id"]
    _state_mapping(SESSION_CACHE_KEY)[session_id] = session
    _state_mapping(TURN_HISTORY_KEY)[session_id] = []
    _sync_session_summary(session)
    st.session_state[SELECTED_KEY] = session_id
    st.session_state[VIEW_KEY] = "chat"
    return session


def _base_revision(session_id):
    cached = _state_mapping(SESSION_CACHE_KEY).get(session_id)
    if not isinstance(cached, dict):
        return None
    revision = cached.get("revision")
    return revision if type(revision) is int else None


def _attempt(client, session_id, message, focus=None):
    attempts = _state_mapping(ATTEMPTS_KEY)
    existing = attempts.get(session_id)
    if isinstance(existing, dict) and existing.get("message") == message:
        return existing
    selected_focus = programming_focus(focus)
    snapshot = _request(client, "GET", "/api/me/problem-statuses/")
    try:
        epoch = context_epoch(snapshot)
    except ChatUIContractError:
        raise _contract_error() from None
    attempt = {
        "message": message,
        "expected_context_epoch": epoch,
        "idempotency_key": new_idempotency_key(),
        "base_revision": _base_revision(session_id),
        "focus": selected_focus,
    }
    attempts[session_id] = attempt
    return attempt


def send_turn(client, session_id, message, focus=None):
    """Send one logical turn with only a bounded, server-verified focus selector."""

    session_id = _identifier(session_id, "session id")
    # Validate the UTF-8 wire limit before reading progress. Invalid local
    # input must not make even a read-only API request.
    normalized = _normalized_message(message)
    attempt = _attempt(client, session_id, normalized, focus)
    payload = turn_payload(
        normalized,
        attempt["expected_context_epoch"],
        attempt["idempotency_key"],
        attempt["focus"],
    )
    try:
        raw = _request(
            client,
            "POST",
            f"/api/chat/sessions/{resource(session_id)}/turns/",
            payload=payload,
        )
        turn = turn_detail(raw, expected_session=session_id)
    except APIError as error:
        # A server-confirmed conflict consumed no new turn for the requested
        # epoch. Rotate both epoch and key on the next explicit retry. For an
        # ambiguous transport/response failure, retain both so retry is idempotent.
        if error.status != 0 and error.status < 500:
            _state_mapping(ATTEMPTS_KEY).pop(session_id, None)
        raise
    except ChatUIContractError:
        raise _contract_error() from None
    _state_mapping(ATTEMPTS_KEY).pop(session_id, None)
    _state_mapping(TURNS_KEY)[session_id] = turn
    _state_mapping(PRESERVED_INPUTS_KEY)[session_id] = normalized
    cached = _state_mapping(SESSION_CACHE_KEY).get(session_id)
    if isinstance(cached, dict) and not any(
        item.get("turn_id") == turn["turn_id"] and item.get("role") == "user"
        for item in cached.get("messages", [])
        if isinstance(item, dict)
    ):
        cached["messages"].append(
            {
                "message_id": turn["user_message_id"],
                "role": "user",
                "content": normalized,
                "created_at": turn["created_at"],
                "turn_id": turn["turn_id"],
            }
        )
        cached["revision"] += 1
        cached["updated_at"] = turn["created_at"] or cached.get("updated_at", "")
        cached["last_context_epoch"] = turn["expected_context_epoch"]
        _sync_session_summary(cached)
    history = _state_mapping(TURN_HISTORY_KEY).setdefault(session_id, [])
    if isinstance(history, list):
        history[:] = [item for item in history if item.get("turn_id") != turn["turn_id"]]
        history.append(turn)
    return turn


def _select_session(client, session_id, copy):
    previous = st.session_state.get(SELECTED_KEY)
    try:
        _load_session(client, session_id)
        _load_turn_history(client, session_id)
    except APIError as error:
        st.session_state[SELECTED_KEY] = previous
        _show_error(error, copy)
        return
    st.session_state[SELECTED_KEY] = session_id
    st.session_state[VIEW_KEY] = "chat"
    st.rerun(scope="app")


def _new_session(client, locale, copy):
    try:
        _create_session(client, locale)
    except APIError as error:
        _show_error(error, copy)
        return
    st.rerun(scope="app")


def _refresh_history(client, locale, copy):
    previous = st.session_state.get(SESSIONS_KEY, [])
    try:
        _load_sessions(client, locale)
    except APIError as error:
        st.session_state[SESSIONS_KEY] = previous
        _show_error(error, copy)


def _delete_session(client, session_id, copy):
    try:
        _request(client, "DELETE", f"/api/chat/sessions/{resource(session_id)}")
    except APIError as error:
        _show_error(error, copy)
        return False
    for key in (
        SESSION_CACHE_KEY,
        TURNS_KEY,
        TURN_HISTORY_KEY,
        ATTEMPTS_KEY,
        CLEAR_DRAFTS_KEY,
        PRESERVED_INPUTS_KEY,
    ):
        _state_mapping(key).pop(session_id, None)
    st.session_state[SESSIONS_KEY] = [
        item
        for item in st.session_state.get(SESSIONS_KEY, [])
        if item.get("session_id") != session_id
    ]
    if st.session_state.get(SELECTED_KEY) == session_id:
        sessions = st.session_state.get(SESSIONS_KEY, [])
        st.session_state[SELECTED_KEY] = sessions[0]["session_id"] if sessions else None
    st.session_state.pop(f"chat_draft_{_widget_suffix(session_id)}", None)
    st.session_state[DELETE_PENDING_KEY] = None
    return True


def _avatar_slot(copy, variant):
    st.html(
        '<span class="oj-chat-avatar-slot oj-chat-avatar-'
        + html.escape(variant, quote=True)
        + '" role="img" aria-label="'
        + html.escape(copy["title"], quote=True)
        + '"><img src="app/static/brand/ai-chat-avatar.png" alt="" '
        + 'aria-hidden="true"></span>'
    )


def _render_history(client, locale, copy, *, compact):
    with st.container(key=STYLE_HOOKS["history"], height="stretch"):
        heading, refresh = st.columns([5, 1])
        heading.subheader(copy["history"])
        if refresh.button(
            copy["refresh"],
            key="chat_refresh_history",
            icon=":material/refresh:",
            type="tertiary",
            width="stretch",
        ):
            _refresh_history(client, locale, copy)
        if compact:
            with st.container(key="chat_history_back_control"):
                if st.button(
                    copy["back"],
                    key="chat_history_back",
                    icon=":material/arrow_back:",
                    type="tertiary",
                ):
                    st.session_state[VIEW_KEY] = "chat"
                    st.rerun(scope="app")
        sessions = st.session_state.get(SESSIONS_KEY, [])
        if not sessions:
            st.info(copy["empty"])
        selected = st.session_state.get(SELECTED_KEY)
        for item in sessions:
            session_id = item["session_id"]
            label = item["title"] or ("New chat" if locale == "en" else "新会话")
            with st.container(key=f"chat_history_item_{_widget_suffix(session_id)}"):
                st.caption(copy["message_count"].format(count=item["message_count"]))
                choose, remove = st.columns([4, 1.35], vertical_alignment="center")
                if choose.button(
                    label,
                    key=f"chat_select_{_widget_suffix(session_id)}",
                    icon=":material/chat_bubble:" if session_id == selected else None,
                    type="primary" if session_id == selected else "tertiary",
                    width="stretch",
                ):
                    _select_session(client, session_id, copy)
                if remove.button(
                    copy["delete_session"],
                    key=f"chat_delete_{_widget_suffix(session_id)}",
                    icon=":material/delete_outline:",
                    type="tertiary",
                    width="stretch",
                ):
                    st.session_state[DELETE_PENDING_KEY] = session_id
                    st.rerun(scope="app")
                if st.session_state.get(DELETE_PENDING_KEY) == session_id:
                    st.warning(copy["delete_confirm"])
                    confirm, keep = st.columns(2)
                    if confirm.button(
                        copy["delete_yes"],
                        key=f"chat_delete_yes_{_widget_suffix(session_id)}",
                        type="primary",
                        width="stretch",
                    ):
                        if _delete_session(client, session_id, copy):
                            st.rerun(scope="app")
                    if keep.button(
                        copy["delete_no"],
                        key=f"chat_delete_no_{_widget_suffix(session_id)}",
                        width="stretch",
                    ):
                        st.session_state[DELETE_PENDING_KEY] = None
                        st.rerun(scope="app")


def _render_recovered_turn(turn, copy):
    status = turn["status"]
    content = turn.get("result") or turn.get("partial") or ""
    with st.chat_message("assistant", avatar=AI_AVATAR_FILE):
        if content:
            st.markdown(content)
        if status == "failed":
            st.error(copy["retryable_failed"] if turn.get("retryable") else copy["failed"])
        elif status == "cancelled":
            st.info(copy["cancelled"])


def _render_messages(session, turn_records, copy):
    turn_by_id = {item["turn_id"]: item for item in turn_records}
    persisted_assistant_turns = {
        message["turn_id"]
        for message in session.get("messages", [])
        if message["role"] == "assistant" and message.get("turn_id")
    }
    with st.container(key=STYLE_HOOKS["messages"], height="stretch", autoscroll=True):
        for message in session.get("messages", []):
            role = message["role"]
            avatar = AI_AVATAR_FILE if role == "assistant" else ":material/person:"
            with st.chat_message(role, avatar=avatar):
                st.markdown(message["content"])
            turn_id = message.get("turn_id")
            recovered = turn_by_id.get(turn_id)
            if (
                role == "user"
                and recovered
                and turn_id not in persisted_assistant_turns
                and recovered["status"] in TERMINAL_STATUSES
            ):
                _render_recovered_turn(recovered, copy)


def _loading_markup(copy):
    phrases = "".join(
        '<span class="oj-chat-loading-phrase" data-phase="'
        + str(index)
        + '">'
        + html.escape(copy[f"loading_{index + 1}"])
        + "</span>"
        for index in range(3)
    )
    return (
        '<div class="oj-chat-loading" role="status" aria-live="polite">'
        '<span class="oj-chat-loading-spinner" aria-hidden="true"></span>'
        '<span class="oj-chat-loading-phrases">' + phrases + "</span></div>"
    )


def _render_turn_state(client, session_id, copy):
    turns = _state_mapping(TURNS_KEY)
    saved = turns.get(session_id)
    if not isinstance(saved, dict):
        return
    active = saved.get("status") in ACTIVE_STATUSES

    @st.fragment(run_every=0.7 if active else None)
    def panel():
        current = _state_mapping(TURNS_KEY).get(session_id, saved)
        if current.get("status") in ACTIVE_STATUSES:
            try:
                current = turn_detail(
                    _request(
                        client,
                        "GET",
                        f"/api/chat/sessions/{resource(session_id)}/turns/"
                        f"{resource(current['turn_id'])}",
                    ),
                    expected_session=session_id,
                )
                _state_mapping(TURNS_KEY)[session_id] = current
            except (APIError, ChatUIContractError) as error:
                if isinstance(error, APIError) and error.status == 404:
                    # A deterministic missing turn can never become active
                    # again.  Persist a local terminal projection and rebuild
                    # the fragment without its polling interval.
                    missing = dict(current)
                    missing.update(
                        status="failed",
                        retryable=False,
                        error="",
                        error_code="chat_turn_not_found",
                    )
                    history = _state_mapping(TURN_HISTORY_KEY).setdefault(session_id, [])
                    if isinstance(history, list):
                        history[:] = [
                            item
                            for item in history
                            if item.get("turn_id") != missing.get("turn_id")
                        ]
                        history.append(missing)
                        _restore_retry_input(session_id, history)
                    _state_mapping(TURNS_KEY).pop(session_id, None)
                    st.rerun(scope="app")
                _show_error(error if isinstance(error, APIError) else _contract_error(), copy)
                current = _state_mapping(TURNS_KEY).get(session_id, saved)
        status = current.get("status")
        partial = current.get("partial", "")
        if partial:
            with st.chat_message("assistant", avatar=AI_AVATAR_FILE):
                st.markdown(partial)
                if status in ACTIVE_STATUSES:
                    st.html('<span class="oj-chat-stream-cursor" aria-hidden="true"></span>')
        elif status in ACTIVE_STATUSES:
            with st.container(key=STYLE_HOOKS["loading"]):
                _avatar_slot(copy, "loading")
                st.html(_loading_markup(copy))
        if status in ACTIVE_STATUSES:
            if st.button(
                copy["stop"],
                key=f"chat_stop_{_widget_suffix(current['turn_id'])}",
                icon=":material/stop_circle:",
                type="tertiary",
            ):
                try:
                    stopped = turn_detail(
                        _request(
                            client,
                            "DELETE",
                            f"/api/chat/sessions/{resource(session_id)}/turns/"
                            f"{resource(current['turn_id'])}",
                        ),
                        expected_session=session_id,
                    )
                    _state_mapping(TURNS_KEY)[session_id] = stopped
                    try:
                        _load_session(client, session_id)
                        _load_turn_history(client, session_id)
                    except APIError:
                        pass
                    st.rerun(scope="app")
                except (APIError, ChatUIContractError) as error:
                    _show_error(error if isinstance(error, APIError) else _contract_error(), copy)
        elif status == "failed":
            st.error(copy["retryable_failed"] if current.get("retryable") else copy["failed"])
            if active:
                try:
                    _load_session(client, session_id)
                    _load_turn_history(client, session_id)
                except APIError:
                    pass
                st.rerun(scope="app")
        elif status == "cancelled":
            st.info(copy["cancelled"])
            if active:
                try:
                    _load_session(client, session_id)
                    _load_turn_history(client, session_id)
                except APIError:
                    pass
                st.rerun(scope="app")
        elif status == "completed":
            try:
                _load_session(client, session_id)
                _load_turn_history(client, session_id)
            except APIError as error:
                _show_error(error, copy)
                return
            _state_mapping(CLEAR_DRAFTS_KEY)[session_id] = True
            _state_mapping(PRESERVED_INPUTS_KEY).pop(session_id, None)
            _state_mapping(TURNS_KEY).pop(session_id, None)
            st.rerun(scope="app")

    panel()


def _render_composer(client, session_id, copy, focus):
    current = _state_mapping(TURNS_KEY).get(session_id, {})
    active = current.get("status") in ACTIVE_STATUSES
    suffix = _widget_suffix(session_id)
    draft_key = f"chat_draft_{suffix}"
    with st.container(key=STYLE_HOOKS["composer"]):
        with st.form(f"chat_form_{suffix}", border=False):
            message = st.text_area(
                copy["input"],
                key=draft_key,
                height=92,
                max_chars=20_000,
                disabled=active,
                label_visibility="collapsed",
                placeholder=copy["input"],
            )
            submitted = st.form_submit_button(
                copy["sending"] if active else copy["send"],
                icon=":material/send:",
                type="primary",
                disabled=active,
                width="stretch",
            )
        if not submitted:
            return
        if not isinstance(message, str) or not message.strip():
            st.error(copy["input_required"])
            return
        try:
            send_turn(client, session_id, message, focus=focus)
        except (APIError, ChatUIContractError) as error:
            _show_error(
                error if isinstance(error, APIError) else APIError(error.status, str(error)),
                copy,
            )
            return
        try:
            _load_session(client, session_id)
        except APIError as error:
            # The turn is already accepted. Keep polling it and retain the draft;
            # a transient history refresh failure must not trigger another POST.
            _show_error(error, copy)
        # Keep the widget value while the accepted turn is active. It is cleared
        # only after completion; immediate and asynchronous failures retain it.
        st.rerun(scope="app")


def _render_conversation(client, locale, copy, focus):
    with st.container(key=STYLE_HOOKS["conversation"], height="stretch"):
        session_id = st.session_state.get(SELECTED_KEY)
        if not session_id:
            _avatar_slot(copy, "empty")
            st.info(copy["empty"])
            if st.button(
                copy["new"],
                key="chat_empty_new",
                icon=":material/add_comment:",
                type="primary",
            ):
                _new_session(client, locale, copy)
            return
        clear_drafts = _state_mapping(CLEAR_DRAFTS_KEY)
        draft_key = f"chat_draft_{_widget_suffix(session_id)}"
        if clear_drafts.pop(session_id, False):
            st.session_state[draft_key] = ""
        elif not st.session_state.get(draft_key):
            preserved = _state_mapping(PRESERVED_INPUTS_KEY).get(session_id)
            if isinstance(preserved, str):
                st.session_state[draft_key] = preserved
        cache = _state_mapping(SESSION_CACHE_KEY)
        session = cache.get(session_id)
        if not isinstance(session, dict):
            try:
                session = _load_session(client, session_id)
            except APIError as error:
                _show_error(error, copy)
                return
        turn_records = _state_mapping(TURN_HISTORY_KEY).get(session_id, [])
        _render_messages(session, turn_records if isinstance(turn_records, list) else [], copy)
        _render_turn_state(client, session_id, copy)
        _render_composer(client, session_id, copy, focus)


def _close_drawer():
    st.session_state[OPEN_KEY] = False
    st.session_state[FULLSCREEN_KEY] = False
    st.session_state.pop(CLOSING_KEY, None)


def _begin_close_drawer():
    st.session_state[CLOSING_KEY] = time.monotonic()


def _render_toolbar(client, locale, copy):
    with st.container(key=STYLE_HOOKS["toolbar"], horizontal=True, wrap=True):
        _avatar_slot(copy, "header")
        st.caption(copy["subtitle"])
        if st.button(
            copy["history"],
            key="chat_show_history",
            icon=":material/history:",
            type="tertiary",
        ):
            st.session_state[VIEW_KEY] = "history"
            st.rerun(scope="app")
        if st.button(
            copy["new"],
            key="chat_new_session",
            icon=":material/add_comment:",
            type="tertiary",
        ):
            _new_session(client, locale, copy)
        fullscreen = bool(st.session_state.get(FULLSCREEN_KEY))
        if st.button(
            copy["restore"] if fullscreen else copy["fullscreen"],
            key="chat_toggle_fullscreen",
            icon=":material/close_fullscreen:" if fullscreen else ":material/open_in_full:",
            type="tertiary",
        ):
            st.session_state[FULLSCREEN_KEY] = not fullscreen
            st.rerun(scope="app")
        if st.button(
            copy["close"],
            key="chat_close",
            icon=":material/close:",
            type="tertiary",
        ):
            _begin_close_drawer()
            st.rerun(scope="app")


def _render_drawer(client, locale, copy, focus):
    hook = (
        STYLE_HOOKS["drawer_fullscreen"]
        if st.session_state.get(FULLSCREEN_KEY)
        else STYLE_HOOKS["drawer"]
    )
    with st.container(key=hook, height="stretch"):
        st.html(
            '<div class="oj-chat-drawer-marker'
            + (" is-closing" if CLOSING_KEY in st.session_state else "")
            + '" aria-hidden="true"></div>'
        )
        _render_toolbar(client, locale, copy)
        if not st.session_state.get(SESSIONS_LOADED_KEY):
            try:
                _load_sessions(client, locale)
            except APIError as error:
                _show_error(error, copy)
        selected = st.session_state.get(SELECTED_KEY)
        if selected and selected not in _state_mapping(SESSION_CACHE_KEY):
            try:
                _load_session(client, selected)
            except APIError as error:
                _show_error(error, copy)
                return
        if selected and selected not in _state_mapping(TURN_HISTORY_KEY):
            try:
                _load_turn_history(client, selected)
            except APIError as error:
                _show_error(error, copy)
        fullscreen = bool(st.session_state.get(FULLSCREEN_KEY))
        if fullscreen:
            mobile_view = (
                "history" if st.session_state.get(VIEW_KEY) == "history" else "conversation"
            )
            st.html(
                '<div class="oj-chat-mobile-view-marker is-'
                + mobile_view
                + '" aria-hidden="true"></div>'
            )
            with st.container(
                key="chat_fullscreen_split",
                horizontal=True,
                wrap=False,
                height="stretch",
            ):
                with st.container(width=320, height="stretch"):
                    _render_history(client, locale, copy, compact=True)
                _render_conversation(client, locale, copy, focus)
        elif st.session_state.get(VIEW_KEY, "chat") == "history":
            _render_history(client, locale, copy, compact=True)
        else:
            _render_conversation(client, locale, copy, focus)


def _bind_authenticated_owner():
    """Drop browser-only chat caches if the verified account identity changes."""

    owner = user().get("user_id")
    if not owner:
        return
    previous = st.session_state.get(OWNER_KEY)
    if previous is not None and previous != owner:
        for key in (
            OPEN_KEY,
            FULLSCREEN_KEY,
            VIEW_KEY,
            SESSIONS_KEY,
            SESSIONS_LOADED_KEY,
            SELECTED_KEY,
            SESSION_CACHE_KEY,
            TURNS_KEY,
            TURN_HISTORY_KEY,
            ATTEMPTS_KEY,
            CLEAR_DRAFTS_KEY,
            PRESERVED_INPUTS_KEY,
            DELETE_PENDING_KEY,
            CLOSING_KEY,
            LOCALE_KEY,
        ):
            st.session_state.pop(key, None)
        for key in list(st.session_state):
            if str(key).startswith(("chat_draft_", "chat_form_")):
                st.session_state.pop(key, None)
    st.session_state[OWNER_KEY] = owner


def _bind_chat_locale(locale):
    """Keep histories language-pure while preserving the other locale on the server."""

    previous = st.session_state.get(LOCALE_KEY)
    if previous is not None and previous != locale:
        st.session_state[SESSIONS_KEY] = []
        st.session_state[SESSIONS_LOADED_KEY] = False
        st.session_state[SELECTED_KEY] = None
        st.session_state[VIEW_KEY] = "chat"
        st.session_state[DELETE_PENDING_KEY] = None
    st.session_state[LOCALE_KEY] = locale


def chat_assistant(client=None, locale=None, focus=None):
    """Render the global launcher and, while open, the programming chat drawer.

    The workspace shell should call this exactly once after authentication. The
    optional ``client`` and ``locale`` parameters exist for isolated component
    tests; production callers can omit them. ``focus`` is a non-authoritative
    selector only; the backend rechecks ownership and field visibility.
    """

    selected_locale = normalize_locale(
        locale if locale is not None else st.session_state.get("_locale", "zh-CN")
    )
    copy = chat_copy(selected_locale)
    client = _client(client)
    selected_focus = focus
    _bind_authenticated_owner()
    _bind_chat_locale(selected_locale)
    with st.container(key=STYLE_HOOKS["launcher"]):
        if st.button(
            copy["launcher"],
            key="chat_launcher_button",
            type="primary",
            help=copy["subtitle"],
        ):
            st.session_state[OPEN_KEY] = True
            st.session_state.setdefault(VIEW_KEY, "chat")
    if not st.session_state.get(OPEN_KEY):
        return
    fullscreen = bool(st.session_state.get(FULLSCREEN_KEY))

    @st.dialog(
        copy["title"],
        width="stretch" if fullscreen else "small",
        dismissible=True,
        # Backdrop clicks and Escape use the same short exit transition as the
        # visible close control.  Keeping OPEN_KEY true for that one frame lets
        # the marker render ``is-closing`` before the fragment finalizes state.
        on_dismiss=_begin_close_drawer,
    )
    def drawer():
        _render_drawer(client, selected_locale, copy, selected_focus)

    drawer()
    if CLOSING_KEY in st.session_state:

        @st.fragment(run_every=0.2)
        def finish_close_animation():
            started = st.session_state.get(CLOSING_KEY)
            if isinstance(started, (int, float)) and time.monotonic() - started >= 0.18:
                _close_drawer()
                st.rerun(scope="app")

        finish_close_animation()


# Short aliases keep the integration call obvious without proliferating stateful
# wrappers.  All names resolve to the same one-instance component contract.
render_chat_assistant = chat_assistant
render_chat = chat_assistant


def chat_drawer(locale=None, client=None, focus=None):
    """Locale-first shell alias matching the other frontend page wrappers."""

    return chat_assistant(client=client, locale=locale, focus=focus)


def render_chat_drawer(client=None, locale=None, focus=None):
    """Injectable renderer alias for isolated component tests."""

    return chat_assistant(client=client, locale=locale, focus=focus)


__all__ = (
    "ACTIVE_STATUSES",
    "ChatUIContractError",
    "SESSION_SCHEMA",
    "STATUS_SCHEMA",
    "STYLE_HOOKS",
    "TURN_SCHEMA",
    "chat_assistant",
    "chat_copy",
    "chat_drawer",
    "context_epoch",
    "new_idempotency_key",
    "programming_focus",
    "render_chat",
    "render_chat_assistant",
    "render_chat_drawer",
    "send_turn",
    "session_detail",
    "session_summaries",
    "turn_detail",
    "turn_history",
    "turn_payload",
    "workspace_focus",
)
