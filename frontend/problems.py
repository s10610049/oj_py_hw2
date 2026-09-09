"""Problem catalog, complete editor and programming workspace."""

import hashlib
import html
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timezone

import streamlit as st

from frontend.client import APIError, resource
from frontend.common import api, go, is_admin, mutation, notice, show_error
from frontend.forms import (
    cleanup_manual_ai,
    cleanup_reference_attachments,
    difficulty_option_label,
    difficulty_options,
    manual_ai_assistant,
    problem_form,
    reference_attachments,
)
from frontend.i18n import locale as current_locale
from frontend.i18n import t
from frontend.import_template import native_problem_template
from frontend.metadata_i18n import localized_optional_metadata, localized_tags
from shared.taxonomy import DIFFICULTIES, normalize_difficulty

STATUS_SCHEMA = "oj.problem-status.v1"
_PROBLEM_STATES = {"unattempted", "pending", "failed", "partial", "passed", "outdated"}
_OUTCOMES = {
    "pending",
    "accepted",
    "wrong_answer",
    "partial",
    "compile_error",
    "time_limit",
    "memory_limit",
    "runtime_error",
    "judge_error",
}
_DIFFICULTY_TOKENS = {item["color_token"] for item in DIFFICULTIES} | {"difficulty-neutral"}
_TRANSLATABLE_FIELDS = (
    "title",
    "description",
    "input_description",
    "output_description",
    "constraints",
    "hint",
)
_IMPORT_MISSING_FIELDS = {
    "id",
    "title",
    "description",
    "input_description",
    "output_description",
    "constraints",
    "samples",
    "testcases",
}

_STATE_PRESENTATION = {
    "zh-CN": {
        "unattempted": ("未尝试", "status-unattempted"),
        "pending": ("判题中", "status-pending"),
        "failed": ("未通过", "status-failed"),
        "partial": ("部分通过", "status-partial"),
        "passed": ("已通过", "status-ac"),
        "outdated": ("题目已更新", "status-outdated"),
        "unavailable": ("状态暂缺", "status-unavailable"),
    },
    "en": {
        "unattempted": ("Not attempted", "status-unattempted"),
        "pending": ("Pending", "status-pending"),
        "failed": ("Not passed", "status-failed"),
        "partial": ("Partially passed", "status-partial"),
        "passed": ("Accepted", "status-ac"),
        "outdated": ("Problem updated", "status-outdated"),
        "unavailable": ("Status unavailable", "status-unavailable"),
    },
}

_OUTCOME_PRESENTATION = {
    "zh-CN": {
        "pending": ("判题中", "status-pending"),
        "accepted": ("已通过", "status-ac"),
        "wrong_answer": ("答案错误", "status-failed"),
        "partial": ("部分通过", "status-partial"),
        "compile_error": ("编译错误", "status-compile"),
        "time_limit": ("运行超时", "status-timeout"),
        "memory_limit": ("内存超限", "status-memory"),
        "runtime_error": ("运行错误", "status-runtime"),
        "judge_error": ("评测异常", "status-judge-error"),
    },
    "en": {
        "pending": ("Pending", "status-pending"),
        "accepted": ("Accepted", "status-ac"),
        "wrong_answer": ("Wrong answer", "status-failed"),
        "partial": ("Partially passed", "status-partial"),
        "compile_error": ("Compile error", "status-compile"),
        "time_limit": ("Time limit", "status-timeout"),
        "memory_limit": ("Memory limit", "status-memory"),
        "runtime_error": ("Runtime error", "status-runtime"),
        "judge_error": ("Judge error", "status-judge-error"),
    },
}


def _locale_code(locale=None):
    if locale is None:
        locale = current_locale()
    return "en" if str(locale).lower().startswith("en") else "zh-CN"


def _original_display(value, locale, key="problem.original_value"):
    text = str(value or "")
    return t(key, locale_code=locale, value=text) if locale == "en" and text else text


def _has_cjk(value):
    return any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in str(value or "")
    )


def localized_problem(problem, locale=None):
    """Apply only a complete locale projection and fail closed in English."""

    locale = _locale_code(locale)
    base = dict(problem) if isinstance(problem, Mapping) else {}
    content = base.get("content")
    fields = content.get("fields") if isinstance(content, Mapping) else None
    schema = content.get("schema_version") if isinstance(content, Mapping) else None
    structurally_valid = (
        isinstance(content, Mapping)
        and schema in {"oj.problem-content.v1", "oj.problem-content.v2"}
        and content.get("requested_locale") == locale
        and content.get("status") in {"ready", "missing", "stale"}
        and isinstance(fields, Mapping)
        and all(isinstance(fields.get(field), str) for field in _TRANSLATABLE_FIELDS)
    )
    warning = None
    ready = (
        structurally_valid
        and content.get("status") == "ready"
        and content.get("resolved_locale") == locale
        and (locale != "en" or not any(_has_cjk(fields[field]) for field in _TRANSLATABLE_FIELDS))
    )
    if ready:
        base.update({field: fields[field] for field in _TRANSLATABLE_FIELDS})
    elif locale == "en":
        status = content.get("status") if structurally_valid else "missing"
        warning = (
            "translation.fallback_stale" if status == "stale" else "translation.fallback_missing"
        )
        for field in _TRANSLATABLE_FIELDS:
            base[field] = ""
        base["title"] = t(
            "translation.problem_title_missing",
            locale_code="en",
            id=str(base.get("id") or "—"),
        )
    return base, warning


def difficulty_projection(raw, locale="zh-CN"):
    """Map canonical and explicitly migrated labels to Luogu color tokens."""

    locale = _locale_code(locale)
    projection = normalize_difficulty(str(raw or ""), locale)
    if projection["recognized"]:
        return {
            "id": projection["id"],
            "label": projection["label"],
            "token": projection["color_token"],
            "recognized": True,
        }
    return {
        "id": None,
        "label": t("problems.unrated", locale_code=locale),
        "token": "difficulty-neutral",
        "recognized": False,
    }


def problem_status_index(payload):
    """Return an allow-listed problem status index, or ``None`` on bad schema."""

    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != STATUS_SCHEMA
        or not isinstance(payload.get("items"), list)
    ):
        return None
    result = {}
    for raw in payload["items"]:
        if not isinstance(raw, Mapping):
            continue
        problem_id = raw.get("problem_id")
        state = raw.get("state")
        if (
            not isinstance(problem_id, str)
            or not problem_id.strip()
            or problem_id in result
            or state not in _PROBLEM_STATES
        ):
            continue
        terminal = raw.get("latest_terminal")
        terminal_status = terminal.get("status") if isinstance(terminal, Mapping) else None
        outcome = raw.get("latest_outcome")
        latest_pending = raw.get("latest_pending")
        result[problem_id] = {
            "state": state,
            "latest_outcome": outcome if outcome in _OUTCOMES else None,
            "terminal_error": terminal_status == "error",
            "has_pending": isinstance(latest_pending, Mapping) or outcome == "pending",
        }
    return result


def _status_presentation(status, locale):
    locale = _locale_code(locale)
    if not isinstance(status, Mapping):
        return _STATE_PRESENTATION[locale]["unavailable"]
    state = status.get("state")
    # Best-score lifecycle states are stable: a later WA or a pending retry must
    # never downgrade a problem that has already earned full or partial credit.
    if state in {"unattempted", "pending", "outdated"}:
        return _STATE_PRESENTATION[locale][state]
    if state in {"passed", "partial"}:
        return _STATE_PRESENTATION[locale][state]
    outcome = status.get("latest_outcome")
    if status.get("terminal_error"):
        return _OUTCOME_PRESENTATION[locale]["judge_error"]
    if outcome in {
        "wrong_answer",
        "compile_error",
        "time_limit",
        "memory_limit",
        "runtime_error",
    }:
        return _OUTCOME_PRESENTATION[locale][outcome]
    return _STATE_PRESENTATION[locale].get(state, _STATE_PRESENTATION[locale]["unavailable"])


def problem_badges_html(difficulty, status, locale="zh-CN"):
    """Render two small, escaped badges without exposing raw status records."""

    locale = _locale_code(locale)
    safe_status = status if isinstance(status, Mapping) else {}
    label, status_class = _status_presentation(safe_status, locale)
    if not isinstance(difficulty, Mapping):
        difficulty = {}
    difficulty_label = difficulty.get("label")
    if not isinstance(difficulty_label, str) or not difficulty_label:
        difficulty_label = t("problems.unrated", locale_code=locale)
    difficulty_token = difficulty.get("token")
    if difficulty_token not in _DIFFICULTY_TOKENS:
        difficulty_token = "difficulty-neutral"
    status_prefix = "提交状态" if locale == "zh-CN" else "Submission status"
    difficulty_prefix = "难度" if locale == "zh-CN" else "Difficulty"
    pending_badge = ""
    if safe_status.get("has_pending") and safe_status.get("state") != "pending":
        pending_label = "新提交判题中" if locale == "zh-CN" else "New submission pending"
        pending_badge = (
            "<span class='oj-status-token status-pending' aria-label='"
            f"{html.escape(status_prefix + ': ' + pending_label, quote=True)}'>"
            f"{html.escape(pending_label)}</span>"
        )
    return (
        "<div class='oj-catalog-badges'>"
        f"<span class='oj-status-token {status_class}' aria-label='"
        f"{html.escape(status_prefix + ': ' + label, quote=True)}'>{html.escape(label)}</span>"
        f"{pending_badge}"
        f"<span class='oj-difficulty-token {difficulty_token}' aria-label='"
        f"{html.escape(difficulty_prefix + ': ' + difficulty_label, quote=True)}'>"
        f"{html.escape(difficulty_label)}</span></div>"
    )


def _difficulty_filter(rows, locale):
    present = {row[1]["id"] for row in rows if row[1]["recognized"]}
    has_neutral = any(not row[1]["recognized"] for row in rows)
    options = ["all"] + [item["id"] for item in DIFFICULTIES if item["id"] in present]
    if has_neutral:
        options.append("neutral")
    labels = {"all": t("problems.all_difficulties", locale_code=locale)}
    labels.update({item["id"]: item[locale] for item in DIFFICULTIES})
    labels["neutral"] = t("problems.unrated", locale_code=locale)
    return options, labels


def catalog_search_text(problem, locale):
    """Build search text from the same localized metadata shown in the card."""

    locale = _locale_code(locale)
    tags, _ = localized_tags(problem.get("tags"), locale)
    return " ".join(
        [str(problem.get("id") or ""), str(problem.get("title") or ""), *tags]
    ).casefold()


def catalog():
    locale = _locale_code()
    st.title(t("problems.title"))
    st.caption(t("problems.caption"))
    top, action = st.columns([4, 1])
    search = top.text_input(
        t("problems.search"),
        placeholder=t("problems.search_placeholder"),
        label_visibility="collapsed",
    )
    action.button(
        t("problems.add"),
        type="primary",
        on_click=go,
        args=("题库",),
        kwargs={"_problem_mode": "new"},
    )
    client = api()
    raw_problems = client.request("GET", "/api/problems/", params={"locale": locale})
    projected = [localized_problem(problem, locale) for problem in raw_problems]
    status_message = None
    try:
        statuses = problem_status_index(client.request("GET", "/api/me/problem-statuses/"))
        if statuses is None:
            statuses = {}
            status_message = t("problems.status_invalid")
    except APIError as exc:
        if exc.status == 401:
            raise
        statuses = {}
        status_message = t("problems.status_failed")
    rows = [
        (problem, difficulty_projection(problem.get("difficulty"), locale), warning)
        for problem, warning in projected
    ]
    options, option_labels = _difficulty_filter(rows, locale)
    difficulty = st.selectbox(
        t("field.difficulty"),
        options,
        format_func=option_labels.get,
    )
    if status_message:
        st.caption(status_message)
    query = search.casefold().strip()
    filtered = [
        (p, projection, warning)
        for p, projection, warning in rows
        if (not query or query in catalog_search_text(p, locale))
        and (
            difficulty == "all"
            or projection["id"] == difficulty
            or difficulty == "neutral"
            and not projection["recognized"]
        )
    ]
    st.caption(t("problems.count", count=len(filtered)))
    if not filtered:
        st.info(t("problems.empty"))
        return
    pages = max(1, (len(filtered) + 11) // 12)
    signature = (search, difficulty)
    if st.session_state.get("_catalog_filter") != signature:
        st.session_state["catalog_page"] = 1
        st.session_state["_catalog_filter"] = signature
    st.session_state["catalog_page"] = min(st.session_state.get("catalog_page", 1), pages)
    page = st.number_input(
        t("problems.page"), min_value=1, max_value=pages, step=1, key="catalog_page"
    )
    for problem, projection, warning in filtered[(page - 1) * 12 : page * 12]:
        row_key = hashlib.sha256(problem["id"].encode("utf-8")).hexdigest()[:12]
        with st.container(key=f"catalog_problem_{row_key}"):
            title, meta, action = st.columns([5, 2.5, 1.5], vertical_alignment="center")
            title.write(problem["title"])
            tag_values, missing_tags = localized_tags(problem.get("tags"), locale)
            tags = " / ".join(tag_values)
            title.caption(problem["id"] + (" · " + tags if tags else ""))
            if missing_tags:
                title.caption(t("translation.metadata_missing", count=missing_tags))
            if warning:
                title.caption(t(warning))
            meta.html(problem_badges_html(projection, statuses.get(problem["id"]), locale))
            action.button(
                t("problems.open"),
                key=f"open_{problem['id']}",
                on_click=go,
                args=("题库",),
                kwargs={"_problem_mode": "detail", "_problem_id": problem["id"]},
            )


def render_statement(problem):
    with st.container(key="problem_prose"):
        for field, label_key in (
            ("description", "field.description"),
            ("input_description", "field.input_description"),
            ("output_description", "field.output_description"),
            ("constraints", "field.constraints"),
        ):
            st.subheader(t(label_key))
            st.markdown(problem.get(field, ""))
        st.subheader(t("field.samples"))
        for index, sample in enumerate(problem.get("samples", []), 1):
            left, right = st.columns(2)
            left.caption(t("problem.sample_input", index=index))
            left.code(sample["input"], language="text")
            right.caption(t("problem.sample_output", index=index))
            right.code(sample["output"], language="text")
        if problem.get("hint"):
            st.subheader(t("field.hint"))
            st.markdown(problem["hint"])
        with st.expander(t("problem.test_data", count=len(problem.get("testcases", [])))):
            for index, case in enumerate(problem.get("testcases", []), 1):
                st.caption(t("problem.test_case", index=index))
                left, right = st.columns(2)
                left.code(case["input"], language="text")
                right.code(case["output"], language="text")


def code_submission(problem):
    st.subheader(t("problem.write_submit"))
    names = api().request("GET", "/api/languages/")["name"]
    if not names:
        st.warning(t("problem.no_languages"))
        return
    with st.form("submission_form", border=False):
        language = st.selectbox(t("problem.language"), names)
        st.caption(t("problem.code_help"))
        with st.container(key="code_editor"):
            code = st.text_area(t("problem.code"), height=360, key=f"code_{problem['id']}")
        submit = st.form_submit_button(t("problem.submit"), type="primary")
    if submit:
        if not code.strip():
            st.error(t("problem.code_required"))
            return
        ok, result = mutation(
            "POST",
            "/api/submissions/",
            json={"problem_id": problem["id"], "language": language, "code": code},
        )
        if ok:
            go("提交记录", _submission_id=result["submission_id"])
            notice(t("problem.submitted"))
            st.rerun()


def _translation_editor(problem):
    problem_id = problem["id"]
    with st.expander(t("translation.manage")):
        english = api().request(
            "GET", f"/api/problems/{resource(problem_id)}", params={"locale": "en"}
        )
        content = english.get("content") if isinstance(english, Mapping) else None
        fields = content.get("fields") if isinstance(content, Mapping) else None
        ready = (
            isinstance(content, Mapping)
            and content.get("status") == "ready"
            and isinstance(fields, Mapping)
            and all(isinstance(fields.get(field), str) for field in _TRANSLATABLE_FIELDS)
        )
        exists = isinstance(content, Mapping) and content.get("status") in {"ready", "stale"}
        initial = fields if ready else {}
        with st.form(f"translation_{problem_id}", border=False):
            values = {}
            for field in _TRANSLATABLE_FIELDS:
                widget = st.text_input if field == "title" else st.text_area
                values[field] = widget(
                    t(f"field.{field}"),
                    value=initial.get(field, ""),
                    key=f"translation_{problem_id}_{field}",
                )
            submitted = st.form_submit_button(t("translation.save"), type="primary")
        if submitted:
            if any(not values[field].strip() for field in _TRANSLATABLE_FIELDS if field != "hint"):
                st.error(t("validation.required", label=t("translation.manage")))
            else:
                ok, _ = mutation(
                    "PUT",
                    f"/api/problems/{resource(problem_id)}/translations/en",
                    json=values,
                )
                if ok:
                    notice(t("translation.saved"))
                    st.rerun()
        if exists:
            confirmed = st.checkbox(
                t("translation.delete_confirm"), key=f"translation_delete_confirm_{problem_id}"
            )
            if st.button(
                t("translation.delete"),
                disabled=not confirmed,
                key=f"translation_delete_{problem_id}",
            ):
                ok, _ = mutation("DELETE", f"/api/problems/{resource(problem_id)}/translations/en")
                if ok:
                    notice(t("translation.deleted"))
                    st.rerun()


def _ready_english_translation(problem):
    """Return only a complete English projection suitable for editor defaults."""

    content = problem.get("content") if isinstance(problem, Mapping) else None
    fields = content.get("fields") if isinstance(content, Mapping) else None
    if not (
        isinstance(content, Mapping)
        and content.get("requested_locale") == "en"
        and content.get("resolved_locale") == "en"
        and content.get("status") == "ready"
        and isinstance(fields, Mapping)
        and all(isinstance(fields.get(field), str) for field in _TRANSLATABLE_FIELDS)
        and not any(_has_cjk(fields[field]) for field in _TRANSLATABLE_FIELDS)
    ):
        return None
    return {field: fields[field] for field in _TRANSLATABLE_FIELDS}


def _import_binding(archive, source_format, metadata_values):
    if archive is None:
        return None
    content = archive.getvalue()
    metadata = metadata_values if isinstance(metadata_values, Mapping) else {}
    try:
        metadata_json = json.dumps(
            dict(metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        return None
    return {
        "filename": str(archive.name),
        "archive_sha256": hashlib.sha256(content).hexdigest(),
        "source_format": source_format,
        "metadata_sha256": hashlib.sha256(metadata_json.encode("utf-8")).hexdigest(),
    }


def _future_expiry(value, now=None):
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return parsed.astimezone(timezone.utc) > reference.astimezone(timezone.utc)


def _valid_expiry(value):
    if not isinstance(value, str) or not value or len(value) > 80:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _valid_import_binding(binding, *, filename, archive_sha256, source_format):
    return (
        isinstance(binding, Mapping)
        and set(binding) == {"filename", "archive_sha256", "source_format", "metadata_sha256"}
        and binding.get("filename") == filename
        and binding.get("archive_sha256") == archive_sha256
        and binding.get("source_format") == source_format
        and isinstance(binding.get("metadata_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", binding["metadata_sha256"])
    )


def _safe_limit(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _valid_preview_limits(limits):
    time_limit = limits.get("time_limit")
    memory_limit = limits.get("memory_limit")
    valid_time = time_limit is None or (
        isinstance(time_limit, (int, float))
        and not isinstance(time_limit, bool)
        and math.isfinite(time_limit)
        and time_limit > 0
    )
    valid_memory = memory_limit is None or (
        isinstance(memory_limit, int) and not isinstance(memory_limit, bool) and memory_limit > 0
    )
    return valid_time and valid_memory


def _safe_import_preview(raw, *, filename, binding):
    if not isinstance(raw, Mapping) or raw.get("schema_version") != "oj.problem-import-preview.v1":
        return None
    preview_id = raw.get("preview_id")
    archive_sha256 = raw.get("archive_sha256")
    source_format = raw.get("source_format")
    expires_at = raw.get("expires_at")
    problem = raw.get("problem")
    cases = raw.get("cases")
    limits = raw.get("limits")
    conflict = raw.get("conflict")
    if not (
        isinstance(preview_id, str)
        and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", preview_id)
        and isinstance(filename, str)
        and re.fullmatch(r"[^\\/\x00-\x1f]{1,255}\.zip", filename, re.IGNORECASE)
        and isinstance(archive_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", archive_sha256)
        and source_format in {"native-v1", "luogu-flat-v1"}
        and _valid_expiry(expires_at)
        and isinstance(problem, Mapping)
        and isinstance(cases, Mapping)
        and isinstance(limits, Mapping)
        and _valid_preview_limits(limits)
        and isinstance(conflict, Mapping)
        and isinstance(raw.get("can_commit"), bool)
        and isinstance(raw.get("warnings", []), list)
        and isinstance(raw.get("missing_fields", []), list)
    ):
        return None
    if not _valid_import_binding(
        binding,
        filename=filename,
        archive_sha256=archive_sha256,
        source_format=source_format,
    ):
        return None
    problem_id, title = problem.get("id"), problem.get("title")
    if not (
        isinstance(problem_id, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", problem_id)
        and isinstance(title, str)
        and 0 < len(title) <= 500
    ):
        return None
    for count in (cases.get("samples"), cases.get("testcases")):
        if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 200:
            return None
    warnings = []
    for item in raw.get("warnings", []):
        if (
            isinstance(item, Mapping)
            and isinstance(item.get("code"), str)
            and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", item["code"])
        ):
            warnings.append(item["code"])
    raw_missing = raw.get("missing_fields", [])
    if any(
        not isinstance(value, str) or value not in _IMPORT_MISSING_FIELDS for value in raw_missing
    ):
        return None
    missing = list(dict.fromkeys(raw_missing))
    conflict_exists = conflict.get("exists")
    current_digest = conflict.get("current_digest")
    if not isinstance(conflict_exists, bool) or (
        conflict_exists
        and (
            not isinstance(current_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", current_digest)
        )
    ):
        return None
    translations = problem.get("translations")
    english = translations.get("en") if isinstance(translations, Mapping) else None
    has_english = isinstance(english, Mapping) and all(
        isinstance(english.get(field), str) for field in _TRANSLATABLE_FIELDS
    )
    return {
        "schema_version": "oj.problem-import-preview.v1",
        "preview_id": preview_id,
        "filename": str(filename)[:255],
        "archive_sha256": archive_sha256,
        "source_format": source_format,
        "expires_at": expires_at[:80],
        "server_can_commit": raw["can_commit"],
        "has_english": has_english,
        "problem": {"id": problem_id, "title": title},
        "cases": {
            "samples": cases.get("samples") if isinstance(cases.get("samples"), int) else 0,
            "testcases": (cases.get("testcases") if isinstance(cases.get("testcases"), int) else 0),
        },
        "warnings": warnings,
        "missing_fields": missing,
        "conflict": {
            "exists": conflict_exists,
            "current_digest": current_digest if conflict_exists else None,
        },
        "limits": {
            "time_limit": _safe_limit(limits.get("time_limit")),
            "memory_limit": _safe_limit(limits.get("memory_limit")),
        },
        "binding": dict(binding),
    }


def _luogu_metadata():
    values = {}
    selected_locale = _locale_code()
    left, right = st.columns([1, 2])
    values["id"] = left.text_input(t("field.problem_id") + " *", key="import_meta_id")
    values["title"] = right.text_input(t("field.title") + " *", key="import_meta_title")
    for field in ("description", "input_description", "output_description", "constraints"):
        values[field] = st.text_area(
            t(f"field.{field}") + " *", key=f"import_meta_{field}", height=120
        )
    values["samples_json"] = st.text_area(
        t("field.samples") + " JSON *",
        value='[{"input": "", "output": ""}]',
        key="import_meta_samples",
    )
    a, b = st.columns(2)
    values["difficulty"] = a.selectbox(
        t("field.difficulty"),
        difficulty_options(),
        format_func=lambda value: difficulty_option_label(value, selected_locale),
        key="import_meta_difficulty",
    )
    values["tags"] = b.text_input(t("field.tags"), key="import_meta_tags")
    values["source"] = a.text_input(t("field.source"), key="import_meta_source")
    values["author"] = b.text_input(t("field.author"), key="import_meta_author")
    values["hint"] = st.text_area(t("field.hint"), key="import_meta_hint")
    with st.expander(t("translation.manage"), expanded=selected_locale == "en"):
        st.caption(t("translation.form_help"))
        values["translations_en"] = {
            field: (st.text_input if field == "title" else st.text_area)(
                t(f"field.{field}"), key=f"import_meta_en_{field}"
            )
            for field in _TRANSLATABLE_FIELDS
        }
    return values


def _validate_luogu_metadata(values):
    problem_id = values["id"].strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", problem_id):
        raise ValueError(t("validation.problem_id"))
    result = {"id": problem_id}
    for field in ("title", "description", "input_description", "output_description", "constraints"):
        value = values[field]
        if not value.strip():
            raise ValueError(t("validation.required", label=t(f"field.{field}")))
        result[field] = value
    try:
        samples = json.loads(values["samples_json"])
    except (ValueError, TypeError):
        raise ValueError(t("validation.json", label=t("field.samples"))) from None
    if not isinstance(samples, list) or not 1 <= len(samples) <= 200:
        raise ValueError(t("validation.case_count", label=t("field.samples")))
    if any(
        not isinstance(case, dict)
        or not isinstance(case.get("input"), str)
        or not isinstance(case.get("output"), str)
        for case in samples
    ):
        raise ValueError(t("validation.case_shape", label=t("field.samples")))
    result["samples"] = [{"input": case["input"], "output": case["output"]} for case in samples]
    result.update(
        {
            "hint": values["hint"],
            "source": values["source"],
            "author": values["author"],
            "difficulty": values["difficulty"],
            "tags": [tag.strip() for tag in values["tags"].split(",") if tag.strip()],
        }
    )
    english = values.get("translations_en", {})
    if not isinstance(english, Mapping):
        raise ValueError(t("validation.required", label=t("translation.manage")))
    normalized_english = {field: str(english.get(field, "")) for field in _TRANSLATABLE_FIELDS}
    if any(value.strip() for value in normalized_english.values()):
        if any(
            not normalized_english[field].strip()
            for field in _TRANSLATABLE_FIELDS
            if field != "hint"
        ):
            raise ValueError(t("validation.required", label=t("translation.manage")))
        if any(_has_cjk(value) for value in normalized_english.values()):
            raise ValueError(t("translation.english_only"))
        result["translations"] = {"en": normalized_english}
    return result


def _import_missing_label(field):
    labels = {
        "id": "field.problem_id",
        "title": "field.title",
        "description": "field.description",
        "input_description": "field.input_description",
        "output_description": "field.output_description",
        "constraints": "field.constraints",
        "samples": "field.samples",
        "testcases": "field.testcases",
    }
    return t(labels[field])


def _import_warning_label(code):
    keys = {
        "TRANSLATION_MISSING": "import.warning.translation_missing",
        "LUOGU_DATA_ONLY": "import.warning.luogu_data_only",
        "LIMITS_NOT_PROVIDED": "import.warning.limits_not_provided",
    }
    return t(keys[code]) if code in keys else t("import.warning.other", code=code)


def problem_importer():
    st.subheader(t("import.title"))
    st.caption(t("import.help"))
    template, guide = st.columns([1, 2])
    template.download_button(
        t("import.template_download"),
        data=native_problem_template(),
        file_name="oj-problem-archive-v1-template.zip",
        mime="application/zip",
        key="problem_import_template",
        width="stretch",
    )
    with guide.expander(t("import.guide_title")):
        st.markdown(t("import.guide"))
    archive = st.file_uploader(
        t("import.file"),
        type=["zip"],
        key="problem_import_file",
        max_upload_size=16,
    )
    source_format = st.radio(
        t("import.format"),
        ["native-v1", "luogu-flat-v1"],
        format_func=lambda value: t("import.native") if value == "native-v1" else t("import.luogu"),
        horizontal=True,
        key="problem_import_format",
    )
    metadata_values = _luogu_metadata() if source_format == "luogu-flat-v1" else None
    binding = _import_binding(archive, source_format, metadata_values)
    stored = st.session_state.get("_problem_import_preview")
    if isinstance(stored, Mapping) and stored.get("binding") != binding:
        st.session_state.pop("_problem_import_preview", None)
        st.info(t("import.selection_changed"))
    if st.button(t("import.upload_preview"), type="primary", key="problem_import_preview"):
        # A failed replacement must never leave an older preview commit-capable.
        st.session_state.pop("_problem_import_preview", None)
        if archive is None:
            st.error(t("import.file_required"))
        else:
            raw = archive.getvalue()
            if len(raw) > 50 * 1024 * 1024:
                st.error(t("import.file_too_large"))
            else:
                try:
                    metadata = (
                        _validate_luogu_metadata(metadata_values)
                        if metadata_values is not None
                        else None
                    )
                    upload = api().request(
                        "POST",
                        "/api/problem-imports/uploads/",
                        params={
                            "filename": archive.name,
                            "media_type": archive.type or "application/zip",
                        },
                        content=raw,
                    )
                    if not (
                        isinstance(upload, Mapping)
                        and upload.get("schema_version") == "oj.problem-import-upload.v1"
                        and isinstance(upload.get("upload_id"), str)
                        and upload["upload_id"]
                        and upload.get("sha256") == binding["archive_sha256"]
                        and upload.get("size_bytes") == len(raw)
                    ):
                        raise APIError(502, "Invalid import upload")
                    preview_raw = api().request(
                        "POST",
                        "/api/problem-imports/previews/",
                        json={
                            "upload_id": upload["upload_id"],
                            "source_format": source_format,
                            **({"metadata": metadata} if metadata is not None else {}),
                        },
                    )
                    preview = _safe_import_preview(
                        preview_raw, filename=archive.name, binding=binding
                    )
                    if preview is None:
                        raise APIError(502, "Invalid import preview")
                    st.session_state["_problem_import_preview"] = preview
                except ValueError as exc:
                    st.error(str(exc))
                except (APIError, KeyError) as exc:
                    show_error(exc if isinstance(exc, APIError) else APIError(502, str(exc)))

    preview = st.session_state.get("_problem_import_preview")
    if not isinstance(preview, Mapping):
        return
    st.divider()
    st.subheader(t("import.preview"))
    display_title = _original_display(preview["problem"]["title"], _locale_code())
    st.text(
        t(
            "import.problem",
            title=display_title,
            id=preview["problem"]["id"],
        )
    )
    format_label = (
        t("import.native") if preview["source_format"] == "native-v1" else t("import.luogu")
    )
    st.caption(t("import.filename", value=preview["filename"]))
    st.caption(t("import.format_value", value=format_label))
    st.caption(
        t(
            "import.languages",
            value=t(
                "import.translation_included"
                if preview["has_english"]
                else "import.translation_missing"
            ),
        )
    )
    st.caption(
        t(
            "import.cases",
            samples=preview["cases"]["samples"],
            testcases=preview["cases"]["testcases"],
        )
    )
    limit_time = (
        t("problem.limit_seconds", value=preview["limits"]["time_limit"])
        if preview["limits"]["time_limit"] is not None
        else t("problem.limit_inherit")
    )
    limit_memory = (
        t("problem.limit_mb", value=preview["limits"]["memory_limit"])
        if preview["limits"]["memory_limit"] is not None
        else t("problem.limit_inherit")
    )
    st.caption(t("import.limits", time=limit_time, memory=limit_memory))
    st.caption(t("import.digest", value=preview["archive_sha256"]))
    st.caption(t("import.expires", value=preview["expires_at"]))
    st.caption(
        t(
            "import.can_commit",
            value=t("common.yes") if preview["server_can_commit"] else t("common.no"),
        )
    )
    if preview["missing_fields"]:
        st.error(
            t(
                "import.missing",
                fields=", ".join(
                    _import_missing_label(field) for field in preview["missing_fields"]
                ),
            )
        )
    if preview["warnings"]:
        st.caption(
            t(
                "import.warning",
                warnings=", ".join(_import_warning_label(code) for code in preview["warnings"]),
            )
        )
    expired = not _future_expiry(preview["expires_at"])
    if expired:
        st.error(t("import.expired"))
    conflict = preview["conflict"]["exists"]
    overwrite = False
    if conflict:
        st.warning(t("import.conflict"))
        overwrite = st.checkbox(t("import.overwrite"), key="problem_import_overwrite")
    parsed_ready = not preview["missing_fields"] and (preview["server_can_commit"] or conflict)
    ready = parsed_ready and not expired and (not conflict or overwrite)
    if preview["missing_fields"]:
        st.info(t("import.not_ready"))
    if st.button(t("import.confirm"), disabled=not ready, key="problem_import_commit"):
        body = {"overwrite": bool(overwrite)}
        if conflict:
            body["expected_digest"] = preview["conflict"]["current_digest"]
        ok, result = mutation(
            "POST",
            f"/api/problem-imports/previews/{resource(preview['preview_id'])}/commit",
            json=body,
        )
        if ok:
            problem_id = result.get("id") or preview["problem"]["id"]
            st.session_state.pop("_problem_import_preview", None)
            cleanup_reference_attachments("manual_new_problem")
            go("题库", _problem_mode="detail", _problem_id=problem_id)
            notice(t("import.committed"))
            st.rerun()


def problem_detail(problem, warning=None, source_problem=None):
    st.title(problem["title"])
    localized_difficulty = difficulty_projection(problem.get("difficulty"), _locale_code())
    time_limit = (
        t("problem.limit_seconds", value=problem["time_limit"])
        if problem.get("time_limit") is not None
        else t("problem.limit_inherit")
    )
    memory = (
        t("problem.limit_mb", value=problem["memory_limit"])
        if problem.get("memory_limit") is not None
        else t("problem.limit_inherit")
    )
    st.caption(
        t(
            "problem.meta",
            id=problem["id"],
            difficulty=localized_difficulty["label"],
            time=time_limit,
            memory=memory,
        )
    )
    if warning:
        st.warning(t(warning))
    if problem.get("source") or problem.get("author"):
        locale = _locale_code()
        source, source_missing = localized_optional_metadata(
            problem.get("source"), locale, "source"
        )
        author, author_missing = localized_optional_metadata(
            problem.get("author"), locale, "author"
        )
        st.caption(
            t(
                "problem.byline",
                source=source or t("problem.not_provided"),
                author=author or t("problem.not_provided"),
            )
        )
        if source_missing or author_missing:
            st.caption(
                t("translation.metadata_missing", count=sum((source_missing, author_missing)))
            )
    st.button(t("problem.edit"), on_click=go, args=("题库",), kwargs={"_problem_mode": "edit"})
    statement, program = st.tabs([t("problem.tab.statement"), t("problem.tab.code")])
    with statement:
        render_statement(problem)
    with program:
        code_submission(problem)
    _translation_editor(source_problem or problem)
    if is_admin():
        with st.expander(t("problem.manage")):
            visibility = st.checkbox(
                t("problem.public_logs"), value=bool(problem.get("public_cases"))
            )
            if st.button(t("problem.save_visibility")):
                ok, _ = mutation(
                    "PUT",
                    f"/api/problems/{resource(problem['id'])}/log_visibility",
                    json={"public_cases": visibility},
                )
                if ok:
                    notice(t("problem.visibility_updated"))
                    st.rerun()
            st.divider()
            confirmed = st.checkbox(t("problem.delete_confirm", id=problem["id"]))
            if st.button(t("problem.delete"), disabled=not confirmed):
                ok, _ = mutation("DELETE", f"/api/problems/{resource(problem['id'])}")
                if ok:
                    go("题库", _problem_mode="list", _problem_id=None)
                    notice(t("problem.deleted"))
                    st.rerun()


def _leave_problem_editor(mode, problem_id=None):
    if mode == "new":
        cleanup_manual_ai("new_problem")
        cleanup_reference_attachments("manual_new_problem")
    elif mode == "edit" and problem_id:
        cleanup_manual_ai(f"edit_{problem_id}")
        cleanup_reference_attachments(f"manual_{problem_id}")
    st.session_state.pop("_problem_import_preview", None)
    go("题库", _problem_mode="list", _problem_id=None)


def problems_page():
    mode = st.session_state.get("_problem_mode", "list")
    if mode == "list":
        catalog()
        return
    # Keep recovery available before fetching a selected problem: another
    # session may have deleted it. Returning also discards the stale identity.
    st.button(
        t("problems.back"),
        on_click=_leave_problem_editor,
        args=(mode, st.session_state.get("_problem_id")),
    )
    problem = None
    display_problem = None
    warning = None
    if mode in ("detail", "edit"):
        problem = api().request(
            "GET",
            f"/api/problems/{resource(st.session_state['_problem_id'])}",
            params={"locale": _locale_code()},
        )
        display_problem, warning = localized_problem(problem)
    if mode == "detail":
        problem_detail(display_problem, warning, problem)
        return
    st.title(t("problem.edit_title") if problem else t("problem.new_title"))
    st.caption(t("problem.editor_caption"))
    if problem and _locale_code() == "en":
        st.caption(t("problem.editor_original_notice"))
    payload = None
    if problem:
        form_prefix = f"edit_{problem['id']}"
        attachment_prefix = f"manual_{problem['id']}"
        english_problem = (
            problem
            if _locale_code() == "en"
            else api().request(
                "GET",
                f"/api/problems/{resource(problem['id'])}",
                params={"locale": "en"},
            )
        )
        english = _ready_english_translation(english_problem)
        form_problem = dict(problem)
        if english is not None:
            form_problem["translations"] = {"en": english}
        payload = problem_form(
            form_problem,
            prefix=form_prefix,
            locked_id=problem["id"],
        )
        attachments = reference_attachments(prefix=attachment_prefix)
        manual_ai_assistant(
            form_prefix,
            attachments,
            locked_id=problem["id"],
        )
    else:
        manual, importer = st.tabs([t("import.manual"), t("import.title")])
        with manual:
            form_prefix = "new_problem"
            attachment_prefix = "manual_new_problem"
            payload = problem_form(None, prefix=form_prefix)
            attachments = reference_attachments(prefix=attachment_prefix)
            manual_ai_assistant(form_prefix, attachments)
        with importer:
            problem_importer()
    if payload:
        path = f"/api/problems/{resource(problem['id'])}" if problem else "/api/problems/"
        ok, _ = mutation("PUT" if problem else "POST", path, json=payload)
        if ok:
            cleanup_manual_ai(
                f"edit_{problem['id']}" if problem else "new_problem",
            )
            cleanup_reference_attachments(
                f"manual_{problem['id']}" if problem else "manual_new_problem"
            )
            go("题库", _problem_mode="detail", _problem_id=payload["id"])
            notice(t("problem.saved"))
            st.rerun()
