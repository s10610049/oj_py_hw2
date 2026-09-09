"""Create a repeatable multi-account demo cohort through the public API.

One hot SQLite backup is completed before the first login or mutation. The
shared demo password is read from ``OJ_LOCAL_PASSWORD`` or requested securely;
it is never written or printed. Re-running the command reuses judge markers and
AI idempotency keys instead of creating unbounded duplicate activity.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sqlite3

import httpx

try:
    from scripts.seed_demo_activity import (
        _data,
        _positive_float,
        _positive_integer,
        backup_database,
        seed_activity,
        seed_ai_trace,
    )
except ModuleNotFoundError:  # Direct ``python scripts/seed_demo_cohort.py`` execution.
    from seed_demo_activity import (  # type: ignore[no-redef]
        _data,
        _positive_float,
        _positive_integer,
        backup_database,
        seed_activity,
        seed_ai_trace,
    )

COHORT = (
    {
        "username": "demo_aurora",
        "activity_keys": ("accepted", "partial", "compile_error"),
    },
    {
        "username": "demo_binary",
        "activity_keys": ("accepted", "partial", "compile_error", "wrong_answer"),
    },
    {
        "username": "demo_cedar",
        "activity_keys": ("accepted", "partial", "compile_error", "time_limit"),
    },
)


def _login(client, username, password):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )


def ensure_account(client, username, password):
    """Log in to an existing fixed demo user, or register it exactly once."""

    response = _login(client, username, password)
    if response.status_code == 200:
        return _data(response), "existing"
    if response.status_code != 401:
        _data(response)

    registration = client.post(
        "/api/users/",
        json={"username": username, "password": password},
    )
    if registration.status_code not in {200, 400}:
        _data(registration)

    # A 400 can be a concurrent create or an account owned by somebody else.
    # In either case, only a successful login proves this run may use it.
    response = _login(client, username, password)
    if response.status_code != 200:
        raise RuntimeError("A fixed demo account exists with different credentials")
    return _data(response), "created" if registration.status_code == 200 else "existing"


def seed_cohort(
    client,
    password,
    *,
    wait_for_quota=False,
    include_submissions=True,
    include_ai=True,
    ai_attempts=2,
    ai_timeout=245.0,
):
    """Ensure differentiated judged activity and two-stage AI traces per user."""

    summaries = []
    for profile in COHORT:
        login, account_state = ensure_account(client, profile["username"], password)
        user_id = login.get("user_id")
        if not isinstance(user_id, str):
            raise RuntimeError("Login response did not identify the demo account")
        submission_results = []
        ai_result = None
        try:
            if include_submissions:
                submission_results = seed_activity(
                    client,
                    user_id,
                    wait_for_quota=wait_for_quota,
                    activity_keys=profile["activity_keys"],
                )
            if include_ai:
                ai_result = seed_ai_trace(
                    client,
                    trace_key=profile["username"].replace("_", "-"),
                    max_attempts=ai_attempts,
                    timeout=ai_timeout,
                )
        finally:
            client.post("/api/auth/logout")
        summaries.append(
            {
                "username": profile["username"],
                "account_state": account_state,
                "submissions": submission_results,
                "ai": ai_result,
            }
        )
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--wait-for-quota", action="store_true")
    parser.add_argument("--database", default=os.environ.get("OJ_DATABASE", "runtime/oj.sqlite3"))
    parser.add_argument(
        "--backup-dir",
        default=os.environ.get("OJ_DEMO_BACKUP_DIR", "runtime/backups"),
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

    password = os.environ.get("OJ_LOCAL_PASSWORD") or getpass.getpass("Demo password: ")
    if not password:
        raise SystemExit("A demo password is required")

    with httpx.Client(
        base_url=args.url,
        timeout=20,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        summaries = seed_cohort(
            client,
            password,
            wait_for_quota=args.wait_for_quota,
            include_submissions=not args.skip_submissions,
            include_ai=not args.skip_ai,
            ai_attempts=args.ai_attempts,
            ai_timeout=args.ai_timeout,
        )

    for summary in summaries:
        created = sum(1 for item in summary["submissions"] if item[1] == "created")
        existing = sum(1 for item in summary["submissions"] if item[1] == "existing")
        ai_state = summary["ai"]["state"] if summary["ai"] is not None else "skipped"
        print(
            f"{summary['username']}: {summary['account_state']}; "
            f"submissions {created} created/{existing} existing; AI {ai_state}"
        )


if __name__ == "__main__":
    main()
