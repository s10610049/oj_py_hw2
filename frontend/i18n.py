"""Small, strict bilingual catalog shared by the Streamlit frontend.

Page identity and API values remain stable machine keys.  Only presentation
copy is localized.  Unknown keys fail loudly in tests instead of leaking a
half-translated fallback into the interface.
"""

from __future__ import annotations

from string import Formatter
from types import MappingProxyType
from typing import Any

import streamlit as st

SUPPORTED_LOCALES = ("zh-CN", "en")

_PAIRS = {
    # Application shell and common feedback.
    "app.title": ("OJ · 编程练习室", "OJ · Coding Studio"),
    "brand.name": ("编程练习室", "Coding Studio"),
    "language.switch": ("English", "中文"),
    "language.switch_help": ("切换到英文", "Switch to Chinese"),
    "nav.problems": ("题库", "Problems"),
    "nav.submissions": ("提交记录", "Submissions"),
    "nav.analytics": ("成绩总览", "Analytics"),
    "nav.authoring": ("智能命题", "AI Authoring"),
    "nav.account": ("账户", "Account"),
    "nav.admin": ("管理工作区", "Admin Workspace"),
    "nav.group.learning": ("学习工作台", "Learning"),
    "nav.group.creation": ("创作工具", "Creation"),
    "nav.group.admin": ("管理", "Administration"),
    "nav.current": ("当前页面", "Current page"),
    "nav.open": ("打开{page}", "Open {page}"),
    "nav.breadcrumb": ("工作台", "Workspace"),
    "role.admin": ("管理员", "Administrator"),
    "role.user": ("学习者", "Learner"),
    "role.banned": ("已禁用", "Disabled"),
    "action.logout": ("退出登录", "Sign out"),
    "action.retry_connection": ("重试连接", "Retry connection"),
    "action.reload": ("重新加载", "Reload"),
    "session.expired": (
        "会话已失效或账户不可用，请重新登录。",
        "Your session expired or the account is unavailable. Please sign in again.",
    ),
    "session.login_expired": (
        "登录已失效，请重新登录。",
        "Your session expired. Please sign in again.",
    ),
    "session.logged_out": ("已退出登录。", "Signed out."),
    "notice.welcome": ("欢迎回来。", "Welcome back."),
    "table.aria": ("数据表", "Data table"),
    "score.pending": ("尚未返回", "Not returned yet"),
    "error.connection": ("连接暂不可用", "Connection unavailable"),
    "error.input": ("请检查输入", "Check your input"),
    "error.auth": ("登录状态已失效", "Session expired"),
    "error.permission": ("无法执行此操作", "Action not permitted"),
    "error.not_found": ("未找到记录", "Record not found"),
    "error.conflict": ("记录状态已变化", "The record has changed"),
    "error.rate_limit": ("请求过于频繁，请稍后再试", "Too many requests. Try again later"),
    "error.server": ("服务暂时异常", "Service temporarily unavailable"),
    "error.response": ("响应异常", "Invalid service response"),
    "error.generic": ("操作失败", "Action failed"),
    "error.detail_generic": (
        "请稍后重试；若问题持续，请联系管理员。",
        "Try again later. Contact an administrator if the problem continues.",
    ),
    "poll.preserved": (
        "保留上次已确认状态；连接失败不表示后台任务已停止。",
        "The last confirmed state is preserved; a connection failure does not "
        "mean the task stopped.",
    ),
    # Authentication and account management.
    "auth.login": ("登录", "Sign in"),
    "auth.welcome_back": ("欢迎回来", "Welcome back"),
    "auth.create_account": ("创建账户", "Create account"),
    "auth.set_password": ("设置密码", "Set a password"),
    "auth.login_caption": ("继续你的编程练习。", "Continue your coding practice."),
    "auth.register_caption": ("从一次清晰的思考开始。", "Start with one clear line of thought."),
    "auth.step": ("第 {step} 步，共 2 步 · {label}", "Step {step} of 2 · {label}"),
    "auth.username": ("用户名", "Username"),
    "auth.new_username": ("新用户名", "New username"),
    "auth.password": ("密码", "Password"),
    "auth.password_again": ("再次输入密码", "Confirm password"),
    "auth.change_username": ("更换用户名", "Change username"),
    "auth.next": ("下一步", "Next"),
    "auth.back_login": ("返回登录", "Back to sign in"),
    "auth.username_help": (
        "3—40 个字符，使用你的编程练习室用户名。",
        "3–40 characters; use your Coding Studio username.",
    ),
    "auth.password_help": ("至少 6 个字符", "At least 6 characters"),
    "auth.username_invalid": (
        "用户名需 3—40 个字符，且不能全部为空白。",
        "Username must contain 3–40 characters and cannot be only spaces.",
    ),
    "auth.username_required": ("请先输入有效的用户名。", "Enter a valid username first."),
    "auth.password_required": ("请输入密码。", "Enter your password."),
    "auth.password_short": (
        "密码至少需要 6 个字符。",
        "Password must contain at least 6 characters.",
    ),
    "auth.password_mismatch": (
        "两次密码不一致，请重新输入。",
        "Passwords do not match. Enter them again.",
    ),
    "auth.logging_in": ("正在登录…", "Signing in…"),
    "auth.creating": ("正在创建账户…", "Creating account…"),
    "auth.created": (
        "账户已创建。输入密码，开始练习。",
        "Account created. Enter your password to begin.",
    ),
    "auth.invalid_credentials": ("用户名或密码不正确，请重试。", "Incorrect username or password."),
    "auth.banned": (
        "账户已被禁用，请联系管理员。",
        "This account is disabled. Contact an administrator.",
    ),
    "auth.network": ("连接暂不可用，请稍后重试。", "Connection unavailable. Try again later."),
    "auth.footer": ("阅读 · 编写 · 验证，每一步都算数。", "READ · CODE · VERIFY"),
    "account.title": ("账户", "Account"),
    "account.joined": ("{role} · 加入于 {date}", "{role} · Joined {date}"),
    "account.submissions": ("代码提交", "Submissions"),
    "account.solved": ("已通过题目", "Problems solved"),
    "account.user_id": ("用户编号：{user_id}", "User ID: {user_id}"),
    "users.title": ("用户与权限", "Users and permissions"),
    "users.page": ("用户列表页码", "User list page"),
    "users.total": ("共 {count} 位用户", "{count} users"),
    "users.column.id": ("用户编号", "User ID"),
    "users.column.name": ("用户名", "Username"),
    "users.column.role": ("角色", "Role"),
    "users.column.joined": ("加入日期", "Joined"),
    "users.column.submissions": ("提交", "Submissions"),
    "users.column.solved": ("通过题目", "Solved"),
    "users.select": ("选择用户", "Select user"),
    "users.role": ("调整为", "Change role to"),
    "users.confirm": (
        "我已确认所选用户及新的权限",
        "I confirm the selected user and new permissions",
    ),
    "users.update": ("更新角色", "Update role"),
    "users.confirm_required": ("请先确认用户及权限。", "Confirm the user and permissions first."),
    "users.updated": ("用户角色已更新。", "User role updated."),
    "users.empty": ("本页暂无用户。", "No users on this page."),
    "users.create_admin": ("创建管理员账户", "Create administrator account"),
    "users.admin_name": ("管理员用户名", "Administrator username"),
    "users.admin_password": ("管理员密码", "Administrator password"),
    "users.admin_submit": ("创建管理员", "Create administrator"),
    "users.admin_created": ("管理员账户已创建。", "Administrator account created."),
    # Administrative workspace.
    "admin.forbidden": ("此页面仅对管理员开放。", "This page is available to administrators only."),
    "admin.title": ("管理工作区", "Admin Workspace"),
    "admin.tab.overview": ("全员概览", "Cohort overview"),
    "admin.tab.users": ("用户与权限", "Users and permissions"),
    "admin.tab.audit": ("日志访问审计", "Log access audit"),
    "admin.tab.judge": ("题目与评测", "Problems and judging"),
    "admin.audit_owner": ("访问用户编号（可选）", "Accessing user ID (optional)"),
    "admin.audit_problem": ("日志题号（可选）", "Problem ID (optional)"),
    "admin.audit_page": ("审计页码", "Audit page"),
    "admin.audit_query": ("查询访问记录", "Search access records"),
    "admin.audit_empty": ("没有匹配的访问记录。", "No matching access records."),
    "admin.audit_column.user": ("访问用户编号", "Accessing user ID"),
    "admin.audit_column.problem": ("题号", "Problem ID"),
    "admin.audit_column.action": ("操作", "Action"),
    "admin.audit_column.time": ("访问时间", "Access time"),
    "admin.audit_column.status": ("结果", "Result"),
    "admin.audit_action.view_logs": ("查看评测日志", "View judge log"),
    "admin.audit_action.other": ("其他操作", "Other action"),
    "admin.judge_note": (
        "题目删除与日志可见性在题目详情的管理区操作。重新评测在提交详情中操作。",
        "Manage problem deletion and log visibility in problem details. "
        "Rejudge from submission details.",
    ),
    "admin.manage_problems": ("管理题库", "Manage problems"),
    "admin.manage_rejudge": ("查询与重新评测", "Search and rejudge"),
    # Problem editor and validation.
    "field.title": ("题目标题", "Problem title"),
    "field.description": ("题目描述", "Description"),
    "field.input_description": ("输入格式", "Input format"),
    "field.output_description": ("输出格式", "Output format"),
    "field.constraints": ("数据范围与约束", "Constraints"),
    "field.hint": ("提示", "Hint"),
    "field.source": ("来源", "Source"),
    "field.author": ("作者", "Author"),
    "field.source_original": ("来源", "Original source"),
    "field.author_original": ("作者", "Original author"),
    "field.difficulty": ("难度", "Difficulty"),
    "field.difficulty_original": ("原难度 · {value}", "Original difficulty · {value}"),
    "field.difficulty_legacy": (
        "{label}（原值：{value}）",
        "{label} (original: {value})",
    ),
    "field.tags": ("标签（英文逗号分隔）", "Tags (comma-separated)"),
    "field.tags_original": ("标签（英文逗号分隔）", "Original tags (comma-separated)"),
    "field.problem_id": ("题号", "Problem ID"),
    "field.samples": ("样例", "Samples"),
    "field.testcases": ("测试点", "Test cases"),
    "field.time_limit": ("时间限制", "Time limit"),
    "field.memory_limit": ("内存限制", "Memory limit"),
    "form.save_problem": ("保存题目", "Save problem"),
    "form.case_json_help": (
        '样例与测试点使用 JSON 数组，例如 [{"input": "1 2\\n", "output": "3\\n"}]。保留空格与换行。',
        'Samples and test cases use a JSON array, for example [{"input": "1 2\\n", '
        '"output": "3\\n"}]. Spaces and line breaks are preserved.',
    ),
    "form.more": ("提示、来源与资源限制", "Hint, source and resource limits"),
    "form.time_label": ("时间限制（秒，留空继承）", "Time limit (seconds; blank to inherit)"),
    "form.memory_label": ("内存限制（MB，留空继承）", "Memory limit (MB; blank to inherit)"),
    "form.limits_help": (
        "时间与内存分别按题目 → 语言 → 系统默认值继承；留空不会写入固定默认值。",
        "Time and memory limits inherit from problem → language → system defaults; "
        "blank values are not stored as fixed defaults.",
    ),
    "validation.json": ("{label}须为有效 JSON 数组。", "{label} must be a valid JSON array."),
    "validation.case_count": (
        "{label}须包含 1 至 200 组输入输出。",
        "{label} must contain 1–200 input/output pairs.",
    ),
    "validation.case_shape": (
        "{label}每组须含字符串 input 和 output。",
        "Every {label} entry must contain string input and output values.",
    ),
    "validation.case_long": ("{label}单项过长。", "An item in {label} is too long."),
    "validation.number": ("{label}须为{kind}。", "{label} must be {kind}."),
    "validation.integer": ("整数", "an integer"),
    "validation.numeric": ("数字", "a number"),
    "validation.nonnegative": ("非负数", "non-negative"),
    "validation.positive": ("正数", "positive"),
    "validation.problem_id": (
        "题号须为 1—80 位字母、数字、下划线、点或短横线，以字母或数字开头。",
        "Problem ID must contain 1–80 letters, digits, underscores, dots or "
        "hyphens and start with a letter or digit.",
    ),
    "validation.required": ("请填写{label}。", "Enter {label}."),
    # Problem catalog, detail, imports and references.
    "problems.title": ("题库", "Problems"),
    "problems.caption": (
        "从一个问题开始，把解题思路变成可运行的程序。",
        "Start with a problem and turn your reasoning into working code.",
    ),
    "problems.search": ("搜索题目", "Search problems"),
    "problems.search_placeholder": ("题名、题号或知识点", "Title, ID or topic"),
    "problems.add": ("新增题目", "New problem"),
    "problems.all_difficulties": ("全部难度", "All difficulties"),
    "problems.unrated": ("未分级", "Unrated"),
    "problems.status_invalid": (
        "提交状态数据暂不可用，题库仍可正常浏览。",
        "Submission status is unavailable; the catalog remains usable.",
    ),
    "problems.status_failed": (
        "提交状态暂时无法加载，题库仍可正常浏览。",
        "Submission status could not be loaded; the catalog remains usable.",
    ),
    "problems.count": ("{count} 道题目", "{count} problems"),
    "problems.empty": (
        "暂无匹配题目。可调整搜索条件，或新增一道题目。",
        "No matching problems. Adjust the filters or create a problem.",
    ),
    "problems.page": ("题库页码", "Catalog page"),
    "problems.open": ("打开", "Open"),
    "problems.back": ("← 返回题库", "← Back to problems"),
    "problem.sample_input": ("输入 {index}", "Input {index}"),
    "problem.sample_output": ("输出 {index}", "Output {index}"),
    "problem.test_data": ("测试数据 · {count} 组", "Test data · {count} cases"),
    "problem.test_case": ("测试点 {index}", "Test case {index}"),
    "problem.write_submit": ("编写并提交", "Write and submit"),
    "problem.no_languages": (
        "当前暂无可用编程语言，请联系管理员。",
        "No programming language is available. Contact an administrator.",
    ),
    "problem.language": ("编程语言", "Programming language"),
    "problem.code_help": (
        "使用标准输入输出，提交完整程序。代码中的空格与换行将原样发送。",
        "Use standard input/output and submit a complete program. "
        "Spaces and line breaks are preserved.",
    ),
    "problem.code": ("代码", "Code"),
    "problem.submit": ("提交代码", "Submit code"),
    "problem.code_required": ("请先填写代码。", "Enter code before submitting."),
    "problem.submitted": ("代码已提交，正在等待评测。", "Code submitted and waiting for judging."),
    "problem.limit_seconds": ("{value} 秒", "{value} s"),
    "problem.limit_mb": ("{value} MB", "{value} MB"),
    "problem.limit_inherit": ("随语言配置", "Language default"),
    "problem.meta": (
        "{id} · {difficulty} · 时间 {time} · 内存 {memory}",
        "{id} · {difficulty} · Time {time} · Memory {memory}",
    ),
    "problem.byline": ("来源：{source} · 作者：{author}", "Source: {source} · Author: {author}"),
    "problem.not_provided": ("未标注", "Not provided"),
    "problem.original_value": ("{value}", "Original · {value}"),
    "problem.original_tags": ("{value}", "Original tags · {value}"),
    "problem.edit": ("编辑题目", "Edit problem"),
    "problem.tab.statement": ("题目", "Statement"),
    "problem.tab.code": ("编程", "Code"),
    "problem.manage": ("题目管理", "Problem management"),
    "problem.public_logs": (
        "向登录用户公开逐测试点评测日志",
        "Show per-case judge logs to signed-in users",
    ),
    "problem.save_visibility": ("保存日志可见性", "Save log visibility"),
    "problem.visibility_updated": ("日志可见性已更新。", "Log visibility updated."),
    "problem.delete_confirm": (
        "确认删除题目 {id}；已有记录不会因此重新评测",
        "Confirm deletion of {id}; existing submissions will not be rejudged",
    ),
    "problem.delete": ("删除题目", "Delete problem"),
    "problem.deleted": ("题目已删除。", "Problem deleted."),
    "problem.edit_title": ("编辑题目", "Edit problem"),
    "problem.new_title": ("新增题目", "New problem"),
    "problem.editor_caption": (
        "完整填写题面与测试数据。保存后仍可继续编辑。",
        "Complete the statement and test data. You can continue editing after saving.",
    ),
    "problem.editor_original_notice": (
        "正在编辑中文原始题面；同一表单下方可维护完整英文稿。",
        "You are editing the original Chinese statement. The complete English "
        "version is maintained later in this form.",
    ),
    "problem.saved": ("题目已保存。", "Problem saved."),
    "translation.fallback_missing": (
        "暂无可用英文译文；中文原文已隐藏，可切换中文查看。",
        "No English translation is available. The Chinese original is hidden; "
        "switch to Chinese to read it.",
    ),
    "translation.fallback_stale": (
        "英文译文已过期；旧译文与中文原文均已隐藏，请更新译文或切换中文。",
        "The English translation is outdated. Stale English and the Chinese original "
        "are hidden; update the translation or switch to Chinese.",
    ),
    "translation.metadata_missing": (
        "有 {count} 项可选元数据尚无英文译文。",
        "{count} optional metadata item(s) have no English translation and are hidden.",
    ),
    "translation.manage": ("英文译文", "English translation"),
    "translation.form_help": (
        "选填完整英文题面；填写任一项后，除提示外其余五项必须完整。代码、样例和测试数据不会翻译。",
        "Optional complete English statement. Once any field is filled, all five required "
        "fields must be complete. Code, samples, and judge data are never translated.",
    ),
    "translation.problem_title_missing": (
        "题目 {id} · 英文译文暂缺",
        "Problem {id} · English translation unavailable",
    ),
    "translation.english_only": (
        "英文译文不能包含中文字符。",
        "English translation fields cannot contain Chinese characters.",
    ),
    "translation.save": ("保存英文译文", "Save English translation"),
    "translation.delete": ("删除英文译文", "Delete English translation"),
    "translation.saved": ("英文译文已保存。", "English translation saved."),
    "translation.deleted": ("英文译文已删除。", "English translation deleted."),
    "translation.delete_confirm": (
        "确认删除当前英文译文",
        "Confirm deletion of the current English translation",
    ),
    "import.title": ("从 ZIP 导入题目", "Import problem from ZIP"),
    "import.manual": ("手工出题", "Manual editor"),
    "import.help": (
        "支持 OJ Problem Archive v1，或洛谷数据 ZIP。先生成安全预览，再明确确认写入题库。",
        "Supports OJ Problem Archive v1 and Luogu data ZIPs. A safe preview is "
        "required before an explicit commit.",
    ),
    "import.template_download": ("下载标准题目包模板", "Download standard archive template"),
    "import.guide_title": ("格式说明", "Format guide"),
    "import.guide": (
        "**标准题目包**：ZIP 根目录放 `problem.json`，题面放在 "
        "`statements/zh-CN/` 与可选的 `statements/en/`，样例放 `data/sample/`，"
        "隐藏测试点放 `data/secret/`。所有文本使用 UTF-8；每个 `.in` 必须配对同名 "
        "`.out` 或 `.ans`。当前仅支持标准输出比较。下载模板后直接替换内容即可。\n\n"
        "**洛谷数据包**：ZIP 根目录平铺成对的 `.in/.out`（或 `.ans`）文件；此格式只含测试数据，"
        "选择“洛谷数据包”后还需在页面补齐题号、题面、样例和元数据。",
        "**Standard archive**: put `problem.json` at the ZIP root, statements under "
        "`statements/zh-CN/` and optionally `statements/en/`, samples under `data/sample/`, "
        "and hidden cases under `data/secret/`. Use UTF-8 text and pair every `.in` with "
        "a same-named `.out` or `.ans`. Only standard output comparison is supported. "
        "Download the template and replace its example content.\n\n"
        "**Luogu data archive**: place paired `.in/.out` (or `.ans`) files directly at the ZIP "
        "root. It contains test data only, so select “Luogu data archive” and complete the ID, "
        "statement, samples, and metadata on this page.",
    ),
    "import.file": ("选择 ZIP 文件", "Choose a ZIP file"),
    "import.format": ("导入格式", "Import format"),
    "import.native": ("标准 OJ 题目包", "Standard OJ archive"),
    "import.luogu": ("洛谷数据包", "Luogu data archive"),
    "import.upload_preview": ("上传并生成预览", "Upload and preview"),
    "import.file_required": ("请选择一个 ZIP 文件。", "Choose a ZIP file."),
    "import.file_too_large": (
        "ZIP 文件超过 16 MiB 限制。",
        "The ZIP file exceeds the 16 MiB limit.",
    ),
    "import.preview": ("导入预览", "Import preview"),
    "import.problem": ("题目：{title}（{id}）", "Problem: {title} ({id})"),
    "import.cases": (
        "样例 {samples} 组 · 测试点 {testcases} 组",
        "{samples} samples · {testcases} test cases",
    ),
    "import.missing": ("缺少必填内容：{fields}", "Missing required content: {fields}"),
    "import.warning": ("预览包含提示：{warnings}", "Preview warnings: {warnings}"),
    "import.warning.translation_missing": ("未附英文译文", "English translation missing"),
    "import.warning.luogu_data_only": ("洛谷包仅包含数据", "Luogu archive contains data only"),
    "import.warning.limits_not_provided": ("未提供资源限制", "Resource limits not provided"),
    "import.warning.other": ("其他解析提示（{code}）", "Other parser notice ({code})"),
    "import.conflict": (
        "题号已存在。覆盖会保留原日志可见性，但题目版本会更新。",
        "This problem ID exists. Overwriting preserves log visibility but "
        "updates the problem version.",
    ),
    "import.overwrite": ("确认覆盖现有题目", "Confirm overwrite"),
    "import.confirm": ("确认导入题库", "Commit import"),
    "import.not_ready": (
        "当前预览尚不能导入，请补齐数据并重新预览。",
        "This preview cannot be committed. Complete the data and preview again.",
    ),
    "import.committed": ("题目已导入题库。", "Problem imported."),
    "import.selection_changed": (
        "ZIP、格式或洛谷元数据已改变，请重新生成预览。",
        "The ZIP, format or Luogu metadata changed. Generate a new preview.",
    ),
    "import.expired": (
        "导入预览已过期，请重新生成。",
        "The import preview expired. Preview again.",
    ),
    "import.filename": ("文件：{value}", "File: {value}"),
    "import.format_value": ("格式：{value}", "Format: {value}"),
    "import.languages": ("题面语言：{value}", "Statement languages: {value}"),
    "import.translation_included": ("中文、英文", "Chinese and English"),
    "import.translation_missing": (
        "仅中文（未附英文译文）",
        "Chinese only (no English translation)",
    ),
    "import.limits": ("限制：时间 {time} · 内存 {memory}", "Limits: time {time} · memory {memory}"),
    "import.digest": ("ZIP SHA-256：{value}", "ZIP SHA-256: {value}"),
    "import.expires": ("预览有效至：{value}", "Preview expires: {value}"),
    "import.can_commit": ("服务端可提交：{value}", "Server can commit: {value}"),
    "common.yes": ("是", "Yes"),
    "common.no": ("否", "No"),
    "attachment.title": ("参考附件", "Reference attachments"),
    "attachment.help": (
        "附件只作为出题参考，内容不会执行。最多 8 个文件、每个不超过 10 MiB。",
        "Attachments are reference data only and are never executed. Up to 8 files, 10 MiB each.",
    ),
    "attachment.image_notice": (
        "当前模型不读取图片画面；图片仅校验并记录尺寸等元数据，不会虚构视觉理解。",
        "The current model does not inspect image pixels. Images are validated "
        "as metadata only; no visual understanding is claimed.",
    ),
    "attachment.files": ("选择参考文件", "Choose reference files"),
    "attachment.parse": ("解析所选附件", "Parse selected attachments"),
    "attachment.none": ("请先选择文件。", "Choose at least one file."),
    "attachment.too_many": ("一次最多选择 8 个附件。", "Select at most 8 attachments."),
    "attachment.total_too_large": (
        "附件总大小不能超过 32 MiB。",
        "Attachments may total at most 32 MiB.",
    ),
    "attachment.too_large": (
        "附件 {name} 超过 10 MiB 限制。",
        "Attachment {name} exceeds the 10 MiB limit.",
    ),
    "attachment.ready": ("已解析 {count} 个附件。", "Parsed {count} attachments."),
    "attachment.remove": ("移除", "Remove"),
    "attachment.preview": ("内容预览", "Content preview"),
    "attachment.text_ready": ("可作为文本参考", "Text reference ready"),
    "attachment.metadata_only": ("仅元数据", "Metadata only"),
    "attachment.meta": ("{kind} · {size}", "{kind} · {size}"),
    "attachment.kind.text": ("文本", "Text"),
    "attachment.kind.code": ("代码", "Code"),
    "attachment.kind.document": ("文档", "Document"),
    "attachment.kind.spreadsheet": ("表格", "Spreadsheet"),
    "attachment.kind.presentation": ("演示文稿", "Presentation"),
    "attachment.kind.image": ("图片", "Image"),
    "attachment.kind.archive": ("压缩包", "Archive"),
    "attachment.kind.unknown": ("文件", "File"),
    "attachment.expires": ("临时保存至 {time}", "Temporarily stored until {time}"),
    "attachment.warning": ("解析提示：{codes}", "Parser notices: {codes}"),
    "attachment.manual_note": (
        "这些附件用于你核对和整理题面；保存题目时不会把临时附件写入公开题面。",
        "Use these temporary attachments while editing. Saving the problem does "
        "not publish them in the statement.",
    ),
    "attachment.handoff": ("转入 AI 智能命题", "Continue in AI Authoring"),
    "attachment.handoff_help": (
        "仅把安全附件引用带入智能命题，不会写入公开题面。",
        "Only safe attachment references are carried into AI Authoring; they are not published.",
    ),
    "manual_ai.title": ("AI 整理题目", "Organize with AI"),
    "manual_ai.help": (
        "把当前表单与已解析附件交给 AI 整理；结果只回填到本页，仍需你审核并保存。",
        "AI uses the current form and parsed attachments. The result only refills this page; "
        "you still review and save it.",
    ),
    "manual_ai.instruction": ("补充整理要求（可选）", "Additional instructions (optional)"),
    "manual_ai.instruction_placeholder": (
        "例如：保留题目背景，补齐边界测试并让题面更清晰。",
        "For example: keep the scenario, add edge cases, and clarify the statement.",
    ),
    "manual_ai.action": ("AI 整理 / 补全", "Organize / complete with AI"),
    "manual_ai.progress": ("AI 整理进度 {percent}%", "AI organization {percent}%"),
    "manual_ai.running": ("正在整理题面与测试数据。", "Organizing the statement and tests."),
    "manual_ai.connecting": ("正在连接模型并提交草稿。", "Connecting and sending the draft."),
    "manual_ai.receiving": ("正在接收并检查模型输出。", "Receiving and checking model output."),
    "manual_ai.validating": ("正在校验参考解与测试数据。", "Validating the solution and tests."),
    "manual_ai.repairing": ("正在进行有限自动修正。", "Applying a bounded automatic repair."),
    "manual_ai.stop": ("停止整理", "Stop"),
    "manual_ai.cancelled": (
        "整理已停止，当前表单和附件均已保留。",
        "Organization stopped. The current form and attachments are preserved.",
    ),
    "manual_ai.restarted": (
        "服务重启中断了本轮整理，当前表单和附件均已保留。",
        "A service restart interrupted this run. The current form and attachments are preserved.",
    ),
    "manual_ai.failed": (
        "本轮 AI 整理未完成，当前表单和附件均已保留，可调整要求后重试。",
        "AI organization did not finish. The current form and attachments are preserved; "
        "adjust the instructions and retry.",
    ),
    "manual_ai.error_code": ("错误代码：{code}", "Error code: {code}"),
    "manual_ai.invalid": (
        "当前草稿、标签或附件超出命题请求限制，请精简后重试。",
        "The draft, tags, or attachments exceed the authoring request limits. "
        "Reduce them and retry.",
    ),
    "manual_ai.invalid_result": (
        "AI 返回的题目未通过本地格式校验，当前表单没有被覆盖。",
        "The AI result failed local format checks. The current form was not overwritten.",
    ),
    "manual_ai.changed": (
        "AI 整理期间表单内容发生过变化。请确认后再用 AI 草稿覆盖当前字段。",
        "The form changed while AI was working. Confirm before replacing the current fields.",
    ),
    "manual_ai.apply": ("应用 AI 草稿到表单", "Apply AI draft to form"),
    "manual_ai.applied": (
        "AI 草稿已回填；请继续编辑和审核，确认后再保存题目。",
        "The AI draft is in the form. Continue editing and review it before saving.",
    ),
    # Submission pages.
    "submission.status.pending": ("评测中", "Judging"),
    "submission.status.success": ("评测完成", "Judged"),
    "submission.status.error": ("评测异常", "Judge error"),
    "submission.received": ("代码已接收，正在评测", "Code received and being judged"),
    "submission.task_error": (
        "评测任务异常，请查看错误信息。",
        "The judge task failed. See the error details.",
    ),
    "submission.accepted": ("全部通过 · AC", "Accepted · AC"),
    "submission.incomplete": (
        "评测完成，尚未全部通过。请查看编译、运行信息或授权日志。",
        "Judging finished without full acceptance. Review compile/run information "
        "or an authorized log.",
    ),
    "submission.score": ("得分：{score}", "Score: {score}"),
    "submission.compile": ("编译信息", "Compile information"),
    "submission.run": ("运行结果", "Run result"),
    "submission.error": ("错误信息", "Error information"),
    "submission.result.success": ("成功", "Success"),
    "submission.result.error": ("失败", "Error"),
    "submission.result.finished": ("已完成", "Finished"),
    "submission.message.compilation_limit": (
        "编译超过资源或时间限制。",
        "Compilation exceeded its resource or time limit.",
    ),
    "submission.message.service_restarted": (
        "评测被服务重启中断，请重新评测。",
        "Judging was interrupted by a service restart. Please rejudge.",
    ),
    "submission.message.infrastructure_failed": (
        "判题基础设施未能完成本次提交。",
        "Judge infrastructure could not complete this submission.",
    ),
    "submission.message.judge_incomplete": (
        "判题器未能完成本次提交。",
        "The judge could not complete this submission.",
    ),
    "submission.message.cases_finished": (
        "{count} 个测试点已完成。",
        "{count} test cases finished.",
    ),
    "submission.message.overall_errors": (
        "未通过结果：{errors}",
        "Non-accepted results: {errors}",
    ),
    "submission.technical_diagnostic": (
        "以下为编译器或运行环境返回的原始技术诊断。",
        "The following is a raw technical diagnostic from the compiler or runtime.",
    ),
    "submission.verdict.AC": ("通过 · AC", "Accepted · AC"),
    "submission.verdict.WA": ("答案错误 · WA", "Wrong answer · WA"),
    "submission.verdict.CE": ("编译错误 · CE", "Compile error · CE"),
    "submission.verdict.TLE": ("运行超时 · TLE", "Time limit exceeded · TLE"),
    "submission.verdict.MLE": ("内存超限 · MLE", "Memory limit exceeded · MLE"),
    "submission.verdict.RE": ("运行错误 · RE", "Runtime error · RE"),
    "submission.verdict.UNK": ("判题异常 · UNK", "Judge error · UNK"),
    "submission.log_score": ("日志得分：{score}", "Log score: {score}"),
    "submission.log_private": (
        "本题未公开逐测试点结果；当前权限仅可查看总分。",
        "Per-case results are private; your permission allows only the total score.",
    ),
    "submission.log_pending": ("尚未产生逐测试点结果。", "No per-case results yet."),
    "submission.column.case": ("测试点", "Test case"),
    "submission.column.result": ("结果", "Result"),
    "submission.column.time": ("耗时（秒）", "Time (s)"),
    "submission.column.memory": ("内存（MiB）", "Memory (MiB)"),
    "submission.back": ("← 返回提交列表", "← Back to submissions"),
    "submission.detail": ("提交详情", "Submission details"),
    "submission.id": ("提交编号：{id}", "Submission ID: {id}"),
    "submission.meta": (
        "题目 {problem} · {language} · {time}",
        "Problem {problem} · {language} · {time}",
    ),
    "submission.refresh": ("刷新评测状态", "Refresh judge status"),
    "submission.view_code": ("查看本次提交代码", "View submitted code"),
    "submission.query_log": ("查询评测日志", "View judge log"),
    "submission.admin": ("管理员操作", "Administrator actions"),
    "submission.rejudge_confirm": (
        "重新评测会覆盖本次评测结果",
        "Rejudging will replace this result",
    ),
    "submission.rejudge": ("重新评测", "Rejudge"),
    "submission.rejudge_started": ("已开始重新评测。", "Rejudge started."),
    "submissions.title": ("提交记录", "Submissions"),
    "submissions.caption": (
        "每一次提交，都留下可回看的解题轨迹。",
        "Every submission leaves a trace you can revisit.",
    ),
    "submissions.problem_filter": ("题号筛选（可选）", "Problem ID (optional)"),
    "submissions.status_filter": ("评测状态", "Judge status"),
    "submissions.all": ("全部", "All"),
    "submissions.owner": ("用户编号", "User ID"),
    "submissions.query": ("查询记录", "Search submissions"),
    "submissions.filter_required": (
        "请填写用户编号或题号。管理员可清空用户编号，查询某题的全部提交。",
        "Enter a user ID or problem ID. Administrators may leave the user ID blank "
        "to search all submissions for a problem.",
    ),
    "submissions.page": ("提交列表页码", "Submission list page"),
    "submissions.total": ("共 {count} 次提交", "{count} submissions"),
    "submissions.column.id": ("提交编号", "Submission ID"),
    "submissions.column.problem": ("题目", "Problem"),
    "submissions.column.language": ("语言", "Language"),
    "submissions.column.status": ("状态", "Status"),
    "submissions.column.score": ("得分", "Score"),
    "submissions.column.time": ("提交时间", "Submitted"),
    "submissions.select": ("选择提交查看详情", "Select a submission"),
    "submissions.open": ("打开提交", "Open submission"),
    "submissions.empty": ("本页暂无提交记录。", "No submissions on this page."),
    "submissions.direct": ("通过提交编号查询", "Find by submission ID"),
    "submissions.direct_id": ("提交编号", "Submission ID"),
    "submissions.direct_detail": ("查询提交详情", "Open submission details"),
    "submissions.direct_log": ("查询公开日志", "View public log"),
    # Shared visual copy.
    "story.kicker": ("A SPACE TO THINK IN CODE", "A SPACE TO THINK IN CODE"),
    "story.title": ("让思路成形，<br>让代码作答。", "SHAPE THE IDEA.<br>LET CODE ANSWER."),
    "story.body": (
        "从读懂一道题，到写出可靠的程序。<br>把每一次思考，变成看得见的进步。",
        "From understanding a problem to writing reliable code.<br>Turn each "
        "thought into visible progress.",
    ),
    "story.step1": ("阅读题目与边界", "Read the problem and boundaries"),
    "story.step2": ("编写你的解法", "Write your solution"),
    "story.step3": ("验证与继续探索", "Verify and keep exploring"),
    "story.bottom": ("READ · CODE · REFINE", "READ · CODE · REFINE"),
    "loading.waiting": ("正在等待任务更新", "Waiting for a task update"),
    "loading.elapsed": ("已耗时 {seconds} 秒", "Elapsed {seconds} s"),
    "loading.phrase1": (
        "先把问题说清楚，再让代码说话。",
        "Clarify the problem, then let code speak.",
    ),
    "loading.phrase2": (
        "边界条件，也是题目的一部分。",
        "Boundary conditions are part of the problem.",
    ),
    "loading.phrase3": ("让每个样例，都讲清一条规则。", "Let every sample explain one rule."),
    "loading.phrase4": (
        "清晰的约束，成就可靠的程序。",
        "Clear constraints lead to reliable programs.",
    ),
}


def normalize_locale(value: Any) -> str:
    if not isinstance(value, str):
        return "zh-CN"
    normalized = value.strip().lower()
    return "en" if normalized in {"en", "en-us", "english"} else "zh-CN"


def locale() -> str:
    return normalize_locale(st.session_state.get("_locale", "zh-CN"))


def set_locale(value: Any) -> None:
    st.session_state["_locale"] = normalize_locale(value)


def t(key: str, locale_code: str | None = None, **values: Any) -> str:
    selected = normalize_locale(locale_code) if locale_code is not None else locale()
    try:
        template = MESSAGES[selected][key]
    except KeyError:
        raise KeyError(f"unknown translation key: {key}") from None
    return template.format(**values) if values else template


def placeholders(value: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(value) if name}


def other_locale(value: Any = None) -> str:
    current = locale() if value is None else normalize_locale(value)
    return "zh-CN" if current == "en" else "en"


def role_label(role: Any, locale_code: str | None = None) -> str:
    key = f"role.{role}"
    if key not in _PAIRS:
        return t("role.user", locale_code)
    return t(key, locale_code)


def api_error_message(message: Any, locale_code: str | None = None) -> str:
    """Translate known transport/auth messages; hide unknown mixed-language text."""

    known = {
        "Account is banned": "auth.banned",
        "Login required": "session.login_expired",
        "请求超时。请重试查询；写入请求可能已处理，请先核对结果。": "error.detail_generic",
        "暂时无法连接服务，请确认后端已启动后重试。": "error.detail_generic",
        "服务返回了无法识别的响应，请稍后重试。": "error.detail_generic",
        "服务响应格式不符合约定，请联系管理员。": "error.detail_generic",
    }
    key = known.get(str(message), "error.detail_generic")
    return t(key, locale_code)


MESSAGES = MappingProxyType(
    {
        locale_code: MappingProxyType(
            {key: pair[0 if locale_code == "zh-CN" else 1] for key, pair in _PAIRS.items()}
        )
        for locale_code in SUPPORTED_LOCALES
    }
)


__all__ = (
    "MESSAGES",
    "SUPPORTED_LOCALES",
    "api_error_message",
    "locale",
    "normalize_locale",
    "other_locale",
    "placeholders",
    "role_label",
    "set_locale",
    "t",
)
