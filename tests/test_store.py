"""Atomic multi-document persistence primitives used by extension contracts."""

import asyncio

import pytest

from oj.store import Store


@pytest.mark.asyncio
async def test_snapshot_returns_stable_namespace_order_and_detached_values(tmp_path):
    store = Store(tmp_path / "snapshot.sqlite3")
    await store.initialize()
    await store.put("problems", "p1", {"id": "p1", "title": "first"})
    await store.put("submissions", "s1", {"submission_id": "s1"})

    result = await store.snapshot("problems", "submissions", "problems")
    assert list(result) == ["problems", "submissions"]
    assert result["problems"] == [{"id": "p1", "title": "first"}]
    result["problems"][0]["title"] = "caller mutation"
    assert (await store.get("problems", "p1"))["title"] == "first"


@pytest.mark.asyncio
async def test_write_batch_commits_puts_updates_and_deletes_together(tmp_path):
    store = Store(tmp_path / "batch.sqlite3")
    await store.initialize()
    await store.put("items", "old", {"value": 1})
    await store.write_batch(
        puts=[("items", "new", {"value": 2}), ("items", "old", {"value": 3})],
        deletes=[("items", "new")],
    )
    assert await store.get("items", "old") == {"value": 3}
    assert await store.get("items", "new") is None


@pytest.mark.asyncio
async def test_write_batch_rolls_back_every_write_when_serialization_fails(tmp_path):
    store = Store(tmp_path / "rollback.sqlite3")
    await store.initialize()
    await store.put("items", "stable", {"value": "kept"})

    with pytest.raises(TypeError):
        await store.write_batch(
            puts=[("items", "first", {"value": 1}), ("items", "bad", {"set": {1}})]
        )
    assert await store.get("items", "stable") == {"value": "kept"}
    assert await store.get("items", "first") is None


@pytest.mark.asyncio
async def test_cancelled_batch_finishes_before_caller_observes_cancellation(tmp_path, monkeypatch):
    store = Store(tmp_path / "cancel.sqlite3")
    await store.initialize()
    started = asyncio.Event()
    release = asyncio.Event()
    original = store._worker

    async def delayed(operation):
        started.set()
        await release.wait()
        return await original(operation)

    monkeypatch.setattr(store, "_worker", delayed)
    task = asyncio.create_task(store.write_batch(puts=[("items", "one", {"value": 1})]))
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_snapshot_and_batch_reject_empty_identifiers(tmp_path):
    store = Store(tmp_path / "invalid.sqlite3")
    await store.initialize()
    with pytest.raises(ValueError):
        await store.snapshot()
    with pytest.raises(ValueError):
        await store.write_batch(puts=[("", "key", {})])
