"""Protect local-only files while retaining code, fixtures and visual assets."""

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def git_command():
    command = shutil.which("git")
    if command is None:
        pytest.skip("Git is not installed in this environment")
    result = subprocess.run(
        [command, "rev-parse", "--show-toplevel"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or Path(result.stdout.strip()).resolve() != PROJECT_ROOT:
        pytest.skip("Repository checks require a Git checkout of this project")
    return command


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.production",
        "docs/requirements.md",
        "codex-workflow/task.json",
        "AGENTS.md",
        "PROJECT.md",
        "PROJECT_STATE.md",
        ".venv/pyvenv.cfg",
        "runtime/database.sqlite3",
        "logs/judge.log",
    ],
)
def test_local_only_paths_are_ignored(git_command, path):
    result = subprocess.run(
        [git_command, "check-ignore", "--no-index", "--quiet", "--", path],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode == 0, f"Local-only path must be ignored: {path}"


@pytest.mark.parametrize(
    "path", [".env.example", "uv.lock", "assets/example.png", "tests/fixtures/problem.json"]
)
def test_deliverable_paths_are_not_ignored(git_command, path):
    result = subprocess.run(
        [git_command, "check-ignore", "--no-index", "--quiet", "--", path],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode == 1, f"Deliverable path must remain versionable: {path}"
