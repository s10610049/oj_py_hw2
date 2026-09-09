"""Safety, verdict-oracle and idempotency checks for the demo seeder."""

import copy
from pathlib import Path
import sqlite3
import sys

import httpx
import pytest

import scripts.seed_demo_activity as seeder
from scripts.seed_demo_activity import (
    ACTIVITIES,
    AI_REQUEST,
    _existing_markers,
    _post_idempotent,
    _verify,
    backup_database,
    seed_activity,
    seed_ai_trace,
)


def envelope(data, status=200):
    return httpx.Response(status, json={"code": status, "msg": "ok", "data": data})


def revision(number, operation, status):
    return {
        "revision": number,
        "operation": operation,
        "task": {"status": status},
    }


def session(session_id, revisions):
    return {
        "session_id": session_id,
        "current_revision": revisions[-1]["revision"],
        "revisions": revisions,
    }


def judged(score, counts, *, errors=(), compile_result=None, run=True):
    compile_info = None
    if compile_result is not None:
        compile_info = {"result": compile_result, "message": "diagnostic"}
    run_info = None
    if run:
        message = f"{counts // 10} test cases finished"
        if errors:
            message += "\nOverall errors: " + ", ".join(errors)
        run_info = {"result": "finished", "message": message}
    return {
        "status": "success",
        "score": score,
        "counts": counts,
        "compile_info": compile_info,
        "run_info": run_info,
    }


def test_demo_activity_matrix_has_stable_unique_real_judge_cases():
    assert [item["key"] for item in ACTIVITIES] == [
        "accepted",
        "partial",
        "wrong_answer",
        "compile_error",
        "time_limit",
    ]
    assert len({item["problem_id"] for item in ACTIVITIES}) == len(ACTIVITIES)
    assert {item["language"] for item in ACTIVITIES} == {"python", "cpp"}
    assert next(item for item in ACTIVITIES if item["key"] == "compile_error")["language"] == "cpp"
    for item in ACTIVITIES:
        assert f"OJ_DEMO_ACTIVITY:v1:{item['key']}" in item["code"]
        assert not {"password", "api_key", "authorization"} & set(item)


def test_database_backup_is_distinct_consistent_and_integrity_checked(tmp_path):
    source = tmp_path / "runtime" / "oj.sqlite3"
    source.parent.mkdir()
    with sqlite3.connect(source) as database:
        database.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT)")
        database.execute("INSERT INTO evidence(value) VALUES ('before')")
        database.commit()

    backup = backup_database(source, tmp_path / "backups")

    assert backup.parent == (tmp_path / "backups").resolve()
    assert backup != source.resolve()
    assert backup.suffix == ".sqlite3"
    assert not list(backup.parent.glob("*.partial"))
    with sqlite3.connect(backup) as database:
        assert database.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert database.execute("SELECT value FROM evidence").fetchall() == [("before",)]
    with sqlite3.connect(source) as database:
        assert database.execute("SELECT value FROM evidence").fetchall() == [("before",)]


def test_database_backup_refuses_missing_source_without_creating_destination(tmp_path):
    destination = tmp_path / "backups"
    with pytest.raises(RuntimeError, match="does not exist"):
        backup_database(tmp_path / "missing.sqlite3", destination)
    assert not destination.exists()


def test_demo_outcome_oracles_distinguish_all_five_verdicts():
    by_key = {item["key"]: item for item in ACTIVITIES}
    _verify(by_key["accepted"], judged(80, 80))
    _verify(by_key["partial"], judged(40, 80, errors=("WA",)))
    _verify(
        by_key["wrong_answer"],
        judged(0, 80, errors=("WA",), compile_result="success"),
    )
    _verify(
        by_key["compile_error"],
        judged(0, 80, compile_result="error", run=False),
    )
    _verify(by_key["time_limit"], judged(0, 80, errors=("TLE",)))


@pytest.mark.parametrize(
    ("key", "detail"),
    [
        ("wrong_answer", judged(0, 80, errors=("TLE",))),
        ("time_limit", judged(0, 80, errors=("WA",))),
        ("compile_error", judged(0, 80, errors=("RE",))),
        ("partial", judged(40, 80, errors=("TLE",))),
        ("accepted", judged(80, 80, errors=("WA",))),
        ("wrong_answer", judged(0, 80)),
    ],
)
def test_zero_or_partial_score_cannot_impersonate_a_specific_verdict(key, detail):
    activity = next(item for item in ACTIVITIES if item["key"] == key)
    with pytest.raises(RuntimeError):
        _verify(activity, detail)


def test_existing_marker_is_reused_only_after_exact_verdict_verification():
    activity = next(item for item in ACTIVITIES if item["key"] == "wrong_answer")

    class Client:
        def __init__(self, errors):
            self.errors = errors

        def get(self, path, params=None):
            if path == "/api/submissions/":
                assert params == {"user_id": "demo-user"}
                return envelope({"submissions": [{"submission_id": "submission-1"}]})
            detail = judged(0, 80, errors=self.errors, compile_result="success")
            detail.update(
                {
                    "problem_id": activity["problem_id"],
                    "language": activity["language"],
                    "code": activity["code"],
                }
            )
            return envelope(detail)

    assert _existing_markers(Client(("TLE",)), "demo-user") == set()
    assert _existing_markers(Client(("WA",)), "demo-user") == {"wrong_answer"}


def test_activity_subset_reuses_only_requested_stable_markers(monkeypatch):
    monkeypatch.setattr(
        seeder,
        "_existing_markers",
        lambda _client, user_id: (
            {"accepted", "partial", "wrong_answer"} if user_id == "demo-user" else set()
        ),
    )

    results = seed_activity(
        object(),
        "demo-user",
        activity_keys=("accepted", "wrong_answer"),
    )

    assert results == [
        ("accepted", "existing", None, None),
        ("wrong_answer", "existing", None, None),
    ]
    with pytest.raises(ValueError, match="unknown demo activity"):
        seed_activity(object(), "demo-user", activity_keys=("not-real",))


def test_idempotent_post_reuses_exact_payload_on_ambiguous_failure():
    class Client:
        def __init__(self):
            self.payloads = []

        def post(self, _path, json):
            self.payloads.append(copy.deepcopy(json))
            if len(self.payloads) == 1:
                return envelope(None, 503)
            return envelope({"session_id": "session-1"})

    client = Client()
    payload = {"idempotency_key": "stable-key", "request": AI_REQUEST}
    assert _post_idempotent(client, "/authoring", payload, retry_delay=0) == {
        "session_id": "session-1"
    }
    assert client.payloads == [payload, payload]


class CompletedAIClient:
    def __init__(self):
        self.posts = []
        self.current = None

    def post(self, path, json):
        self.posts.append((path, copy.deepcopy(json)))
        if path == "/api/ai/authoring-sessions/":
            self.current = session(
                "demo-session",
                [revision(1, "initial", "completed")],
            )
        elif path.endswith("/refinements"):
            self.current = session(
                "demo-session",
                [
                    revision(1, "initial", "completed"),
                    revision(2, "refine_draft", "completed"),
                ],
            )
        else:
            raise AssertionError(path)
        return envelope(copy.deepcopy(self.current))

    def get(self, _path):
        return envelope(copy.deepcopy(self.current))

    def delete(self, path):
        raise AssertionError(path)


def test_ai_demo_creates_completed_initial_and_refinement_with_stable_keys():
    client = CompletedAIClient()

    result = seed_ai_trace(client, poll_interval=0, timeout=1)

    assert result == {
        "session_id": "demo-session",
        "initial_revision": 1,
        "refinement_revision": 2,
        "state": "created",
    }
    initial_path, initial = client.posts[0]
    refine_path, refinement = client.posts[1]
    assert initial_path == "/api/ai/authoring-sessions/"
    assert initial == {
        "idempotency_key": "oj-demo-ai-initial-v1-a1",
        "request": AI_REQUEST,
    }
    assert refine_path == "/api/ai/authoring-sessions/demo-session/refinements"
    assert refinement["expected_revision"] == 1
    assert refinement["idempotency_key"] == "oj-demo-ai-refine-v1-demo-session-r1"
    assert "improvement" in refinement
    assert not any(
        key in str(client.posts).casefold() for key in ("password", "authorization", "api_key")
    )


def test_ai_demo_cohort_trace_uses_stable_account_scoped_keys():
    client = CompletedAIClient()

    result = seed_ai_trace(
        client,
        trace_key="demo-aurora",
        poll_interval=0,
        timeout=1,
    )

    assert result["refinement_revision"] == 2
    assert client.posts[0][1]["idempotency_key"] == ("oj-demo-cohort-demo-aurora-ai-initial-v1-a1")
    assert client.posts[1][1]["idempotency_key"] == (
        "oj-demo-cohort-demo-aurora-ai-refine-v1-demo-session-r1"
    )


@pytest.mark.parametrize("trace_key", ["", "Demo", "contains_underscore", "x" * 41])
def test_ai_demo_rejects_unstable_trace_keys(trace_key):
    with pytest.raises(ValueError, match="trace_key"):
        seed_ai_trace(CompletedAIClient(), trace_key=trace_key)


def test_ai_demo_reuses_existing_completed_refinement_without_new_revision():
    client = CompletedAIClient()
    client.current = session(
        "demo-session",
        [
            revision(1, "initial", "completed"),
            revision(2, "refine_draft", "completed"),
        ],
    )

    def replay_initial(_path, json):
        client.posts.append((_path, copy.deepcopy(json)))
        return envelope(copy.deepcopy(client.current))

    client.post = replay_initial
    result = seed_ai_trace(client, poll_interval=0, timeout=1)

    assert result["state"] == "existing"
    assert result["refinement_revision"] == 2
    assert len(client.posts) == 1


def test_ai_demo_retries_terminal_initial_and_refinement_failures_boundedly():
    class RetryingClient:
        def __init__(self):
            self.posts = []
            self.current = None

        def post(self, path, json):
            self.posts.append((path, copy.deepcopy(json)))
            if path == "/api/ai/authoring-sessions/":
                initial_attempt = len(
                    [item for item in self.posts if item[0] == "/api/ai/authoring-sessions/"]
                )
                self.current = session(
                    f"demo-session-{initial_attempt}",
                    [
                        revision(
                            1,
                            "initial",
                            "failed" if initial_attempt == 1 else "completed",
                        )
                    ],
                )
            elif path.endswith("/refinements"):
                expected = json["expected_revision"]
                earlier = list(self.current["revisions"])
                self.current = session(
                    self.current["session_id"],
                    [
                        *earlier,
                        revision(
                            expected + 1,
                            "refine_draft",
                            "failed" if expected == 1 else "completed",
                        ),
                    ],
                )
            return envelope(copy.deepcopy(self.current))

        def get(self, _path):
            return envelope(copy.deepcopy(self.current))

        def delete(self, path):
            raise AssertionError(path)

    client = RetryingClient()
    result = seed_ai_trace(client, max_attempts=2, poll_interval=0, timeout=1)

    assert result["session_id"] == "demo-session-2"
    assert result["refinement_revision"] == 3
    keys = [payload["idempotency_key"] for _, payload in client.posts]
    assert keys == [
        "oj-demo-ai-initial-v1-a1",
        "oj-demo-ai-initial-v1-a2",
        "oj-demo-ai-refine-v1-demo-session-2-r1",
        "oj-demo-ai-refine-v1-demo-session-2-r2",
    ]


def test_cli_default_backs_up_before_login_then_runs_both_activity_types(monkeypatch, capsys):
    events = []

    def fake_backup(database, backup_dir):
        events.append(("backup", database, backup_dir))
        return Path("runtime/backups/safe.sqlite3")

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, path, json=None):
            events.append(("post", path))
            if path == "/api/auth/login":
                assert json == {"username": "demo-user", "password": "private-password"}
                return envelope({"user_id": "demo-id"})
            if path == "/api/auth/logout":
                return envelope(None)
            raise AssertionError(path)

    def fake_submissions(_client, user_id, *, wait_for_quota):
        events.append(("submissions", user_id, wait_for_quota))
        return []

    def fake_ai(_client, *, max_attempts, timeout):
        events.append(("ai", max_attempts, timeout))
        return {
            "session_id": "demo-session",
            "initial_revision": 1,
            "refinement_revision": 2,
            "state": "created",
        }

    monkeypatch.setattr(seeder, "backup_database", fake_backup)
    monkeypatch.setattr(seeder.httpx, "Client", lambda **_kwargs: Client())
    monkeypatch.setattr(seeder, "seed_activity", fake_submissions)
    monkeypatch.setattr(seeder, "seed_ai_trace", fake_ai)
    monkeypatch.setenv("OJ_LOCAL_PASSWORD", "private-password")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed_demo_activity.py",
            "--username",
            "demo-user",
            "--database",
            "runtime/oj.sqlite3",
        ],
    )

    seeder.main()

    assert [event[0:2] for event in events] == [
        ("backup", "runtime/oj.sqlite3"),
        ("post", "/api/auth/login"),
        ("submissions", "demo-id"),
        ("ai", 2),
        ("post", "/api/auth/logout"),
    ]
    output = capsys.readouterr().out
    assert "private-password" not in output
    assert "demo-user" not in output
    assert "session demo-session" in output
