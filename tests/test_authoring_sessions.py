"""Domain-contract tests for persistent iterative AI authoring sessions."""

import asyncio
import copy
import json

import pytest

from oj.authoring_sessions import (
    IDEMPOTENCY_NAMESPACE,
    SESSION_NAMESPACE,
    AuthoringSessionService,
    normalize_request,
)
from oj.common import APIError
from oj.store import Store


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += 1
        return f"2026-09-09T12:00:{self.value:02d}Z"


class Ids:
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += 1
        return f"session-{self.value}"


def usage(
    input_tokens=None,
    output_tokens=None,
    *,
    cost=0.0,
    incomplete=True,
    currency="USD",
):
    total = None if input_tokens is None or output_tokens is None else input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "cost": cost,
        "currency": currency,
        "incomplete": incomplete,
        "source": "synthetic-test",
        "note": "fixture",
    }


class FakeAI:
    def __init__(self):
        self.tasks = {}
        self.prompts = {}
        self.references = {}
        self.events = []
        self.start_delay = 0
        self.fail_cancel = False
        self.fail_next_start = False
        self.complete_after_next_get = None

    def _public(self, task_id):
        return copy.deepcopy(self.tasks[task_id])

    async def start(self, owner_id, prompt, attachment_refs):
        self.events.append(("start", owner_id))
        if self.start_delay:
            await asyncio.sleep(self.start_delay)
        if self.fail_next_start:
            self.fail_next_start = False
            raise APIError(503, "Synthetic start failure")
        task_id = f"task-{len(self.tasks) + 1}"
        self.tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": "queued",
            "result": None,
            "error": None,
            "error_code": None,
            "retryable": None,
            "error_detail": None,
            "provider_calls": 0,
            "usage": usage(),
            "elapsed_seconds": 0,
        }
        self.prompts[task_id] = prompt
        self.references[task_id] = copy.deepcopy(attachment_refs)
        return self._public(task_id)

    async def get(self, task_id, owner_id):
        self.events.append(("get", task_id))
        value = self._public(task_id)
        if self.complete_after_next_get == task_id:
            self.complete_after_next_get = None
            self.complete(task_id, {"id": "RACE-DRAFT", "title": "Race completed"})
        return value

    async def cancel(self, task_id, owner_id):
        self.events.append(("cancel", task_id))
        if self.fail_cancel:
            raise APIError(503, "Synthetic cancel failure")
        task = self.tasks[task_id]
        if task["status"] not in {"pending", "running"}:
            raise APIError(409, "AI task has already ended")
        task.update(
            status="cancelled",
            progress="cancelled",
            retryable=True,
            usage=usage(2, 1, cost=0.01, incomplete=True),
            provider_calls=1,
            elapsed_seconds=0.2,
        )
        return self._public(task_id)

    def complete(self, task_id, result, *, task_usage=None, calls=1):
        self.tasks[task_id].update(
            status="completed",
            progress="completed",
            result=copy.deepcopy(result),
            retryable=False,
            usage=task_usage or usage(10, 5, cost=0.1, incomplete=False),
            provider_calls=calls,
            elapsed_seconds=1.2,
        )

    def fail(self, task_id, *, task_usage=None):
        self.tasks[task_id].update(
            status="failed",
            progress="failed",
            result=None,
            error="Synthetic generation failure",
            error_code="synthetic_failure",
            retryable=True,
            usage=task_usage or usage(3, 2, cost=0.05, incomplete=False),
            provider_calls=1,
            elapsed_seconds=0.7,
        )


def authoring_request(requirement="设计一道有向图判环题", **updates):
    value = {
        "requirement": requirement,
        "knowledge_point_ids": ["engineering.deadlock", "graph.topological-sort"],
        "difficulty_id": "luogu.4",
        "free_prompt": "使用简洁中文题面",
        "attachments": [
            {"attachment_id": "attachment-1", "sha256": "a" * 64},
        ],
    }
    value.update(updates)
    return value


async def environment(tmp_path, ai=None, *, clock=None, ids=None):
    store = Store(tmp_path / "authoring.sqlite3")
    await store.initialize()
    ai = ai or FakeAI()
    service = AuthoringSessionService(
        store,
        start_task=ai.start,
        get_task=ai.get,
        cancel_task=ai.cancel,
        clock=clock or Clock(),
        id_factory=ids or Ids(),
    )
    return store, ai, service


def prompt_payload(ai, task_id):
    return json.loads(ai.prompts[task_id].split("结构化命题请求：\n", 1)[1])


@pytest.mark.asyncio
async def test_initial_revision_is_structured_persistent_and_attachment_reference_only(tmp_path):
    store, ai, service = await environment(tmp_path)
    result = await service.initial("alice", authoring_request(), idempotency_key="create-1")

    assert result["schema_version"] == "oj.authoring-session.v1"
    assert result["session_id"] == "session-1"
    assert result["status"] == "pending"
    assert result["current_revision"] == 1
    assert result["latest_success_revision"] is None and result["draft"] is None
    assert result["revisions"][0]["operation"] == "initial"
    assert result["revisions"][0]["task"]["task_id"] == "task-1"
    assert "_idempotency" not in result

    payload = prompt_payload(ai, "task-1")
    assert payload["schema_version"] == "oj.authoring-revision-request.v1"
    assert payload["operation"] == "initial"
    assert payload["original_request"] == payload["current_request"]
    assert payload["current_request"]["knowledge_points"][0]["id"] == "engineering.deadlock"
    assert ai.references["task-1"] == ({"attachment_id": "attachment-1", "sha256": "a" * 64},)

    stored = await store.get(SESSION_NAMESPACE, "session-1")
    encoded = json.dumps(stored, ensure_ascii=False)
    assert "raw_bytes" not in encoded and "file_content" not in encoded
    assert stored["original_request"]["attachments"] == [
        {"attachment_id": "attachment-1", "sha256": "a" * 64}
    ]
    assert len(await store.all(IDEMPOTENCY_NAMESPACE)) == 1


@pytest.mark.parametrize(
    "invalid_payload",
    [
        authoring_request(requirement="   "),
        authoring_request(requirement="x" * 20_001),
        authoring_request(knowledge_point_ids=["engineering.deadlock"] * 2),
        authoring_request(knowledge_point_ids=["unknown.point"]),
        authoring_request(difficulty_id="提高"),
        authoring_request(free_prompt="x" * 10_001),
        authoring_request(extra="unsupported"),
        authoring_request(
            attachments=[
                {
                    "attachment_id": "attachment-1",
                    "sha256": "a" * 64,
                    "content": "must not be accepted",
                }
            ]
        ),
        authoring_request(attachments=[{"attachment_id": "attachment-1", "sha256": "not-a-hash"}]),
    ],
)
@pytest.mark.asyncio
async def test_invalid_request_never_starts_ai(tmp_path, invalid_payload):
    _, ai, service = await environment(tmp_path)
    with pytest.raises(APIError) as caught:
        await service.initial("alice", invalid_payload, idempotency_key="invalid")
    assert caught.value.status == 400
    assert ai.events == []


def test_normalization_rejects_duplicate_attachments_and_preserves_order():
    with pytest.raises(APIError) as caught:
        normalize_request(
            authoring_request(
                attachments=[
                    {"attachment_id": "same", "sha256": "a" * 64},
                    {"attachment_id": "same", "sha256": "b" * 64},
                ]
            )
        )
    assert caught.value.status == 400
    value = normalize_request(authoring_request())
    assert [point["id"] for point in value["knowledge_points"]] == [
        "engineering.deadlock",
        "graph.topological-sort",
    ]


@pytest.mark.asyncio
async def test_initial_idempotency_is_persistent_and_concurrent(tmp_path):
    store, ai, service = await environment(tmp_path)
    ai.start_delay = 0.02
    first, duplicate = await asyncio.gather(
        service.initial("alice", authoring_request(), idempotency_key="same-create"),
        service.initial("alice", authoring_request(), idempotency_key="same-create"),
    )
    assert first["session_id"] == duplicate["session_id"]
    assert first["revisions"][0]["task"]["task_id"] == duplicate["revisions"][0]["task"]["task_id"]
    assert [event[0] for event in ai.events].count("start") == 1

    restarted = AuthoringSessionService(
        store,
        start_task=ai.start,
        get_task=ai.get,
        cancel_task=ai.cancel,
        clock=Clock(),
        id_factory=Ids(),
    )
    replay = await restarted.initial("alice", authoring_request(), idempotency_key="same-create")
    assert replay["session_id"] == first["session_id"]
    assert [event[0] for event in ai.events].count("start") == 1
    with pytest.raises(APIError) as conflict:
        await restarted.initial(
            "alice",
            authoring_request(requirement="different"),
            idempotency_key="same-create",
        )
    assert conflict.value.status == 409
    assert [event[0] for event in ai.events].count("start") == 1


@pytest.mark.asyncio
async def test_all_session_reads_and_mutations_are_owner_only(tmp_path):
    _, ai, service = await environment(tmp_path)
    created = await service.initial("alice", authoring_request(), idempotency_key="owner")
    session_id = created["session_id"]
    for operation in (
        lambda: service.get(session_id, "bob"),
        lambda: service.poll(session_id, "bob"),
        lambda: service.replace_requirements(
            session_id,
            "bob",
            None,
            expected_revision=1,
            idempotency_key="replace",
        ),
        lambda: service.refine_draft(
            session_id,
            "bob",
            "",
            expected_revision=1,
            idempotency_key="refine",
        ),
    ):
        with pytest.raises(APIError) as denied:
            await operation()
        assert denied.value.status == 403
    assert [event[0] for event in ai.events].count("start") == 1


@pytest.mark.asyncio
async def test_expected_revision_conflict_has_zero_ai_side_effects(tmp_path):
    _, ai, service = await environment(tmp_path)
    created = await service.initial("alice", authoring_request(), idempotency_key="initial")
    before = list(ai.events)
    with pytest.raises(APIError) as conflict:
        await service.replace_requirements(
            created["session_id"],
            "alice",
            authoring_request(requirement="updated"),
            expected_revision=2,
            idempotency_key="replace",
        )
    assert conflict.value.status == 409
    assert ai.events == before
    with pytest.raises(APIError) as refine_conflict:
        await service.refine_draft(
            created["session_id"],
            "alice",
            "make it clearer",
            expected_revision=2,
            idempotency_key="refine",
        )
    assert refine_conflict.value.status == 409
    assert ai.events == before


@pytest.mark.asyncio
async def test_replace_cancels_active_task_before_new_task_and_keeps_original_intent(tmp_path):
    _, ai, service = await environment(tmp_path)
    initial = await service.initial("alice", authoring_request(), idempotency_key="initial")
    original_snapshot = copy.deepcopy(initial["revisions"][0]["request"])
    updated_request = authoring_request(
        requirement="改为判断等待图是否存在环",
        free_prompt="要求给出三个样例",
    )
    replaced = await service.replace_requirements(
        initial["session_id"],
        "alice",
        updated_request,
        expected_revision=1,
        idempotency_key="replace-1",
    )
    actions = [event[0] for event in ai.events]
    assert actions == ["start", "get", "cancel", "start"]
    assert replaced["current_revision"] == 2
    assert replaced["revisions"][0]["task"]["status"] == "cancelled"
    assert replaced["revisions"][0]["request"] == original_snapshot
    assert replaced["revisions"][1]["parent_revision"] == 1
    assert replaced["revisions"][1]["task"]["task_id"] == "task-2"
    assert replaced["original_request"]["requirement"] == "设计一道有向图判环题"
    assert replaced["current_request"]["requirement"] == "改为判断等待图是否存在环"
    payload = prompt_payload(ai, "task-2")
    assert payload["operation"] == "replace_requirements"
    assert payload["original_request"]["requirement"] == "设计一道有向图判环题"
    assert payload["current_request"]["free_prompt"] == "要求给出三个样例"


@pytest.mark.asyncio
async def test_replace_idempotency_precedes_stale_expected_revision(tmp_path):
    _, ai, service = await environment(tmp_path)
    initial = await service.initial("alice", authoring_request(), idempotency_key="initial")
    updated = authoring_request(requirement="updated")
    first = await service.replace_requirements(
        initial["session_id"],
        "alice",
        updated,
        expected_revision=1,
        idempotency_key="same-replace",
    )
    before = list(ai.events)
    replay = await service.replace_requirements(
        initial["session_id"],
        "alice",
        updated,
        expected_revision=1,
        idempotency_key="same-replace",
    )
    assert replay["current_revision"] == first["current_revision"] == 2
    assert ai.events == before
    with pytest.raises(APIError) as reused:
        await service.replace_requirements(
            initial["session_id"],
            "alice",
            authoring_request(requirement="different"),
            expected_revision=1,
            idempotency_key="same-replace",
        )
    assert reused.value.status == 409
    assert ai.events == before


@pytest.mark.asyncio
async def test_concurrent_replacements_create_only_one_next_revision(tmp_path):
    _, ai, service = await environment(tmp_path)
    ai.start_delay = 0.01
    initial = await service.initial("alice", authoring_request(), idempotency_key="initial")

    results = await asyncio.gather(
        service.replace_requirements(
            initial["session_id"],
            "alice",
            authoring_request(requirement="first candidate"),
            expected_revision=1,
            idempotency_key="replace-a",
        ),
        service.replace_requirements(
            initial["session_id"],
            "alice",
            authoring_request(requirement="second candidate"),
            expected_revision=1,
            idempotency_key="replace-b",
        ),
        return_exceptions=True,
    )
    successes = [item for item in results if isinstance(item, dict)]
    conflicts = [item for item in results if isinstance(item, APIError)]
    assert len(successes) == len(conflicts) == 1
    assert conflicts[0].status == 409
    assert successes[0]["current_revision"] == 2
    assert [event[0] for event in ai.events].count("start") == 2
    assert [event[0] for event in ai.events].count("cancel") == 1


@pytest.mark.asyncio
async def test_poll_completion_then_failed_refinement_preserves_last_good_draft_and_usage(tmp_path):
    _, ai, service = await environment(tmp_path)
    initial = await service.initial("alice", authoring_request(), idempotency_key="initial")
    draft = {"id": "AI-001", "title": "等待图判环", "description": "第一稿"}
    ai.complete("task-1", draft)
    completed = await service.poll(initial["session_id"], "alice")
    assert completed["status"] == "completed"
    assert completed["draft"] == draft
    assert completed["latest_success_revision"] == 1
    get_count = [event[0] for event in ai.events].count("get")
    await service.poll(initial["session_id"], "alice")
    assert [event[0] for event in ai.events].count("get") == get_count

    refinement = await service.refine_draft(
        initial["session_id"],
        "alice",
        "补充无环和自环边界，并降低题面歧义",
        expected_revision=1,
        idempotency_key="refine-1",
    )
    assert refinement["current_revision"] == 2
    payload = prompt_payload(ai, "task-2")
    assert payload["operation"] == "refine_draft"
    assert payload["latest_successful_draft"] == draft
    assert payload["improvement"] == "补充无环和自环边界，并降低题面歧义"
    assert payload["original_request"]["requirement"] == "设计一道有向图判环题"

    ai.fail("task-2")
    failed = await service.poll(initial["session_id"], "alice")
    assert failed["status"] == "failed"
    assert failed["latest_success_revision"] == 1
    assert failed["draft"] == draft
    assert failed["revisions"][1]["task"]["error_code"] == "synthetic_failure"
    assert failed["cumulative_usage"] == {
        "revision_count": 2,
        "provider_calls": 2,
        "incomplete": False,
        "input_tokens": 13,
        "output_tokens": 7,
        "total_tokens": 20,
        "cost": 0.15,
        "currency": "USD",
    }


@pytest.mark.asyncio
async def test_multiple_refinements_keep_history_and_base_only_on_last_success(tmp_path):
    _, ai, service = await environment(tmp_path)
    initial = await service.initial("alice", authoring_request(), idempotency_key="initial")
    first_draft = {"id": "AI-001", "title": "First"}
    ai.complete("task-1", first_draft)
    await service.poll(initial["session_id"], "alice")
    await service.refine_draft(
        initial["session_id"],
        "alice",
        "first improvement",
        expected_revision=1,
        idempotency_key="r1",
    )
    ai.fail("task-2")
    await service.poll(initial["session_id"], "alice")
    await service.refine_draft(
        initial["session_id"],
        "alice",
        "second improvement",
        expected_revision=2,
        idempotency_key="r2",
    )
    payload = prompt_payload(ai, "task-3")
    assert payload["latest_successful_draft"] == first_draft
    assert payload["original_request"]["requirement"] == "设计一道有向图判环题"
    assert payload["refinement_history"] == [
        {"revision": 2, "improvement": "first improvement", "status": "failed"}
    ]
    ai.complete("task-3", {"id": "AI-001", "title": "Improved"})
    final = await service.poll(initial["session_id"], "alice")
    assert final["latest_success_revision"] == 3
    assert final["draft"]["title"] == "Improved"


@pytest.mark.asyncio
async def test_refinement_requires_successful_draft_and_nonempty_instruction(tmp_path):
    _, ai, service = await environment(tmp_path)
    initial = await service.initial("alice", authoring_request(), idempotency_key="initial")
    before = list(ai.events)
    with pytest.raises(APIError) as no_draft:
        await service.refine_draft(
            initial["session_id"],
            "alice",
            "improve",
            expected_revision=1,
            idempotency_key="refine",
        )
    assert no_draft.value.status == 409
    assert [event[0] for event in ai.events] == [event[0] for event in before] + ["get"]
    with pytest.raises(APIError) as empty:
        await service.refine_draft(
            initial["session_id"],
            "alice",
            "   ",
            expected_revision=1,
            idempotency_key="empty",
        )
    assert empty.value.status == 400


@pytest.mark.asyncio
async def test_cancel_terminal_race_syncs_old_result_before_starting_replacement(tmp_path):
    _, ai, service = await environment(tmp_path)
    initial = await service.initial("alice", authoring_request(), idempotency_key="initial")
    ai.complete_after_next_get = "task-1"
    replaced = await service.replace_requirements(
        initial["session_id"],
        "alice",
        authoring_request(requirement="updated after race"),
        expected_revision=1,
        idempotency_key="replace",
    )
    assert [event[0] for event in ai.events] == ["start", "get", "cancel", "get", "start"]
    assert replaced["latest_success_revision"] == 1
    assert replaced["draft"]["id"] == "RACE-DRAFT"
    assert replaced["revisions"][0]["task"]["status"] == "completed"


@pytest.mark.asyncio
async def test_cancel_failure_prevents_new_task_and_start_failure_keeps_cancelled_history(tmp_path):
    _, ai, service = await environment(tmp_path)
    initial = await service.initial("alice", authoring_request(), idempotency_key="initial")
    ai.fail_cancel = True
    with pytest.raises(APIError) as cancel_failure:
        await service.replace_requirements(
            initial["session_id"],
            "alice",
            authoring_request(requirement="replacement"),
            expected_revision=1,
            idempotency_key="replace-a",
        )
    assert cancel_failure.value.status == 503
    assert [event[0] for event in ai.events].count("start") == 1

    ai.fail_cancel = False
    ai.fail_next_start = True
    with pytest.raises(APIError) as start_failure:
        await service.replace_requirements(
            initial["session_id"],
            "alice",
            authoring_request(requirement="replacement"),
            expected_revision=1,
            idempotency_key="replace-b",
        )
    assert start_failure.value.status == 503
    stored = await service.get(initial["session_id"], "alice")
    assert stored["current_revision"] == 1
    assert stored["status"] == "cancelled"
    assert stored["revisions"][0]["task"]["usage"]["input_tokens"] == 2


@pytest.mark.asyncio
async def test_restart_marks_only_active_current_revision_and_preserves_history_idempotency(
    tmp_path,
):
    store, ai, service = await environment(tmp_path)
    initial = await service.initial("alice", authoring_request(), idempotency_key="initial")
    restarted = AuthoringSessionService(
        store,
        start_task=ai.start,
        get_task=ai.get,
        cancel_task=ai.cancel,
        clock=Clock(),
        id_factory=Ids(),
    )
    assert await restarted.recover_after_restart() == 1
    recovered = await restarted.get(initial["session_id"], "alice")
    assert recovered["status"] == "service_restarted"
    assert recovered["revisions"][0]["task"]["error_code"] == "service_restarted"
    assert recovered["revisions"][0]["task"]["task_id"] == "task-1"
    assert recovered["current_revision"] == 1
    assert await restarted.recover_after_restart() == 0

    replay = await restarted.initial("alice", authoring_request(), idempotency_key="initial")
    assert replay["session_id"] == initial["session_id"]
    assert [event[0] for event in ai.events].count("start") == 1
    replaced = await restarted.replace_requirements(
        initial["session_id"],
        "alice",
        authoring_request(requirement="retry after restart"),
        expected_revision=1,
        idempotency_key="restart-replace",
    )
    assert replaced["current_revision"] == 2
    assert replaced["revisions"][0]["task"]["status"] == "service_restarted"
    assert [event[0] for event in ai.events].count("cancel") == 0
    assert [event[0] for event in ai.events].count("start") == 2


@pytest.mark.asyncio
async def test_ai_task_identity_and_json_contract_are_enforced(tmp_path):
    _, ai, service = await environment(tmp_path)
    initial = await service.initial("alice", authoring_request(), idempotency_key="initial")
    ai.tasks["task-1"]["task_id"] = "different-task"
    with pytest.raises(APIError) as identity:
        await service.poll(initial["session_id"], "alice")
    assert identity.value.status == 502

    ai.tasks["task-1"]["task_id"] = "task-1"
    ai.tasks["task-1"]["status"] = "completed"
    ai.tasks["task-1"]["result"] = None
    with pytest.raises(APIError) as missing_result:
        await service.poll(initial["session_id"], "alice")
    assert missing_result.value.status == 502
