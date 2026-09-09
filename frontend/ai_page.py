"""Iterative AI problem authoring with real task progress and durable drafts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
import mimetypes
import re
import uuid

import streamlit as st

from frontend.authoring_ui import (
    ACTIVE,
    MAX_ATTACHMENTS,
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENT_TOTAL_BYTES,
    build_authoring_request,
    current_status,
    current_task,
    difficulty_options,
    finite_usage,
    idempotency_key,
    knowledge_label,
    knowledge_options,
    last_successful_draft,
    locale_code,
    request_defaults,
)
from frontend.client import APIClient, APIError, resource
from frontend.common import api, clear_session, go, notice
from frontend.forms import TRANSLATION_FIELDS, optional_number, problem_payload
from frontend.styles import loading

_COPY = {
    "zh-CN": {
        "title": "智能命题",
        "subtitle": "把教学目标整理成可审阅、可持续改进的标准算法题。",
        "config": "模型与计价配置",
        "config_caption": "密钥仅用于本账户的模型调用；已保存的密钥不会显示。",
        "provider": "提供商 URL",
        "model": "模型名称",
        "key": "模型 API Key",
        "key_help": "已配置时可留空保留密钥；更换提供商需重新输入。",
        "input_price": "输入单价（未知留空）",
        "output_price": "输出单价（未知留空）",
        "unit": "计价 Token 单位",
        "currency": "币种",
        "save_config": "保存模型配置",
        "configured": "✓ 后端已配置密钥",
        "config_required": "请完整填写提供商、模型名称和必要的模型密钥。",
        "config_number": "请检查模型单价与计价单位。",
        "config_saved": "模型配置已保存，将用于下一次生成。",
        "knowledge": "知识点",
        "knowledge_placeholder": "搜索 249 个知识点，或输入自定义知识点",
        "knowledge_help": "可多选共享知识点；输入新文字并确认即可加入自定义要求。",
        "difficulty": "目标难度",
        "requirement": "命题需求 *",
        "requirement_placeholder": "说明题目目标、输入输出、数据规模、边界情况和希望区分的错误思路。",
        "free_prompt": "自定义补充要求（可选）",
        "free_prompt_placeholder": "可自由补充题面风格、情境、限制或其他希望模型遵守的细节。",
        "reference": "参考题号（可选）",
        "reference_help": "可引用题库中的现有题目作为风格或结构参考。",
        "files": "参考文件（可选）",
        "files_help": "支持文本、源码、PDF、Office 文档、图片与安全 ZIP；单个 10 MiB，最多 8 个。",
        "prepare_files": "解析所选附件",
        "prepare_required": "请先解析新选择的参考文件，并核对预览与提示。",
        "attachment_review": "参考附件核对",
        "attachment_review_help": "附件内容不会执行；确认后只把临时附件编号和摘要交给命题任务。",
        "attachment_text_ready": "可作为文本参考",
        "attachment_metadata": "仅元数据",
        "attachment_preview": "内容预览",
        "attachment_warning": "解析提示：{codes}",
        "attachment_expires": "临时保存至 {time}",
        "attachment_image": "当前模型不读取图片画面；该图片只提供已校验的元数据。",
        "attachment_unavailable": "附件已过期或暂时不可用，请移除后重新上传。",
        "attachment_confirm": "我已核对附件预览与解析提示",
        "attachment_confirm_required": "请核对并确认全部参考附件。",
        "attachment_remove": "从本轮移除",
        "attachment_retry": "重新检查附件",
        "generate": "生成题目",
        "resend": "重新发送",
        "edit": "编辑要求",
        "discard_edit": "放弃编辑",
        "locked": "本轮要求已锁定；任务继续运行。需要调整时先进入编辑状态。",
        "empty_requirement": "请填写命题需求。",
        "invalid_request": "请检查命题需求、难度、知识点或参考题号。",
        "upload_limits": "参考文件数量或大小超过限制。",
        "upload_failed": "参考文件未能安全上传，请检查文件后重试。",
        "upload_ready": "已准备 {count} 个安全附件引用。",
        "task_id": "任务编号：{task_id}",
        "revision": "版本 {revision}",
        "stop": "停止生成",
        "stopping": "正在停止当前任务…",
        "refresh": "刷新进度",
        "progress_bar": "生成进度 {percent}%",
        "progress_title": "生成进度",
        "pending": "命题任务已排队。",
        "running": "正在组织题面、样例与测试数据。",
        "completed": "本轮生成完成，可以审阅草稿。",
        "cancelled": "本轮任务已取消。",
        "service_restarted": "服务重启中断了本轮任务。",
        "restarted": "服务重启中断了本轮任务，可编辑要求后重新发送。",
        "failed": "本轮生成失败，请调整要求后重试。",
        "failed_with_draft": "本轮整改未完成，上一份成功草稿已保留。",
        "elapsed": "耗时 {elapsed:.1f} 秒 · {progress}",
        "input_tokens": "输入 Token",
        "output_tokens": "输出 Token",
        "total_tokens": "总 Token",
        "cost": "估算费用",
        "current_usage": "本轮用量",
        "cumulative_usage": "会话累计用量",
        "history": "版本记录",
        "history_caption": "每次重发或整改都是独立模型任务；旧任务的终态与用量会保留。",
        "history_item": "版本 {revision} · {operation} · {status}",
        "history_meta": "任务 {task_id} · {elapsed:.1f} 秒 · {tokens} Token · {cost:.8g} {currency}",
        "operation_initial": "首稿",
        "operation_replace_requirements": "更新要求",
        "operation_refine_draft": "整改题目",
        "review": "审阅题目",
        "review_caption": "先核对题意、样例与测试点，再决定继续整改或保存到题库。",
        "draft_version": "查看成功稿",
        "draft_version_option": "版本 {revision} · {title}",
        "historical_draft_notice": (
            "当前查看的是历史成功稿；提交整改后会以此稿为基础创建一个新版本。"
        ),
        "improvement": "改进要求 *",
        "improvement_placeholder": "例如：补充无解边界，收紧数据范围，并让样例覆盖关键分支。",
        "refine": "重新整改出题",
        "empty_improvement": "请填写具体的改进要求。",
        "reference_code": "生成的参考程序（需核验）",
        "validation_notes": "生成说明",
        "validation_notes_source_only": "生成说明保留在中文原稿中。",
        "save_heading": "保存草稿",
        "save_mode": "保存方式",
        "save_new": "新增题目",
        "save_update": "更新已有题目",
        "empty_catalog": "题库为空，请选择新增题目。",
        "target": "更新目标",
        "confirm": "已确认更新目标，保存将替换该题目的配置",
        "confirm_required": "请先确认更新目标。",
        "save": "保存到题库",
        "saved": "AI 草稿已保存到题库。",
        "draft_invalid": "请检查题目必填字段、样例和测试点格式。",
        "id": "题号 *",
        "problem_title": "题目标题 *",
        "description": "题目描述 *",
        "input_description": "输入格式 *",
        "output_description": "输出格式 *",
        "constraints": "数据范围与约束 *",
        "english_translation": "完整英文题面",
        "english_translation_help": (
            "AI 草稿必须包含完整英文稿；代码、样例和测试数据保持原样，不参与翻译。"
        ),
        "chinese_source": "中文原稿与元数据",
        "chinese_source_help": "此区域维护题库采用的中文原稿；英文稿与中文原稿会原子保存。",
        "chinese_field": "中文原稿 · {label}",
        "case_note": "样例与测试点使用 JSON 数组，每项包含字符串 input 与 output。",
        "samples": "样例 JSON *",
        "testcases": "测试点 JSON *",
        "details": "提示、来源与资源限制",
        "hint": "提示",
        "source": "来源",
        "author": "作者",
        "draft_difficulty": "难度",
        "tags": "标签（英文逗号分隔）",
        "time": "时间限制（秒，留空继承）",
        "memory": "内存限制（MB，留空继承）",
        "limits_note": "时间与内存分别按题目、语言、系统默认值依次继承。",
        "new_session": "开始新的命题会话",
        "restore": "恢复已有会话",
        "session_id": "会话编号",
        "load": "载入会话",
        "legacy_restore": "恢复已有任务",
        "legacy_task_id": "任务编号",
        "legacy_load": "载入任务",
        "legacy_notice": "检测到升级前的命题任务；其真实状态与草稿仍可继续查看。",
        "legacy_upgrade": "继续后将切换到可追踪版本、编辑重发与多轮整改的新命题会话。",
        "legacy_refine_requirement": (
            "请基于下面的已有草稿重新命题，并完整落实改进要求。\n"
            "原始命题需求：{requirement}\n改进要求：{instruction}\n已有草稿：{draft}"
        ),
        "knowledge_prefix": "知识点",
        "difficulty_prefix": "目标难度",
        "permission": "无法执行此操作",
        "connection": "连接暂不可用",
        "not_found": "未找到记录",
        "conflict": "记录状态已变化",
        "bad_request": "请检查输入",
        "server": "服务暂时异常",
        "response": "响应异常",
        "operation": "操作失败",
        "last_state": "保留上次已确认状态；连接失败不表示后台任务已停止。",
    },
    "en": {
        "title": "AI Problem Authoring",
        "subtitle": "Turn a learning objective into a reviewable standard problem that can evolve.",
        "config": "Model and pricing",
        "config_caption": (
            "The key is used only for this account's model calls and is never displayed "
            "after saving."
        ),
        "provider": "Provider URL",
        "model": "Model",
        "key": "Model API key",
        "key_help": "Leave blank to retain the saved key; changing provider requires a new key.",
        "input_price": "Input price (optional)",
        "output_price": "Output price (optional)",
        "unit": "Token pricing unit",
        "currency": "Currency",
        "save_config": "Save model settings",
        "configured": "✓ API key configured on the server",
        "config_required": "Complete the provider, model, and required API key fields.",
        "config_number": "Check the model prices and pricing unit.",
        "config_saved": "Model settings saved for the next generation.",
        "knowledge": "Knowledge points",
        "knowledge_placeholder": "Search 249 shared topics or enter a custom topic",
        "knowledge_help": "Select shared topics or type and confirm a custom requirement.",
        "difficulty": "Target difficulty",
        "requirement": "Authoring request *",
        "requirement_placeholder": (
            "Describe the objective, I/O, constraints, edge cases, and misconceptions "
            "to distinguish."
        ),
        "free_prompt": "Custom instructions (optional)",
        "free_prompt_placeholder": (
            "Add any preferred setting, statement style, constraint, or other model guidance."
        ),
        "reference": "Reference problem ID (optional)",
        "reference_help": "Use an existing catalog problem as a style or structure reference.",
        "files": "Reference files (optional)",
        "files_help": (
            "Text, source, PDF, Office, images, and safe ZIP are supported; "
            "10 MiB each, up to 8 files."
        ),
        "prepare_files": "Parse selected files",
        "prepare_required": "Parse newly selected files and review their previews first.",
        "attachment_review": "Review reference files",
        "attachment_review_help": (
            "Files are never executed. After confirmation, only temporary identities "
            "and parsed snapshots are sent to the authoring task."
        ),
        "attachment_text_ready": "Text reference ready",
        "attachment_metadata": "Metadata only",
        "attachment_preview": "Content preview",
        "attachment_warning": "Parser notices: {codes}",
        "attachment_expires": "Temporarily stored until {time}",
        "attachment_image": (
            "The current model does not inspect image pixels; only validated metadata "
            "is available."
        ),
        "attachment_unavailable": (
            "This file expired or is unavailable. Remove it and upload it again."
        ),
        "attachment_confirm": "I reviewed the file previews and parser notices",
        "attachment_confirm_required": "Review and confirm every reference file.",
        "attachment_remove": "Remove from this revision",
        "attachment_retry": "Check files again",
        "generate": "Generate problem",
        "resend": "Resend requirements",
        "edit": "Edit requirements",
        "discard_edit": "Discard edits",
        "locked": "This revision is locked while it runs. Enter edit mode before changing it.",
        "empty_requirement": "Enter an authoring request.",
        "invalid_request": (
            "Check the request, difficulty, knowledge points, or reference problem ID."
        ),
        "upload_limits": "The reference-file count or size exceeds the limit.",
        "upload_failed": "A reference file could not be uploaded safely. Check it and retry.",
        "upload_ready": "{count} safe attachment references ready.",
        "task_id": "Task ID: {task_id}",
        "revision": "Revision {revision}",
        "stop": "Stop generation",
        "stopping": "Stopping the active task…",
        "refresh": "Refresh progress",
        "progress_bar": "Generation progress {percent}%",
        "progress_title": "Generation progress",
        "pending": "The authoring task is queued.",
        "running": "Building the statement, examples, and test data.",
        "completed": "This revision is complete and ready for review.",
        "cancelled": "This revision has been stopped.",
        "service_restarted": "A service restart interrupted this revision.",
        "restarted": "A service restart interrupted this revision. Edit and resend to continue.",
        "failed": "This revision failed. Adjust the request and retry.",
        "failed_with_draft": "This refinement failed; the last successful draft is preserved.",
        "elapsed": "Elapsed {elapsed:.1f}s · {progress}",
        "input_tokens": "Input tokens",
        "output_tokens": "Output tokens",
        "total_tokens": "Total tokens",
        "cost": "Estimated cost",
        "current_usage": "Current revision usage",
        "cumulative_usage": "Session cumulative usage",
        "history": "Revision history",
        "history_caption": (
            "Every resend or refinement is a separate model task; prior terminal states "
            "and usage remain available."
        ),
        "history_item": "Revision {revision} · {operation} · {status}",
        "history_meta": (
            "Task {task_id} · {elapsed:.1f}s · {tokens} tokens · {cost:.8g} {currency}"
        ),
        "operation_initial": "Initial draft",
        "operation_replace_requirements": "Updated requirements",
        "operation_refine_draft": "Problem refinement",
        "review": "Review problem",
        "review_caption": (
            "Check the statement, examples, and tests before refining or saving to the catalog."
        ),
        "draft_version": "Successful draft",
        "draft_version_option": "Revision {revision} · {title}",
        "historical_draft_notice": (
            "You are viewing an earlier successful draft. Submitting an improvement "
            "creates a new revision from this draft."
        ),
        "improvement": "Improvement request *",
        "improvement_placeholder": (
            "For example: add an impossible case, tighten constraints, and cover the key "
            "branch in samples."
        ),
        "refine": "Regenerate with improvements",
        "empty_improvement": "Enter a concrete improvement request.",
        "reference_code": "Generated reference solution (verify before use)",
        "validation_notes": "Generation notes",
        "validation_notes_source_only": (
            "Generation notes are stored in the canonical source language. "
            "Switch to Chinese to review them."
        ),
        "save_heading": "Save draft",
        "save_mode": "Save mode",
        "save_new": "Create new problem",
        "save_update": "Update existing problem",
        "empty_catalog": "The catalog is empty; create a new problem instead.",
        "target": "Problem to update",
        "confirm": "I confirm this will replace the selected problem configuration",
        "confirm_required": "Confirm the update target first.",
        "save": "Save to catalog",
        "saved": "The AI draft was saved to the catalog.",
        "draft_invalid": "Check required problem fields and the example/test JSON.",
        "id": "Problem ID *",
        "problem_title": "Problem title *",
        "description": "Description *",
        "input_description": "Input format *",
        "output_description": "Output format *",
        "constraints": "Constraints *",
        "english_translation": "Complete English statement",
        "english_translation_help": (
            "Every AI draft includes a complete English version. Code, examples, and "
            "judge data remain unchanged."
        ),
        "chinese_source": "Canonical Chinese statement and metadata",
        "chinese_source_help": (
            "This collapsed section intentionally maintains the canonical Chinese source. "
            "Switch to Chinese for a fully Chinese editing view."
        ),
        "chinese_field": "Canonical Chinese · {label}",
        "case_note": (
            "Examples and tests use a JSON array; every item contains string input and "
            "output fields."
        ),
        "samples": "Example JSON *",
        "testcases": "Test-case JSON *",
        "details": "Hints, attribution, and limits",
        "hint": "Hint",
        "source": "Source",
        "author": "Author",
        "draft_difficulty": "Difficulty",
        "tags": "Tags (comma-separated)",
        "time": "Time limit in seconds (blank to inherit)",
        "memory": "Memory limit in MiB (blank to inherit)",
        "limits_note": "Time and memory inherit from problem, language, then system defaults.",
        "new_session": "Start a new authoring session",
        "restore": "Restore a session",
        "session_id": "Session ID",
        "load": "Load session",
        "legacy_restore": "Restore a task",
        "legacy_task_id": "Task ID",
        "legacy_load": "Load task",
        "legacy_notice": (
            "A pre-upgrade authoring task is available; its real status and draft remain "
            "accessible."
        ),
        "legacy_upgrade": (
            "Continuing will move this task into the versioned workflow with edit, resend, "
            "and iterative refinement."
        ),
        "legacy_refine_requirement": (
            "Regenerate the problem from the existing draft and apply every improvement.\n"
            "Original request: {requirement}\nImprovement request: {instruction}\n"
            "Existing draft: {draft}"
        ),
        "knowledge_prefix": "Knowledge points",
        "difficulty_prefix": "Target difficulty",
        "permission": "Action not permitted",
        "connection": "Connection unavailable",
        "not_found": "Record not found",
        "conflict": "Record state changed",
        "bad_request": "Check the input",
        "server": "Service temporarily unavailable",
        "response": "Invalid response",
        "operation": "Action failed",
        "last_state": (
            "The last confirmed state is preserved; a connection error does not stop the "
            "server task."
        ),
    },
}

_UPLOAD_TYPES = [
    "txt",
    "md",
    "json",
    "yaml",
    "yml",
    "csv",
    "py",
    "c",
    "cc",
    "cpp",
    "cxx",
    "h",
    "hpp",
    "java",
    "js",
    "ts",
    "go",
    "rs",
    "swift",
    "kt",
    "kts",
    "sh",
    "sql",
    "pdf",
    "docx",
    "xlsx",
    "pptx",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "zip",
]

_FORM_KEYS = {
    "requirement": "ai_requirement",
    "difficulty": "ai_difficulty",
    "knowledge_points": "ai_knowledge_points",
    "free_prompt": "ai_free_prompt",
    "reference_problem_id": "ai_reference_problem",
}

_EN_LOADING_PHRASES = (
    "A good edge case is a bug report written early.",
    "First make the invariant clear; then make it fast.",
    "Every useful sample should explain one rule.",
    "The best off-by-one error is the one caught in the statement.",
)


def _copy(locale=None):
    return _COPY[locale_code(locale)]


def _authoring_styles():
    st.html("""<style>
.st-key-ai_authoring_locked [data-testid="stForm"]{background:#F0F2F1;
  border-color:#D7DEDA;box-shadow:none;opacity:.82;transition:all 180ms var(--oj-ease);}
.st-key-ai_authoring_editing [data-testid="stForm"]{
  animation:oj-authoring-unlock 220ms var(--oj-ease);}
.st-key-ai_authoring_review{margin-top:20px;padding:20px;border:1px solid
  var(--oj-border-accent);border-radius:16px;background:var(--oj-surface);
  animation:oj-authoring-review 240ms var(--oj-ease);}
.st-key-ai_authoring_status{padding:16px 18px;border:1px solid #D7E5DD;
  border-radius:14px;background:var(--oj-surface-tint);}
@keyframes oj-authoring-unlock{from{opacity:.72;transform:translateY(4px)}
  to{opacity:1;transform:translateY(0)}}
@keyframes oj-authoring-review{from{opacity:.72;transform:translateY(6px)}
  to{opacity:1;transform:translateY(0)}}
@media(prefers-reduced-motion:reduce){.st-key-ai_authoring_editing [data-testid="stForm"],
  .st-key-ai_authoring_review{animation:none}}
</style>""")


def _client(value=None):
    return value or api()


def _session_capable(client):
    marker = getattr(client, "supports_authoring_sessions", None)
    return isinstance(client, APIClient) if marker is None else bool(marker)


def _show_error(error, copy):
    labels = {
        0: copy["connection"],
        400: copy["bad_request"],
        403: copy["permission"],
        404: copy["not_found"],
        409: copy["conflict"],
        500: copy["server"],
        502: copy["response"],
    }
    label = labels.get(error.status, copy["operation"])
    message = str(error.message or "").strip()
    english_ui = copy is _COPY["en"]
    same_language = bool(_has_cjk(message)) != english_ui
    st.error(f"{label}: {message}" if message and same_language else label)


def _mutation(client, method, path, copy, *, payload=None):
    try:
        return True, client.request(method, path, json=payload)
    except APIError as error:
        if error.status == 401:
            clear_session(copy["permission"])
            st.rerun()
        _show_error(error, copy)
        return False, None


def config_form(config, locale=None, client=None):
    """Render the existing account-scoped model configuration in one locale."""

    copy = _copy(locale)
    client = _client(client)
    with st.expander(copy["config"], expanded=not config.get("api_key_configured")):
        st.caption(copy["config_caption"])
        with st.form("ai_config_form", border=False):
            provider = st.text_input(
                copy["provider"],
                value=config.get("provider_url", ""),
                placeholder="https://api.example.com/v1",
            )
            model = st.text_input(copy["model"], value=config.get("model", ""))
            key = st.text_input(
                copy["key"],
                type="password",
                key="ai_api_key",
                help=copy["key_help"],
            )
            left, right = st.columns(2)
            price_in = left.text_input(
                copy["input_price"],
                value="" if config.get("input_price") is None else str(config["input_price"]),
            )
            price_out = right.text_input(
                copy["output_price"],
                value="" if config.get("output_price") is None else str(config["output_price"]),
            )
            unit = left.number_input(
                copy["unit"],
                min_value=1,
                value=int(config.get("price_unit") or 1_000_000),
                step=1000,
            )
            currency = right.text_input(copy["currency"], value=config.get("currency") or "CNY")
            submitted = st.form_submit_button(copy["save_config"], type="primary")
        if config.get("api_key_configured"):
            st.caption(copy["configured"])
        if submitted:
            if (
                not provider.strip()
                or not model.strip()
                or (not key.strip() and not config.get("api_key_configured"))
            ):
                st.error(copy["config_required"])
                return
            try:
                payload = {
                    "provider_url": provider.strip(),
                    "model": model.strip(),
                    "api_key": key,
                    "input_price": optional_number(price_in, copy["input_price"], allow_zero=True),
                    "output_price": optional_number(
                        price_out, copy["output_price"], allow_zero=True
                    ),
                    "price_unit": int(unit),
                    "currency": currency.strip(),
                }
            except ValueError:
                st.error(copy["config_number"])
                return
            ok, _ = _mutation(client, "PUT", "/api/ai/model-config", copy, payload=payload)
            if ok:
                st.session_state["_clear_secrets"] = True
                notice(copy["config_saved"])
                st.rerun()


def usage_display(usage, prompt_text="", config=None, locale=None, *, heading=None):
    """Render finite compact metrics; provider values win over estimates."""

    copy = _copy(locale)
    projected = finite_usage(usage, prompt_text=prompt_text, pricing=config)
    if heading:
        st.caption(heading)
    columns = st.columns(4)
    prefix = "≈ " if projected["estimated"] else ""
    for column, field, label in zip(
        columns[:3],
        ("input_tokens", "output_tokens", "total_tokens"),
        (copy["input_tokens"], copy["output_tokens"], copy["total_tokens"]),
    ):
        column.metric(label, prefix + str(projected[field]))
    columns[3].metric(
        copy["cost"],
        f"{prefix}{projected['cost']:.8g} {projected['currency']}",
    )


def _loading(progress, elapsed, locale):
    if locale_code(locale) == "zh-CN":
        loading(progress, elapsed)
        return
    elapsed = max(0, float(elapsed or 0))
    phrase = _EN_LOADING_PHRASES[int(elapsed // 10) % len(_EN_LOADING_PHRASES)]
    with st.container(key="ai_loading_surface", horizontal=True, vertical_alignment="center"):
        with st.container(key="ai_loading_mark", width=64):
            st.html(
                '<div class="oj-mark" aria-hidden="true">{<span class="oj-dot"></span>'
                '<span class="oj-dot"></span><span class="oj-dot"></span>}</div>'
            )
        with st.container(key="ai_loading_copy", gap=None):
            st.html(
                '<div class="oj-loading-title" role="status" aria-live="polite">'
                + html.escape(str(progress or "Waiting for task progress"))
                + "</div>"
            )
            st.html(f'<div class="oj-loading-note">Elapsed {elapsed:.0f}s</div>')
            st.html(
                '<div class="oj-loading-note oj-phrase" aria-hidden="true">' + phrase + "</div>"
            )


def _has_cjk(value):
    return any("\u3400" <= character <= "\u9fff" for character in str(value or ""))


def _draft_display_title(draft, locale):
    """Return a locale-safe selector title without leaking canonical Chinese in English."""

    draft = draft if isinstance(draft, Mapping) else {}
    if locale_code(locale) == "en":
        translations = draft.get("translations")
        english = translations.get("en") if isinstance(translations, Mapping) else None
        translated = english.get("title") if isinstance(english, Mapping) else None
        if isinstance(translated, str) and translated.strip() and not _has_cjk(translated):
            return translated.strip()
        canonical = draft.get("title")
        if isinstance(canonical, str) and canonical.strip() and not _has_cjk(canonical):
            return canonical.strip()
        return str(draft.get("id") or "Draft")
    return str(draft.get("title") or draft.get("id") or "—")


def _catalog_problem_label(problem, locale):
    """Build an update-target label from the localized list-problem projection."""

    problem = problem if isinstance(problem, Mapping) else {}
    problem_id = str(problem.get("id") or "—")
    if locale_code(locale) == "en":
        content = problem.get("content")
        fields = content.get("fields") if isinstance(content, Mapping) else None
        title = fields.get("title") if isinstance(fields, Mapping) else None
        if (
            isinstance(content, Mapping)
            and content.get("status") == "ready"
            and content.get("resolved_locale") == "en"
            and isinstance(title, str)
            and title.strip()
            and not _has_cjk(title)
        ):
            return f"{problem_id} · {title.strip()}"
        raw_title = problem.get("title")
        if isinstance(raw_title, str) and raw_title.strip() and not _has_cjk(raw_title):
            return f"{problem_id} · {raw_title.strip()}"
        return problem_id
    title = str(problem.get("title") or "").strip()
    return f"{problem_id} · {title}" if title else problem_id


def _task_progress(task, locale, copy):
    status = str(task.get("status") or "")
    progress = str(task.get("progress") or "").strip()
    if not progress:
        return copy.get(status, copy["running"])
    if locale_code(locale) == "zh-CN":
        return progress if _has_cjk(progress) else copy.get(status, copy["running"])
    if not _has_cjk(progress):
        return progress
    if any(word in progress for word in ("连接", "提交命题")):
        return "Connecting to the model and submitting the request."
    if any(word in progress for word in ("接收", "生成内容")):
        return "Receiving and validating the model output."
    if "自动修正" in progress:
        return "Applying a bounded automatic correction after validation."
    if any(word in progress for word in ("校验", "测试", "参考解")):
        return "Checking the reference solution and test data."
    return copy.get(status, copy["running"])


def _task_progress_percent(task):
    """Project real backend stages to a bounded percentage, never elapsed time."""

    status = str(task.get("status") or "")
    explicit = task.get("progress_percent")
    if type(explicit) is int and 0 <= explicit <= 100:
        return 100 if status == "completed" else min(explicit, 99)
    if status == "completed":
        return 100
    if status == "pending":
        return 5
    progress = str(task.get("progress") or "")
    if "等待人工审阅" in progress:
        return 96
    match = re.search(r"参考解与答案.*[（(](\d+)/(\d+)[）)]", progress)
    if match and int(match.group(2)) > 0:
        return min(94, 82 + round(12 * int(match.group(1)) / int(match.group(2))))
    stages = (
        (("第 2 次", "determinism"), 80),
        (("第 1 次", "generator"), 74),
        (("静态检查", "static"), 68),
        (("自动修正", "repair"), 62),
        (("字段", "格式", "received"), 60),
        (("接收", "生成内容", "receiving"), 35),
        (("已连接", "waiting"), 20),
        (("连接", "提交命题", "connecting"), 10),
    )
    lowered = progress.lower()
    for markers, value in stages:
        if any(marker.lower() in lowered for marker in markers):
            return value
    return 10 if status == "running" else 5


def _render_task_progress(task, copy):
    task_id = str(task.get("task_id") or "unknown")
    status = str(task.get("status") or "")
    value = _task_progress_percent(task)
    state_key = "_ai_progress_floor_" + task_id
    previous = st.session_state.get(state_key)
    if type(previous) is int and status != "completed":
        value = max(previous, value)
    if status == "completed":
        value = 100
    st.session_state[state_key] = value
    with st.container(key="ai_generation_progress"):
        title = html.escape(str(copy["progress_title"]))
        st.html(
            "<div class='oj-stage-progress' role='progressbar' aria-valuemin='0' "
            f"aria-valuemax='100' aria-valuenow='{value}' aria-label='{title} {value}%'>"
            "<div class='oj-stage-progress-head'>"
            f"<span>{title}</span><strong>{value}%</strong></div>"
            "<div class='oj-stage-progress-track' aria-hidden='true'>"
            f"<span style='width:{value}%'></span></div></div>"
        )


def _task_error(task, locale, copy):
    message = str(task.get("error") or "").strip()
    if not message:
        return copy["failed"]
    if locale_code(locale) == "zh-CN":
        return message if _has_cjk(message) else copy["failed"]
    return copy["failed"] if _has_cjk(message) else message


def _render_revision_history(session, locale, config, copy):
    revisions = session.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        return
    with st.expander(copy["history"]):
        st.caption(copy["history_caption"])
        for revision in reversed(revisions):
            if not isinstance(revision, Mapping):
                continue
            task = revision.get("task") if isinstance(revision.get("task"), Mapping) else {}
            status = str(task.get("status") or "failed")
            operation = copy.get(
                f"operation_{revision.get('operation')}", str(revision.get("operation") or "")
            )
            st.markdown(
                "**"
                + copy["history_item"].format(
                    revision=revision.get("revision", "—"),
                    operation=operation,
                    status=copy.get(status, status),
                )
                + "**"
            )
            usage = finite_usage(
                task.get("usage"),
                prompt_text=str(revision.get("request", {}).get("requirement") or ""),
                pricing=config,
            )
            st.caption(
                copy["history_meta"].format(
                    task_id=task.get("task_id", "—"),
                    elapsed=float(task.get("elapsed_seconds") or 0),
                    tokens=usage["total_tokens"],
                    cost=usage["cost"],
                    currency=usage["currency"],
                )
            )
            if status == "failed":
                st.caption(_task_error(task, locale, copy))


def _poll_error(error, copy):
    if error.status == 401:
        clear_session(copy["permission"])
        st.rerun(scope="app")
    _show_error(error, copy)
    st.caption(copy["last_state"])


def _store_session(session):
    if not isinstance(session, Mapping) or not isinstance(session.get("session_id"), str):
        raise APIError(502, "Invalid authoring-session response")
    stored = deepcopy(dict(session))
    st.session_state["_ai_authoring_session"] = stored
    task = current_task(stored)
    if task:
        st.session_state["_ai_task"] = task
    return stored


def _raw_attachment_upload(client, *, filename, media_type, content):
    custom = getattr(client, "upload_attachment", None)
    if callable(custom):
        return custom(filename=filename, media_type=media_type, content=content)
    if not isinstance(client, APIClient):
        raise APIError(502, "The client does not support attachment upload")
    return client.request(
        "POST",
        "/api/attachments/",
        content=content,
        headers={"content-type": media_type},
        params={"filename": filename, "media_type": media_type},
    )


def _safe_attachment_record(value, *, expected=None):
    if not isinstance(value, Mapping) or value.get("schema_version") != "oj.attachment.v1":
        raise APIError(502, "Invalid attachment response")
    attachment_id = value.get("attachment_id")
    sha256 = value.get("sha256")
    filename = value.get("filename")
    if (
        value.get("status") != "ready"
        or not isinstance(attachment_id, str)
        or not attachment_id
        or len(attachment_id) > 128
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
        or not isinstance(filename, str)
        or not filename
    ):
        raise APIError(502, "Invalid attachment response")
    if expected is not None and (
        attachment_id != expected.get("attachment_id") or sha256 != expected.get("sha256")
    ):
        raise APIError(502, "Attachment identity changed")
    preview = value.get("preview") if isinstance(value.get("preview"), Mapping) else {}
    capabilities = (
        value.get("capabilities") if isinstance(value.get("capabilities"), Mapping) else {}
    )
    warnings = value.get("warning_codes")
    if not isinstance(warnings, list) or any(not isinstance(code, str) for code in warnings):
        raise APIError(502, "Invalid attachment response")
    return {
        "schema_version": "oj.attachment.v1",
        "attachment_id": attachment_id,
        "filename": filename[:255],
        "media_type": str(value.get("media_type") or "")[:200],
        "size_bytes": (
            value.get("size_bytes")
            if type(value.get("size_bytes")) is int and value["size_bytes"] >= 0
            else 0
        ),
        "sha256": sha256,
        "status": "ready",
        "kind": str(value.get("kind") or "")[:80],
        "capabilities": {
            "text": capabilities.get("text") is True,
            "vision": capabilities.get("vision") is True,
        },
        "preview": {
            "text": str(preview.get("text") or "")[:4000],
            "width": preview.get("width"),
            "height": preview.get("height"),
            "character_count": preview.get("character_count"),
        },
        "warning_codes": [code[:80] for code in warnings[:20]],
        "created_at": str(value.get("created_at") or "")[:80],
        "expires_at": str(value.get("expires_at") or "")[:80],
    }


def _attachment_expired(record):
    raw = record.get("expires_at") if isinstance(record, Mapping) else None
    if not isinstance(raw, str) or not raw:
        return True
    try:
        expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc)


def _attachment_records():
    value = st.session_state.setdefault("_ai_attachment_records", {})
    if not isinstance(value, dict):
        value = {}
        st.session_state["_ai_attachment_records"] = value
    return value


def _attachment_ids(key):
    value = st.session_state.setdefault(key, [])
    if not isinstance(value, list):
        value = []
        st.session_state[key] = value
    return value


def _hydrate_attachment_records(client, references, copy):
    records = _attachment_records()
    failures = st.session_state.setdefault("_ai_attachment_failures", {})
    if not isinstance(failures, dict):
        failures = {}
        st.session_state["_ai_attachment_failures"] = failures
    for reference in references:
        attachment_id = reference["attachment_id"]
        record = records.get(attachment_id)
        if (
            isinstance(record, Mapping)
            and record.get("sha256") == reference["sha256"]
            and not _attachment_expired(record)
        ):
            failures.pop(attachment_id, None)
            continue
        if attachment_id in failures:
            continue
        try:
            raw = client.request("GET", f"/api/attachments/{resource(attachment_id)}")
            record = _safe_attachment_record(raw, expected=reference)
            if _attachment_expired(record):
                raise APIError(410, "Attachment expired")
        except APIError as error:
            if error.status == 401:
                clear_session(copy["permission"])
                st.rerun()
            failures[attachment_id] = error.status
        else:
            records[attachment_id] = record
            failures.pop(attachment_id, None)


def _consume_attachment_handoff(client, copy):
    """Move validated manual-authoring files into the next AI request draft.

    The manual problem editor stores only opaque attachment identity pairs in
    session state.  Re-fetching each record from the authenticated API keeps
    browser state from becoming an authority for filenames, previews, sizes,
    ownership, or expiry.
    """

    raw = st.session_state.pop("_ai_handoff_attachments", None)
    if raw is None:
        return
    references = request_defaults({"attachments": raw})["attachments"]
    if not references:
        return
    _hydrate_attachment_records(client, references, copy)
    records = _attachment_records()
    failures = st.session_state.get("_ai_attachment_failures", {})
    pending = _attachment_ids("_ai_pending_attachment_ids")
    removed = _attachment_ids("_ai_removed_attachment_ids")
    for reference in references:
        attachment_id = reference["attachment_id"]
        record = records.get(attachment_id)
        if (
            attachment_id not in failures
            and isinstance(record, Mapping)
            and record.get("sha256") == reference["sha256"]
            and not _attachment_expired(record)
        ):
            if attachment_id not in pending:
                pending.append(attachment_id)
            if attachment_id in removed:
                removed.remove(attachment_id)


def _delete_attachment(client, attachment_id):
    try:
        client.request("DELETE", f"/api/attachments/{resource(attachment_id)}")
    except APIError:
        pass


def _upload_files(client, files, existing, copy):
    files = list(files or [])
    # A rerun may return files which are already represented by ``existing``.
    # Enforce the limit after identity de-duplication instead of counting those
    # references twice.
    if len(files) > MAX_ATTACHMENTS:
        st.error(copy["upload_limits"])
        return None
    prepared = []
    total = 0
    for uploaded in files:
        content = uploaded.getvalue()
        total += len(content)
        if len(content) > MAX_ATTACHMENT_BYTES or total > MAX_ATTACHMENT_TOTAL_BYTES:
            st.error(copy["upload_limits"])
            return None
        prepared.append((uploaded, content, hashlib.sha256(content).hexdigest()))
    cache = st.session_state.setdefault("_ai_attachment_cache", {})
    records = _attachment_records()
    pending = _attachment_ids("_ai_pending_attachment_ids")
    removed = set(_attachment_ids("_ai_removed_attachment_ids"))
    known_ids = {item["attachment_id"] for item in existing if item["attachment_id"] not in removed}
    known_ids.update(pending)
    staged = []
    staged_by_digest = {}
    uploaded_now = []
    try:
        for uploaded, content, digest in prepared:
            record = staged_by_digest.get(digest)
            attachment_id = cache.get(digest)
            if not isinstance(record, Mapping):
                record = records.get(attachment_id) if isinstance(attachment_id, str) else None
            if not isinstance(record, Mapping) or _attachment_expired(record):
                media_type = (
                    uploaded.type
                    or mimetypes.guess_type(uploaded.name)[0]
                    or "application/octet-stream"
                )
                record = _raw_attachment_upload(
                    client,
                    filename=uploaded.name,
                    media_type=media_type,
                    content=content,
                )
                record = _safe_attachment_record(record)
                if record["sha256"] != digest or _attachment_expired(record):
                    raise APIError(502, "Invalid attachment identity")
                uploaded_now.append(record["attachment_id"])
            cache[digest] = record["attachment_id"]
            staged_by_digest[digest] = record
            staged.append(record)
    except APIError as error:
        for attachment_id in uploaded_now:
            _delete_attachment(client, attachment_id)
        if error.status == 401:
            clear_session(copy["permission"])
            st.rerun()
        _show_error(error, copy)
        st.error(copy["upload_failed"])
        return False
    prospective = known_ids | {record["attachment_id"] for record in staged}
    if len(prospective) > MAX_ATTACHMENTS:
        for attachment_id in uploaded_now:
            _delete_attachment(client, attachment_id)
        st.error(copy["upload_limits"])
        return False
    prospective_records = {
        attachment_id: records.get(attachment_id) for attachment_id in prospective
    }
    prospective_records.update({record["attachment_id"]: record for record in staged})
    if (
        sum(
            int(record.get("size_bytes") or 0)
            for record in prospective_records.values()
            if isinstance(record, Mapping)
        )
        > MAX_ATTACHMENT_TOTAL_BYTES
    ):
        for attachment_id in uploaded_now:
            _delete_attachment(client, attachment_id)
        st.error(copy["upload_limits"])
        return False
    for record in staged:
        records[record["attachment_id"]] = record
        if record["attachment_id"] not in known_ids and record["attachment_id"] not in pending:
            pending.append(record["attachment_id"])
    st.success(copy["upload_ready"].format(count=len(staged)))
    return True


def _selected_files_prepared(files, references):
    selected = {hashlib.sha256(uploaded.getvalue()).hexdigest() for uploaded in list(files or [])}
    return selected <= {item["sha256"] for item in references}


def _attachment_references_for_edit(existing):
    records = _attachment_records()
    pending = _attachment_ids("_ai_pending_attachment_ids")
    removed = set(_attachment_ids("_ai_removed_attachment_ids"))
    references = [deepcopy(item) for item in existing if item["attachment_id"] not in removed]
    known = {item["attachment_id"] for item in references}
    for attachment_id in pending:
        record = records.get(attachment_id)
        if (
            isinstance(record, Mapping)
            and attachment_id not in known
            and attachment_id not in removed
        ):
            references.append(
                {"attachment_id": attachment_id, "sha256": str(record.get("sha256") or "")}
            )
            known.add(attachment_id)
    return references


def _remove_attachment(client, attachment_id, existing_ids):
    pending = _attachment_ids("_ai_pending_attachment_ids")
    removed = _attachment_ids("_ai_removed_attachment_ids")
    if attachment_id in pending:
        pending.remove(attachment_id)
        if attachment_id not in existing_ids:
            _delete_attachment(client, attachment_id)
            _attachment_records().pop(attachment_id, None)
            cache = st.session_state.get("_ai_attachment_cache", {})
            if isinstance(cache, dict):
                for digest, cached_id in list(cache.items()):
                    if cached_id == attachment_id:
                        cache.pop(digest, None)
    if attachment_id in existing_ids and attachment_id not in removed:
        removed.append(attachment_id)
    st.session_state["_ai_clear_selected_files"] = True


def _render_attachment_manager(client, existing, copy, *, editable):
    _hydrate_attachment_records(client, existing, copy)
    references = _attachment_references_for_edit(existing)
    if not references:
        return [], True
    records = _attachment_records()
    failures = st.session_state.get("_ai_attachment_failures", {})
    st.subheader(copy["attachment_review"])
    st.caption(copy["attachment_review_help"])
    valid = True
    existing_ids = {item["attachment_id"] for item in existing}
    for index, reference in enumerate(references):
        attachment_id = reference["attachment_id"]
        record = records.get(attachment_id)
        with st.container(key=f"ai_attachment_{attachment_id}_{index}", border=True):
            if not isinstance(record, Mapping) or attachment_id in failures:
                valid = False
                st.text(f"{attachment_id} · {reference['sha256'][:12]}")
                st.error(copy["attachment_unavailable"])
            else:
                capability = (
                    copy["attachment_text_ready"]
                    if record["capabilities"]["text"]
                    else copy["attachment_metadata"]
                )
                st.text(f"{record['filename']} · {capability}")
                preview = record["preview"].get("text")
                if preview:
                    with st.expander(copy["attachment_preview"]):
                        st.code(preview, language="text")
                if record["warning_codes"]:
                    st.caption(
                        copy["attachment_warning"].format(codes=", ".join(record["warning_codes"]))
                    )
                if record["kind"] == "image" and not record["capabilities"]["vision"]:
                    st.caption(copy["attachment_image"])
                if record["expires_at"]:
                    st.caption(copy["attachment_expires"].format(time=record["expires_at"]))
                if _attachment_expired(record):
                    valid = False
                    st.error(copy["attachment_unavailable"])
            if st.button(
                copy["attachment_remove"],
                key=f"remove_ai_attachment_{attachment_id}_{index}",
                disabled=not editable,
            ):
                _remove_attachment(client, attachment_id, existing_ids)
                st.rerun()
    if failures and st.button(copy["attachment_retry"], key="retry_ai_attachments"):
        st.session_state["_ai_attachment_failures"] = {}
        st.rerun()
    fingerprint = hashlib.sha256(
        json.dumps(references, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    review_key = f"ai_attachment_reviewed_{fingerprint[:16]}"
    if review_key not in st.session_state:
        st.session_state[review_key] = (
            st.session_state.get("_ai_attachment_reviewed_fingerprint") == fingerprint
        )
    reviewed = st.checkbox(
        copy["attachment_confirm"],
        key=review_key,
        disabled=not valid or not editable,
    )
    if reviewed and valid:
        st.session_state["_ai_attachment_reviewed_fingerprint"] = fingerprint
    return references, bool(valid and reviewed)


def _commit_attachment_edits():
    st.session_state["_ai_pending_attachment_ids"] = []
    st.session_state["_ai_removed_attachment_ids"] = []
    st.session_state["_ai_attachment_failures"] = {}
    st.session_state["_ai_clear_selected_files"] = True


def _discard_attachment_edits(client, *, clear_records=False):
    session = st.session_state.get("_ai_authoring_session")
    current_request = session.get("current_request", {}) if isinstance(session, Mapping) else {}
    existing_ids = {
        item.get("attachment_id") for item in request_defaults(current_request)["attachments"]
    }
    for attachment_id in list(_attachment_ids("_ai_pending_attachment_ids")):
        if attachment_id not in existing_ids:
            _delete_attachment(client, attachment_id)
    st.session_state["_ai_pending_attachment_ids"] = []
    st.session_state["_ai_removed_attachment_ids"] = []
    st.session_state["_ai_attachment_failures"] = {}
    st.session_state["_ai_clear_selected_files"] = True
    if clear_records:
        st.session_state["_ai_attachment_records"] = {}
        st.session_state["_ai_attachment_cache"] = {}
        st.session_state.pop("_ai_attachment_reviewed_fingerprint", None)


def _draft_form(initial, *, prefix, locked_id, submit_label, locale):
    copy = _copy(locale)
    initial = initial if isinstance(initial, Mapping) else {}
    is_english = locale_code(locale) == "en"
    translations = initial.get("translations")
    initial_english = translations.get("en") if isinstance(translations, Mapping) else {}
    initial_english = initial_english if isinstance(initial_english, Mapping) else {}
    difficulty = initial.get("difficulty", "")
    if isinstance(difficulty, Mapping):
        difficulty = difficulty.get("zh-CN", difficulty.get("id", ""))
    values = {}
    with st.form(f"{prefix}_form", border=False):
        left, right = st.columns([1, 2])
        values["id"] = left.text_input(
            copy["id"],
            value=locked_id or initial.get("id", ""),
            disabled=locked_id is not None,
            key=f"{prefix}_id",
        )
        if is_english:
            english_values = {
                "title": right.text_input(
                    copy["problem_title"],
                    value=initial_english.get("title", ""),
                    key=f"{prefix}_en_title",
                )
            }
            for field in (
                "description",
                "input_description",
                "output_description",
                "constraints",
            ):
                english_values[field] = st.text_area(
                    copy[field],
                    value=initial_english.get(field, ""),
                    height=180 if field == "description" else 100,
                    key=f"{prefix}_en_{field}",
                )
            english_values["hint"] = st.text_area(
                copy["hint"],
                value=initial_english.get("hint", ""),
                key=f"{prefix}_en_hint",
            )
            values["translations_en"] = english_values
            with st.expander(copy["chinese_source"], expanded=False):
                st.caption(copy["chinese_source_help"])
                values["title"] = st.text_input(
                    copy["chinese_field"].format(label=copy["problem_title"]),
                    value=initial.get("title", ""),
                    key=f"{prefix}_title",
                )
                for field in (
                    "description",
                    "input_description",
                    "output_description",
                    "constraints",
                ):
                    values[field] = st.text_area(
                        copy["chinese_field"].format(label=copy[field]),
                        value=initial.get(field, ""),
                        height=180 if field == "description" else 100,
                        key=f"{prefix}_{field}",
                    )
                values["hint"] = st.text_area(
                    copy["chinese_field"].format(label=copy["hint"]),
                    value=initial.get("hint", ""),
                    key=f"{prefix}_hint",
                )
                source, author = st.columns(2)
                values["source"] = source.text_input(
                    copy["chinese_field"].format(label=copy["source"]),
                    value=initial.get("source", ""),
                    key=f"{prefix}_source",
                )
                values["author"] = author.text_input(
                    copy["chinese_field"].format(label=copy["author"]),
                    value=initial.get("author", ""),
                    key=f"{prefix}_author",
                )
                values["difficulty"] = source.text_input(
                    copy["chinese_field"].format(label=copy["draft_difficulty"]),
                    value=str(difficulty or ""),
                    key=f"{prefix}_difficulty",
                )
                values["tags_text"] = author.text_input(
                    copy["chinese_field"].format(label=copy["tags"]),
                    value=", ".join(str(item) for item in initial.get("tags", [])),
                    key=f"{prefix}_tags",
                )
        else:
            values["title"] = right.text_input(
                copy["problem_title"], value=initial.get("title", ""), key=f"{prefix}_title"
            )
            for field in (
                "description",
                "input_description",
                "output_description",
                "constraints",
            ):
                values[field] = st.text_area(
                    copy[field],
                    value=initial.get(field, ""),
                    height=180 if field == "description" else 100,
                    key=f"{prefix}_{field}",
                )
            with st.expander(copy["english_translation"], expanded=False):
                st.caption(copy["english_translation_help"])
                english_values = {}
                for field in TRANSLATION_FIELDS:
                    widget = st.text_input if field == "title" else st.text_area
                    english_values[field] = widget(
                        copy[field if field != "title" else "problem_title"],
                        value=initial_english.get(field, ""),
                        key=f"{prefix}_en_{field}",
                    )
                values["translations_en"] = english_values
        st.caption(copy["case_note"])
        for field in ("samples", "testcases"):
            values[f"{field}_json"] = st.text_area(
                copy[field],
                value=json.dumps(
                    initial.get(field, [{"input": "", "output": ""}]),
                    ensure_ascii=False,
                    indent=2,
                ),
                height=180,
                key=f"{prefix}_{field}",
            )
        with st.expander(copy["details"], expanded=False):
            if not is_english:
                values["hint"] = st.text_area(
                    copy["hint"], value=initial.get("hint", ""), key=f"{prefix}_hint"
                )
            left, right = st.columns(2)
            if not is_english:
                values["source"] = left.text_input(
                    copy["source"], value=initial.get("source", ""), key=f"{prefix}_source"
                )
                values["author"] = right.text_input(
                    copy["author"], value=initial.get("author", ""), key=f"{prefix}_author"
                )
                values["difficulty"] = left.text_input(
                    copy["draft_difficulty"],
                    value=str(difficulty or ""),
                    key=f"{prefix}_difficulty",
                )
                values["tags_text"] = right.text_input(
                    copy["tags"],
                    value=", ".join(str(item) for item in initial.get("tags", [])),
                    key=f"{prefix}_tags",
                )
            values["time_limit_text"] = left.text_input(
                copy["time"],
                value="" if initial.get("time_limit") is None else str(initial["time_limit"]),
                key=f"{prefix}_time",
            )
            values["memory_limit_text"] = right.text_input(
                copy["memory"],
                value="" if initial.get("memory_limit") is None else str(initial["memory_limit"]),
                key=f"{prefix}_memory",
            )
            st.caption(copy["limits_note"])
        submitted = st.form_submit_button(submit_label, type="primary")
    if not submitted:
        return None
    try:
        payload = problem_payload(values)
        if "translations" not in payload:
            raise ValueError(copy["draft_invalid"])
        return payload
    except ValueError as error:
        st.error(str(error) if locale_code(locale) == "zh-CN" else copy["draft_invalid"])
        return None


def _save_draft(draft, task_id, locale, client):
    copy = _copy(locale)
    st.subheader(copy["save_heading"])
    modes = [copy["save_new"], copy["save_update"]]
    mode = st.radio(copy["save_mode"], modes, horizontal=True, key=f"ai_save_mode_{task_id}")
    target = None
    confirmed = True
    if mode == copy["save_update"]:
        records = client.request("GET", "/api/problems/", params={"locale": locale_code(locale)})
        lookup = {item["id"]: item for item in records}
        if not records:
            st.info(copy["empty_catalog"])
            return
        target = st.selectbox(
            copy["target"],
            list(lookup),
            format_func=lambda value: _catalog_problem_label(lookup[value], locale),
        )
        confirmed = st.checkbox(copy["confirm"])
    if draft.get("reference_solution"):
        with st.expander(copy["reference_code"]):
            st.code(str(draft["reference_solution"]), language="python")
    if draft.get("validation_notes"):
        with st.expander(copy["validation_notes"]):
            notes = str(draft["validation_notes"])
            if locale_code(locale) == "en" and _has_cjk(notes):
                st.caption(copy["validation_notes_source_only"])
            else:
                st.write(notes)
    payload = _draft_form(
        draft,
        prefix=f"ai_draft_{task_id}_{target or 'new'}",
        locked_id=target,
        submit_label=copy["save"],
        locale=locale,
    )
    if payload is None:
        return
    if not confirmed:
        st.error(copy["confirm_required"])
        return
    path = f"/api/problems/{resource(target)}" if target else "/api/problems/"
    ok, _ = _mutation(client, "PUT" if target else "POST", path, copy, payload=payload)
    if ok:
        go("题库", _problem_mode="detail", _problem_id=payload["id"])
        notice(copy["saved"])
        st.rerun()


def _legacy_task_panel(locale, client, config):
    copy = _copy(locale)
    saved = st.session_state.get("_ai_task")
    if not saved:
        return
    task_id = saved["task_id"]
    active = saved.get("status") in ACTIVE

    @st.fragment(run_every=1 if active else None)
    def panel():
        previous = st.session_state["_ai_task"]
        try:
            task = (
                client.request("GET", f"/api/ai/problem-tasks/{resource(task_id)}")
                if active
                else previous
            )
            st.session_state["_ai_task"] = task
        except APIError as error:
            _poll_error(error, copy)
            task = previous
        if active and task.get("status") not in ACTIVE:
            st.rerun(scope="app")
        status = task.get("status")
        st.caption(copy["task_id"].format(task_id=task_id))
        _render_task_progress(task, copy)
        if status in ACTIVE:
            _loading(_task_progress(task, locale, copy), task.get("elapsed_seconds"), locale)
            if st.button(copy["stop"], key=f"cancel_{task_id}"):
                with st.spinner(copy["stopping"]):
                    ok, result = _mutation(
                        client,
                        "PUT",
                        f"/api/ai/problem-tasks/{resource(task_id)}/cancel",
                        copy,
                    )
                if ok:
                    st.session_state["_ai_task"] = result
                    st.rerun(scope="app")
        elif status == "completed":
            st.success(copy["completed"])
        elif status == "cancelled":
            st.info(copy["cancelled"])
        else:
            st.error(_task_error(task, locale, copy))
        if status not in ACTIVE:
            st.caption(
                copy["elapsed"].format(
                    elapsed=float(task.get("elapsed_seconds") or 0),
                    progress=_task_progress(task, locale, copy),
                )
            )
        usage_display(
            task.get("usage"),
            st.session_state.get("ai_requirement", ""),
            config,
            locale,
        )
        if st.button(copy["refresh"], key=f"refresh_ai_{task_id}"):
            ok, result = _mutation(
                client, "GET", f"/api/ai/problem-tasks/{resource(task_id)}", copy
            )
            if ok:
                st.session_state["_ai_task"] = result
                st.rerun(scope="app")

    panel()


def _session_panel(locale, client, config):
    copy = _copy(locale)
    saved = st.session_state.get("_ai_authoring_session")
    if not isinstance(saved, Mapping):
        return
    session_id = str(saved["session_id"])
    active = current_status(saved) in ACTIVE

    @st.fragment(run_every=1 if active else None)
    def panel():
        previous = st.session_state["_ai_authoring_session"]
        try:
            session = (
                client.request("GET", f"/api/ai/authoring-sessions/{resource(session_id)}")
                if active
                else previous
            )
            session = _store_session(session)
        except APIError as error:
            _poll_error(error, copy)
            session = previous
        task = current_task(session)
        status = task.get("status")
        if active and status not in ACTIVE:
            st.rerun(scope="app")
        with st.container(key="ai_authoring_status"):
            left, right = st.columns([3, 1])
            left.caption(copy["task_id"].format(task_id=task.get("task_id", "—")))
            right.caption(copy["revision"].format(revision=session.get("current_revision", "—")))
            _render_task_progress(task, copy)
            if status in ACTIVE:
                _loading(
                    _task_progress(task, locale, copy),
                    task.get("elapsed_seconds"),
                    locale,
                )
                if st.button(copy["stop"], key=f"cancel_authoring_{task.get('task_id')}"):
                    with st.spinner(copy["stopping"]):
                        ok, result = _mutation(
                            client,
                            "DELETE",
                            f"/api/ai/authoring-sessions/{resource(session_id)}/active-task",
                            copy,
                        )
                    if ok:
                        try:
                            if isinstance(result, Mapping) and result.get("session_id"):
                                _store_session(result)
                            else:
                                _store_session(
                                    client.request(
                                        "GET",
                                        f"/api/ai/authoring-sessions/{resource(session_id)}",
                                    )
                                )
                        except APIError as error:
                            _poll_error(error, copy)
                        st.rerun(scope="app")
            elif status == "completed":
                st.success(copy["completed"])
            elif status == "cancelled":
                st.info(copy["cancelled"])
            elif status == "service_restarted":
                st.warning(copy["restarted"])
            elif status == "failed" and session.get("draft"):
                st.warning(copy["failed_with_draft"])
            else:
                st.error(_task_error(task, locale, copy))
            if status not in ACTIVE:
                st.caption(
                    copy["elapsed"].format(
                        elapsed=float(task.get("elapsed_seconds") or 0),
                        progress=_task_progress(task, locale, copy),
                    )
                )
            current = request_defaults(session.get("current_request"))
            usage_display(
                task.get("usage"),
                current["requirement"],
                config,
                locale,
                heading=copy["current_usage"],
            )
            if len(session.get("revisions") or []) > 1:
                usage_display(
                    session.get("cumulative_usage"),
                    current["requirement"],
                    config,
                    locale,
                    heading=copy["cumulative_usage"],
                )
            _render_revision_history(session, locale, config, copy)
            if st.button(copy["refresh"], key=f"refresh_authoring_{session_id}"):
                try:
                    _store_session(
                        client.request("GET", f"/api/ai/authoring-sessions/{resource(session_id)}")
                    )
                    st.rerun(scope="app")
                except APIError as error:
                    _poll_error(error, copy)

    panel()


def _queue_form_seed(request):
    st.session_state["_ai_form_seed"] = request_defaults(request)


def _legacy_request_defaults():
    """Return the last locally known request for a pre-session task.

    The legacy API deliberately exposes only task progress and result.  Tasks
    launched from this UI retain their editable request in private Streamlit
    session state; a task restored by ID therefore starts with empty fields
    instead of inventing inputs that the backend never returned.
    """

    value = st.session_state.get("_ai_legacy_request")
    return request_defaults(value if isinstance(value, Mapping) else None)


def _remember_legacy_task(task):
    if not isinstance(task, Mapping):
        return
    history = st.session_state.setdefault("_ai_legacy_history", [])
    if not isinstance(history, list):
        history = []
        st.session_state["_ai_legacy_history"] = history
    task_id = task.get("task_id")
    if task_id and not any(item.get("task_id") == task_id for item in history):
        history.append(dict(task))
        del history[:-20]


def _cancel_legacy_for_replacement(client, task, copy):
    """End or confirm isolation of an active legacy task before replacement."""

    if not isinstance(task, Mapping) or task.get("status") not in ACTIVE:
        return True
    task_id = str(task.get("task_id") or "")
    if not task_id:
        st.error(copy["conflict"])
        return False
    try:
        stopped = client.request("PUT", f"/api/ai/problem-tasks/{resource(task_id)}/cancel")
    except APIError as error:
        if error.status != 409:
            _show_error(error, copy)
            return False
        try:
            stopped = client.request("GET", f"/api/ai/problem-tasks/{resource(task_id)}")
        except APIError as refresh_error:
            _show_error(refresh_error, copy)
            return False
        if not isinstance(stopped, Mapping) or stopped.get("status") in ACTIVE:
            st.error(copy["conflict"])
            return False
    if isinstance(stopped, Mapping):
        st.session_state["_ai_task"] = dict(stopped)
        _remember_legacy_task(stopped)
    return True


def _start_session_from_legacy(client, request, copy):
    """Upgrade one legacy continuation to the durable authoring contract."""

    body = {"request": request}
    body["idempotency_key"] = idempotency_key(
        "initial",
        request,
        session_id=f"legacy:{_initial_attempt_id()}",
    )
    ok, result = _mutation(
        client,
        "POST",
        "/api/ai/authoring-sessions/",
        copy,
        payload=body,
    )
    if not ok:
        return False
    _remember_legacy_task(st.session_state.get("_ai_task"))
    st.session_state["_ai_task"] = None
    _store_session(result)
    _commit_attachment_edits()
    st.session_state["_ai_editing_requirements"] = False
    return True


def _legacy_refinement_request(draft, instruction, copy):
    defaults = _legacy_request_defaults()
    compact_draft = json.dumps(draft, ensure_ascii=False, separators=(",", ":"))
    # Leave headroom for the system prompt and reference problem while keeping
    # the improvement itself intact under the legacy endpoint's 20k limit.
    compact_draft = compact_draft[:12_000]
    requirement = copy["legacy_refine_requirement"].format(
        requirement=defaults["requirement"] or "—",
        instruction=instruction.strip(),
        draft=compact_draft,
    )
    return build_authoring_request(
        requirement=requirement,
        difficulty_id=defaults["difficulty"],
        knowledge_points=defaults["knowledge_points"],
        free_prompt=defaults["free_prompt"],
        reference_problem_id=defaults["reference_problem_id"],
        attachments=[],
    )


def _initial_attempt_id():
    """Return one retry-stable nonce for the current create attempt."""

    value = st.session_state.get("_ai_initial_attempt_id")
    if not isinstance(value, str) or not value:
        value = uuid.uuid4().hex
        st.session_state["_ai_initial_attempt_id"] = value
    return value


def _rotate_initial_attempt():
    st.session_state["_ai_initial_attempt_id"] = uuid.uuid4().hex


def _apply_form_seed(defaults):
    pending = st.session_state.pop("_ai_form_seed", None)
    values = pending if isinstance(pending, Mapping) else defaults
    for field, key in _FORM_KEYS.items():
        if pending is not None or key not in st.session_state:
            st.session_state[key] = deepcopy(values[field])
    # Sessions can survive a hot reload from the former free-text difficulty
    # widget.  Never let an obsolete blank/raw value turn the canonical
    # selectbox into an empty text-like control.
    difficulty_ids, _ = difficulty_options("zh-CN")
    if st.session_state.get("ai_difficulty") not in difficulty_ids:
        fallback = values.get("difficulty")
        st.session_state["ai_difficulty"] = (
            fallback if fallback in difficulty_ids else difficulty_ids[0]
        )


def _review_session(locale, client):
    copy = _copy(locale)
    session = st.session_state.get("_ai_authoring_session")
    revisions = session.get("revisions") if isinstance(session, Mapping) else None
    successful = []
    if isinstance(revisions, list):
        for revision in revisions:
            if not isinstance(revision, Mapping):
                continue
            task = revision.get("task") if isinstance(revision.get("task"), Mapping) else {}
            if task.get("status") == "completed" and isinstance(task.get("result"), Mapping):
                successful.append(
                    (
                        int(revision.get("revision") or len(successful) + 1),
                        dict(task["result"]),
                        str(task.get("task_id") or "draft"),
                    )
                )
    if not successful:
        draft, task_id = last_successful_draft(session)
        if draft is not None:
            successful.append((int(session.get("latest_success_revision") or 1), draft, task_id))
    if not successful:
        return
    with st.container(key="ai_authoring_review"):
        st.subheader(copy["review"])
        st.caption(copy["review_caption"])
        revision_lookup = {item[0]: item for item in successful}
        latest_success_revision = int(session.get("latest_success_revision") or successful[-1][0])
        if latest_success_revision not in revision_lookup:
            latest_success_revision = successful[-1][0]
        revision_choices = list(revision_lookup)
        selected_revision = st.selectbox(
            copy["draft_version"],
            revision_choices,
            index=revision_choices.index(latest_success_revision),
            format_func=lambda revision: copy["draft_version_option"].format(
                revision=revision,
                title=_draft_display_title(revision_lookup[revision][1], locale),
            ),
            # Keying by the latest successful revision resets the widget only
            # when a new draft completes.  Historical choices remain stable
            # across ordinary reruns, while revision N+1 becomes visible and
            # selected immediately instead of silently leaving N on screen.
            key=(f"ai_successful_draft_{session['session_id']}_" f"{latest_success_revision}"),
        )
        _, draft, task_id = revision_lookup[selected_revision]
        active = current_status(session) in ACTIVE
        viewing_historical = selected_revision != latest_success_revision
        if viewing_historical:
            st.info(copy["historical_draft_notice"])
        revision = int(session.get("current_revision") or 0)
        with st.form(f"ai_refinement_form_{session['session_id']}_{revision}", border=False):
            instruction = st.text_area(
                copy["improvement"],
                placeholder=copy["improvement_placeholder"],
                key=f"ai_refinement_{session['session_id']}_{revision}",
                disabled=active,
            )
            submitted = st.form_submit_button(
                copy["refine"],
                type="primary",
                disabled=active,
            )
        if submitted:
            if not instruction.strip():
                st.error(copy["empty_improvement"])
            else:
                payload = {
                    "expected_revision": revision,
                    "base_revision": selected_revision,
                    "instruction": instruction.strip(),
                }
                payload["idempotency_key"] = idempotency_key(
                    "refine",
                    {
                        "instruction": instruction.strip(),
                        "base_revision": selected_revision,
                    },
                    session_id=session["session_id"],
                    expected_revision=revision,
                )
                ok, result = _mutation(
                    client,
                    "POST",
                    f"/api/ai/authoring-sessions/{resource(session['session_id'])}/refinements",
                    copy,
                    payload=payload,
                )
                if ok:
                    _store_session(result)
                    st.rerun()
        _save_draft(draft, task_id, locale, client)


def _review_legacy_draft(locale, client, draft, task_id, *, session_capable):
    """Offer the same visible review loop for a pre-session completed task."""

    copy = _copy(locale)
    st.caption(copy["legacy_upgrade"])
    with st.form(f"ai_legacy_refinement_form_{task_id}", border=False):
        instruction = st.text_area(
            copy["improvement"],
            placeholder=copy["improvement_placeholder"],
            key=f"ai_legacy_refinement_{task_id}",
        )
        submitted = st.form_submit_button(copy["refine"], type="primary")
    if submitted:
        if not instruction.strip():
            st.error(copy["empty_improvement"])
        else:
            try:
                request = _legacy_refinement_request(draft, instruction, copy)
            except ValueError:
                st.error(copy["invalid_request"])
            else:
                task = st.session_state.get("_ai_task")
                if _cancel_legacy_for_replacement(client, task, copy):
                    if session_capable:
                        if _start_session_from_legacy(client, request, copy):
                            st.rerun()
                    else:
                        payload = {"requirement": request["requirement"]}
                        reference = request.get("reference_problem_id")
                        if reference:
                            payload["problem_id"] = reference
                        ok, result = _mutation(
                            client,
                            "POST",
                            "/api/ai/problem-tasks/",
                            copy,
                            payload=payload,
                        )
                        if ok:
                            _remember_legacy_task(task)
                            st.session_state["_ai_task"] = result
                            st.session_state["_ai_legacy_request"] = request
                            st.rerun()
    _save_draft(draft, task_id, locale, client)


def _render_legacy_snapshot(locale, client, config):
    task = st.session_state.get("_ai_task")
    if not isinstance(task, Mapping) or not isinstance(task.get("task_id"), str):
        return
    copy = _copy(locale)
    st.info(copy["legacy_notice"])
    _legacy_task_panel(locale, client, config)
    draft, task_id = last_successful_draft(st.session_state.get("_ai_task", {}))
    if draft is not None:
        with st.container(key="ai_legacy_authoring_review"):
            st.subheader(copy["review"])
            st.caption(copy["review_caption"])
            _review_legacy_draft(
                locale,
                client,
                draft,
                task_id,
                session_capable=True,
            )


def _render_session_authoring(locale, client, config):
    copy = _copy(locale)
    session = st.session_state.get("_ai_authoring_session")
    if not isinstance(session, Mapping):
        session = None
    legacy_task = st.session_state.get("_ai_task")
    if not isinstance(legacy_task, Mapping):
        legacy_task = None
    if session is not None and legacy_task is not None:
        session_task = current_task(session)
        same_task = session_task.get("task_id") == legacy_task.get("task_id")
        # _store_session mirrors the current task into _ai_task for older UI
        # consumers.  Only archive a genuinely different task left by a
        # scheduled pre-upgrade polling fragment.
        if not same_task:
            _remember_legacy_task(legacy_task)
            st.session_state["_ai_task"] = session_task or None
        legacy_task = None
    if session is None:
        _render_legacy_snapshot(locale, client, config)
    if st.session_state.pop("_ai_clear_selected_files", False):
        st.session_state.pop("ai_reference_files", None)
    defaults = (
        request_defaults(session.get("current_request"))
        if session is not None
        else _legacy_request_defaults()
    )
    existing_attachments = defaults["attachments"] if session is not None else []
    if session is None:
        _consume_attachment_handoff(client, copy)
    _hydrate_attachment_records(client, existing_attachments, copy)
    _apply_form_seed(defaults)
    active = (
        current_status(session) in ACTIVE
        if session is not None
        else bool(legacy_task and legacy_task.get("status") in ACTIVE)
    )
    editing = bool(st.session_state.get("_ai_editing_requirements"))
    locked = active and not editing
    container_key = "ai_authoring_locked" if locked else "ai_authoring_editing"
    with st.container(key=container_key):
        with st.form("ai_requirement_form", border=False):
            left, right = st.columns(2)
            difficulty_ids, difficulty_labels = difficulty_options(locale)
            selected_points = left.multiselect(
                copy["knowledge"],
                knowledge_options(),
                key="ai_knowledge_points",
                format_func=lambda value: knowledge_label(value, locale),
                help=copy["knowledge_help"],
                placeholder=copy["knowledge_placeholder"],
                max_selections=50,
                accept_new_options=True,
                disabled=locked,
            )
            difficulty = right.selectbox(
                copy["difficulty"],
                difficulty_ids,
                key="ai_difficulty",
                format_func=difficulty_labels.get,
                disabled=locked,
            )
            requirement = st.text_area(
                copy["requirement"],
                height=170,
                placeholder=copy["requirement_placeholder"],
                key="ai_requirement",
                disabled=locked,
            )
            free_prompt = st.text_area(
                copy["free_prompt"],
                height=100,
                placeholder=copy["free_prompt_placeholder"],
                key="ai_free_prompt",
                disabled=locked,
            )
            reference = st.text_input(
                copy["reference"],
                key="ai_reference_problem",
                help=copy["reference_help"],
                disabled=locked,
            )
            files = st.file_uploader(
                copy["files"],
                type=_UPLOAD_TYPES,
                accept_multiple_files=True,
                key="ai_reference_files",
                help=copy["files_help"],
                disabled=locked,
                max_upload_size=MAX_ATTACHMENT_BYTES // (1024 * 1024),
            )
            action_label = (
                copy["generate"] if session is None and legacy_task is None else copy["resend"]
            )
            prepare_column, submit_column = st.columns([1, 1])
            prepared = prepare_column.form_submit_button(copy["prepare_files"], disabled=locked)
            submitted = submit_column.form_submit_button(
                action_label, type="primary", disabled=locked
            )
        if locked:
            st.caption(copy["locked"])
            if st.button(copy["edit"], key="ai_edit_requirements"):
                st.session_state["_ai_editing_requirements"] = True
                st.rerun()
        elif active and editing:
            if st.button(copy["discard_edit"], key="ai_discard_requirement_edits"):
                _discard_attachment_edits(client)
                _queue_form_seed(
                    session.get("current_request")
                    if session is not None
                    else st.session_state.get("_ai_legacy_request")
                )
                st.session_state["_ai_editing_requirements"] = False
                st.rerun()
    if prepared:
        _upload_files(client, files, existing_attachments, copy)
    attachment_references, attachments_ready = _render_attachment_manager(
        client, existing_attachments, copy, editable=not locked
    )
    if submitted:
        if not _selected_files_prepared(files, attachment_references):
            st.error(copy["prepare_required"])
        elif not attachments_ready:
            st.error(copy["attachment_confirm_required"])
        else:
            try:
                request = build_authoring_request(
                    requirement=requirement,
                    difficulty_id=difficulty,
                    knowledge_points=selected_points,
                    free_prompt=free_prompt,
                    reference_problem_id=reference,
                    attachments=attachment_references,
                )
            except ValueError as error:
                st.error(
                    copy["empty_requirement"]
                    if str(error) == "empty requirement"
                    else copy["invalid_request"]
                )
            else:
                if session is None:
                    operation = "initial"
                    path = "/api/ai/authoring-sessions/"
                    expected = None
                    body = {"request": request}
                else:
                    operation = "requirements"
                    path = (
                        f"/api/ai/authoring-sessions/{resource(session['session_id'])}/requirements"
                    )
                    expected = int(session.get("current_revision") or 0)
                    body = {"expected_revision": expected, "request": request}
                body["idempotency_key"] = idempotency_key(
                    operation,
                    request,
                    session_id=(
                        str(session.get("session_id"))
                        if session
                        else f"new:{_initial_attempt_id()}"
                    ),
                    expected_revision=expected,
                )
                if session is None and legacy_task is not None:
                    if _cancel_legacy_for_replacement(client, legacy_task, copy):
                        if _start_session_from_legacy(client, request, copy):
                            st.rerun()
                else:
                    ok, result = _mutation(client, "POST", path, copy, payload=body)
                    if ok:
                        _store_session(result)
                        _commit_attachment_edits()
                        st.session_state["_ai_editing_requirements"] = False
                        st.rerun()
    _session_panel(locale, client, config)
    _review_session(locale, client)
    if session is not None and current_status(session) not in ACTIVE:
        if st.button(copy["new_session"], key="ai_new_authoring_session"):
            _discard_attachment_edits(client, clear_records=True)
            st.session_state.pop("_ai_authoring_session", None)
            st.session_state["_ai_task"] = None
            st.session_state.pop("_ai_editing_requirements", None)
            _rotate_initial_attempt()
            _queue_form_seed(None)
            st.rerun()
    with st.expander(copy["restore"]):
        restore_id = st.text_input(copy["session_id"], key="restore_ai_session_id")
        if st.button(copy["load"], disabled=not restore_id.strip() or active):
            try:
                restored = client.request(
                    "GET", f"/api/ai/authoring-sessions/{resource(restore_id.strip())}"
                )
                _discard_attachment_edits(client, clear_records=True)
                _store_session(restored)
                _queue_form_seed(restored.get("current_request"))
                st.session_state["_ai_editing_requirements"] = False
                st.rerun()
            except APIError as error:
                _show_error(error, copy)
    with st.expander(copy["legacy_restore"]):
        legacy_id = st.text_input(copy["legacy_task_id"], key="restore_ai_id")
        if st.button(
            copy["legacy_load"],
            key="load_legacy_ai_task",
            disabled=not legacy_id.strip() or session is not None,
        ):
            ok, result = _mutation(
                client,
                "GET",
                f"/api/ai/problem-tasks/{resource(legacy_id.strip())}",
                copy,
            )
            if ok:
                st.session_state["_ai_task"] = result
                st.session_state.pop("_ai_legacy_request", None)
                st.session_state["_ai_editing_requirements"] = False
                st.rerun()


def _render_legacy_authoring(locale, client, config):
    copy = _copy(locale)
    task = st.session_state.get("_ai_task", {})
    active = task.get("status") in ACTIVE
    editing = bool(st.session_state.get("_ai_editing_legacy_requirements"))
    locked = active and not editing
    with st.container(key="ai_authoring_locked" if locked else "ai_authoring_editing"):
        with st.form("ai_requirement_form", border=False):
            left, right = st.columns(2)
            knowledge = left.text_input(
                copy["knowledge"],
                placeholder=copy["knowledge_placeholder"],
                key="ai_legacy_knowledge",
                disabled=locked,
            )
            level = right.text_input(
                copy["difficulty"],
                key="ai_legacy_difficulty",
                disabled=locked,
            )
            requirement = st.text_area(
                copy["requirement"],
                height=160,
                placeholder=copy["requirement_placeholder"],
                key="ai_requirement",
                disabled=locked,
            )
            reference = st.text_input(
                copy["reference"],
                key="ai_legacy_reference",
                help=copy["reference_help"],
                disabled=locked,
            )
            started = st.form_submit_button(
                copy["resend"] if task else copy["generate"],
                type="primary",
                disabled=locked,
            )
        if locked:
            st.caption(copy["locked"])
            if st.button(copy["edit"], key="ai_edit_legacy_requirements"):
                st.session_state["_ai_editing_legacy_requirements"] = True
                st.rerun()
        elif active and editing:
            if st.button(copy["discard_edit"], key="ai_discard_legacy_edits"):
                st.session_state["_ai_editing_legacy_requirements"] = False
                st.rerun()
    if started:
        if not requirement.strip():
            st.error(copy["empty_requirement"])
        else:
            parts = (
                ([f"{copy['knowledge_prefix']}: {knowledge.strip()}"] if knowledge.strip() else [])
                + ([f"{copy['difficulty_prefix']}: {level.strip()}"] if level.strip() else [])
                + [requirement.strip()]
            )
            payload = {"requirement": "\n".join(parts)}
            if reference.strip():
                payload["problem_id"] = reference.strip()
            if _cancel_legacy_for_replacement(client, task, copy):
                ok, result = _mutation(
                    client,
                    "POST",
                    "/api/ai/problem-tasks/",
                    copy,
                    payload=payload,
                )
                if ok:
                    _remember_legacy_task(task)
                    st.session_state["_ai_task"] = result
                    st.session_state["_ai_legacy_request"] = {
                        "requirement": requirement.strip(),
                        "difficulty_id": "luogu.1",
                        "knowledge_point_ids": [knowledge.strip()] if knowledge.strip() else [],
                        "free_prompt": (
                            f"{copy['difficulty_prefix']}: {level.strip()}" if level.strip() else ""
                        ),
                        "reference_problem_id": reference.strip(),
                        "attachments": [],
                    }
                    st.session_state["_ai_editing_legacy_requirements"] = False
                    st.rerun()
    _legacy_task_panel(locale, client, config)
    legacy = st.session_state.get("_ai_task", {})
    draft, task_id = last_successful_draft(legacy)
    if draft is not None:
        with st.container(key="ai_authoring_review"):
            st.subheader(copy["review"])
            st.caption(copy["review_caption"])
            _review_legacy_draft(
                locale,
                client,
                draft,
                task_id,
                session_capable=False,
            )
    with st.expander(copy["legacy_restore"]):
        restore_id = st.text_input(copy["legacy_task_id"], key="restore_ai_id")
        if st.button(copy["legacy_load"], disabled=not restore_id.strip() or active):
            ok, result = _mutation(
                client,
                "GET",
                f"/api/ai/problem-tasks/{resource(restore_id.strip())}",
                copy,
            )
            if ok:
                st.session_state["_ai_task"] = result
                st.session_state.pop("_ai_legacy_request", None)
                st.session_state["_ai_editing_legacy_requirements"] = False
                st.rerun()


def render_ai_page(client=None, locale=None):
    """Render the page with an optional injected client and explicit locale."""

    client = _client(client)
    locale = locale_code(locale if locale is not None else st.session_state.get("_locale"))
    copy = _copy(locale)
    _authoring_styles()
    st.title(copy["title"])
    st.caption(copy["subtitle"])
    config = client.request("GET", "/api/ai/model-config")
    config_form(config, locale, client)
    if _session_capable(client):
        _render_session_authoring(locale, client, config)
    else:
        _render_legacy_authoring(locale, client, config)


def ai_page(locale=None, client=None):
    """Backward-compatible route entry; both arguments remain optional."""

    return render_ai_page(client=client, locale=locale)


__all__ = ["ai_page", "config_form", "render_ai_page", "usage_display"]
