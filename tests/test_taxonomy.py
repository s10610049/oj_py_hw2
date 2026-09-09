"""The difficulty registry is stable, bilingual and explicitly migrated."""

from shared.taxonomy import (
    DIFFICULTIES,
    LEGACY_DIFFICULTY_MIGRATIONS,
    LEGACY_MIGRATION_VERSION,
    TAXONOMY_VERSION,
    difficulty_from_id,
    migrated_difficulty_label,
    normalize_difficulty,
)


def test_luogu_difficulty_registry_is_ordered_unique_and_bilingual():
    assert TAXONOMY_VERSION == "luogu-2026-09.v1"
    assert len(DIFFICULTIES) == 8
    assert [item["order"] for item in DIFFICULTIES] == list(range(1, 9))
    assert len({item["id"] for item in DIFFICULTIES}) == 8
    assert len({item["zh-CN"] for item in DIFFICULTIES}) == 8
    assert len({item["en"] for item in DIFFICULTIES}) == 8
    assert all(item["color_token"].startswith("difficulty-") for item in DIFFICULTIES)


def test_exact_labels_share_id_but_render_in_the_requested_locale():
    chinese = normalize_difficulty("普及+/提高-", "zh-CN")
    english = normalize_difficulty("Novice+ / Intermediate−", "en")
    assert chinese["id"] == english["id"] == "luogu.4"
    assert chinese["label"] == "普及+/提高-"
    assert english["label"] == "Novice+ / Intermediate−"
    assert chinese["color_token"] == english["color_token"] == "difficulty-green"
    assert difficulty_from_id("luogu.8", "en")["label"] == "NOI / NOI+ / CTS"


def test_known_legacy_values_have_versioned_explicit_luogu_migrations():
    assert LEGACY_MIGRATION_VERSION == "legacy-to-luogu-2026-09.v1"
    assert LEGACY_DIFFICULTY_MIGRATIONS == {
        "easy": "luogu.1",
        "基础": "luogu.2",
        "medium": "luogu.4",
        "进阶": "luogu.4",
        "hard": "luogu.5",
        "困难": "luogu.5",
    }
    expected = {
        "easy": ("luogu.1", "入门"),
        "基础": ("luogu.2", "普及-"),
        "medium": ("luogu.4", "普及+/提高-"),
        "进阶": ("luogu.4", "普及+/提高-"),
        "hard": ("luogu.5", "提高"),
        "困难": ("luogu.5", "提高"),
    }
    for raw, (difficulty_id, label) in expected.items():
        view = normalize_difficulty(raw, "zh-CN")
        assert view["id"] == difficulty_id
        assert view["raw"] == raw
        assert view["label"] == label
        assert view["color_token"] != "difficulty-neutral"
        assert view["recognized"] is True
        assert migrated_difficulty_label(raw) == label


def test_unknown_custom_values_remain_neutral_and_are_never_guessed():
    view = normalize_difficulty("custom difficulty", "zh-CN")
    assert view["id"] is None
    assert view["raw"] == view["label"] == "custom difficulty"
    assert view["color_token"] == "difficulty-neutral"
    assert view["recognized"] is False
    assert migrated_difficulty_label("custom difficulty") is None

    assert normalize_difficulty("", "zh-CN")["label"] == "未分级"
    assert normalize_difficulty("", "en")["label"] == "Unrated"
