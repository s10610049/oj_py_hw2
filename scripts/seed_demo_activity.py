"""Create idempotent judged and AI-authoring activity for a local demo account.

The configured SQLite database is backed up before login or any API mutation.
Credentials are read from ``OJ_LOCAL_USERNAME`` / ``OJ_LOCAL_PASSWORD`` or
prompted interactively. They are never printed or written by this script.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import uuid

import httpx

ACTIVITIES = (
    {
        "key": "accepted",
        "problem_id": "DEMO-001",
        "language": "python",
        "code": (
            "# OJ_DEMO_ACTIVITY:v1:accepted\n" "a, b = map(int, input().split())\n" "print(a + b)\n"
        ),
    },
    {
        "key": "partial",
        "problem_id": "DEMO-005",
        "language": "python",
        "code": (
            "# OJ_DEMO_ACTIVITY:v1:partial\n" "n, k = map(int, input().split())\n" "print(n // k)\n"
        ),
    },
    {
        "key": "wrong_answer",
        "problem_id": "DEMO-006",
        "language": "cpp",
        "code": (
            "// OJ_DEMO_ACTIVITY:v1:wrong_answer\n"
            "#include <iostream>\n"
            'int main() { std::cout << "Z\\n"; }\n'
        ),
    },
    {
        "key": "compile_error",
        "problem_id": "DEMO-003",
        "language": "cpp",
        "code": ("// OJ_DEMO_ACTIVITY:v1:compile_error\n" "int main( { return 0; }\n"),
    },
    {
        "key": "time_limit",
        "problem_id": "DEMO-004",
        "language": "python",
        "code": "# OJ_DEMO_ACTIVITY:v1:time_limit\nwhile True:\n    pass\n",
    },
)

AI_REQUEST = {
    "requirement": (
        "设计一道适合 Python 入门教学的整数奇偶判断题。题目必须给出清晰的标准输入输出、"
        "数据范围、至少两个样例、覆盖负数与零的测试点，以及可直接运行的 Python 参考解答。"
        "题目编号固定为 AI-DEMO-001，不依赖网络、随机数或第三方库。"
    ),
    "knowledge_point_ids": [
        "language.numeric-types",
        "language.conditionals",
        "language.input-output",
    ],
    "difficulty_id": "luogu.1",
    "free_prompt": "语言专业、精简，边界条件可复核；输出仅使用 EVEN 或 ODD。",
    "attachments": [],
    "reference_problem_id": None,
}

AI_REFINEMENT = (
    "在保持原题意和难度不变的前提下，补强零、负奇数和极大整数边界说明，"
    "并确认样例、测试点与参考解答完全一致；返回整改后的完整题目。"
)

_AI_ACTIVE = {"pending", "running"}
_AI_TERMINAL = {"completed", "failed", "cancelled", "service_restarted"}
_NETWORK_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RUN_ERROR_LINE = re.compile(r"^Overall errors:\s*(.*?)\s*$", re.MULTILINE)
_RUN_ERROR_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class _AuthoringAttemptFailed(RuntimeError):
    def __init__(self, session, revision, status):
        super().__init__(f"AI revision {revision} ended as {status}")
        self.session = session
        self.revision = revision
        self.status = status


def _data(response, *, expected=(200,)):
    if response.status_code not in expected:
        raise RuntimeError(f"API request failed ({response.status_code})")
    try:
        body = response.json()
    except ValueError as error:
        raise RuntimeError("API returned invalid JSON") from error
    if (
        not isinstance(body, dict)
        or body.get("code") != response.status_code
        or not isinstance(body.get("msg"), str)
        or "data" not in body
    ):
        raise RuntimeError("API returned an invalid envelope")
    return body["data"]


def backup_database(database_path, backup_dir="runtime/backups"):
    """Create and integrity-check a hot SQLite backup without mutating the source."""

    try:
        source_path = Path(database_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RuntimeError("Configured OJ database does not exist") from error
    if not source_path.is_file():
        raise RuntimeError("Configured OJ database is not a file")
    destination_dir = Path(backup_dir).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination_path = destination_dir / (f"oj-demo-{timestamp}-{uuid.uuid4().hex[:12]}.sqlite3")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".oj-demo-backup-",
        suffix=".partial",
        dir=destination_dir,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    source = destination = None
    try:
        source = sqlite3.connect(str(source_path), timeout=10)
        source.execute("PRAGMA query_only = ON")
        destination = sqlite3.connect(str(temporary_path), timeout=10)
        source.backup(destination)
        destination.commit()
        check = destination.execute("PRAGMA quick_check").fetchone()
        if check != ("ok",):
            raise RuntimeError("SQLite backup failed its integrity check")
        destination.close()
        destination = None
        source.close()
        source = None
        temporary_path.replace(destination_path)
    except Exception:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        temporary_path.unlink(missing_ok=True)
        raise
    return destination_path


def _existing_markers(client, user_id):
    listing = _data(client.get("/api/submissions/", params={"user_id": user_id}))
    markers = set()
    for summary in listing.get("submissions", []):
        submission_id = summary.get("submission_id")
        if not isinstance(submission_id, str):
            continue
        detail = _data(client.get(f"/api/submissions/{submission_id}"))
        code = detail.get("code")
        if not isinstance(code, str):
            continue
        for activity in ACTIVITIES:
            marker = f"OJ_DEMO_ACTIVITY:v1:{activity['key']}"
            if (
                marker in code
                and detail.get("problem_id") == activity["problem_id"]
                and detail.get("language") == activity["language"]
            ):
                try:
                    _verify(activity, detail)
                except RuntimeError:
                    continue
                markers.add(activity["key"])
    return markers


def _wait_terminal(client, submission_id, *, timeout=35.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = _data(client.get(f"/api/submissions/{submission_id}"))
        if detail.get("status") != "pending":
            return detail
        time.sleep(0.2)
    raise RuntimeError(f"Submission {submission_id} did not finish in time")


def _run_errors(run_info):
    if not isinstance(run_info, dict) or run_info.get("result") != "finished":
        raise RuntimeError("submission returned invalid run diagnostics")
    message = run_info.get("message")
    if not isinstance(message, str):
        raise RuntimeError("submission returned invalid run diagnostics")
    match = _RUN_ERROR_LINE.search(message)
    if match is None:
        return set()
    tokens = {item.strip() for item in match.group(1).split(",") if item.strip()}
    if not tokens or any(_RUN_ERROR_TOKEN.fullmatch(item) is None for item in tokens):
        raise RuntimeError("submission returned invalid run diagnostics")
    return tokens


def _verify(activity, detail):
    key = activity["key"]
    if detail.get("status") != "success":
        raise RuntimeError(f"{key} ended as {detail.get('status')}")
    if detail.get("error_info") not in (None, ""):
        raise RuntimeError(f"{key} returned a judge error")
    score, counts = detail.get("score"), detail.get("counts")
    if (
        isinstance(score, bool)
        or not isinstance(score, int)
        or isinstance(counts, bool)
        or not isinstance(counts, int)
        or counts <= 0
        or not 0 <= score <= counts
    ):
        raise RuntimeError(f"{key} returned invalid scores")
    compile_info = detail.get("compile_info")
    if key == "compile_error":
        if (
            score != 0
            or not isinstance(compile_info, dict)
            or compile_info.get("result") != "error"
            or detail.get("run_info") is not None
        ):
            raise RuntimeError("compile_error was not proven by compile diagnostics")
        return
    if compile_info is not None and (
        not isinstance(compile_info, dict) or compile_info.get("result") != "success"
    ):
        raise RuntimeError(f"{key} returned unexpected compile diagnostics")
    errors = _run_errors(detail.get("run_info"))
    expected = {
        "accepted": (lambda: score == counts and errors == set()),
        "partial": (lambda: 0 < score < counts and errors == {"WA"}),
        "wrong_answer": (lambda: score == 0 and errors == {"WA"}),
        "time_limit": (lambda: score == 0 and errors == {"TLE"}),
    }
    check = expected.get(key)
    if check is None or not check():
        raise RuntimeError(f"{key} did not match its exact expected verdict")


def seed_activity(client, user_id, *, wait_for_quota=False, activity_keys=None):
    """Ensure the selected deterministic judge outcomes exist for one account."""

    if activity_keys is None:
        selected = ACTIVITIES
    else:
        requested = tuple(activity_keys)
        known = {activity["key"] for activity in ACTIVITIES}
        unknown = set(requested) - known
        if unknown:
            raise ValueError(f"unknown demo activity keys: {', '.join(sorted(unknown))}")
        selected = tuple(activity for activity in ACTIVITIES if activity["key"] in requested)
    existing = _existing_markers(client, user_id)
    results = []
    for activity in selected:
        if activity["key"] in existing:
            results.append((activity["key"], "existing", None, None))
            continue
        while True:
            response = client.post(
                "/api/submissions/",
                json={
                    "problem_id": activity["problem_id"],
                    "language": activity["language"],
                    "code": activity["code"],
                },
            )
            if response.status_code != 429:
                break
            if not wait_for_quota:
                results.append((activity["key"], "quota_deferred", None, None))
                return results
            time.sleep(30)
        pending = _data(response)
        detail = _wait_terminal(client, pending["submission_id"])
        _verify(activity, detail)
        results.append(
            (
                activity["key"],
                "created",
                detail["score"],
                detail["counts"],
            )
        )
    return results


def _post_idempotent(client, path, payload, *, attempts=3, retry_delay=0.5):
    """Retry ambiguous requests with the exact same idempotency payload."""

    last_response = None
    for attempt in range(attempts):
        try:
            response = client.post(path, json=payload)
        except httpx.TransportError:
            if attempt + 1 == attempts:
                raise RuntimeError("AI API request remained unavailable") from None
        else:
            if response.status_code not in _NETWORK_RETRY_STATUSES:
                return _data(response)
            last_response = response
            if attempt + 1 == attempts:
                return _data(last_response)
        if retry_delay:
            time.sleep(retry_delay)
    raise RuntimeError("AI API request remained unavailable")


def _revision(session, revision_number):
    revisions = session.get("revisions") if isinstance(session, dict) else None
    if not isinstance(revisions, list):
        raise RuntimeError("AI session returned invalid revisions")
    for revision in revisions:
        if isinstance(revision, dict) and revision.get("revision") == revision_number:
            task = revision.get("task")
            if not isinstance(task, dict):
                break
            return revision, task
    raise RuntimeError("AI session omitted the requested revision")


def _wait_authoring_revision(
    client,
    session,
    revision_number,
    *,
    timeout=245.0,
    poll_interval=1.0,
):
    session_id = session.get("session_id") if isinstance(session, dict) else None
    if not isinstance(session_id, str):
        raise RuntimeError("AI session did not include an id")
    deadline = time.monotonic() + timeout
    while True:
        _, task = _revision(session, revision_number)
        status = task.get("status")
        if status == "completed":
            return session
        if status in _AI_TERMINAL:
            raise _AuthoringAttemptFailed(session, revision_number, status)
        if status not in _AI_ACTIVE:
            raise RuntimeError("AI session returned an invalid task status")
        if time.monotonic() >= deadline:
            current = session.get("current_revision")
            if current == revision_number:
                cancelled = client.delete(f"/api/ai/authoring-sessions/{session_id}/active-task")
                if cancelled.status_code == 200:
                    session = _data(cancelled)
            session = _data(client.get(f"/api/ai/authoring-sessions/{session_id}"))
            _, final_task = _revision(session, revision_number)
            final_status = final_task.get("status")
            if final_status == "completed":
                return session
            raise _AuthoringAttemptFailed(
                session,
                revision_number,
                final_status if final_status in _AI_TERMINAL else "timeout",
            )
        if poll_interval:
            time.sleep(poll_interval)
        session = _data(client.get(f"/api/ai/authoring-sessions/{session_id}"))


def _completed_refinement(session):
    revisions = session.get("revisions") if isinstance(session, dict) else None
    if not isinstance(revisions, list):
        raise RuntimeError("AI session returned invalid revisions")
    completed = [
        revision.get("revision")
        for revision in revisions
        if isinstance(revision, dict)
        and revision.get("operation") == "refine_draft"
        and isinstance(revision.get("task"), dict)
        and revision["task"].get("status") == "completed"
        and isinstance(revision.get("revision"), int)
    ]
    return max(completed, default=None)


def seed_ai_trace(
    client,
    *,
    trace_key=None,
    max_attempts=2,
    timeout=245.0,
    poll_interval=1.0,
    network_attempts=3,
):
    """Ensure one completed initial draft and one completed refinement trace."""

    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if trace_key is None:
        key_prefix = "oj-demo"
    elif not isinstance(trace_key, str) or re.fullmatch(r"[a-z0-9-]{1,40}", trace_key) is None:
        raise ValueError("trace_key must contain only lowercase letters, digits, and hyphens")
    else:
        key_prefix = f"oj-demo-cohort-{trace_key}"

    session = None
    initial_failure = None
    for attempt in range(1, max_attempts + 1):
        payload = {
            "idempotency_key": f"{key_prefix}-ai-initial-v1-a{attempt}",
            "request": AI_REQUEST,
        }
        session = _post_idempotent(
            client,
            "/api/ai/authoring-sessions/",
            payload,
            attempts=network_attempts,
        )
        try:
            session = _wait_authoring_revision(
                client,
                session,
                1,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            break
        except _AuthoringAttemptFailed as error:
            session, initial_failure = error.session, error
    else:
        raise RuntimeError(
            f"AI initial draft did not complete after {max_attempts} bounded attempts"
        ) from initial_failure

    existing_refinement = _completed_refinement(session)
    if existing_refinement is not None:
        return {
            "session_id": session["session_id"],
            "initial_revision": 1,
            "refinement_revision": existing_refinement,
            "state": "existing",
        }

    current_revision = session.get("current_revision")
    if not isinstance(current_revision, int) or current_revision < 1:
        raise RuntimeError("AI session returned an invalid current revision")
    _, current_task = _revision(session, current_revision)
    if current_task.get("status") in _AI_ACTIVE:
        try:
            session = _wait_authoring_revision(
                client,
                session,
                current_revision,
                timeout=timeout,
                poll_interval=poll_interval,
            )
        except _AuthoringAttemptFailed as error:
            session = error.session
        existing_refinement = _completed_refinement(session)
        if existing_refinement is not None:
            return {
                "session_id": session["session_id"],
                "initial_revision": 1,
                "refinement_revision": existing_refinement,
                "state": "existing",
            }

    refinement_failure = None
    for _ in range(max_attempts):
        expected_revision = session.get("current_revision")
        if not isinstance(expected_revision, int) or expected_revision < 1:
            raise RuntimeError("AI session returned an invalid current revision")
        payload = {
            "expected_revision": expected_revision,
            "improvement": AI_REFINEMENT,
            "idempotency_key": (
                f"{key_prefix}-ai-refine-v1-{session['session_id']}-r{expected_revision}"
            ),
        }
        session = _post_idempotent(
            client,
            f"/api/ai/authoring-sessions/{session['session_id']}/refinements",
            payload,
            attempts=network_attempts,
        )
        target_revision = expected_revision + 1
        try:
            session = _wait_authoring_revision(
                client,
                session,
                target_revision,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            return {
                "session_id": session["session_id"],
                "initial_revision": 1,
                "refinement_revision": target_revision,
                "state": "created",
            }
        except _AuthoringAttemptFailed as error:
            session, refinement_failure = error.session, error
    raise RuntimeError(
        f"AI refinement did not complete after {max_attempts} bounded attempts"
    ) from refinement_failure


def _positive_integer(value):
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _positive_float(value):
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default=os.environ.get("OJ_LOCAL_USERNAME"))
    parser.add_argument("--wait-for-quota", action="store_true")
    parser.add_argument("--database", default=os.environ.get("OJ_DATABASE", "runtime/oj.sqlite3"))
    parser.add_argument(
        "--backup-dir", default=os.environ.get("OJ_DEMO_BACKUP_DIR", "runtime/backups")
    )
    parser.add_argument("--skip-submissions", action="store_true")
    parser.add_argument("--skip-ai", action="store_true")
    parser.add_argument("--ai-attempts", type=_positive_integer, default=2)
    parser.add_argument("--ai-timeout", type=_positive_float, default=245.0)
    args = parser.parse_args()
    if args.skip_submissions and args.skip_ai:
        parser.error("at least one demo activity must remain enabled")

    try:
        backup_path = backup_database(args.database, args.backup_dir)
    except (OSError, sqlite3.Error, RuntimeError) as error:
        raise SystemExit(f"Database backup failed: {error}") from error
    print(f"database_backup: {backup_path}")

    username = args.username or input("Username: ").strip()
    password = os.environ.get("OJ_LOCAL_PASSWORD") or getpass.getpass("Password: ")
    if not username or not password:
        raise SystemExit("Username and password are required")

    results = []
    ai_result = None
    with httpx.Client(
        base_url=args.url,
        timeout=20,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        login = _data(
            client.post(
                "/api/auth/login",
                json={"username": username, "password": password},
            )
        )
        user_id = login.get("user_id")
        if not isinstance(user_id, str):
            raise SystemExit("Login response did not identify the account")
        try:
            if not args.skip_submissions:
                results = seed_activity(
                    client,
                    user_id,
                    wait_for_quota=args.wait_for_quota,
                )
            if not args.skip_ai:
                ai_result = seed_ai_trace(
                    client,
                    max_attempts=args.ai_attempts,
                    timeout=args.ai_timeout,
                )
        finally:
            client.post("/api/auth/logout")

    for key, state, score, counts in results:
        suffix = "" if score is None else f" ({score}/{counts})"
        print(f"{key}: {state}{suffix}")
    if ai_result is not None:
        print(
            "ai_authoring: "
            f"{ai_result['state']} "
            f"(session {ai_result['session_id']}, "
            f"revisions {ai_result['initial_revision']}+{ai_result['refinement_revision']})"
        )


if __name__ == "__main__":
    main()
