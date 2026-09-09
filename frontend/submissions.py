"""Submission list, live results and explicitly requested authorized logs."""

import re

import streamlit as st

from frontend.client import APIError, resource
from frontend.common import (
    api,
    data_table,
    go,
    is_admin,
    mutation,
    notice,
    poll_error,
    score_text,
    user,
)
from frontend.i18n import locale as current_locale
from frontend.i18n import t

STATUS = {"pending": "评测中", "success": "评测完成", "error": "评测异常"}
VERDICTS = {"AC", "WA", "CE", "TLE", "MLE", "RE", "UNK"}
INFO_RESULTS = {"success", "error", "finished"}


def verdict_label(value, locale_code=None):
    code = str(value or "").strip().upper()
    return t(f"submission.verdict.{code}", locale_code) if code in VERDICTS else code


def info_result_label(value, locale_code=None):
    key = str(value or "").strip().lower()
    return t(f"submission.result.{key}", locale_code) if key in INFO_RESULTS else str(value or "")


def message_projection(value, locale_code=None):
    """Localize structured judge prose and explicitly mark opaque diagnostics."""

    text = str(value or "").strip()
    selected = current_locale() if locale_code is None else locale_code
    known = {
        "Compilation exceeded its limit": "submission.message.compilation_limit",
        "评测被服务重启中断，请重新评测": "submission.message.service_restarted",
        "Judge infrastructure failed": "submission.message.infrastructure_failed",
        "Judge could not complete this submission": "submission.message.judge_incomplete",
    }
    if text in known:
        return t(known[text], locale_code), False
    summary = re.fullmatch(
        r"(?P<count>\d+) test cases finished(?:\nOverall errors: (?P<errors>.+))?",
        text,
    )
    if summary:
        lines = [t("submission.message.cases_finished", locale_code, count=summary["count"])]
        if summary["errors"]:
            errors = (", " if selected == "en" else "、").join(
                verdict_label(item.strip(), locale_code)
                for item in summary["errors"].split(",")
                if item.strip()
            )
            lines.append(t("submission.message.overall_errors", locale_code, errors=errors))
        return "\n".join(lines), False
    if selected == "en" and any("\u3400" <= character <= "\u9fff" for character in text):
        return t("submission.message.infrastructure_failed", locale_code), False
    return text, bool(text)


def status_label(value):
    return t(f"submission.status.{value}") if value in STATUS else str(value)


def render_result(record):
    status = record["status"]
    if status == "pending":
        st.status(t("submission.received"), state="running", type="compact")
    elif status == "error":
        st.error(t("submission.task_error"))
    elif record.get("counts") and record.get("score") == record["counts"]:
        st.success(t("submission.accepted"))
    else:
        st.warning(t("submission.incomplete"))
    st.write(t("submission.score", score=score_text(record)))
    for key, title in (
        ("compile_info", t("submission.compile")),
        ("run_info", t("submission.run")),
    ):
        value = record.get(key)
        if value:
            st.subheader(title)
            st.write(info_result_label(value.get("result", "")))
            if value.get("message"):
                message, technical = message_projection(value["message"])
                if technical:
                    st.caption(t("submission.technical_diagnostic"))
                st.code(message, language="text")
    if record.get("error_info"):
        st.subheader(t("submission.error"))
        message, technical = message_projection(record["error_info"])
        if technical:
            st.caption(t("submission.technical_diagnostic"))
        st.code(message, language="text")


def render_log(log):
    st.write(t("submission.log_score", score=score_text(log)))
    if "details" not in log:
        st.info(t("submission.log_private"))
    elif not log["details"]:
        st.caption(t("submission.log_pending"))
    else:
        data_table(
            [
                {
                    t("submission.column.case"): item["id"],
                    t("submission.column.result"): verdict_label(item["result"]),
                    t("submission.column.time"): item["time"],
                    t("submission.column.memory"): item["memory"],
                }
                for item in log["details"]
            ],
        )


def submission_detail(submission_id):
    st.button(
        t("submission.back"),
        on_click=go,
        args=("提交记录",),
        kwargs={"_submission_id": None},
    )
    st.title(t("submission.detail"))
    st.caption(t("submission.id", id=submission_id))
    cache_key = f"_submission_{submission_id}"
    cached = st.session_state.get(cache_key)
    active = not cached or cached.get("status") == "pending"

    @st.fragment(run_every=1 if active else None)
    def panel():
        previous = st.session_state.get(cache_key)
        try:
            current = (
                api().request("GET", f"/api/submissions/{resource(submission_id)}")
                if active or not previous
                else previous
            )
            st.session_state[cache_key] = current
        except APIError as exc:
            poll_error(exc)
            if previous:
                render_result(previous)
            return
        if active and current["status"] != "pending":
            st.rerun(scope="app")
        if current.get("problem_id"):
            st.caption(
                t(
                    "submission.meta",
                    problem=current["problem_id"],
                    language=current.get("language", ""),
                    time=current.get("created_at", ""),
                )
            )
        render_result(current)
        if st.button(t("submission.refresh"), key=f"refresh_{submission_id}"):
            st.session_state.pop(cache_key, None)
            st.rerun(scope="app")
        if current.get("code") is not None:
            with st.expander(t("submission.view_code")):
                language = "cpp" if current.get("language") == "cpp" else "python"
                st.code(current["code"], language=language)
        st.divider()
        if st.button(t("submission.query_log"), key=f"log_{submission_id}"):
            ok, data = mutation("GET", f"/api/submissions/{resource(submission_id)}/log")
            if ok:
                st.session_state[f"_log_{submission_id}"] = data
        if f"_log_{submission_id}" in st.session_state:
            render_log(st.session_state[f"_log_{submission_id}"])
        if is_admin():
            with st.expander(t("submission.admin")):
                confirmed = st.checkbox(
                    t("submission.rejudge_confirm"), key=f"confirm_rejudge_{submission_id}"
                )
                if st.button(
                    t("submission.rejudge"),
                    disabled=not confirmed,
                    key=f"rejudge_{submission_id}",
                ):
                    ok, _ = mutation("PUT", f"/api/submissions/{resource(submission_id)}/rejudge")
                    if ok:
                        st.session_state.pop(cache_key, None)
                        st.session_state.pop(f"_log_{submission_id}", None)
                        notice(t("submission.rejudge_started"))
                        st.rerun(scope="app")

    panel()


def submission_list():
    st.title(t("submissions.title"))
    st.caption(t("submissions.caption"))
    with st.form("submission_filters", border=False):
        a, b, c = st.columns(3)
        problem_id = a.text_input(t("submissions.problem_filter"))
        status = b.selectbox(
            t("submissions.status_filter"),
            ["all"] + list(STATUS),
            format_func=lambda x: t("submissions.all") if x == "all" else status_label(x),
        )
        owner = c.text_input(
            t("submissions.owner"), value=user()["user_id"], disabled=not is_admin()
        )
        st.form_submit_button(t("submissions.query"), type="primary")
    if not owner.strip() and not problem_id.strip():
        st.info(t("submissions.filter_required"))
        return
    page = st.number_input(t("submissions.page"), min_value=1, value=1, step=1)
    params = {"page": page, "page_size": 20}
    if owner.strip():
        params["user_id"] = owner.strip()
    if problem_id.strip():
        params["problem_id"] = problem_id.strip()
    if status != "all":
        params["status"] = status
    result = api().request("GET", "/api/submissions/", params=params)
    st.caption(t("submissions.total", count=result["total"]))
    records = result["submissions"]
    if records:
        data_table(
            [
                {
                    t("submissions.column.id"): x["submission_id"],
                    t("submissions.column.problem"): x.get("problem_id", ""),
                    t("submissions.column.language"): x.get("language", ""),
                    t("submissions.column.status"): status_label(x["status"]),
                    t("submissions.column.score"): score_text(x),
                    t("submissions.column.time"): x.get("created_at", ""),
                }
                for x in records
            ],
        )
        selected = st.selectbox(t("submissions.select"), [x["submission_id"] for x in records])
        st.button(
            t("submissions.open"),
            on_click=go,
            args=("提交记录",),
            kwargs={"_submission_id": selected},
        )
    else:
        st.info(t("submissions.empty"))
    with st.expander(t("submissions.direct")):
        value = st.text_input(t("submissions.direct_id"), key="direct_submission_id")
        if st.button(t("submissions.direct_detail"), disabled=not value.strip()):
            go("提交记录", _submission_id=value.strip())
            st.rerun()
        if st.button(t("submissions.direct_log"), disabled=not value.strip()):
            ok, data = mutation("GET", f"/api/submissions/{resource(value.strip())}/log")
            if ok:
                render_log(data)


def submissions_page():
    submission_id = st.session_state.get("_submission_id")
    if submission_id:
        submission_detail(submission_id)
    else:
        submission_list()
