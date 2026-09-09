"""Contract and safety checks for the multi-account demo cohort seeder."""

from pathlib import Path
import sys

import httpx
import pytest

import scripts.seed_demo_cohort as cohort
from scripts.seed_demo_activity import ACTIVITIES


def envelope(data, status=200):
    return httpx.Response(status, json={"code": status, "msg": "ok", "data": data})


def test_cohort_profiles_are_fixed_differentiated_and_cover_required_outcomes():
    profiles = cohort.COHORT
    known = {activity["key"] for activity in ACTIVITIES}

    assert len(profiles) >= 3
    assert len({profile["username"] for profile in profiles}) == len(profiles)
    assert all(profile["username"].startswith("demo_") for profile in profiles)
    assert all(len(profile["activity_keys"]) >= 3 for profile in profiles)
    assert all(set(profile["activity_keys"]) <= known for profile in profiles)
    required_per_account = {"accepted", "partial", "compile_error"}
    assert all(required_per_account <= set(profile["activity_keys"]) for profile in profiles)
    assert {tuple(profile["activity_keys"]) for profile in profiles} == {
        ("accepted", "partial", "compile_error"),
        ("accepted", "partial", "compile_error", "wrong_answer"),
        ("accepted", "partial", "compile_error", "time_limit"),
    }
    assert set().union(*(set(profile["activity_keys"]) for profile in profiles)) == known


class AccountClient:
    def __init__(self, login_statuses, register_status=200):
        self.login_statuses = list(login_statuses)
        self.register_status = register_status
        self.calls = []

    def post(self, path, json=None):
        self.calls.append((path, json))
        if path == "/api/auth/login":
            status = self.login_statuses.pop(0)
            data = {"user_id": "demo-id", "role": "user"} if status == 200 else None
            return envelope(data, status)
        if path == "/api/users/":
            return envelope({"user_id": "demo-id"}, self.register_status)
        raise AssertionError(path)


def test_existing_account_is_reused_without_registration():
    client = AccountClient([200])

    login, state = cohort.ensure_account(client, "demo_aurora", "private")

    assert login["user_id"] == "demo-id"
    assert state == "existing"
    assert [call[0] for call in client.calls] == ["/api/auth/login"]


def test_missing_account_is_registered_then_logged_in():
    client = AccountClient([401, 200])

    login, state = cohort.ensure_account(client, "demo_aurora", "private")

    assert login["user_id"] == "demo-id"
    assert state == "created"
    assert [call[0] for call in client.calls] == [
        "/api/auth/login",
        "/api/users/",
        "/api/auth/login",
    ]
    assert client.calls[1][1] == {"username": "demo_aurora", "password": "private"}


def test_inaccessible_preexisting_account_is_never_overwritten():
    client = AccountClient([401, 401], register_status=400)

    with pytest.raises(RuntimeError, match="different credentials"):
        cohort.ensure_account(client, "demo_aurora", "private")

    assert [call[0] for call in client.calls] == [
        "/api/auth/login",
        "/api/users/",
        "/api/auth/login",
    ]


def test_seed_cohort_runs_distinct_real_activity_and_two_stage_ai_for_every_account(
    monkeypatch,
):
    events = []

    class Client:
        def post(self, path, json=None):
            assert path == "/api/auth/logout"
            events.append(("logout",))
            return envelope(None)

    def fake_account(_client, username, password):
        assert password == "private"
        events.append(("account", username))
        return {"user_id": f"id-{username}"}, "existing"

    def fake_activity(_client, user_id, *, wait_for_quota, activity_keys):
        events.append(("activity", user_id, wait_for_quota, tuple(activity_keys)))
        return [(key, "existing", None, None) for key in activity_keys]

    def fake_ai(_client, *, trace_key, max_attempts, timeout):
        events.append(("ai", trace_key, max_attempts, timeout))
        return {
            "session_id": f"session-{trace_key}",
            "initial_revision": 1,
            "refinement_revision": 2,
            "state": "existing",
        }

    monkeypatch.setattr(cohort, "ensure_account", fake_account)
    monkeypatch.setattr(cohort, "seed_activity", fake_activity)
    monkeypatch.setattr(cohort, "seed_ai_trace", fake_ai)

    summaries = cohort.seed_cohort(
        Client(),
        "private",
        wait_for_quota=True,
        ai_attempts=3,
        ai_timeout=99,
    )

    assert len(summaries) == len(cohort.COHORT)
    assert len([event for event in events if event[0] == "activity"]) == len(cohort.COHORT)
    assert len([event for event in events if event[0] == "ai"]) == len(cohort.COHORT)
    assert len([event for event in events if event[0] == "logout"]) == len(cohort.COHORT)
    for profile in cohort.COHORT:
        assert (
            "activity",
            f"id-{profile['username']}",
            True,
            profile["activity_keys"],
        ) in events
        assert (
            "ai",
            profile["username"].replace("_", "-"),
            3,
            99,
        ) in events


def test_cli_backs_up_once_before_any_account_login_and_never_prints_password(monkeypatch, capsys):
    events = []

    def fake_backup(database, backup_dir):
        events.append(("backup", database, backup_dir))
        return Path("runtime/backups/cohort.sqlite3")

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_seed(_client, password, **options):
        assert password == "private-password"
        events.append(("seed", options))
        return [
            {
                "username": profile["username"],
                "account_state": "existing",
                "submissions": [],
                "ai": {"state": "existing"},
            }
            for profile in cohort.COHORT
        ]

    monkeypatch.setattr(cohort, "backup_database", fake_backup)
    monkeypatch.setattr(cohort.httpx, "Client", lambda **_kwargs: Client())
    monkeypatch.setattr(cohort, "seed_cohort", fake_seed)
    monkeypatch.setenv("OJ_LOCAL_PASSWORD", "private-password")
    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_demo_cohort.py", "--database", "runtime/oj.sqlite3"],
    )

    cohort.main()

    assert [event[0] for event in events] == ["backup", "seed"]
    output = capsys.readouterr().out
    assert "private-password" not in output
    assert output.count("database_backup:") == 1
