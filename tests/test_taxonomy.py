"""The difficulty registry is stable, bilingual and deliberately conservative."""

from shared.taxonomy import (
    DIFFICULTIES,
    TAXONOMY_VERSION,
    difficulty_from_id,
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


def test_legacy_values_are_neutral_and_never_guessed_into_luogu_levels():
    for raw in ("medium", "基础", "进阶", "custom difficulty"):
        view = normalize_difficulty(raw, "zh-CN")
        assert view["id"] is None
        assert view["raw"] == view["label"] == raw
        assert view["color_token"] == "difficulty-neutral"
        assert view["recognized"] is False

    assert normalize_difficulty("", "zh-CN")["label"] == "未分级"
    assert normalize_difficulty("", "en")["label"] == "Unrated"
