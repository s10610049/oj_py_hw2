"""Model configuration, real asynchronous task progress and editable drafts."""

import streamlit as st

from frontend.client import APIError, resource
from frontend.common import api, go, mutation, notice, poll_error
from frontend.forms import optional_number, problem_form
from frontend.styles import loading

ACTIVE = {"pending", "running"}
LABELS = {
    "pending": "等待生成",
    "running": "正在生成",
    "completed": "生成完成",
    "cancelled": "已取消",
    "failed": "生成失败",
}


def config_form(config):
    with st.expander("模型与计价配置", expanded=not config.get("api_key_configured")):
        st.caption("密钥仅用于本账户的模型调用；已保存的密钥不会显示。费用按下方输入的价格计算。")
        with st.form("ai_config_form", border=False):
            provider = st.text_input(
                "提供商 URL",
                value=config.get("provider_url", ""),
                placeholder="https://api.example.com/v1",
            )
            model = st.text_input("模型名称", value=config.get("model", ""))
            key = st.text_input(
                "模型 API Key",
                type="password",
                key="ai_api_key",
                help="已配置时可留空保留密钥；更换提供商需重新输入。界面不读取已保存密钥。",
            )
            a, b = st.columns(2)
            price_in = a.text_input(
                "输入单价（未知留空）",
                value="" if config.get("input_price") is None else str(config["input_price"]),
            )
            price_out = b.text_input(
                "输出单价（未知留空）",
                value="" if config.get("output_price") is None else str(config["output_price"]),
            )
            unit = a.number_input(
                "计价 Token 单位",
                min_value=1,
                value=int(config.get("price_unit") or 1_000_000),
                step=1000,
            )
            currency = b.text_input("币种", value=config.get("currency") or "CNY")
            submitted = st.form_submit_button("保存模型配置", type="primary")
        if config.get("api_key_configured"):
            st.caption("✓ 后端已配置密钥")
        if submitted:
            try:
                if not provider.strip() or not model.strip():
                    raise ValueError("请填写提供商 URL 与模型名称。")
                if not key.strip() and not config.get("api_key_configured"):
                    raise ValueError("请填写模型密钥。")
                payload = {
                    "provider_url": provider.strip(),
                    "model": model.strip(),
                    "api_key": key,
                    "input_price": optional_number(price_in, "输入单价", allow_zero=True),
                    "output_price": optional_number(price_out, "输出单价", allow_zero=True),
                    "price_unit": int(unit),
                    "currency": currency.strip(),
                }
                ok, _ = mutation("PUT", "/api/ai/model-config", json=payload)
                if ok:
                    st.session_state["_clear_secrets"] = True
                    notice("模型配置已保存，将用于下一次生成。")
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def usage_display(usage):
    if not usage:
        st.caption("Token 与费用尚未返回。")
        return
    source = usage.get("source") or "unavailable"
    estimated = source in {"estimated", "mixed"}
    columns = st.columns(4)
    for col, field, label in zip(
        columns[:3],
        ("input_tokens", "output_tokens", "total_tokens"),
        ("输入 Token", "输出 Token", "总 Token"),
    ):
        value = usage.get(field)
        col.metric(label, "尚未返回" if value is None else ("≈ " if estimated else "") + str(value))
    cost = usage.get("cost")
    columns[3].metric(
        "估算费用",
        "未知" if cost is None else f"{cost:.8g} {usage.get('currency', '')}",
    )


def task_panel():
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
                api().request("GET", f"/api/ai/problem-tasks/{resource(task_id)}")
                if active
                else previous
            )
            st.session_state["_ai_task"] = task
        except APIError as exc:
            poll_error(exc)
            task = previous
        if active and task.get("status") not in ACTIVE:
            st.rerun(scope="app")
        status = task.get("status")
        st.caption(f"任务编号：{task_id}")
        if status in ACTIVE:
            loading(task.get("progress"), task.get("elapsed_seconds"))
            if st.button("停止生成", key=f"cancel_{task_id}"):
                with st.spinner("正在请求停止…"):
                    ok, result = mutation(
                        "PUT", f"/api/ai/problem-tasks/{resource(task_id)}/cancel"
                    )
                if ok:
                    st.session_state["_ai_task"] = result
                    st.rerun(scope="app")
        elif status == "completed":
            st.success("生成完成，可以审阅和编辑草稿。尚未保存到题库。")
        elif status == "cancelled":
            st.info("任务已取消。")
        else:
            st.error(task.get("error") or "生成未完成，请检查配置后重试。")
        if status not in ACTIVE:
            st.caption(
                f"耗时：{float(task.get('elapsed_seconds') or 0):.1f} 秒 · "
                f"{task.get('progress') or LABELS.get(status, status)}"
            )
        usage_display(task.get("usage"))
        if st.button("刷新任务", key=f"refresh_ai_{task_id}"):
            ok, result = mutation("GET", f"/api/ai/problem-tasks/{resource(task_id)}")
            if ok:
                st.session_state["_ai_task"] = result
                st.rerun(scope="app")

    panel()


def draft_editor(task):
    draft = task.get("result")
    if task.get("status") != "completed" or not isinstance(draft, dict):
        return
    st.divider()
    st.subheader("审阅并保存")
    st.caption("核对题意、样例和测试点，再选择新增或更新。参考程序与模型自述不等于判题验证通过。")
    quality = draft.get("quality", {})
    if quality.get("reference_checked"):
        st.caption(
            f"已运行参考解核对 {quality.get('checked_cases', 0)} 个测试点，"
            f"其中确定性构造 {quality.get('generated_cases', 0)} 个。"
            "这证明数据与参考解一致，不代替题意正确性及覆盖审查。"
        )
    mode = st.radio(
        "保存方式",
        ["新增题目", "更新已有题目"],
        horizontal=True,
        key=f"ai_save_mode_{task['task_id']}",
    )
    target = None
    if mode == "更新已有题目":
        records = api().request("GET", "/api/problems/")
        lookup = {item["id"]: item for item in records}
        if not records:
            st.info("题库为空，请选择新增题目。")
            return
        target = st.selectbox(
            "更新目标", list(lookup), format_func=lambda x: f"{x} · {lookup[x]['title']}"
        )
        confirmed = st.checkbox("已确认更新目标，保存将替换该题目的配置")
    else:
        confirmed = True
    if draft.get("reference_solution"):
        with st.expander("生成的参考程序（需核验）"):
            st.code(str(draft["reference_solution"]), language="python")
    if draft.get("validation_notes"):
        with st.expander("生成说明（模型提供）"):
            st.write(draft["validation_notes"])
    payload = problem_form(
        draft,
        prefix=f"ai_draft_{task['task_id']}_{target or 'new'}",
        locked_id=target,
        submit_label="保存到题库",
    )
    if payload:
        if not confirmed:
            st.error("请确认更新目标。")
            return
        path = f"/api/problems/{resource(target)}" if target else "/api/problems/"
        ok, _ = mutation("PUT" if target else "POST", path, json=payload)
        if ok:
            go("题库", _problem_mode="detail", _problem_id=payload["id"])
            notice("AI 草稿已保存到题库。")
            st.rerun()


def ai_page():
    st.title("智能命题")
    st.caption("从教学目标出发，生成可审阅的题面与测试数据。")
    config = api().request("GET", "/api/ai/model-config")
    config_form(config)
    task = st.session_state.get("_ai_task", {})
    active = task.get("status") in ACTIVE
    with st.form("ai_requirement_form", border=False):
        a, b = st.columns(2)
        knowledge = a.text_input("知识点", placeholder="例如：有向图、拓扑排序、环检测")
        level = b.text_input("目标难度", placeholder="例如：Python 入门 / 中等")
        requirement = st.text_area(
            "命题需求 *",
            height=160,
            placeholder="说明教学目标、输入输出形式、数据规模、边界情况和希望区分的错误思路。",
            key="ai_requirement",
        )
        reference = st.text_input(
            "参考题号（可选）",
            help="填写题库中已有题号，模型可参考该题；生成后仍需明确选择新增或更新。",
        )
        started = st.form_submit_button("生成题目", type="primary", disabled=active)
    if started:
        if not requirement.strip():
            st.error("请填写命题需求。")
        else:
            parts = (
                ([f"知识点：{knowledge.strip()}"] if knowledge.strip() else [])
                + ([f"目标难度：{level.strip()}"] if level.strip() else [])
                + [requirement.strip()]
            )
            payload = {"requirement": "\n".join(parts)}
            if reference.strip():
                payload["problem_id"] = reference.strip()
            ok, result = mutation("POST", "/api/ai/problem-tasks/", json=payload)
            if ok:
                st.session_state["_ai_task"] = result
                st.rerun()
    task_panel()
    draft_editor(st.session_state.get("_ai_task", {}))
    with st.expander("恢复已有任务"):
        restore_id = st.text_input("任务编号", key="restore_ai_id")
        if st.button("载入任务", disabled=not restore_id.strip() or active):
            ok, result = mutation("GET", f"/api/ai/problem-tasks/{resource(restore_id.strip())}")
            if ok:
                st.session_state["_ai_task"] = result
                st.rerun()
