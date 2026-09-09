"""Frontend format checks preserve the public API's missing-value semantics."""

import json
import math
import re

import streamlit as st

FIELDS = {
    "title": "题目标题",
    "description": "题目描述",
    "input_description": "输入格式",
    "output_description": "输出格式",
    "constraints": "数据范围与约束",
}


def parse_cases(text, label):
    try:
        cases = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError(f"{label}须为有效 JSON 数组。") from None
    if not isinstance(cases, list) or not 1 <= len(cases) <= 200:
        raise ValueError(f"{label}须包含 1 至 200 组输入输出。")
    for case in cases:
        if not isinstance(case, dict) or any(
            not isinstance(case.get(key), str) for key in ("input", "output")
        ):
            raise ValueError(f"{label}每组须含字符串 input 和 output。")
        if any(len(case[key]) > 1_000_000 for key in ("input", "output")):
            raise ValueError(f"{label}单项过长。")
    return [{key: case[key] for key in ("input", "output")} for case in cases]


def optional_number(text, label, *, integer=False, allow_zero=False):
    if not str(text).strip():
        return None
    try:
        number = int(text) if integer else float(text)
    except (ValueError, TypeError):
        raise ValueError(f"{label}须为{'整数' if integer else '数字'}。") from None
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"{label}须为{'非负数' if allow_zero else '正数'}。")
    return number


def problem_payload(values):
    identifier = values.get("id", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", identifier):
        raise ValueError("题号须为 1—80 位字母、数字、下划线、点或短横线，以字母或数字开头。")
    result = {"id": identifier}
    for field, label in FIELDS.items():
        value = values.get(field, "")
        if not value.strip():
            raise ValueError(f"请填写{label}。")
        result[field] = value
    result.update({key: values.get(key, "") for key in ("hint", "source", "author", "difficulty")})
    result["tags"] = [tag.strip() for tag in values.get("tags_text", "").split(",") if tag.strip()]
    result["samples"] = parse_cases(values["samples_json"], "样例")
    result["testcases"] = parse_cases(values["testcases_json"], "测试点")
    result["time_limit"] = optional_number(values["time_limit_text"], "时间限制")
    result["memory_limit"] = optional_number(values["memory_limit_text"], "内存限制", integer=True)
    return result


def problem_form(initial=None, *, prefix="problem", locked_id=None, submit_label="保存题目"):
    """Return validated data on submit; preserve all input on validation failure."""
    initial = initial or {}
    values = {}
    with st.form(f"{prefix}_form", border=False):
        left, right = st.columns([1, 2])
        values["id"] = left.text_input(
            "题号 *",
            value=locked_id or initial.get("id", ""),
            disabled=locked_id is not None,
            key=f"{prefix}_id",
        )
        values["title"] = right.text_input(
            "题目标题 *", value=initial.get("title", ""), key=f"{prefix}_title"
        )
        for field in ("description", "input_description", "output_description", "constraints"):
            values[field] = st.text_area(
                FIELDS[field] + " *",
                value=initial.get(field, ""),
                height=180 if field == "description" else 100,
                key=f"{prefix}_{field}",
            )
        st.caption(
            '样例与测试点使用 JSON 数组，例如 [{"input": "1 2\\n", "output": "3\\n"}]。保留空格与换行。'
        )
        for field, label in (("samples", "样例"), ("testcases", "测试点")):
            values[f"{field}_json"] = st.text_area(
                f"{label} JSON *",
                value=json.dumps(
                    initial.get(field, [{"input": "", "output": ""}]), ensure_ascii=False, indent=2
                ),
                height=180,
                key=f"{prefix}_{field}",
            )
        with st.expander("提示、来源与资源限制", expanded=False):
            values["hint"] = st.text_area(
                "提示", value=initial.get("hint", ""), key=f"{prefix}_hint"
            )
            a, b = st.columns(2)
            values["source"] = a.text_input(
                "来源", value=initial.get("source", ""), key=f"{prefix}_source"
            )
            values["author"] = b.text_input(
                "作者", value=initial.get("author", ""), key=f"{prefix}_author"
            )
            values["difficulty"] = a.text_input(
                "难度", value=initial.get("difficulty", ""), key=f"{prefix}_difficulty"
            )
            values["tags_text"] = b.text_input(
                "标签（英文逗号分隔）",
                value=", ".join(initial.get("tags", [])),
                key=f"{prefix}_tags",
            )
            values["time_limit_text"] = a.text_input(
                "时间限制（秒，留空继承）",
                value="" if initial.get("time_limit") is None else str(initial["time_limit"]),
                key=f"{prefix}_time",
            )
            values["memory_limit_text"] = b.text_input(
                "内存限制（MB，留空继承）",
                value="" if initial.get("memory_limit") is None else str(initial["memory_limit"]),
                key=f"{prefix}_memory",
            )
            st.caption("时间与内存分别按题目 → 语言 → 系统默认值继承；留空不会写入固定默认值。")
        submitted = st.form_submit_button(submit_label, type="primary")
    if submitted:
        try:
            return problem_payload(values)
        except ValueError as exc:
            st.error(str(exc))
    return None
