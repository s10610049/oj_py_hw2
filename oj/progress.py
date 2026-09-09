"""Pure, version-aware and privacy-safe learning progress projections.

Callers pass the current problem catalog plus submissions already scoped to the
authenticated user.  This module neither reads persistence nor trusts a
``user_id`` query parameter.  Returned payloads intentionally exclude source
code, judge details, hidden cases and reference solutions.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

PROBLEM_STATUS_SCHEMA = "oj.problem-status.v1"
LEARNING_STATS_SCHEMA = "oj.learning-stats.v1"
ADMIN_LEARNING_OVERVIEW_SCHEMA = "oj.admin-learning-overview.v1"
CHAT_CONTEXT_SCHEMA = "oj.chat-context.v4"
OUTCOME_IDS = ("pending", "judge_error", "zero_score", "partial", "full")
ADMIN_OUTCOME_IDS = (
    "pending",
    "accepted",
    "partial",
    "wrong_answer",
    "compile_error",
    "time_limit",
    "memory_limit",
    "runtime_error",
    "judge_error",
)
CHAT_OUTCOME_IDS = (
    "pending",
    "accepted",
    "wrong_answer",
    "zero_score",
    "partial",
    "compile_error",
    "time_limit",
    "memory_limit",
    "runtime_error",
    "judge_error",
)
VERDICT_IDS = {
    "pending",
    "accepted",
    "wrong_answer",
    "zero_score",
    "partial",
    "compile_error",
    "time_limit",
    "memory_limit",
    "runtime_error",
    "judge_error",
}
_JUDGE_VERDICTS = {
    "CE": "compile_error",
    "TLE": "time_limit",
    "MLE": "memory_limit",
    "RE": "runtime_error",
    "WA": "wrong_answer",
    "UNK": "judge_error",
}

CHAT_CONTEXT_MAX_PROBLEMS = 512
CHAT_CONTEXT_MAX_DIFFICULTIES = 64
CHAT_CONTEXT_MAX_KNOWLEDGE = 256
CHAT_CONTEXT_MAX_LANGUAGES = 64
CHAT_CONTEXT_MAX_PROBLEM_KNOWLEDGE = 30
CHAT_CONTEXT_MAX_RECENT_ACTIVITY = 20
CHAT_CONTEXT_MAX_TITLE_BYTES = 1000
CHAT_CONTEXT_MAX_KNOWLEDGE_BYTES = 240
UNKNOWN_LANGUAGE_ID = "__unknown__"
OTHER_LANGUAGE_ID = "__other__"
CHAT_CONTEXT_OMISSIONS = (
    "orphan_problem_metadata",
    "submission_version_unknown",
    "outdated_submission_version",
    "pending_submission_results",
    "submission_language_unknown",
    "problem_titles_truncated",
    "problem_knowledge_truncated",
    "problem_details_truncated",
    "recent_activity_truncated",
    "difficulty_aggregates_truncated",
    "knowledge_aggregates_truncated",
    "language_aggregates_truncated",
    "english_problem_translation_missing",
    "english_knowledge_translation_missing",
)

PROBLEM_VERSION_FIELDS = (
    "id",
    "title",
    "description",
    "input_description",
    "output_description",
    "constraints",
    "hint",
    "source",
    "author",
    "difficulty",
    "tags",
    "samples",
    "testcases",
    "time_limit",
    "memory_limit",
)

DifficultyNormalizer = Callable[[str], Mapping[str, Any]]


def problem_version_digest(problem: Mapping[str, Any]) -> str:
    """Hash only course problem fields, excluding visibility and display metadata."""

    canonical = _canonical_problem(problem)
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_progress_snapshot(
    problems: Iterable[Mapping[str, Any]],
    submissions: Iterable[Mapping[str, Any]],
    user_id: str,
    *,
    difficulty_normalizer: DifficultyNormalizer | None = None,
    generated_at: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build both v1 payloads from one deterministic in-memory snapshot."""

    if generated_at is None or not str(generated_at).strip():
        raise ValueError("generated_at must be supplied")
    scoped_user = str(user_id).strip()
    if not scoped_user:
        raise ValueError("user_id must be supplied")

    prepared_problems, canonical_problems = _prepare_problems(problems, difficulty_normalizer)
    problem_by_id = {problem["problem_id"]: problem for problem in prepared_problems}
    prepared_submissions = _prepare_submissions(submissions, scoped_user, problem_by_id)

    submissions_by_problem: dict[str, list[dict[str, Any]]] = {}
    for submission in prepared_submissions:
        submissions_by_problem.setdefault(submission["problem_id"], []).append(submission)

    items = []
    facts = []
    for problem in prepared_problems:
        item, fact = _problem_projection(
            problem, submissions_by_problem.get(problem["problem_id"], [])
        )
        items.append(item)
        facts.append(fact)

    epoch = _context_epoch(canonical_problems, prepared_submissions)
    generated = str(generated_at)
    statuses = {
        "schema_version": PROBLEM_STATUS_SCHEMA,
        "context_epoch": epoch,
        "generated_at": generated,
        "items": items,
    }
    stats = _learning_stats(
        scoped_user,
        epoch,
        generated,
        prepared_problems,
        prepared_submissions,
        items,
        facts,
    )
    return {"statuses": statuses, "stats": stats}


def build_problem_statuses(
    problems: Iterable[Mapping[str, Any]],
    submissions: Iterable[Mapping[str, Any]],
    user_id: str,
    *,
    difficulty_normalizer: DifficultyNormalizer | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for ``oj.problem-status.v1``."""

    return build_progress_snapshot(
        problems,
        submissions,
        user_id,
        difficulty_normalizer=difficulty_normalizer,
        generated_at=generated_at,
    )["statuses"]


def build_learning_stats(
    problems: Iterable[Mapping[str, Any]],
    submissions: Iterable[Mapping[str, Any]],
    user_id: str,
    *,
    difficulty_normalizer: DifficultyNormalizer | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for ``oj.learning-stats.v1``."""

    return build_progress_snapshot(
        problems,
        submissions,
        user_id,
        difficulty_normalizer=difficulty_normalizer,
        generated_at=generated_at,
    )["stats"]


def build_progress_payloads(
    problems: Iterable[Mapping[str, Any]],
    submissions: Iterable[Mapping[str, Any]],
    user_id: str,
    *,
    difficulty_normalizer: DifficultyNormalizer | None = None,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the status and statistics payloads as a tuple."""

    snapshot = build_progress_snapshot(
        problems,
        submissions,
        user_id,
        difficulty_normalizer=difficulty_normalizer,
        generated_at=generated_at,
    )
    return snapshot["statuses"], snapshot["stats"]


def build_admin_learning_overview(
    users: Iterable[Mapping[str, Any]],
    problems: Iterable[Mapping[str, Any]],
    submissions: Iterable[Mapping[str, Any]],
    *,
    difficulty_normalizer: DifficultyNormalizer | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Return an administrator-only, privacy-safe account comparison.

    The projection deliberately reuses the personal progress calculation for
    every account so individual and cohort metrics cannot drift.  Only account
    identity, role and aggregate learning values cross the API boundary; raw
    submissions, source code and judge details are never returned.
    """

    if generated_at is None or not str(generated_at).strip():
        raise ValueError("generated_at must be supplied")
    problem_records = list(problems)
    submission_records = list(submissions)
    prepared_users = []
    seen_user_ids = set()
    for raw in users:
        if not isinstance(raw, Mapping):
            raise ValueError("users must contain mappings")
        user_id = str(raw.get("user_id", "")).strip()
        username = str(raw.get("username", "")).strip()
        role = str(raw.get("role", "")).strip()
        join_time = str(raw.get("join_time", "")).strip()
        if not user_id or user_id in seen_user_ids:
            raise ValueError("user ids must be non-empty and unique")
        if not username or role not in {"admin", "user", "banned"} or not join_time:
            raise ValueError("user identity fields are invalid")
        seen_user_ids.add(user_id)
        snapshot = build_progress_snapshot(
            problem_records,
            submission_records,
            user_id,
            difficulty_normalizer=difficulty_normalizer,
            generated_at=str(generated_at),
        )
        statistics = snapshot["stats"]
        kpis = statistics["kpis"]
        scope = statistics["scope"]
        outcome_counts = {outcome: 0 for outcome in ADMIN_OUTCOME_IDS}
        for submission in submission_records:
            if str(submission.get("user_id", "")) == user_id:
                outcome_counts[_admin_submission_outcome(submission)] += 1
        prepared_users.append(
            {
                "user_id": user_id,
                "username": username,
                "role": role,
                "account_status": "disabled" if role == "banned" else "active",
                "join_time": join_time,
                "submission_count": scope["submission_count"],
                "attempted_count": kpis["attempted_count"],
                "passed_count": kpis["passed_count"],
                "earned_score": kpis["earned_score"],
                "available_score": kpis["available_score"],
                "score_rate": _rate(kpis["earned_score"], kpis["available_score"]),
                "pass_rate": kpis["pass_rate"],
                "submission_outcomes": [
                    {"id": outcome, "count": outcome_counts[outcome]}
                    for outcome in ADMIN_OUTCOME_IDS
                ],
            }
        )

    role_order = {"admin": 0, "user": 1, "banned": 2}
    prepared_users.sort(
        key=lambda row: (
            role_order[row["role"]],
            row["username"].casefold(),
            row["username"],
            row["user_id"],
        )
    )
    attempted = sum(row["attempted_count"] for row in prepared_users)
    passed = sum(row["passed_count"] for row in prepared_users)
    earned = _sum_numbers(row["earned_score"] for row in prepared_users)
    available = _sum_numbers(row["available_score"] for row in prepared_users)
    aggregate_outcomes = {outcome: 0 for outcome in ADMIN_OUTCOME_IDS}
    for row in prepared_users:
        for outcome in row["submission_outcomes"]:
            aggregate_outcomes[outcome["id"]] += outcome["count"]
    return {
        "schema_version": ADMIN_LEARNING_OVERVIEW_SCHEMA,
        "generated_at": str(generated_at),
        "timezone": "UTC",
        "summary": {
            "account_count": len(prepared_users),
            "active_count": sum(row["account_status"] == "active" for row in prepared_users),
            "disabled_count": sum(row["account_status"] == "disabled" for row in prepared_users),
            "learner_count": sum(row["role"] == "user" for row in prepared_users),
            "engaged_count": sum(row["attempted_count"] > 0 for row in prepared_users),
            "submission_count": sum(row["submission_count"] for row in prepared_users),
            "attempted_count": attempted,
            "passed_count": passed,
            "earned_score": earned,
            "available_score": available,
            "score_rate": _rate(earned, available),
            "pass_rate": _rate(passed, attempted),
        },
        "submission_outcomes": [
            {"id": outcome, "count": aggregate_outcomes[outcome]} for outcome in ADMIN_OUTCOME_IDS
        ],
        "users": prepared_users,
    }


def _prepare_problems(
    problems: Iterable[Mapping[str, Any]],
    normalizer: DifficultyNormalizer | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prepared = []
    canonical_records = []
    seen = set()
    for raw in problems:
        canonical = _canonical_problem(raw)
        problem_id = str(canonical["id"] or "").strip()
        if not problem_id or problem_id in seen:
            raise ValueError("problem ids must be non-empty and unique")
        seen.add(problem_id)
        cases = canonical["testcases"]
        if not isinstance(cases, list):
            raise ValueError("problem testcases must be a list")
        tags = _dedupe_tags(canonical["tags"])
        difficulty = _difficulty(str(canonical["difficulty"] or ""), normalizer)
        public_cases = raw.get("public_cases", False)
        if not isinstance(public_cases, bool):
            raise ValueError("problem public_cases must be a boolean")
        prepared.append(
            {
                "problem_id": problem_id,
                "title": str(canonical["title"] or ""),
                "current_problem_version": problem_version_digest(raw),
                "available_score": len(cases) * 10,
                "tags": tags,
                "difficulty": difficulty,
                "public_cases": public_cases,
            }
        )
        # Visibility is not a problem-version field, but it must invalidate a
        # Chat context epoch because it changes which diagnostics are allowed.
        canonical_records.append({**canonical, "public_cases": public_cases})
    return prepared, canonical_records


def _prepare_submissions(
    submissions: Iterable[Mapping[str, Any]],
    user_id: str,
    problem_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    prepared = []
    seen_submission_ids = set()
    for raw in submissions:
        if str(raw.get("user_id", "")) != user_id:
            continue
        submission_id = str(raw.get("submission_id", "")).strip()
        problem_id = str(raw.get("problem_id", "")).strip()
        if not submission_id or not problem_id:
            raise ValueError("submission ids and problem ids must be non-empty")
        if submission_id in seen_submission_ids:
            raise ValueError("submission ids must be unique")
        seen_submission_ids.add(submission_id)
        status = str(raw.get("status", ""))
        if status not in {"pending", "success", "error"}:
            raise ValueError("invalid submission status")
        created_at = str(raw.get("created_at", ""))
        created_time = _utc_datetime(created_at)
        language = _submission_language(raw.get("language"))
        score = _optional_number(raw.get("score"), "score")
        counts = _optional_number(raw.get("counts"), "counts")
        _validate_score_state(status, score, counts)
        submitted_version = _optional_text(raw.get("problem_version"))
        inferred = raw.get("version_inferred", False)
        if not isinstance(inferred, bool):
            raise ValueError("version_inferred must be a boolean")

        problem = problem_by_id.get(problem_id)
        public_cases = bool(problem and problem["public_cases"])
        if problem is None:
            relation = "orphan"
        elif submitted_version is None:
            relation = "unknown"
        elif submitted_version == problem["current_problem_version"]:
            relation = "current"
        else:
            relation = "outdated"
        prepared.append(
            {
                "submission_id": submission_id,
                "problem_id": problem_id,
                "status": status,
                "score": score,
                "counts": counts,
                "created_at": created_at,
                "language": language,
                "problem_version": submitted_version,
                "version_inferred": inferred,
                "revision": raw.get("revision"),
                "relation": relation,
                "created_time": created_time,
                "date": created_time.date().isoformat(),
                "outcome": _outcome(status, score, counts),
                "verdict": _submission_verdict(
                    raw, status, score, counts, public_cases=public_cases
                ),
                "chat_outcome": _chat_outcome(
                    raw, status, score, counts, public_cases=public_cases
                ),
            }
        )
    prepared.sort(key=_latest_order)
    return prepared


def _problem_projection(
    problem: Mapping[str, Any], submissions: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    current_terminal = [
        item
        for item in submissions
        if item["relation"] == "current" and item["status"] != "pending"
    ]
    current_success = [item for item in current_terminal if _valid_best(item)]
    historical_success = [
        item
        for item in submissions
        if item["relation"] in {"outdated", "unknown"} and _valid_best(item)
    ]
    historical_terminal = [
        item
        for item in submissions
        if item["relation"] in {"outdated", "unknown"} and item["status"] != "pending"
    ]
    historical_pending = [
        item
        for item in submissions
        if item["relation"] in {"outdated", "unknown"} and item["status"] == "pending"
    ]
    pending = [
        item
        for item in submissions
        if item["relation"] == "current" and item["status"] == "pending"
    ]

    best = max(current_success, key=_best_order, default=None)
    historical_best = max(historical_success, key=_best_order, default=None)
    latest_terminal = max(current_terminal, key=_latest_order, default=None)
    latest_pending = max(pending, key=_latest_order, default=None)

    if best is not None and best["counts"] > 0 and best["score"] == best["counts"]:
        state = "passed"
    elif best is not None and best["score"] > 0:
        state = "partial"
    elif current_terminal:
        state = "failed"
    elif historical_terminal or historical_pending:
        state = "outdated"
    elif pending:
        state = "pending"
    else:
        state = "unattempted"

    item = {
        "problem_id": problem["problem_id"],
        "title": problem["title"],
        "current_problem_version": problem["current_problem_version"],
        "state": state,
        "latest_pending": _submission_ref(latest_pending),
        "best": _submission_ref(best),
        "latest_terminal": _submission_ref(latest_terminal),
        "historical_best": _submission_ref(historical_best),
        "latest_outcome": (
            latest_pending["verdict"]
            if latest_pending is not None
            else latest_terminal["verdict"] if latest_terminal is not None else None
        ),
        "version_unknown": any(item["relation"] == "unknown" for item in submissions),
    }
    attempted = bool(current_terminal or pending)
    earned = best["score"] if best is not None else 0
    fact = {
        "attempted": attempted,
        "passed": state == "passed",
        "earned_score": earned,
        "available_score": problem["available_score"],
        "tags": list(problem["tags"]),
        "difficulty": dict(problem["difficulty"]),
    }
    return item, fact


def _learning_stats(
    user_id: str,
    epoch: str,
    generated_at: str,
    problems: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
    items: list[dict[str, Any]],
    facts: list[dict[str, Any]],
) -> dict[str, Any]:
    attempted = sum(fact["attempted"] for fact in facts)
    passed = sum(fact["passed"] for fact in facts)
    earned = _sum_numbers(fact["earned_score"] for fact in facts)
    available = sum(fact["available_score"] for fact in facts)

    outcome_counts = {outcome: 0 for outcome in OUTCOME_IDS}
    for submission in submissions:
        outcome_counts[submission["outcome"]] += 1

    problem_ids = {problem["problem_id"] for problem in problems}
    stats = {
        "schema_version": LEARNING_STATS_SCHEMA,
        "context_epoch": epoch,
        "generated_at": generated_at,
        "scope": {
            "user_id": user_id,
            "catalog_problem_count": len(problems),
            "submission_count": len(submissions),
            "orphan_submission_count": sum(
                submission["problem_id"] not in problem_ids for submission in submissions
            ),
            "version_unknown_count": sum(
                submission["problem_version"] is None for submission in submissions
            ),
            "timezone": "UTC",
        },
        "kpis": {
            "earned_score": earned,
            "available_score": available,
            "attempted_count": attempted,
            "passed_count": passed,
            "pass_rate": _rate(passed, attempted),
        },
        "submission_outcomes": [
            {"id": outcome, "count": outcome_counts[outcome]} for outcome in OUTCOME_IDS
        ],
        "timeline": _timeline(submissions),
        "difficulty": _difficulty_aggregates(facts),
        "knowledge_points": _knowledge_point_aggregates(facts),
        "problems": [
            {
                **item,
                "available_score": fact["available_score"],
                "best_score": fact["earned_score"],
                "difficulty_id": fact["difficulty"]["id"],
                "difficulty_label": fact["difficulty"]["label"],
                "tags": list(fact["tags"]),
            }
            for item, fact in zip(items, facts, strict=True)
        ],
    }
    stats["chat_context"] = _chat_context(
        epoch,
        generated_at,
        problems,
        submissions,
        items,
        facts,
        earned=earned,
        available=available,
    )
    return stats


def _chat_context(
    epoch: str,
    generated_at: str,
    problems: list[dict[str, Any]],
    submissions: list[dict[str, Any]],
    items: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    *,
    earned: int | float,
    available: int | float,
) -> dict[str, Any]:
    """Build the bounded, source-only projection consumed by programming chat."""

    omissions = set()
    relations = {relation: 0 for relation in ("current", "outdated", "unknown", "orphan")}
    outcome_counts = {outcome: 0 for outcome in CHAT_OUTCOME_IDS}
    language_counts: dict[str, int] = {}
    submissions_by_problem: dict[str, list[dict[str, Any]]] = {}
    for submission in submissions:
        relations[submission["relation"]] += 1
        outcome_counts[submission["chat_outcome"]] += 1
        language = submission["language"]
        language_counts[language] = language_counts.get(language, 0) + 1
        submissions_by_problem.setdefault(submission["problem_id"], []).append(submission)

    if relations["orphan"]:
        omissions.add("orphan_problem_metadata")
    if relations["unknown"]:
        omissions.add("submission_version_unknown")
    if relations["outdated"]:
        omissions.add("outdated_submission_version")
    if outcome_counts["pending"]:
        omissions.add("pending_submission_results")
    if language_counts.get(UNKNOWN_LANGUAGE_ID):
        omissions.add("submission_language_unknown")

    per_problem = []
    chat_facts = []
    for problem, item, fact in zip(problems, items, facts, strict=True):
        problem_submissions = submissions_by_problem.get(problem["problem_id"], [])
        latest = max(problem_submissions, key=_latest_order, default=None)
        chat_fact = dict(fact)
        chat_fact["attempted"] = any(
            submission["relation"] == "current" and submission["status"] != "pending"
            for submission in problem_submissions
        )
        chat_facts.append(chat_fact)
        title, title_truncated = _bounded_source_text(
            problem["title"], CHAT_CONTEXT_MAX_TITLE_BYTES
        )
        knowledge_points, knowledge_truncated = _bounded_knowledge(problem["tags"])
        if title_truncated:
            omissions.add("problem_titles_truncated")
        if knowledge_truncated:
            omissions.add("problem_knowledge_truncated")
        per_problem.append(
            {
                "problem_id": problem["problem_id"],
                "title": title,
                "difficulty_id": fact["difficulty"]["id"],
                "knowledge_points": knowledge_points,
                "state": item["state"],
                "latest_outcome": latest["chat_outcome"] if latest is not None else None,
                "best_score": item["best"]["score"] if item["best"] is not None else None,
                "available_score": fact["available_score"],
                "attempt_count": len(problem_submissions),
                "last_submitted_at": (
                    _utc_text(latest["created_time"]) if latest is not None else None
                ),
            }
        )
    per_problem.sort(key=_chat_problem_order)
    total_problem_count = len(per_problem)
    if total_problem_count > CHAT_CONTEXT_MAX_PROBLEMS:
        per_problem = per_problem[:CHAT_CONTEXT_MAX_PROBLEMS]
        omissions.add("problem_details_truncated")

    recent_source = sorted(submissions, key=_latest_order, reverse=True)
    total_recent_activity_count = len(recent_source)
    if total_recent_activity_count > CHAT_CONTEXT_MAX_RECENT_ACTIVITY:
        recent_source = recent_source[:CHAT_CONTEXT_MAX_RECENT_ACTIVITY]
        omissions.add("recent_activity_truncated")
    recent_activity = [
        {
            "submission_id": submission["submission_id"],
            "problem_id": submission["problem_id"],
            "status": submission["status"],
            "outcome": submission["chat_outcome"],
            "score": submission["score"],
            "counts": submission["counts"],
            "language": submission["language"],
            "relation": submission["relation"],
            "created_at": _utc_text(submission["created_time"]),
        }
        for submission in recent_source
    ]

    difficulty_groups: dict[str | None, dict[str, Any]] = {}
    for row in _difficulty_aggregates(chat_facts):
        difficulty_id = row["difficulty_id"]
        group = difficulty_groups.setdefault(
            difficulty_id,
            {
                "id": difficulty_id,
                "attempted": 0,
                "passed": 0,
                "earned_score": 0,
                "available_score": 0,
            },
        )
        group["attempted"] += row["attempted"]
        group["passed"] += row["passed"]
        group["earned_score"] = _clean_number(group["earned_score"] + row["earned_score"])
        group["available_score"] = _clean_number(group["available_score"] + row["available_score"])
    difficulty = list(difficulty_groups.values())
    difficulty.sort(key=lambda row: (row["id"] is None, str(row["id"])))
    total_difficulty_count = len(difficulty)
    if total_difficulty_count > CHAT_CONTEXT_MAX_DIFFICULTIES:
        difficulty = difficulty[:CHAT_CONTEXT_MAX_DIFFICULTIES]
        omissions.add("difficulty_aggregates_truncated")

    knowledge_groups: dict[str, dict[str, Any]] = {}
    for row in _knowledge_point_aggregates(chat_facts):
        knowledge_id, shortened = _bounded_source_text(row["tag"], CHAT_CONTEXT_MAX_KNOWLEDGE_BYTES)
        if shortened:
            omissions.add("problem_knowledge_truncated")
        if not knowledge_id:
            continue
        group = knowledge_groups.setdefault(
            knowledge_id,
            {
                "id": knowledge_id,
                "attempted": 0,
                "passed": 0,
                "earned_score": 0,
                "available_score": 0,
            },
        )
        group["attempted"] += row["attempted"]
        group["passed"] += row["passed"]
        group["earned_score"] = _clean_number(group["earned_score"] + row["earned_score"])
        group["available_score"] = _clean_number(group["available_score"] + row["available_score"])
    knowledge = list(knowledge_groups.values())
    knowledge.sort(key=lambda row: (-row["attempted"], row["id"].casefold(), row["id"]))
    total_knowledge_count = len(knowledge)
    if total_knowledge_count > CHAT_CONTEXT_MAX_KNOWLEDGE:
        knowledge = knowledge[:CHAT_CONTEXT_MAX_KNOWLEDGE]
        omissions.add("knowledge_aggregates_truncated")

    language = [
        {"id": language_id, "count": count}
        for language_id, count in sorted(
            language_counts.items(), key=lambda pair: (-pair[1], pair[0].casefold(), pair[0])
        )
    ]
    total_language_count = len(language)
    if total_language_count > CHAT_CONTEXT_MAX_LANGUAGES:
        kept = language[: CHAT_CONTEXT_MAX_LANGUAGES - 1]
        kept.append(
            {
                "id": OTHER_LANGUAGE_ID,
                "count": sum(row["count"] for row in language[CHAT_CONTEXT_MAX_LANGUAGES - 1 :]),
            }
        )
        language = kept
        omissions.add("language_aggregates_truncated")

    ordered_omissions = [value for value in CHAT_CONTEXT_OMISSIONS if value in omissions]
    attempted = sum(fact["attempted"] for fact in chat_facts)
    passed = sum(fact["passed"] for fact in chat_facts)
    return {
        "schema_version": CHAT_CONTEXT_SCHEMA,
        "context_epoch": epoch,
        "generated_at": generated_at,
        "coverage": {
            "status": "partial" if ordered_omissions else "complete",
            "omissions": ordered_omissions,
        },
        "summary": {
            "catalog_problem_count": len(problems),
            "submission_count": len(submissions),
            "catalog_linked_submission_count": len(submissions) - relations["orphan"],
            "orphan_submission_count": relations["orphan"],
            "current_version_submission_count": relations["current"],
            "outdated_version_submission_count": relations["outdated"],
            "version_unknown_submission_count": relations["unknown"],
            "pending_submission_count": outcome_counts["pending"],
            "attempted_problem_count": attempted,
            "passed_problem_count": passed,
            "earned_score": earned,
            "available_score": available,
            "pass_rate": _rate(passed, attempted),
            "included_problem_count": len(per_problem),
            "total_recent_activity_count": total_recent_activity_count,
            "included_recent_activity_count": len(recent_activity),
            "total_difficulty_count": total_difficulty_count,
            "included_difficulty_count": len(difficulty),
            "total_knowledge_count": total_knowledge_count,
            "included_knowledge_count": len(knowledge),
            "total_language_count": total_language_count,
            "included_language_count": len(language),
            "content_projection": "source",
        },
        "per_problem": per_problem,
        "recent_activity": recent_activity,
        "aggregates": {
            "difficulty": difficulty,
            "knowledge": knowledge,
            "outcome": [
                {"id": outcome, "count": outcome_counts[outcome]} for outcome in CHAT_OUTCOME_IDS
            ],
            "language": language,
        },
    }


def _timeline(submissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_problem: dict[str, dict[str, Any]] = {}
    rows: dict[str, dict[str, Any]] = {}
    cumulative: int | float = 0
    for submission in submissions:
        date = submission["date"]
        row = rows.setdefault(
            date,
            {
                "date": date,
                "submissions": 0,
                "completed": 0,
                "best_score_delta": 0,
                "cumulative_score": cumulative,
            },
        )
        row["submissions"] += 1
        row["completed"] += submission["status"] != "pending"
        delta: int | float = 0
        if submission["relation"] == "current" and _valid_best(submission):
            previous = best_by_problem.get(submission["problem_id"])
            if previous is None or _best_order(submission) > _best_order(previous):
                previous_score = previous["score"] if previous is not None else 0
                delta = _clean_number(submission["score"] - previous_score)
                cumulative = _clean_number(cumulative + delta)
                best_by_problem[submission["problem_id"]] = submission
        row["best_score_delta"] = _clean_number(row["best_score_delta"] + delta)
        row["cumulative_score"] = cumulative
    return list(rows.values())


def _difficulty_aggregates(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for fact in facts:
        difficulty = fact["difficulty"]
        key = (difficulty["id"], difficulty["label"], difficulty["order"])
        group = groups.setdefault(
            key,
            {
                "difficulty_id": difficulty["id"],
                "difficulty_label": difficulty["label"],
                "attempted": 0,
                "passed": 0,
                "earned_score": 0,
                "available_score": 0,
            },
        )
        _add_fact(group, fact)
    result = []
    for key in sorted(groups, key=lambda value: (value[2], str(value[1]))):
        group = groups[key]
        group["rate"] = _rate(group["passed"], group["attempted"])
        result.append(group)
    return result


def _knowledge_point_aggregates(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for fact in facts:
        for tag in fact["tags"]:
            group = groups.setdefault(
                tag,
                {
                    "tag": tag,
                    "attempted": 0,
                    "passed": 0,
                    "earned_score": 0,
                    "available_score": 0,
                },
            )
            _add_fact(group, fact)
    result = list(groups.values())
    for group in result:
        group["rate"] = _rate(group["passed"], group["attempted"])
    result.sort(key=lambda group: (-group["attempted"], group["tag"]))
    return result


def _add_fact(group: dict[str, Any], fact: Mapping[str, Any]) -> None:
    group["attempted"] += fact["attempted"]
    group["passed"] += fact["passed"]
    group["earned_score"] = _clean_number(group["earned_score"] + fact["earned_score"])
    group["available_score"] += fact["available_score"]


def _submission_ref(submission: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if submission is None:
        return None
    current: bool | None
    if submission["relation"] == "unknown":
        current = None
    else:
        current = submission["relation"] == "current"
    return {
        "submission_id": submission["submission_id"],
        "status": submission["status"],
        "score": submission["score"],
        "counts": submission["counts"],
        "created_at": submission["created_at"],
        "problem_version": submission["problem_version"],
        "current_version": current,
        "version_inferred": submission["version_inferred"],
    }


def _canonical_problem(problem: Mapping[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "hint": "",
        "source": "",
        "author": "",
        "difficulty": "",
        "tags": [],
        "time_limit": None,
        "memory_limit": None,
    }
    canonical = {field: problem.get(field, defaults.get(field)) for field in PROBLEM_VERSION_FIELDS}
    try:
        # Round-tripping rejects non-JSON database corruption without retaining
        # aliases to caller-owned mutable objects.
        return json.loads(json.dumps(canonical, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("problem fields must be finite JSON values") from error


def _context_epoch(
    canonical_problems: list[dict[str, Any]], submissions: list[dict[str, Any]]
) -> str:
    problems = sorted(
        canonical_problems,
        key=lambda item: (str(item.get("id", "")), _canonical_json(item)),
    )
    submission_projection = [
        {
            "submission_id": item["submission_id"],
            "problem_id": item["problem_id"],
            "revision": item["revision"],
            "status": item["status"],
            "score": item["score"],
            "counts": item["counts"],
            "created_at": item["created_at"],
            "language": item["language"],
            "problem_version": item["problem_version"],
            "version_inferred": item["version_inferred"],
            "verdict": item["verdict"],
            "chat_outcome": item["chat_outcome"],
        }
        for item in submissions
    ]
    encoded = _canonical_json({"problems": problems, "submissions": submission_projection}).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("snapshot contains non-JSON values") from error


def _difficulty(raw: str, normalizer: DifficultyNormalizer | None) -> dict[str, Any]:
    if normalizer is None:
        return {
            "id": None,
            "label": raw.strip() or "unrated",
            "order": 999,
            "recognized": False,
        }
    normalized = normalizer(raw)
    if not isinstance(normalized, Mapping):
        raise ValueError("difficulty normalizer must return a mapping")
    difficulty_id = normalized.get("id")
    label = str(normalized.get("label", "")).strip()
    order = normalized.get("order")
    recognized = normalized.get("recognized")
    if difficulty_id is not None and not isinstance(difficulty_id, str):
        raise ValueError("difficulty id must be a string or null")
    if not label or isinstance(order, bool) or not isinstance(order, int):
        raise ValueError("difficulty label and order are required")
    if not isinstance(recognized, bool):
        raise ValueError("difficulty recognized must be a boolean")
    return {
        "id": difficulty_id,
        "label": label,
        "order": order,
        "recognized": recognized,
    }


def _dedupe_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("problem tags must be a list")
    result = []
    seen = set()
    for raw in value:
        tag = str(raw).strip()
        if not tag:
            continue
        marker = tag.casefold()
        if marker not in seen:
            seen.add(marker)
            result.append(tag)
    return result


def _bounded_source_text(value: Any, maximum_bytes: int) -> tuple[str, bool]:
    text = str(value or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return text, False
    shortened = encoded[:maximum_bytes]
    while True:
        try:
            return shortened.decode("utf-8"), True
        except UnicodeDecodeError as error:
            shortened = shortened[: error.start]


def _bounded_knowledge(values: list[str]) -> tuple[list[str], bool]:
    bounded = []
    seen = set()
    truncated = len(values) > CHAT_CONTEXT_MAX_PROBLEM_KNOWLEDGE
    for value in sorted(values, key=lambda item: (item.casefold(), item))[
        :CHAT_CONTEXT_MAX_PROBLEM_KNOWLEDGE
    ]:
        safe, shortened = _bounded_source_text(value, CHAT_CONTEXT_MAX_KNOWLEDGE_BYTES)
        marker = safe.casefold()
        if safe and marker not in seen:
            bounded.append(safe)
            seen.add(marker)
        else:
            truncated = True
        truncated = truncated or shortened
    return bounded, truncated


def _submission_language(value: Any) -> str:
    if value is None or not str(value).strip():
        return UNKNOWN_LANGUAGE_ID
    language = str(value).strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_+.-]{0,63}", language) is None:
        raise ValueError("submission language is invalid")
    return language


def _chat_problem_order(problem: Mapping[str, Any]) -> tuple[int, float, str]:
    submitted = problem["last_submitted_at"]
    if submitted is None:
        return 1, 0.0, problem["problem_id"]
    timestamp = _utc_datetime(submitted).timestamp()
    return 0, -timestamp, problem["problem_id"]


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("submission created_at must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise ValueError("submission created_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _optional_number(value: Any, field: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"submission {field} must be numeric or null")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"submission {field} must be finite")
    return value


def _validate_score_state(
    status: str, score: int | float | None, counts: int | float | None
) -> None:
    if status == "success" and (score is None or counts is None):
        raise ValueError("successful submissions require score and counts")
    if score is not None and score < 0:
        raise ValueError("submission score cannot be negative")
    if counts is not None and counts < 0:
        raise ValueError("submission counts cannot be negative")
    if score is not None and counts is not None and score > counts:
        raise ValueError("submission score cannot exceed counts")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _outcome(status: str, score: int | float | None, counts: int | float | None) -> str:
    if status == "pending":
        return "pending"
    if status != "success":
        return "judge_error"
    if counts is not None and counts > 0 and score == counts:
        return "full"
    if score is not None and score > 0:
        return "partial"
    return "zero_score"


def _admin_submission_outcome(raw: Mapping[str, Any]) -> str:
    """Reduce one validated submission to a non-sensitive admin chart category."""

    status = str(raw.get("status", ""))
    if status == "pending":
        return "pending"
    if status != "success":
        return "judge_error"
    score = raw.get("score")
    counts = raw.get("counts")
    if counts is not None and counts > 0 and score == counts:
        return "accepted"
    if score is not None and score > 0:
        return "partial"
    compile_info = raw.get("compile_info")
    if isinstance(compile_info, Mapping) and compile_info.get("result") == "error":
        return "compile_error"
    details = raw.get("details")
    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, Mapping):
                continue
            verdict = _JUDGE_VERDICTS.get(detail.get("result"))
            if verdict is not None:
                return verdict
    return "judge_error"


def _submission_verdict(
    raw: Mapping[str, Any],
    status: str,
    score: int | float | None,
    counts: int | float | None,
    *,
    public_cases: bool,
) -> str:
    """Reduce private judge details to one allow-listed, display-safe enum."""

    if status == "pending":
        return "pending"
    if status != "success":
        return "judge_error"
    if counts is not None and counts > 0 and score == counts:
        return "accepted"
    if score is not None and score > 0:
        return "partial"
    details = raw.get("details")
    if public_cases and isinstance(details, list):
        for detail in details:
            if not isinstance(detail, Mapping):
                continue
            verdict = _JUDGE_VERDICTS.get(detail.get("result"))
            if verdict is not None:
                return verdict
    return "judge_error"


def _chat_outcome(
    raw: Mapping[str, Any],
    status: str,
    score: int | float | None,
    counts: int | float | None,
    *,
    public_cases: bool,
) -> str:
    """Expose only an authorized error category, never a private judge detail."""

    if status == "pending":
        return "pending"
    if status != "success":
        return "judge_error"
    if counts is not None and counts > 0 and score == counts:
        return "accepted"
    details = raw.get("details")
    if public_cases and isinstance(details, list):
        for detail in details:
            if not isinstance(detail, Mapping):
                continue
            verdict = _JUDGE_VERDICTS.get(detail.get("result"))
            if verdict is not None:
                return verdict
    if score is not None and score > 0:
        return "partial"
    return "zero_score"


def _valid_best(submission: Mapping[str, Any]) -> bool:
    return (
        submission["status"] == "success"
        and submission["score"] is not None
        and submission["counts"] is not None
        and submission["counts"] > 0
    )


def _latest_order(submission: Mapping[str, Any]) -> tuple[datetime, str]:
    return submission["created_time"], submission["submission_id"]


def _best_order(submission: Mapping[str, Any]) -> tuple[float, float, datetime, str]:
    return (
        submission["score"] / submission["counts"],
        submission["score"],
        submission["created_time"],
        submission["submission_id"],
    )


def _sum_numbers(values: Iterable[int | float]) -> int | float:
    return _clean_number(sum(values))


def _clean_number(value: int | float) -> int | float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("aggregate score is not finite")
    return int(number) if number.is_integer() else number


def _rate(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    value = numerator / denominator
    if not math.isfinite(value):
        raise ValueError("aggregate rate is not finite")
    return value
