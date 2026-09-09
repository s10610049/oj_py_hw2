"""The live AI matrix is tested with a fake API and never contacts a provider."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re

import httpx
import pytest

import scripts.verify_ai_matrix as matrix


def envelope(data, status=200):
    return httpx.Response(status, json={"code": status, "msg": "ok", "data": data})


ORACLE_INPUTS = {
    "deadlock": (
        "4 4\n1 2\n1 3\n2 4\n3 4\n",
        "3 3\n1 2\n2 3\n3 1\n",
        "3 2\n1 2\n2 3\n",
    ),
    "input-output": ("1\n-5\n", "4\n-2 0 3 1\n", "3\n0 0 0\n"),
    "strings": ("Aa b\n", "\n", "b B a A\n"),
    "arrays": ("6 7\n2 3 1 2 4 3\n", "3 20\n1 2 3\n", "1 5\n5\n"),
    "sorting": (
        "4\na 1 2\nb 1 9\nc 0 1\nd 1 9\n",
        "3\nx 2 1\ny 1 1\nz 3 1\n",
        "3\np 0 0\nq 0 2\nr 0 1\n",
    ),
    "binary-search": (
        "5 3\n1 2 2 2 5\n2 1 4\n",
        "3 2\n0 0 1\n0 2\n",
        "4 2\n-2 -1 3 3\n3 -2\n",
    ),
    "stack": ("([)]\n", "([]{})\n", "(()\n"),
    "queue": (
        "5\nIN a\nIN b\nFRONT\nOUT\nOUT\n",
        "3\nOUT\nIN x\nFRONT\n",
        "4\nIN x\nIN y\nOUT\nFRONT\n",
    ),
    "graph": (
        "5 2\n1 2\n2 3\n",
        "4 0\n",
        "6 3\n1 2\n3 4\n4 3\n",
    ),
    "bfs": ("3 4\nS#T.\n....\n####\n", "1 2\nST\n", "3 3\nS##\n###\n##T\n"),
    "dfs": ("2 2\n10\n01\n", "2 3\n111\n000\n", "3 3\n101\n000\n101\n"),
    "greedy": (
        "4\n1 10\n2 3\n3 4\n4 5\n",
        "3\n0 1\n1 2\n2 3\n",
        "3\n1 5\n2 6\n6 7\n",
    ),
    "dynamic-programming": ("2 4\n3 5\n2 3\n", "1 6\n2 4\n", "3 0\n1 9\n2 8\n3 7\n"),
    "mathematics": ("2\n6 9\n5 5\n", "1\n7 11\n", "2\n12 4\n8 20\n"),
    "simulation": (
        "5 3 4\nUP 5\nUP 2\nDOWN 1\nGOTO 8\n",
        "10 1 3\nDOWN 1\nGOTO 7\nUP 7\n",
        "4 4 3\nUP 9\nDOWN 2\nGOTO 1\n",
    ),
    "boundary-cases": ("-3 3\n", "1 3\n", "1000000000000000000 1000000000000000000\n"),
    "grid-dp": (
        "2 3\n1 9 1\n2 1 8\n",
        "2 2\n1 X\nX 2\n",
        "1 4\n-5 2 -1 3\n",
    ),
}


def valid_result(problem_id, *, case, difficulty="普及+/提高-", secret=""):
    oracle_key = matrix._oracle_key(case)
    oracle = matrix.ORACLES[oracle_key]
    inputs = ORACLE_INPUTS[oracle_key]
    pairs = [{"input": value, "output": oracle.solve(value) + "\n"} for value in inputs]
    return {
        "id": problem_id,
        "title": "Synthetic problem",
        "description": oracle.contract,
        "input_description": oracle.contract,
        "output_description": oracle.contract,
        "constraints": "1 <= n <= 10",
        "hint": "",
        "source": "AI generated",
        "author": "AI",
        "difficulty": difficulty,
        "tags": ["test"],
        "samples": pairs[:1],
        "testcases": pairs,
        "time_limit": 1.0,
        "memory_limit": 128,
        "reference_solution": f"print(1)\n# {secret}",
        "test_generator": "import json\nprint(json.dumps(['1\\n']))",
        "validation_notes": "checked",
        "test_generation_notes": "deterministic",
        "translations": {
            "en": {
                "title": "Synthetic problem",
                "description": "Description",
                "input_description": "Input",
                "output_description": "Output",
                "constraints": "1 <= n <= 10",
                "hint": "",
            }
        },
    }


class FakeClient:
    def __init__(
        self,
        *,
        provider=matrix.EXPECTED_PROVIDER,
        model=matrix.EXPECTED_MODEL,
        key_configured=True,
        terminal="completed",
        interrupt_on_get=False,
        retry_first_create=False,
    ):
        self.provider = provider
        self.model = model
        self.key_configured = key_configured
        self.terminal = terminal
        self.interrupt_on_get = interrupt_on_get
        self.retry_first_create = retry_first_create
        self.create_failures = 0
        self.calls = []
        self.sessions = {}
        self.cancelled = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def request(self, method, path, json=None):
        self.calls.append((method, path, copy.deepcopy(json)))
        if path == "/api/auth/login":
            return envelope({"user_id": "admin", "role": "admin"})
        if path == "/api/ai/model-config":
            return envelope(
                {
                    "provider_url": self.provider,
                    "model": self.model,
                    "api_key_configured": self.key_configured,
                }
            )
        if method == "POST" and path == "/api/ai/authoring-sessions/":
            if self.retry_first_create and self.create_failures == 0:
                self.create_failures += 1
                return envelope(None, 503)
            session_number = len(self.sessions) + 1
            session_id = f"session-{session_number}"
            task_id = f"task-{session_number}"
            expected_id = re.search(
                r"题目 id 必须精确使用 ([A-Z0-9-]+)", json["request"]["free_prompt"]
            ).group(1)
            expected_difficulty = matrix.EXPECTED_DIFFICULTIES[json["request"]["difficulty_id"]]
            task = {
                "task_id": task_id,
                "status": "pending",
                "progress": "api_key=sk-do-not-save-this",
                "progress_percent": 5,
                "result": None,
                "error_code": None,
                "provider_calls": 0,
                "usage": {},
            }
            session = {
                "session_id": session_id,
                "current_revision": 1,
                "revisions": [{"revision": 1, "task": task}],
                "_expected_id": expected_id,
                "_expected_difficulty": expected_difficulty,
                "_case": matrix.CASES[session_number - 1],
            }
            self.sessions[session_id] = session
            return envelope(self._public(session))
        if method == "GET" and path.startswith("/api/ai/authoring-sessions/"):
            if self.interrupt_on_get:
                raise KeyboardInterrupt
            session_id = path.rsplit("/", 1)[-1]
            session = self.sessions[session_id]
            task = session["revisions"][0]["task"]
            task.update(
                {
                    "status": self.terminal,
                    "progress": self.terminal,
                    "progress_percent": 100 if self.terminal == "completed" else 72,
                    "result": (
                        valid_result(
                            session["_expected_id"],
                            case=session["_case"],
                            difficulty=session["_expected_difficulty"],
                            secret="sk-hidden-in-result",
                        )
                        if self.terminal == "completed"
                        else None
                    ),
                    "error_code": None if self.terminal == "completed" else "provider_failed",
                    "provider_calls": 1,
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 200,
                        "total_tokens": 300,
                        "cost": 0.01,
                        "currency": "CNY",
                        "source": "provider",
                        "incomplete": False,
                    },
                }
            )
            return envelope(self._public(session))
        if method == "DELETE" and path.endswith("/active-task"):
            session_id = path.split("/")[-2]
            self.cancelled.append(session_id)
            return envelope({"session_id": session_id, "status": "cancelled"})
        raise AssertionError((method, path))

    @staticmethod
    def _public(session):
        value = copy.deepcopy(session)
        value.pop("_expected_id", None)
        value.pop("_expected_difficulty", None)
        value.pop("_case", None)
        return value


def verifier(tmp_path, client, *, run_id="1" * 32):
    return matrix.LiveMatrixVerifier(
        client,
        run_id=run_id,
        evidence_path=tmp_path / "evidence.json",
        poll_interval=0,
    )


def test_inventory_has_three_exact_deadlock_runs_and_sixteen_unique_matrix_cases():
    assert len(matrix.CASES) == 19
    assert len({case["case_id"] for case in matrix.CASES}) == 19
    assert all(case["requirement"] == matrix.DEADLOCK_REQUIREMENT for case in matrix.CASES[:3])
    assert matrix.DEADLOCK_REQUIREMENT == (
        "多线程死锁检测：设计一道与多线程资源竞争有关的题目。"
        "给出若干线程获取锁的先后关系，要求判断这些线程是否可能发生死锁。"
        "题目不依赖真实线程运行，预期将锁的依赖关系转换为有向图，"
        "并使用拓扑排序或环检测算法完成判断。"
    )
    categories = {case["category"] for case in matrix.CASES[3:]}
    assert {
        "input-output",
        "strings",
        "arrays",
        "sorting",
        "binary-search",
        "stack",
        "queue",
        "graph",
        "bfs",
        "dfs",
        "greedy",
        "dynamic-programming",
        "mathematics",
        "simulation",
        "boundary-cases",
    }.issubset(categories)
    assert {case["difficulty"] for case in matrix.CASES} >= {
        "luogu.1",
        "luogu.2",
        "luogu.3",
        "luogu.4",
        "luogu.5",
    }


@pytest.mark.parametrize(
    "case",
    [
        next(item for item in matrix.CASES if matrix._oracle_key(item) == oracle_id)
        for oracle_id in matrix.ORACLES
    ],
    ids=list(matrix.ORACLES),
)
def test_each_category_oracle_rejects_its_typical_wrong_solution(case):
    result = valid_result("LIVE-ORACLE-01", case=case)
    oracle = matrix.ORACLES[matrix._oracle_key(case)]
    for collection in (result["samples"], result["testcases"]):
        for item in collection:
            item["output"] = oracle.typical_wrong(item["input"])

    expected_code = f"oracle_{matrix._oracle_key(case).replace('-', '_')}_answer_mismatch"
    with pytest.raises(matrix.VerificationError, match=expected_code):
        matrix._validate_result(result, "LIVE-ORACLE-01", "普及+/提高-", case)


def test_each_live_discriminator_defeats_its_typical_wrong_solution():
    assert set(matrix.DISCRIMINATING_INPUTS) == set(matrix.ORACLES)
    for oracle_id, raw_input in matrix.DISCRIMINATING_INPUTS.items():
        oracle = matrix.ORACLES[oracle_id]
        assert oracle.solve(raw_input) != oracle.typical_wrong(raw_input)


def test_category_oracle_fails_closed_without_echoing_malformed_input():
    case = next(item for item in matrix.CASES if item["category"] == "deadlock")
    result = valid_result("LIVE-ORACLE-02", case=case)
    result["testcases"][1] = {
        "input": "not-a-graph sk-sensitive-value",
        "output": "NO",
    }

    with pytest.raises(matrix.VerificationError) as captured:
        matrix._validate_result(result, "LIVE-ORACLE-02", "普及+/提高-", case)

    assert captured.value.code == "oracle_deadlock_invalid_input"
    assert "sensitive" not in str(captured.value)


def test_each_request_freezes_its_oracle_contract_without_changing_requirement():
    for ordinal, case in enumerate(matrix.CASES, start=1):
        body = matrix._request_body(case, f"LIVE-TEST-{ordinal:02d}")
        oracle = matrix.ORACLES[matrix._oracle_key(case)]
        assert body["requirement"] == case["requirement"]
        assert oracle.contract in body["free_prompt"]
        assert "至少 3 个" in body["free_prompt"]
        assert "畸形输入" in body["free_prompt"]
        assert (
            json.dumps(matrix.DISCRIMINATING_INPUTS[matrix._oracle_key(case)], ensure_ascii=False)
            in body["free_prompt"]
        )


def test_queue_oracle_keeps_successful_out_silent():
    oracle = matrix.ORACLES["queue"]
    raw = "5\nIN a\nIN b\nFRONT\nOUT\nOUT\n"

    assert oracle.solve(raw) == "a"
    assert oracle.typical_wrong(raw) == "b"


def test_simulation_oracle_accepts_both_declared_header_layouts():
    oracle = matrix.ORACLES["simulation"]
    one_line = "5 3 4\nUP 5\nUP 2\nDOWN 1\nGOTO 8\n"
    two_lines = "5 3\n4\nUP 5\nUP 2\nDOWN 1\nGOTO 8\n"

    assert oracle.solve(one_line) == "3\n5\n4\n4"
    assert oracle.solve(two_lines) == oracle.solve(one_line)


def test_without_live_flag_constructs_no_http_client(capsys):
    constructed = []

    def factory(**_):
        constructed.append(True)
        return FakeClient()

    assert matrix.main([], client_factory=factory) == 2
    assert constructed == []
    assert "No provider call made" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"provider": "https://example.invalid"}, "unexpected_provider"),
        ({"model": "not-flash"}, "unexpected_model"),
        ({"key_configured": False}, "api_key_not_configured"),
    ],
)
def test_configuration_guard_prevents_authoring(tmp_path, updates, code):
    client = FakeClient(**updates)
    with pytest.raises(matrix.VerificationError, match=code):
        verifier(tmp_path, client).run(matrix.CASES[:1])
    assert not any(path == "/api/ai/authoring-sessions/" for _, path, _ in client.calls)


def test_success_runs_independent_sessions_and_writes_only_redacted_evidence(tmp_path):
    client = FakeClient()
    evidence = verifier(tmp_path, client).run()

    assert len(evidence) == 19
    assert len({item["session_id"] for item in evidence}) == 19
    assert len({item["task_id"] for item in evidence}) == 19
    assert all(item["status"] == "completed" for item in evidence)
    assert all(item["elapsed_seconds"] < 240 for item in evidence)
    assert all(item["result_digest"] and len(item["result_digest"]) == 64 for item in evidence)
    assert all(item["progress_trace"][-1]["percent"] == 100 for item in evidence)
    assert evidence[0]["progress_trace"][0]["stage"] == "[redacted]"
    assert all(set(item) == matrix.EVIDENCE_FIELDS for item in evidence)

    raw = (tmp_path / "evidence.json").read_text(encoding="utf-8")
    assert json.loads(raw) == evidence
    for forbidden in (
        "admintestpassword",
        "sk-do-not-save-this",
        "sk-hidden-in-result",
        "reference_solution",
        "testcases",
        matrix.DEADLOCK_REQUIREMENT,
    ):
        assert forbidden not in raw

    posts = [
        payload
        for method, path, payload in client.calls
        if method == "POST" and path.endswith("sessions/")
    ]
    assert len(posts) == 19
    assert len({payload["idempotency_key"] for payload in posts}) == 19
    assert [payload["request"]["requirement"] for payload in posts[:3]] == [
        matrix.DEADLOCK_REQUIREMENT
    ] * 3


def test_ambiguous_create_retry_reuses_exact_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(matrix.time, "sleep", lambda _: None)
    client = FakeClient(retry_first_create=True)
    verifier(tmp_path, client).run(matrix.CASES[:1])

    posts = [
        payload
        for method, path, payload in client.calls
        if method == "POST" and path.endswith("sessions/")
    ]
    assert len(posts) == 2
    assert posts[0] == posts[1]
    assert posts[0]["idempotency_key"] == f"ai-matrix-{'1' * 32}-01"


def test_terminal_failure_returns_nonzero_and_records_only_error_code(tmp_path, capsys):
    client = FakeClient(terminal="failed")

    def factory(**_):
        return client

    result = matrix.main(
        [
            "--live",
            "--poll-interval",
            "0",
            "--evidence-dir",
            str(tmp_path),
        ],
        client_factory=factory,
    )
    assert result == 1
    assert "Matrix failed" in capsys.readouterr().out
    evidence_files = list(tmp_path.glob("ai-matrix-*.json"))
    assert len(evidence_files) == 1
    evidence = json.loads(evidence_files[0].read_text(encoding="utf-8"))
    assert evidence[0]["status"] == "failed"
    assert evidence[0]["error_code"] == "provider_failed"
    assert evidence[0]["session_id"] == "session-1"
    assert evidence[0]["task_id"] == "task-1"


def test_interrupt_cancels_only_the_active_session_and_keeps_safe_evidence(tmp_path):
    client = FakeClient(interrupt_on_get=True)
    runner = verifier(tmp_path, client)

    with pytest.raises(KeyboardInterrupt):
        runner.run(matrix.CASES[:1])

    assert client.cancelled == ["session-1"]
    evidence = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert evidence[0]["status"] == "interrupted"
    assert evidence[0]["error_code"] == "keyboard_interrupt"
    assert evidence[0]["session_id"] == "session-1"
    assert evidence[0]["task_id"] == "task-1"


def test_deadline_is_strictly_below_four_minutes(tmp_path):
    with pytest.raises(ValueError, match="below 240"):
        matrix.LiveMatrixVerifier(
            FakeClient(),
            run_id="a" * 32,
            evidence_path=Path(tmp_path) / "evidence.json",
            timeout_seconds=240,
        )


def test_completed_task_without_bilingual_checked_result_is_a_failure(tmp_path):
    client = FakeClient()
    original_public = client._public

    def strip_translation(session):
        value = original_public(session)
        task = value["revisions"][0]["task"]
        if isinstance(task.get("result"), dict):
            task["result"].pop("translations", None)
        return value

    client._public = strip_translation
    runner = verifier(tmp_path, client)
    with pytest.raises(matrix.VerificationError, match="incomplete_consistency_checked_result"):
        runner.run(matrix.CASES[:1])
    evidence = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert evidence[0]["status"] == "failed_validation"
    assert evidence[0]["result_digest"] is None


def test_completed_task_with_difficulty_drift_is_a_failure(tmp_path):
    client = FakeClient()
    original_public = client._public

    def drift_difficulty(session):
        value = original_public(session)
        task = value["revisions"][0]["task"]
        if isinstance(task.get("result"), dict):
            task["result"]["difficulty"] = "入门"
        return value

    client._public = drift_difficulty
    runner = verifier(tmp_path, client)
    with pytest.raises(matrix.VerificationError, match="unexpected_problem_difficulty"):
        runner.run(matrix.CASES[:1])
    evidence = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    assert evidence[0]["status"] == "failed_validation"
    assert evidence[0]["result_digest"] is None
