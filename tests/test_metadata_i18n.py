"""Optional metadata never creates a mixed-language English catalog."""

from frontend.metadata_i18n import localized_optional_metadata, localized_tags
from frontend.problems import catalog_search_text


def test_seed_metadata_has_complete_english_display_labels():
    from scripts.seed_data import DEMO_PROBLEMS

    for problem in DEMO_PROBLEMS:
        tags, missing = localized_tags(problem["tags"], "en")
        source, source_missing = localized_optional_metadata(problem["source"], "en", "source")
        author, author_missing = localized_optional_metadata(problem["author"], "en", "author")
        rendered = " ".join([*tags, source, author])
        assert tags and not missing and not source_missing and not author_missing
        assert rendered and not any("\u3400" <= character <= "\u9fff" for character in rendered)


def test_unknown_chinese_metadata_is_explicitly_suppressed_in_english():
    tags, missing = localized_tags(["自定义中文标签", "ASCII-tag"], "en")
    source, source_missing = localized_optional_metadata("未知中文来源", "en", "source")

    assert tags == ["ASCII-tag"] and missing == 1
    assert source == "" and source_missing is True


def test_chinese_mode_preserves_canonical_metadata():
    assert localized_tags(["数组"], "zh-CN") == (["数组"], 0)
    assert localized_optional_metadata("课程组", "zh-CN", "author") == ("课程组", False)


def test_saved_ai_metadata_has_exact_english_projections():
    tags, missing = localized_tags(["图", "环检测", "入门"], "en")
    source, source_missing = localized_optional_metadata("AI生成", "en", "source")
    assert tags == ["Graphs", "Cycle detection", "Introductory"] and missing == 0
    assert source == "AI-generated" and source_missing is False


def test_catalog_search_uses_the_same_localized_tags_that_are_displayed():
    problem = {"id": "P1", "title": "Range Query", "tags": ["二分查找", "查询"]}
    english = catalog_search_text(problem, "en")
    assert "binary search" in english and "queries" in english
    assert "二分查找" not in english and "查询" not in english
    assert "binary search" not in catalog_search_text(problem, "zh-CN")
