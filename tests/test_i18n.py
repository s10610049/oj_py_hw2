"""The bilingual frontend catalog is complete and strict."""

import pytest

from frontend.i18n import (
    MESSAGES,
    api_error_message,
    normalize_locale,
    placeholders,
    role_label,
    t,
)
from frontend.submissions import info_result_label, message_projection, verdict_label


def test_catalog_has_exact_locale_parity_and_matching_placeholders():
    assert set(MESSAGES) == {"zh-CN", "en"}
    assert set(MESSAGES["zh-CN"]) == set(MESSAGES["en"])
    assert len(MESSAGES["zh-CN"]) >= 180
    for key in MESSAGES["zh-CN"]:
        assert MESSAGES["zh-CN"][key]
        assert MESSAGES["en"][key]
        assert placeholders(MESSAGES["zh-CN"][key]) == placeholders(MESSAGES["en"][key])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "zh-CN"), ("zh-CN", "zh-CN"), ("EN", "en"), ("en-US", "en"), ("fr", "zh-CN")],
)
def test_locale_normalization_is_bounded(raw, expected):
    assert normalize_locale(raw) == expected


def test_translation_is_strict_formats_values_and_localizes_roles():
    assert t("problems.count", "zh-CN", count=3) == "3 道题目"
    assert t("problems.count", "en", count=3) == "3 problems"
    assert role_label("admin", "en") == "Administrator"
    assert role_label("future-role", "zh-CN") == "学习者"
    with pytest.raises(KeyError, match="unknown translation key"):
        t("missing.key", "en")


def test_literal_json_examples_are_not_interpreted_without_format_values():
    assert '{"input"' in t("form.case_json_help", "en")


def test_unknown_backend_text_is_never_echoed_across_language_boundaries():
    secret = "数据库内部错误：SECRET_TABLE"
    chinese = api_error_message(secret, "zh-CN")
    english = api_error_message(secret, "en")

    assert chinese == t("error.detail_generic", "zh-CN")
    assert english == t("error.detail_generic", "en")
    assert "SECRET_TABLE" not in chinese + english


def test_structured_judge_feedback_is_localized_without_mixed_prose():
    chinese, raw = message_projection("3 test cases finished\nOverall errors: WA, TLE", "zh-CN")
    english, english_raw = message_projection(
        "3 test cases finished\nOverall errors: WA, TLE", "en"
    )
    assert chinese == "3 个测试点已完成。\n未通过结果：答案错误 · WA、运行超时 · TLE"
    assert english == (
        "3 test cases finished.\n"
        "Non-accepted results: Wrong answer · WA, Time limit exceeded · TLE"
    )
    assert raw is False and english_raw is False
    assert info_result_label("finished", "zh-CN") == "已完成"
    assert verdict_label("CE", "en") == "Compile error · CE"


def test_judge_restart_message_and_opaque_diagnostic_have_explicit_boundaries():
    english, raw = message_projection("评测被服务重启中断，请重新评测", "en")
    assert english == "Judging was interrupted by a service restart. Please rejudge."
    assert raw is False
    diagnostic, raw = message_projection("compiler: expected semicolon", "zh-CN")
    assert diagnostic == "compiler: expected semicolon"
    assert raw is True
