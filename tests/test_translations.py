"""Problem translations are complete, versioned, and never touch judge data."""

import json

import pytest

from oj.common import APIError
from oj.translations import (
    CONTENT_SCHEMA,
    TRANSLATABLE_FIELDS,
    embedded_english_translation,
    localized_content,
    make_translation_record,
    normalize_locale,
    source_digest,
    translation_key,
    validate_translation,
)


def problem():
    return {
        "id": "P-1",
        "title": "两数之和",
        "description": "计算两个整数之和。",
        "input_description": "输入两个整数。",
        "output_description": "输出它们的和。",
        "constraints": "绝对值不超过 10^9。",
        "hint": "使用加法。",
        "samples": [{"input": "1 2\n", "output": "3\n"}],
        "testcases": [{"input": "SECRET_INPUT", "output": "SECRET_OUTPUT"}],
        "reference_solution": "SECRET_REFERENCE",
        "author": "课程组",
    }


def english():
    return {
        "title": "A + B",
        "description": "Add two integers.",
        "input_description": "Read two integers.",
        "output_description": "Print their sum.",
        "constraints": "Absolute values do not exceed 10^9.",
        "hint": "Use addition.",
    }


def test_locale_contract_is_small_and_exact():
    assert normalize_locale(None) == "zh-CN"
    assert normalize_locale("zh") == "zh-CN"
    assert normalize_locale("en-US") == "en"
    with pytest.raises(APIError) as unsupported:
        normalize_locale("fr")
    assert unsupported.value.status == 400


def test_translation_requires_every_prose_field_and_rejects_judge_fields():
    assert set(validate_translation(english())) == set(TRANSLATABLE_FIELDS)
    for value in (
        {**english(), "description": ""},
        {**english(), "description": "Add 两个 integers."},
        {**english(), "testcases": []},
        {key: value for key, value in english().items() if key != "title"},
    ):
        with pytest.raises(APIError):
            validate_translation(value)


def test_source_digest_ignores_judge_data_but_changes_with_prose():
    original = problem()
    changed_judge = {
        **original,
        "testcases": [{"input": "OTHER_SECRET", "output": "OTHER_OUTPUT"}],
        "samples": [],
        "reference_solution": "OTHER_REFERENCE",
        "author": "another author",
    }
    assert source_digest(original) == source_digest(changed_judge)
    assert source_digest({**original, "description": "新题意"}) != source_digest(original)


def test_ready_translation_is_complete_and_secret_free():
    source = problem()
    record = make_translation_record(
        source,
        english(),
        source="seed",
        updated_at="2026-09-09T12:00:00+00:00",
    )
    content = localized_content(source, "en", record)

    assert content == {
        "schema_version": CONTENT_SCHEMA,
        "requested_locale": "en",
        "resolved_locale": "en",
        "status": "ready",
        "fallback": False,
        "source_digest": source_digest(source),
        "fields": english(),
    }
    rendered = json.dumps(content)
    assert "SECRET_INPUT" not in rendered
    assert "SECRET_OUTPUT" not in rendered
    assert "SECRET_REFERENCE" not in rendered


def test_missing_and_stale_records_fail_closed_without_mixing_languages():
    source = problem()
    missing = localized_content(source, "en")
    assert missing["status"] == "missing"
    assert missing["fallback"] is False
    assert missing["resolved_locale"] is None
    assert missing["fields"] == {field: "" for field in TRANSLATABLE_FIELDS}

    record = make_translation_record(
        source,
        english(),
        source="manual",
        updated_at="2026-09-09T12:00:00+00:00",
    )
    changed = {**source, "title": "新的标题"}
    stale = localized_content(changed, "en", record)
    assert stale["status"] == "stale"
    assert stale["fallback"] is False
    assert stale["resolved_locale"] is None
    assert stale["fields"] == {field: "" for field in TRANSLATABLE_FIELDS}


def test_corrupt_persisted_record_fails_closed_to_empty_english_content():
    source = problem()
    record = make_translation_record(
        source,
        english(),
        source="ai",
        updated_at="2026-09-09T12:00:00+00:00",
    )
    record["fields"] = {"title": "Partial English"}

    content = localized_content(source, "en", record)

    assert content["status"] == "missing"
    assert content["fallback"] is False
    assert content["resolved_locale"] is None
    assert content["fields"] == {field: "" for field in TRANSLATABLE_FIELDS}


def test_embedded_translation_is_additive_and_strict():
    assert embedded_english_translation({"id": "P"}) is None
    assert embedded_english_translation({"translations": {"en": english()}}) == english()
    with pytest.raises(APIError):
        embedded_english_translation({"translations": {"en": english(), "fr": english()}})
    with pytest.raises(APIError):
        embedded_english_translation({"translations": {"en": {"title": "Only"}}})


def test_translation_key_and_source_metadata_are_stable():
    record = make_translation_record(
        problem(),
        english(),
        source="import",
        updated_at="now",
    )
    assert translation_key("P-1") == "P-1:en"
    assert record["problem_id"] == "P-1"
    assert record["locale"] == "en"
    assert record["source"] == "import"
    with pytest.raises(APIError):
        make_translation_record(problem(), english(), source="crawler", updated_at="now")
