"""Golden, hand-calculated tests for the versioned progress contracts."""

import hashlib
import json
import math

import pytest

from oj.progress import (
    PROBLEM_VERSION_FIELDS,
    build_learning_stats,
    build_problem_statuses,
    build_progress_snapshot,
    problem_version_digest,
)

USER = "student-1"
STAMP = "2026-09-09T12:00:00+00:00"


def make_problem(key, cases, difficulty="", tags=None, **extra):
    return {
        "id": key,
        "title": f"Problem {key}",
        "description": "Public statement",
        "input_description": "Input",
        "output_description": "Output",
        "constraints": "Constraints",
        "hint": "",
        "source": "fixture",
        "author": "tester",
        "difficulty": difficulty,
        "tags": tags or [],
        "samples": [{"input": "1", "output": "1"}],
        "testcases": [
            {"input": f"SECRET_CASE_{key}_{index}", "output": "SECRET_EXPECTED"}
            for index in range(cases)
        ],
        "time_limit": 3,
        "memory_limit": 128,
        "public_cases": extra.get("public_cases", False),
        "translations": extra.get("translations", {"en": "display only"}),
        "reference_solution": extra.get("reference_solution", "SECRET_REFERENCE"),
    }


def make_submission(
    key,
    problem_id,
    version,
    status,
    score,
    counts,
    minute,
    *,
    day=9,
    user_id=USER,
    inferred=False,
):
    return {
        "submission_id": key,
        "user_id": user_id,
        "problem_id": problem_id,
        "problem_version": version,
        "version_inferred": inferred,
        "status": status,
        "score": score,
        "counts": counts,
        "created_at": f"2026-09-{day:02d}T10:{minute:02d}:00+00:00",
        "revision": 1,
        "code": "SECRET_SOURCE_CODE",
        "details": [{"input": "SECRET_HIDDEN_INPUT", "result": "WA"}],
    }


def golden_fixture():
    problems = [
        make_problem("p1", 3, "hard", ["Graph", "graph", "环检测"]),
        make_problem("p2", 4, "medium", ["DP"]),
        make_problem("p3", 2),
        make_problem("p4", 1, "easy", ["Simulation"]),
        make_problem("p5", 1, "hard", ["Graph"]),
        make_problem("p6", 1, "easy", ["Math"]),
    ]
    versions = {problem["id"]: problem_version_digest(problem) for problem in problems}
    submissions = [
        make_submission("s-old-p1", "p1", "old-v1", "success", 30, 30, 1, day=7),
        make_submission("s-pass", "p1", versions["p1"], "success", 30, 30, 2, day=8),
        make_submission("s-later-wa", "p1", versions["p1"], "success", 0, 30, 3, day=8),
        make_submission("s-pending-p1", "p1", versions["p1"], "pending", None, None, 4, day=8),
        make_submission("s-partial", "p2", versions["p2"], "success", 20, 40, 5),
        make_submission("s-error", "p3", versions["p3"], "error", None, None, 6),
        make_submission("s-legacy", "p3", None, "success", 20, 20, 7),
        make_submission("s-pending-p4", "p4", versions["p4"], "pending", None, None, 8),
        make_submission("s-old-p5", "p5", "old-v1", "success", 10, 10, 9),
        make_submission("s-orphan", "deleted", "old-v1", "success", 10, 10, 10),
        make_submission(
            "other-user-secret",
            "p6",
            versions["p6"],
            "success",
            10,
            10,
            11,
            user_id="student-2",
        ),
    ]
    return problems, submissions


def normalize_difficulty(raw):
    values = {
        "hard": {"id": "luogu-5", "label": "提高", "order": 5, "recognized": True},
        "medium": {"id": "luogu-3", "label": "普及", "order": 3, "recognized": True},
        "easy": {"id": "luogu-1", "label": "入门", "order": 1, "recognized": True},
        "": {"id": None, "label": "未分级", "order": 999, "recognized": False},
    }
    return values[raw]


def snapshot(problems=None, submissions=None, generated_at=STAMP):
    if problems is None or submissions is None:
        problems, submissions = golden_fixture()
    return build_progress_snapshot(
        problems,
        submissions,
        USER,
        difficulty_normalizer=normalize_difficulty,
        generated_at=generated_at,
    )


def test_problem_version_is_canonical_and_excludes_display_metadata():
    problem = make_problem("digest", 2)
    canonical = {field: problem.get(field) for field in PROBLEM_VERSION_FIELDS}
    expected = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert problem_version_digest(problem) == expected
    assert len(expected) == 64 and expected == expected.lower()

    display_only = {
        **problem,
        "public_cases": True,
        "translations": {"en": "changed"},
        "reference_solution": "DIFFERENT_SECRET_REFERENCE",
    }
    assert problem_version_digest(display_only) == expected
    assert problem_version_digest({**problem, "title": "Changed"}) != expected


def test_problem_status_contract_and_pending_overlay_are_hand_calculated():
    result = snapshot()["statuses"]
    rows = {item["problem_id"]: item for item in result["items"]}

    assert set(result) == {"schema_version", "context_epoch", "generated_at", "items"}
    assert result["schema_version"] == "oj.problem-status.v1"
    assert result["generated_at"] == STAMP
    assert list(rows) == ["p1", "p2", "p3", "p4", "p5", "p6"]

    # Later WA and an in-flight submission are overlays, not regressions from AC.
    assert rows["p1"]["state"] == "passed"
    assert rows["p1"]["best"]["submission_id"] == "s-pass"
    assert rows["p1"]["best"]["current_version"] is True
    assert rows["p1"]["latest_terminal"]["submission_id"] == "s-later-wa"
    assert rows["p1"]["latest_pending"]["submission_id"] == "s-pending-p1"
    assert rows["p1"]["historical_best"]["submission_id"] == "s-old-p1"

    assert rows["p2"]["state"] == "partial" and rows["p2"]["best"]["score"] == 20
    assert rows["p3"]["state"] == "failed" and rows["p3"]["version_unknown"] is True
    assert rows["p3"]["historical_best"]["current_version"] is None
    assert rows["p4"]["state"] == "pending" and rows["p4"]["latest_pending"]
    assert rows["p5"]["state"] == "outdated"
    assert rows["p5"]["historical_best"]["current_version"] is False
    assert rows["p6"]["state"] == "unattempted"

    reference_keys = {
        "submission_id",
        "status",
        "score",
        "counts",
        "created_at",
        "problem_version",
        "current_version",
        "version_inferred",
    }
    assert set(rows["p1"]["best"]) == reference_keys


def test_stats_kpis_scope_outcomes_and_timeline_are_hand_calculated():
    stats = snapshot()["stats"]
    assert set(stats) == {
        "schema_version",
        "context_epoch",
        "generated_at",
        "scope",
        "kpis",
        "submission_outcomes",
        "timeline",
        "difficulty",
        "knowledge_points",
        "problems",
    }
    assert stats["schema_version"] == "oj.learning-stats.v1"
    assert stats["scope"] == {
        "user_id": USER,
        "catalog_problem_count": 6,
        "submission_count": 10,
        "orphan_submission_count": 1,
        "version_unknown_count": 1,
        "timezone": "UTC",
    }
    assert stats["kpis"] == {
        "earned_score": 50,
        "available_score": 120,
        "attempted_count": 4,
        "passed_count": 1,
        "pass_rate": 0.25,
    }
    assert stats["submission_outcomes"] == [
        {"id": "pending", "count": 2},
        {"id": "judge_error", "count": 1},
        {"id": "zero_score", "count": 1},
        {"id": "partial", "count": 1},
        {"id": "full", "count": 5},
    ]
    assert stats["timeline"] == [
        {
            "date": "2026-09-07",
            "submissions": 1,
            "completed": 1,
            "best_score_delta": 0,
            "cumulative_score": 0,
        },
        {
            "date": "2026-09-08",
            "submissions": 3,
            "completed": 2,
            "best_score_delta": 30,
            "cumulative_score": 30,
        },
        {
            "date": "2026-09-09",
            "submissions": 6,
            "completed": 5,
            "best_score_delta": 20,
            "cumulative_score": 50,
        },
    ]
    assert stats["timeline"][-1]["cumulative_score"] == stats["kpis"]["earned_score"]


def test_difficulty_knowledge_points_and_problem_rows_are_reconcilable():
    stats = snapshot()["stats"]
    difficulty = {row["difficulty_label"]: row for row in stats["difficulty"]}
    assert difficulty["提高"] == {
        "difficulty_id": "luogu-5",
        "difficulty_label": "提高",
        "attempted": 1,
        "passed": 1,
        "earned_score": 30,
        "available_score": 40,
        "rate": 1.0,
    }
    assert difficulty["未分级"]["rate"] == 0.0

    points = {row["tag"]: row for row in stats["knowledge_points"]}
    assert points["Graph"] == {
        "tag": "Graph",
        "attempted": 1,
        "passed": 1,
        "earned_score": 30,
        "available_score": 40,
        "rate": 1.0,
    }
    assert [row["tag"] for row in stats["knowledge_points"][:4]] == [
        "DP",
        "Graph",
        "Simulation",
        "环检测",
    ]
    assert points["Graph"]["available_score"] == 40  # multi-tag slices are independent

    problems = {row["problem_id"]: row for row in stats["problems"]}
    assert problems["p1"]["best_score"] == 30
    assert problems["p1"]["available_score"] == 30
    assert problems["p1"]["difficulty_id"] == "luogu-5"
    assert problems["p1"]["tags"] == ["Graph", "环检测"]


def test_best_order_is_ratio_score_time_then_identifier():
    problem = make_problem("rank", 2)
    version = problem_version_digest(problem)
    submissions = [
        make_submission("a", "rank", version, "success", 4, 10, 1),
        make_submission("b", "rank", version, "success", 5, 20, 2),
        make_submission("c", "rank", version, "success", 4, 10, 3),
        make_submission("d", "rank", version, "success", 4, 10, 3),
    ]
    row = build_problem_statuses([problem], submissions, USER, generated_at=STAMP)["items"][0]
    assert row["best"]["submission_id"] == "d"
    assert row["best"]["score"] == 4 and row["state"] == "partial"


def test_success_is_not_ac_and_rejudge_overwrite_recomputes_without_stale_score():
    problem = make_problem("rejudge", 1)
    version = problem_version_digest(problem)
    completed = make_submission("same", "rejudge", version, "success", 10, 10, 1)
    before = build_problem_statuses([problem], [completed], USER, generated_at=STAMP)["items"][0]
    assert before["state"] == "passed"

    pending = {**completed, "status": "pending", "score": None, "counts": None, "revision": 2}
    after = build_problem_statuses([problem], [pending], USER, generated_at=STAMP)["items"][0]
    assert after["state"] == "pending"
    assert after["best"] is None and after["latest_pending"]["submission_id"] == "same"

    zero = {**completed, "score": 0}
    result = build_progress_snapshot([problem], [zero], USER, generated_at=STAMP)
    assert result["statuses"]["items"][0]["state"] == "failed"
    assert result["stats"]["kpis"]["passed_count"] == 0


def test_unknown_version_is_outdated_not_silently_current():
    problem = make_problem("legacy", 1)
    legacy = make_submission("legacy-row", "legacy", None, "success", 10, 10, 1)
    result = build_progress_snapshot([problem], [legacy], USER, generated_at=STAMP)
    row = result["statuses"]["items"][0]
    assert row["state"] == "outdated" and row["version_unknown"] is True
    assert row["best"] is None
    assert row["historical_best"]["current_version"] is None
    assert result["stats"]["kpis"]["earned_score"] == 0
    assert result["stats"]["kpis"]["attempted_count"] == 0


def test_outdated_pending_submission_does_not_overlay_the_current_problem():
    problem = make_problem("p-stale-pending", 1, difficulty="入门")
    stale = make_submission(
        "s-stale-pending",
        problem["id"],
        "an-old-problem-version",
        "pending",
        None,
        None,
        1,
    )

    row = build_problem_statuses([problem], [stale], USER, generated_at=STAMP)["items"][0]

    assert row["state"] == "outdated"
    assert row["latest_pending"] is None


def test_zero_data_has_null_rates_and_never_nan():
    result = build_progress_snapshot([], [], USER, generated_at=STAMP)
    assert result["statuses"]["items"] == []
    assert result["stats"]["kpis"] == {
        "earned_score": 0,
        "available_score": 0,
        "attempted_count": 0,
        "passed_count": 0,
        "pass_rate": None,
    }
    assert result["stats"]["timeline"] == []
    json.dumps(result, allow_nan=False)
    assert_no_nonfinite(result)


def test_epoch_is_shared_deterministic_and_secret_safe():
    problems, submissions = golden_fixture()
    original = snapshot(problems, submissions)
    statuses, stats = original["statuses"], original["stats"]
    assert statuses["context_epoch"] == stats["context_epoch"]
    assert len(statuses["context_epoch"]) == 64

    rendered = json.dumps(original, ensure_ascii=False, allow_nan=False)
    for secret in (
        "SECRET_SOURCE_CODE",
        "SECRET_HIDDEN_INPUT",
        "SECRET_CASE_",
        "SECRET_EXPECTED",
        "SECRET_REFERENCE",
        "other-user-secret",
    ):
        assert secret not in rendered

    changed_runtime = [
        {**submission, "code": "DIFFERENT_CODE", "details": ["DIFFERENT_DETAIL"]}
        for submission in submissions
    ]
    changed = snapshot(problems, changed_runtime, generated_at="2099-01-01T00:00:00+00:00")
    assert changed["statuses"]["context_epoch"] == statuses["context_epoch"]

    reordered = snapshot(list(reversed(problems)), list(reversed(submissions)))
    assert reordered["statuses"]["context_epoch"] == statuses["context_epoch"]
    assert reordered["stats"]["timeline"] == stats["timeline"]
    assert [row["problem_id"] for row in reordered["statuses"]["items"]] == list(
        reversed([row["problem_id"] for row in statuses["items"]])
    )

    changed_cases = [{**problems[0], "testcases": [{"input": "x", "output": "y"}]}, *problems[1:]]
    assert (
        snapshot(changed_cases, submissions)["statuses"]["context_epoch"]
        != statuses["context_epoch"]
    )


def test_timeline_uses_utc_dates():
    problem = make_problem("timezone", 1)
    version = problem_version_digest(problem)
    row = make_submission("tz", "timezone", version, "success", 10, 10, 1)
    row["created_at"] = "2026-09-09T00:30:00+08:00"
    stats = build_learning_stats([problem], [row], USER, generated_at=STAMP)
    assert stats["timeline"][0]["date"] == "2026-09-08"


@pytest.mark.parametrize(
    "change, match",
    [
        ({"created_at": "2026-09-09 10:00:00"}, "timezone"),
        ({"created_at": "not-a-date"}, "ISO-8601"),
        ({"score": float("nan")}, "finite"),
        ({"status": "AC"}, "status"),
        ({"score": 11}, "exceed"),
    ],
)
def test_malformed_submission_fails_atomically(change, match):
    problem = make_problem("bad", 1)
    version = problem_version_digest(problem)
    row = make_submission("bad-row", "bad", version, "success", 10, 10, 1)
    with pytest.raises(ValueError, match=match):
        build_progress_snapshot([problem], [{**row, **change}], USER, generated_at=STAMP)


def test_default_difficulty_is_neutral_and_does_not_infer_medium():
    problem = make_problem("custom", 1, "medium")
    result = build_learning_stats([problem], [], USER, generated_at=STAMP)
    assert result["difficulty"] == [
        {
            "difficulty_id": None,
            "difficulty_label": "medium",
            "attempted": 0,
            "passed": 0,
            "earned_score": 0,
            "available_score": 10,
            "rate": None,
        }
    ]


def assert_no_nonfinite(value):
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for nested in value.values():
            assert_no_nonfinite(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_no_nonfinite(nested)
