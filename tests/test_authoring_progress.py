"""Real-stage progress contract for AI problem generation."""

import pytest

from frontend.ai_page import _render_task_progress, _task_progress_percent
from oj.ai import AIService, _Task
from oj.authoring_sessions import _normalize_task
from oj.common import APIError


def test_backend_authoring_progress_is_monotonic_and_bounded():
    task = _Task("owner", {}, [])
    assert task.public()["progress_percent"] == 5

    observed = []
    for message in (
        "正在静态检查参考解与测试数据生成器",
        "正在执行测试数据生成器（第 1 次）",
        "正在复跑测试数据生成器并检查确定性（第 2 次）",
        "正在校验参考解与答案（3/4）",
        "参考解与答案一致性检查完成，等待人工审阅",
    ):
        AIService._check_progress(task, message)
        observed.append(task.progress_percent)

    assert observed == sorted(observed)
    assert observed[0] >= 68 and observed[-1] == 96
    assert all(0 <= value < 100 for value in observed)


def test_frontend_progress_uses_explicit_stage_and_never_elapsed_time():
    task = {
        "task_id": "task-1",
        "status": "running",
        "progress": "正在连接模型并提交命题需求",
        "progress_percent": 47,
        "elapsed_seconds": 229,
    }
    assert _task_progress_percent(task) == 47
    task.pop("progress_percent")
    assert _task_progress_percent(task) == 10
    task["status"] = "completed"
    assert _task_progress_percent(task) == 100


def test_frontend_stage_fallback_tracks_case_validation():
    task = {
        "status": "running",
        "progress": "正在校验参考解与答案（3/4）",
    }
    assert 82 < _task_progress_percent(task) <= 94


@pytest.mark.parametrize("status", ["pending", "running", "failed", "cancelled"])
def test_non_completed_authoring_task_cannot_claim_one_hundred_percent(status):
    task = {
        "task_id": "task-1",
        "status": status,
        "result": None,
        "progress": "last real stage",
        "progress_percent": 100,
    }
    assert _task_progress_percent(task) == 99
    with pytest.raises(APIError, match="invalid state"):
        _normalize_task(task)


def test_progress_markup_shows_number_and_uses_the_same_percentage_width(monkeypatch):
    from frontend import ai_page

    rendered = []
    state = {}

    class Container:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(ai_page.st, "session_state", state)
    monkeypatch.setattr(ai_page.st, "container", lambda **_kwargs: Container())
    monkeypatch.setattr(ai_page.st, "html", rendered.append)
    _render_task_progress(
        {
            "task_id": "stage-47",
            "status": "running",
            "progress_percent": 47,
        },
        {"progress_title": "生成进度"},
    )

    assert len(rendered) == 1
    assert "aria-valuenow='47'" in rendered[0]
    assert "<strong>47%</strong>" in rendered[0]
    assert "style='width:47%'" in rendered[0]
