"""Golden producer/consumer contract for bilingual AI problem drafts."""

import json
from pathlib import Path
import re

from oj.schemas import validate_problem
from oj.translations import TRANSLATABLE_FIELDS, embedded_english_translation

FIXTURE = Path(__file__).parent / "fixtures" / "bilingual_ai_problem_v1.json"


def test_bilingual_ai_golden_is_accepted_without_translating_judge_data():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    judge_snapshot = {
        key: raw[key] for key in ("samples", "testcases", "time_limit", "memory_limit")
    }

    canonical = validate_problem(raw)
    english = embedded_english_translation(raw)

    assert english is not None and set(english) == set(TRANSLATABLE_FIELDS)
    assert not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", " ".join(english.values()))
    assert {
        key: canonical[key] for key in ("samples", "testcases", "time_limit", "memory_limit")
    } == judge_snapshot
    assert {"samples", "testcases", "time_limit", "memory_limit", "reference_solution"}.isdisjoint(
        english
    )
