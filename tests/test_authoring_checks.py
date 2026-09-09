"""Synthetic source safety, real bounded execution and reference consistency checks."""

import asyncio
from copy import deepcopy
import json

import psutil
import pytest

from oj import authoring_checks as checks
from oj.common import APIError
from oj.runner import ProcessResult

SUM = "import sys\nprint(sum(map(int, sys.stdin.read().split())))\n"
GRAPH = """import sys
from collections import deque
def cyclic(n, edges):
    graph = [[] for _ in range(n)]
    degree = [0]*n
    for u,v in edges:
        graph[u-1].append(v-1)
        degree[v-1] += 1
    queue = deque(i for i in range(n) if degree[i] == 0)
    seen = 0
    while queue:
        u = queue.popleft()
        seen += 1
        for v in graph[u]:
            degree[v] -= 1
            if degree[v] == 0:
                queue.append(v)
    return seen != n
data = iter(map(int, sys.stdin.read().split()))
answers = []
for _ in range(next(data)):
    n,m = next(data),next(data)
    edges = [(next(data),next(data)) for _ in range(m)]
    answers.append('YES' if cyclic(n,edges) else 'NO')
print('\\n'.join(answers))
"""


def problem(reference=SUM, cases=None, samples=None, generator=None):
    cases = cases or [{"input": "1 2 3", "output": "6"}]
    value = {
        "id": "test-authoring",
        "title": "Synthetic problem",
        "description": "Test description",
        "input_description": "Integer input",
        "output_description": "Integer output",
        "constraints": "Small bounded synthetic data",
        "samples": deepcopy(samples or cases),
        "testcases": deepcopy(cases),
        "reference_solution": reference,
        "time_limit": 1.0,
        "memory_limit": 256,
    }
    if generator is not None:
        value["test_generator"] = generator
    return value


@pytest.mark.parametrize(
    "source",
    [
        "open('/outside', 'r')",
        "eval('1+1')",
        "exec('print(1)')",
        "compile('1','x','eval')",
        "import os",
        "import pathlib",
        "import subprocess",
        "import socket",
        "from sys import modules",
        "from json import decoder",
        "from . import math",
        "import sys\nprint(sys.modules)",
        "getattr(1, 'real')",
        "setattr(1,'a',2)",
        "globals()",
        "locals()",
        "vars()",
        "type(1)",
        "object()",
        "help(1)",
        "print((1).__class__)",
        "print(__builtins__)",
        "import sys\nprint(sys.stdin.buffer.raw.read())",
        "import sys\nprint(sys.stdin.buffer.fileno())",
        "import sys\nsys.stdin.buffer.write(b'x')",
        "import sys\nprint(sys.stdout.buffer.read())",
        "import sys\nbuffer=sys.stdin.buffer\nprint(buffer.read())",
        "import sys\nread=sys.stdin.buffer.read\nprint(read())",
        "import sys\nprint(list(map(sys.stdin.buffer.read, [1])))",
        "x = b'x'\nx.buffer.read()",
        "import sys\nprint(sys.stdout.write.__self__)",
        "print('{0.__class__}'.format(1))",
        "print('{x}'.format_map({'x': 1}))",
        "@staticmethod\ndef f():\n    return 1",
        "class X: pass",
        "f=print\nf('callable alias')",
        "import sys\nsys.stdout = 1",
        "import sys\nsys = 1",
        "def print(x):\n    return x",
        "import json as j\ndef f(j):\n    return j",
        "import random\nprint(random.random())",
        "import random\nrandom.seed(None)",
        "import random\nx=random.Random()",
        "import random\nr=random\nprint(r.random())",
        "from random import random\nprint(list(map(random, [1])))",
        "import random\nr=random.Random(7)\nprint(random.random())",
        "import random\nif False:\n    random.seed(42)\nprint(random.random())",
        "import random\nrandom.seed(42)\nf=random.random\nprint(f())",
        "import math\nprint(math.__dict__)",
        "if __name__ == '__main__':\n    print(1)",
        "x = [][0:0]\nprint(x.imag)",
        "(lambda: 1)()",
    ],
)
def test_unsafe_or_unsupported_source_is_rejected(source):
    with pytest.raises(APIError, match="reference_(unsafe_source|random_seed_scope)") as error:
        checks._validate_source(source, "reference")
    assert error.value.status == 400
    assert ":line=" in error.value.message
    assert int(error.value.message.rsplit("=", 1)[1]) > 0


@pytest.mark.parametrize(
    "source,line",
    [
        ("x=1\n\nimport os", 3),
        ("x=1\nprint(open('/private-source-value'))", 2),
        ("import sys\nx=1\nprint(sys.modules)", 3),
        ("x=1\ndef __hidden():\n    return x", 2),
        ("import json\ndef json():\n    return 1", 2),
    ],
)
@pytest.mark.parametrize("category", ["reference", "generator"])
def test_static_rejection_reports_only_exact_safe_category_and_line(source, line, category):
    with pytest.raises(APIError) as error:
        checks._validate_source(source, category)
    assert error.value.message == f"authoring_check:{category}_unsafe_source:line={line}"


@pytest.mark.parametrize("category", ["reference", "generator"])
def test_function_scoped_random_seed_has_specific_safe_repair_feedback(category):
    source = (
        "import random\n"
        "def generate():\n"
        "    random.seed(20240517)\n"
        "    return random.randint(1, 100)\n"
        "print(generate())\n"
    )
    with pytest.raises(APIError) as error:
        checks._validate_source(source, category)
    assert error.value.message == f"authoring_check:{category}_random_seed_scope:line=4"
    corrected = (
        "import random\nrandom.seed(20240517)\n"
        "def generate():\n    return random.randint(1, 100)\nprint(generate())\n"
    )
    checks._validate_source(corrected, category)


@pytest.mark.parametrize(
    "source",
    [
        SUM,
        GRAPH,
        "from math import sqrt as root\nprint(int(root(9)))",
        "import heapq\na=[3,1,2]\nheapq.heapify(a)\nprint(heapq.heappop(a))",
        "from collections import Counter,defaultdict\nx=Counter('aab')\nprint(x.most_common())",
        "import json, random\nrandom.seed(42)\nprint(json.dumps([str(random.randint(1,9))]))",
        "from random import Random\nrng=Random(7)\nprint(rng.randrange(10))",
        "def f(x):\n    return x*x\nprint(sorted([1,3,2], key=lambda n: f(n)))",
        "print('open and __class__ are harmless text')",
        "print(sum(map(int, input().split())))",
        "import sys\nfrom sys import stdin, stdout\nstdout.write(stdin.readline().strip())",
        "import sys\nprint(sum(map(int, sys.stdin.buffer.read().split())))",
        "import sys\nprint(sys.stdin.buffer.readline().decode())",
        "import sys\nprint(len(sys.stdin.buffer.readlines()))",
        "import sys\nsys.stdout.buffer.write(b'6')",
    ],
)
def test_algorithm_subset_accepts_data_operations(source):
    checks._validate_source(source, "reference")


@pytest.mark.asyncio
async def test_array_generator_real_determinism_samples_and_immutable_input():
    generator = (
        "import json, random\nrandom.seed(23)\n"
        "cases=[' '.join(str(random.randrange(10)) for _ in range(4)), '9 -9']\n"
        "print(json.dumps(cases))"
    )
    original = problem(generator=generator, samples=[{"input": "0", "output": "0\n"}])
    before = deepcopy(original)
    progress = []
    result = await checks.check_generated(original, progress.append)
    assert original == before
    assert result["testcases"][:2] == [original["testcases"][0], original["samples"][0]]
    assert len(result["testcases"]) == 4
    for case in result["testcases"]:
        assert case["output"].strip() == str(sum(map(int, case["input"].split())))
    assert result["quality"]["reference_checked"] is True
    assert result["quality"]["checked_cases"] == 4
    assert result["quality"]["generated_cases"] == 2
    assert "不构成数学正确性证明" in result["quality"]["note"]
    assert len(progress) == 8
    assert "第 1 次" in progress[1] and "第 2 次" in progress[2]


@pytest.mark.asyncio
async def test_graph_reference_real_handles_duplicate_self_loop_and_other_component():
    cases = [
        {"input": "1\n2 2\n1 2\n1 2\n", "output": "NO"},
        {"input": "1\n4 3\n1 2\n3 4\n4 3\n", "output": "YES"},
        {"input": "2\n1 1\n1 1\n1 0\n", "output": "YES\nNO"},
    ]
    result = await checks.check_generated(problem(GRAPH, cases), lambda _: None)
    assert result["quality"]["checked_cases"] == 3
    assert result["quality"]["generated_cases"] == 0


@pytest.mark.asyncio
async def test_builtin_input_reads_only_the_supplied_stdin():
    result = await checks.check_generated(
        problem("print(sum(map(int, input().split())))"), lambda _: None
    )
    assert result["quality"]["reference_checked"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("read", ["read()", "readline()", "readlines()[0]"])
async def test_fixed_stdio_buffer_paths_execute_on_supplied_streams(read):
    source = (
        f"import sys\nvalue=sum(map(int, sys.stdin.buffer.{read}.split()))\n"
        "sys.stdout.buffer.write(str(value).encode())"
    )
    result = await checks.check_generated(problem(source), lambda _: None)
    assert result["quality"]["reference_checked"] is True


@pytest.mark.asyncio
async def test_bad_generator_is_rejected_before_any_source_runs(monkeypatch):
    calls = []

    async def unexpected(*args, **kwargs):
        calls.append(args)
        pytest.fail("Neither source may execute until both have passed static checks")

    monkeypatch.setattr(checks, "run_command", unexpected)
    with pytest.raises(APIError, match="generator_unsafe_source"):
        await checks.check_generated(problem(generator="import os"), lambda _: None)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "generator,category",
    [
        ("print('not JSON')", "generator_json"),
        ("print('{}')", "generator_inputs"),
        ("print('[1]')", "generator_input_size:case=1"),
        ("import json\nprint(json.dumps(['x']*13))", "generator_inputs"),
        ("import json\nprint(json.dumps(['x'*1000001]))", "generator_input_size:case=1"),
    ],
)
async def test_generator_json_shape_and_bounds_real(generator, category):
    with pytest.raises(APIError, match=category):
        await checks.check_generated(problem(generator=generator), lambda _: None)


@pytest.mark.asyncio
async def test_nondeterministic_generator_is_rejected_and_runner_bounds(monkeypatch):
    outputs = iter([json.dumps(["1"]), json.dumps(["2"])])
    calls = []

    async def fake(argv, directory, stdin, seconds, memory, limit):
        calls.append((argv, directory, stdin, seconds, memory, limit))
        return ProcessResult("ok", returncode=0, stdout=next(outputs))

    monkeypatch.setattr(checks, "run_command", fake)
    with pytest.raises(APIError, match="generator_nondeterministic"):
        await checks.check_generated(problem(generator="print('[]')"), lambda _: None)
    assert len(calls) == 2
    assert all(call[2:] == ("", 5.0, 128, 2 * 1024 * 1024) for call in calls)
    assert calls[0][1] != calls[1][1]
    assert all(not directory.exists() for _, directory, *_ in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("sample", [False, True])
async def test_literal_and_sample_answer_disagreement_fails_with_index(sample):
    value = problem()
    if sample:
        value["samples"] = [{"input": "1 2", "output": "4"}]
    else:
        value["testcases"][0]["output"] = "7"
    with pytest.raises(APIError, match=f"answer_mismatch:case={2 if sample else 1}"):
        await checks.check_generated(value, lambda _: None)


@pytest.mark.asyncio
async def test_runtime_error_hides_traceback_source_and_path():
    with pytest.raises(APIError) as error:
        await checks.check_generated(
            problem("raise ValueError('private-value /private/path')"), lambda _: None
        )
    assert error.value.message == "authoring_check:reference_execution:case=1"


@pytest.mark.asyncio
async def test_missing_declared_graph_edges_fail_instead_of_claiming_quality():
    cases = [{"input": "1\n3 3\n1 2\n2 3\n", "output": "NO"}]
    with pytest.raises(APIError, match="reference_execution:case=1"):
        await checks.check_generated(problem(GRAPH, cases), lambda _: None)


@pytest.mark.asyncio
async def test_real_reference_timeout(monkeypatch):
    monkeypatch.setattr(checks, "REFERENCE_SECONDS", 0.12)
    with pytest.raises(APIError, match="reference_timeout:case=1"):
        await checks.check_generated(problem("while True: pass"), lambda _: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["memory", "output", "spawn", "policy", "monitor"])
async def test_resource_and_infrastructure_failures_are_safe(monkeypatch, reason):
    async def fake(argv, directory, stdin, seconds, memory, limit):
        assert (seconds, memory, limit) == (3.0, 128, 2 * 1024 * 1024)
        return ProcessResult(reason, returncode=-1, stderr="private-value /private/path")

    monkeypatch.setattr(checks, "run_command", fake)
    expected = reason if reason in {"memory", "output"} else "execution"
    with pytest.raises(APIError) as error:
        await checks.check_generated(problem(), lambda _: None)
    assert error.value.message == f"authoring_check:reference_{expected}:case=1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,category",
    [
        (None, "source_size"),
        ("", "source_missing"),
        ("if:", "source_syntax"),
        ("x" * 100001, "source_size"),
    ],
    ids=["missing", "empty", "syntax", "too-large"],
)
async def test_missing_invalid_and_oversized_reference(source, category):
    with pytest.raises(APIError, match="reference_" + category):
        await checks.check_generated(problem(source), lambda _: None)


@pytest.mark.asyncio
async def test_case_limit_includes_samples_before_execution(monkeypatch):
    async def unexpected(*args, **kwargs):
        pytest.fail("Oversized case sets must not execute")

    monkeypatch.setattr(checks, "run_command", unexpected)
    cases = [{"input": str(i), "output": str(i)} for i in range(40)]
    value = problem(cases=cases, samples=[{"input": "99", "output": "99"}])
    with pytest.raises(APIError, match="case_limit"):
        await checks.check_generated(value, lambda _: None)


@pytest.mark.asyncio
async def test_total_reference_output_is_bounded(monkeypatch):
    answer = "x" * 800_000
    cases = [{"input": str(i), "output": answer} for i in range(3)]

    async def fake(*args, **kwargs):
        return ProcessResult("ok", returncode=0, stdout=answer)

    monkeypatch.setattr(checks, "run_command", fake)
    with pytest.raises(APIError, match="combined_output_size:case=3"):
        await checks.check_generated(problem(cases=cases), lambda _: None)


@pytest.mark.asyncio
async def test_generated_answers_must_remain_valid_for_problem_save(monkeypatch):
    outputs = iter(['["0"]', '["0"]', "6", "x" * 1_000_001])

    async def fake(*args, **kwargs):
        return ProcessResult("ok", returncode=0, stdout=next(outputs))

    monkeypatch.setattr(checks, "run_command", fake)
    with pytest.raises(APIError, match="generated_problem_schema"):
        await checks.check_generated(problem(generator="print('[]')"), lambda _: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["reference", "generator"])
async def test_cancellation_waits_for_real_process_cleanup(monkeypatch, stage):
    actual = checks.run_command
    started = asyncio.Event()
    directories = []

    async def observed(argv, directory, *args, **kwargs):
        directories.append(directory)
        started.set()
        return await actual(argv, directory, *args, **kwargs)

    monkeypatch.setattr(checks, "run_command", observed)
    value = (
        problem("while True: pass")
        if stage == "reference"
        else problem(generator="while True: pass")
    )
    task = asyncio.create_task(checks.check_generated(value, lambda _: None))
    await asyncio.wait_for(started.wait(), timeout=2)
    processes = []
    try:
        for _ in range(100):
            for process in psutil.Process().children(recursive=True):
                try:
                    if any(str(directories[0]) in arg for arg in process.cmdline()):
                        processes.append(process)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if processes:
                break
            await asyncio.sleep(0.01)
        assert processes, "Reference process should actually start before cancellation"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert all(not directory.exists() for directory in directories)
    for process in processes:
        try:
            assert not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass
