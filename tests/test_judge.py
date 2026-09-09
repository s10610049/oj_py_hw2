"""Real local process judgments and boundary checks for the judge v1 contract."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import time

import psutil
import pytest

from oj.common import APIError
from oj.judge import judge_submission, normalize_output, resolve_limits, validate_language
from oj.runner import ProcessResult, child_environment, run_command

PYTHON = {"name": "python", "file_ext": ".py", "run_cmd": "python3 {src}"}
CPP = {
    "name": "cpp",
    "file_ext": ".cpp",
    "compile_cmd": "g++ {src} -std=c++14 -O2 -o {exe}",
    "run_cmd": "{exe}",
}
SUM_PY = "a,b=map(int,input().split()); print(a+b)"
SUM_CPP = "#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b;}"


def problem(*, expected="3", seconds=2.0, memory=128):
    return {
        "testcases": [{"input": "1 2\n", "output": expected}],
        "time_limit": seconds,
        "memory_limit": memory,
    }


def assert_verdict(result, verdict, count=1):
    assert result["status"] == ("error" if verdict == "UNK" else "success"), result
    assert result["counts"] == 10 * count
    assert [case["result"] for case in result["details"]] == [verdict] * count, result
    assert result["score"] == (10 * count if verdict == "AC" else 0)
    for detail in result["details"]:
        assert set(detail) == {"id", "result", "time", "memory"}
        assert detail["time"] >= 0 and detail["memory"] >= 0


def process_stopped(pid):
    # Process disappearance during inspection is successful cleanup, not a failure.
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def test_process_stopped_handles_concurrent_reaping(monkeypatch):
    def reaped(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", reaped)
    assert process_stopped(123456)


@pytest.mark.parametrize(
    "change",
    [
        {"run_cmd": "sh -c {src}"},
        {"run_cmd": "python3 -c {src}"},
        {"run_cmd": "python3 {src}; whoami"},
        {"run_cmd": "python3 {src} > stolen.txt"},
        {"run_cmd": "python3 ${src}"},
        {"run_cmd": "python3 {src.__class__}"},
        {"run_cmd": 'python3 "{src}'},
        {"run_cmd": "{exe}"},
        {"run_cmd": "/unknown/python3 {src}"},
        {"file_ext": "/../../.env"},
        {"name": "../cpp"},
        {"memory_limit": True},
        {"memory_limit": 12.5},
        {"time_limit": 0},
        {"time_limit": float("nan")},
        {"time_limit": float("inf")},
        {"time_limit": 10**400},
        {"compile_cmd": 42},
    ],
)
def test_reject_unsafe_language(change):
    with pytest.raises(APIError) as exc:
        validate_language({**PYTHON, **change})
    assert exc.value.status == 400


@pytest.mark.parametrize(
    "compile_cmd",
    ["g++ {src} -o /tmp/unrelated", "g++ {src} -fplugin=bad.so -o {exe}", "sh {src} -o {exe}"],
)
def test_reject_unsafe_compiler(compile_cmd):
    with pytest.raises(APIError):
        validate_language({**CPP, "compile_cmd": compile_cmd})


def test_dynamic_languages_and_independent_fallback():
    assert validate_language({**PYTHON, "name": "python-alias"})["name"] == "python-alias"
    assert validate_language({"name": "go", "file_ext": ".go", "run_cmd": "go run {src}"})
    assert validate_language(PYTHON)["time_limit"] is None
    assert resolve_limits({}, {}) == (3.0, 128)
    assert resolve_limits({"time_limit": 0.5}, {"memory_limit": 64}) == (0.5, 64)
    assert resolve_limits({"memory_limit": 96}, {"time_limit": 2}) == (2.0, 96)
    assert resolve_limits({"time_limit": None}, {"time_limit": 1}) == (1.0, 128)


def test_normalization_preserves_meaningful_whitespace():
    assert normalize_output("a \t\r\nb\n\n") == "a\nb"
    assert normalize_output(" a\n") != normalize_output("a\n")
    assert normalize_output("a  b") != normalize_output("a b")
    assert normalize_output("a\n\nb") != normalize_output("a\nb")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "expected", "verdict"),
    [
        (SUM_PY, "3 \t\n\n", "AC"),
        (SUM_PY, "4", "WA"),
        ("1/0", "", "RE"),
        ("def invalid(:", "", "RE"),
    ],
)
async def test_python_real_verdicts(code, expected, verdict):
    result = await judge_submission(problem(expected=expected), PYTHON, code)
    assert_verdict(result, verdict)
    assert result["compile_info"] is None
    assert result["run_info"]["result"] == "finished"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [
        "raise ValueError('MemoryError')",
        "raise ValueError('std::bad_alloc')",
        "raise ValueError('ordinary error\\nMemoryError')",
        "raise ValueError('ordinary error') # MemoryError",
        "raise MemoryError",
        "raise MemoryError('deliberate exception, no allocation')",
        "try:\n raise MemoryError\nexcept MemoryError:\n raise ValueError('final error')",
        "def values():\n yield 1\ng=values()\nnext(g)\ng.throw(MemoryError)",
        pytest.param(
            "def values():\n yield 1\ng=values()\ng.throw(MemoryError)",
            id="unstarted-generator-injection",
        ),
        pytest.param(
            "import asyncio\nloop=asyncio.new_event_loop()\n"
            "try:\n f=loop.create_future()\n f.set_exception(MemoryError())\n f.result()\n"
            "finally:\n loop.close()",
            id="future-result-replay",
        ),
    ],
)
async def test_memory_words_and_manual_exceptions_are_not_resource_evidence(code):
    result = await judge_submission(problem(), PYTHON, code)
    assert_verdict(result, "RE")


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("g++") is None, reason="C++ compiler is not installed")
async def test_manually_thrown_bad_alloc_is_not_memory_exhaustion():
    code = (
        "#include <new>\n#include <exception>\n#include <cstdio>\n#include <cstdlib>\n"
        "int main(){\n#ifdef _WIN32\n"
        'std::set_terminate([](){std::fputs("std::bad_alloc\\n",stderr);std::_Exit(1);});\n'
        "#endif\nthrow std::bad_alloc();}"
    )
    result = await judge_submission(problem(), CPP, code)
    if os.name == "nt" and "execution policy" in (result["error_info"] or ""):
        pytest.skip(result["error_info"])
    assert_verdict(result, "RE")


@pytest.mark.asyncio
async def test_actual_allocation_failure_without_memory_keywords():
    result = await judge_submission(problem(), PYTHON, "value=bytearray(2**63-1)")
    assert_verdict(result, "MLE")


@pytest.mark.asyncio
async def test_future_replay_preserves_original_allocation_failure():
    code = (
        "import asyncio\nloop=asyncio.new_event_loop()\n"
        "try:\n f=loop.create_future()\n"
        " try:\n  value=bytearray(2**63-1)\n"
        " except MemoryError as error:\n  f.set_exception(error)\n"
        " f.result()\nfinally:\n loop.close()"
    )
    assert_verdict(await judge_submission(problem(), PYTHON, code), "MLE")


@pytest.mark.asyncio
async def test_future_probe_does_not_replace_pending_or_cancelled_errors():
    code = (
        "import asyncio\nloop=asyncio.new_event_loop()\n"
        "try:\n f=loop.create_future()\n"
        " try:\n  f.result()\n except asyncio.InvalidStateError:\n  pass\n"
        " f.cancel()\n"
        " try:\n  f.result()\n except asyncio.CancelledError:\n  pass\n"
        " value=bytearray(2**63-1)\nfinally:\n loop.close()"
    )
    assert_verdict(await judge_submission(problem(), PYTHON, code), "MLE")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Requires real Linux rlimits")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "code"),
    [
        (PYTHON, "value=bytearray(128*1024*1024)"),
        (
            CPP,
            "int main(){volatile char* p=new char[128*1024*1024];p[0]=1;return p[0];}",
        ),
    ],
)
async def test_linux_single_allocation_reports_limit_failure_without_peak_crossing(language, code):
    result = await judge_submission(problem(memory=64), language, code)
    assert_verdict(result, "MLE")
    # RLIMIT_AS refuses the allocation before RSS can cross the configured limit.
    assert result["details"][0]["memory"] < 64


@pytest.mark.asyncio
async def test_python_probe_preserves_script_entry_semantics():
    code = (
        "import pathlib,sys,__main__,atexit\n"
        "assert __name__ == '__main__'\n"
        "assert pathlib.Path(sys.argv[0]) == pathlib.Path(__file__)\n"
        "assert len(sys.argv) == 1\n"
        "assert __main__.__file__ == __file__\n"
        "value='exit-ok'\n"
        "def on_exit():\n import __main__\n print(__main__.value)\n"
        "atexit.register(on_exit)\n"
        "print('entry-ok')"
    )
    assert_verdict(
        await judge_submission(problem(expected="entry-ok\nexit-ok"), PYTHON, code), "AC"
    )


@pytest.mark.asyncio
async def test_real_partial_score_and_language_limit_fallback():
    cases = [{"input": "1 2", "output": "3"}, {"input": "1 2", "output": "4"}]
    result = await judge_submission({"testcases": cases}, PYTHON, SUM_PY)
    assert result["score"] == 10 and result["counts"] == 20
    assert [detail["id"] for detail in result["details"]] == [1, 2]
    assert "Case 1" not in result["run_info"]["message"]
    assert "Case 2" not in result["run_info"]["message"]
    assert result["run_info"]["message"].count("WA") == 1


@pytest.mark.asyncio
async def test_python_real_timeout_and_memory_limit():
    assert_verdict(await judge_submission(problem(seconds=0.3), PYTHON, "while True: pass"), "TLE")
    code = "import time\nx = bytearray(128*1024*1024)\ntime.sleep(2)"
    assert_verdict(await judge_submission(problem(memory=64), PYTHON, code), "MLE")


@pytest.mark.asyncio
async def test_memory_limit_counts_descendants():
    code = (
        "import subprocess,sys,time\n"
        "own=bytearray(16*1024*1024)\n"
        "child=subprocess.Popen([sys.executable,'-c',"
        "'import time;x=bytearray(64*1024*1024);time.sleep(2)'])\n"
        "time.sleep(2)"
    )
    result = await judge_submission(problem(seconds=3, memory=96), PYTHON, code)
    assert_verdict(result, "MLE")


@pytest.mark.asyncio
async def test_output_flood_is_bounded():
    result = await judge_submission(problem(), PYTHON, "while True: print('x'*10000)")
    assert_verdict(result, "RE")
    assert len(json.dumps(result)) < 6000


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("g++") is None, reason="C++ compiler is not installed")
@pytest.mark.parametrize(
    ("code", "expected", "seconds", "memory", "verdict"),
    [
        (SUM_CPP, "3", 2, 128, "AC"),
        (SUM_CPP, "4", 2, 128, "WA"),
        ("int main(){return 1;}", "", 2, 128, "RE"),
        ("int main(){while(true){}}", "", 0.3, 128, "TLE"),
        ("int main( {", "", 2, 128, "CE"),
        (
            "#include <thread>\n#include <chrono>\n"
            "int main(){volatile char* x=new char[128*1024*1024];"
            "for(int i=0;i<128*1024*1024;i+=4096){x[i]=1;}"
            "std::this_thread::sleep_for(std::chrono::seconds(2));return x[0];}",
            "",
            2,
            64,
            "MLE",
        ),
    ],
)
async def test_cpp_real_verdicts(code, expected, seconds, memory, verdict):
    result = await judge_submission(
        problem(expected=expected, seconds=seconds, memory=memory), CPP, code
    )
    if os.name == "nt" and "execution policy" in (result["error_info"] or ""):
        pytest.skip(result["error_info"])
    assert_verdict(result, verdict)
    assert result["compile_info"]["result"] == ("error" if verdict == "CE" else "success")


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("g++") is None, reason="C++ compiler is not installed")
async def test_real_compilation_deadline(monkeypatch):
    monkeypatch.setattr("oj.judge.COMPILE_TIMEOUT", 0.001)
    result = await judge_submission(problem(), CPP, SUM_CPP)
    if os.name == "nt" and "execution policy" in (result["error_info"] or ""):
        pytest.skip(result["error_info"])
    assert_verdict(result, "CE")


@pytest.mark.asyncio
async def test_real_spawn_failure_is_infrastructure_error(tmp_path):
    result = await run_command([str(tmp_path / "missing-executable")], tmp_path, "", 1, 128)
    assert result.reason == "spawn" or "OJ_RUNNER_EXEC_FAILED" in result.stderr


@pytest.mark.asyncio
async def test_judge_unknown_dependency_and_compilation_limit(monkeypatch):
    async def unavailable(*args, **kwargs):
        return ProcessResult("spawn")

    monkeypatch.setattr("oj.judge.run_command", unavailable)
    assert_verdict(await judge_submission(problem(), PYTHON, SUM_PY), "UNK")

    async def timed_out(*args, **kwargs):
        return ProcessResult("timeout", returncode=-1)

    monkeypatch.setattr("oj.judge.run_command", timed_out)
    result = await judge_submission(problem(), CPP, SUM_CPP)
    assert_verdict(result, "CE")
    assert "limit" in result["compile_info"]["message"]


@pytest.mark.asyncio
async def test_windows_policy_denial_stays_infrastructure_failure(monkeypatch):
    def rejected(*args, **kwargs):
        error = OSError("Synthetic application control denial")
        error.winerror = 4551
        raise error

    monkeypatch.setattr("oj.runner.subprocess.Popen", rejected)
    result = await judge_submission(problem(), PYTHON, SUM_PY)
    assert_verdict(result, "UNK")
    assert "execution policy" in result["error_info"]


@pytest.mark.asyncio
async def test_filtered_environment_and_private_working_directory(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-secret-do-not-inherit")
    monkeypatch.setenv("OJ_ADMIN_SECRET", "synthetic-admin-secret")
    monkeypatch.setenv("PYTHONPATH", "synthetic-import-path")
    code = (
        "import os\n"
        "names=['DEEPSEEK_API_KEY','OJ_ADMIN_SECRET','PYTHONPATH']\n"
        "assert not any(x in os.environ for x in names)\n"
        "assert os.environ['HOME'] == os.getcwd()\nprint('clean')"
    )
    assert_verdict(await judge_submission(problem(expected="clean"), PYTHON, code), "AC")
    assert "DEEPSEEK_API_KEY" not in child_environment(Path.cwd())


@pytest.mark.asyncio
async def test_cancellation_kills_child_and_removes_scratch(tmp_path):
    marker = tmp_path / "child.json"
    code = (
        "import json,os,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
        f"with open({str(marker)!r},'w') as handle: json.dump([child.pid,os.getcwd()],handle)\n"
        "time.sleep(60)\n"
    )
    task = asyncio.create_task(judge_submission(problem(seconds=30), PYTHON, code))
    for _ in range(200):
        if marker.exists() and marker.stat().st_size:
            break
        await asyncio.sleep(0.01)
    else:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pytest.fail("Submission did not start its child")
    child_pid, directory = json.loads(marker.read_text())
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process_stopped(child_pid)
    assert not Path(directory).exists()


@pytest.mark.asyncio
async def test_child_is_reaped_when_parent_exits(tmp_path):
    marker = tmp_path / "orphan.json"
    code = (
        "import json,os,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
        f"with open({str(marker)!r},'w') as handle: json.dump(child.pid,handle)\n"
        "print('done')\n"
    )
    result = await judge_submission(problem(expected="done"), PYTHON, code)
    assert_verdict(result, "AC")
    child_pid = json.loads(marker.read_text())
    assert process_stopped(child_pid)


@pytest.mark.asyncio
async def test_run_command_deadline_and_event_loop_remain_responsive(tmp_path):
    started = time.monotonic()
    task = asyncio.create_task(
        run_command(
            [sys.executable, "-c", "import time;time.sleep(10)"],
            tmp_path,
            "",
            0.3,
            128,
        )
    )
    await asyncio.sleep(0.05)
    assert not task.done()
    assert time.monotonic() - started < 0.25
    result = await task
    assert result.reason == "timeout"
    assert result.time < 2


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Requires real Linux rlimits")
@pytest.mark.asyncio
async def test_linux_address_space_limit_is_set():
    code = "import resource\nprint(resource.getrlimit(resource.RLIMIT_AS)[0])"
    assert_verdict(
        await judge_submission(problem(expected=str(64 * 1024 * 1024), memory=64), PYTHON, code),
        "AC",
    )
