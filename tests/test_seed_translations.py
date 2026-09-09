import re

from oj.translations import TRANSLATABLE_FIELDS, validate_translation
from scripts.seed_data import DEMO_ENGLISH, DEMO_PROBLEMS


def test_every_seed_problem_has_a_complete_distinct_english_statement():
    assert set(DEMO_ENGLISH) == {problem["id"] for problem in DEMO_PROBLEMS}
    titles = set()
    for problem in DEMO_PROBLEMS:
        english = problem["translations"]["en"]
        assert set(english) == set(TRANSLATABLE_FIELDS)
        assert validate_translation(english) == english
        assert not re.search(r"[\u4e00-\u9fff]", " ".join(english.values()))
        assert english["title"] != problem["title"]
        titles.add(english["title"])
    assert len(titles) == len(DEMO_PROBLEMS)


def test_translations_never_duplicate_judge_or_identity_fields():
    forbidden = {"id", "samples", "testcases", "time_limit", "memory_limit", "tags"}
    for translation in DEMO_ENGLISH.values():
        assert forbidden.isdisjoint(translation)
