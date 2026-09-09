"""Offline contracts plus real-process reference checks for original seed problems.

GOLDEN is hand-calculated independently of seed fixture construction and reference
programs. No HTTP request leaves MockTransport; tests never use accounts or a DB.
"""

from copy import deepcopy
import json

import httpx
import pytest

from oj.judge import judge_submission
from oj.schemas import validate_problem
from oj.translations import embedded_english_translation
from scripts.seed_data import DEMO_PROBLEMS, SEED_SOLUTIONS
from scripts.seed_demo import seed_problems

PYTHON = {"name": "python", "file_ext": ".py", "run_cmd": "python3 {src}"}
EXPECTED_IDS = [f"DEMO-{number:03d}" for number in range(1, 25)]

# Deliberately not calculated by the programs under test or copied from samples.
GOLDEN = {
    "DEMO-001": ("-100 37\n", "-63\n"),
    "DEMO-002": ("8\n1 1 0 1 1 1 0 1\n", "3\n"),
    "DEMO-003": ("5 3\n7 0 2 9 1\n2 5\n3 3\n1 4\n", "12\n2\n18\n"),
    "DEMO-004": ("5 5\n1 2\n2 3\n3 4\n4 2\n1 5\n", "YES\n"),
    "DEMO-005": ("1001 64\n", "16\n"),
    "DEMO-006": ("88\n", "B\n"),
    "DEMO-007": ("808202\n", "20\n"),
    "DEMO-008": ("50\n", "12\n"),
    "DEMO-009": ("abccba\n", "YES\n"),
    "DEMO-010": ("ddacccdda\n", "d 4\n"),
    "DEMO-011": ("abbbaac\n", "a1 b3 a2 c1\n"),
    "DEMO-012": ("6\n8 -3 8 6 6 1\n", "6\n"),
    "DEMO-013": ("6 8\n10 20 30 40 50 60\n", "50 60 10 20 30 40\n"),
    "DEMO-014": ("5\n6 9 6 9 2\n", "2 4 1 3 5\n"),
    "DEMO-015": ("5\n8 9\n1 4\n4 6\n7 7\n2 3\n", "3\n"),
    "DEMO-016": ("6 4\n-4 -4 1 3 3 8\n-4\n0\n3\n9\n", "1\n3\n4\n7\n"),
    # k=4 needs 8 hours; k=5 needs 6 hours, so the threshold for h=7 is 5.
    "DEMO-017": ("3 7\n8 13 5\n", "5\n"),
    "DEMO-018": ("[{()}]([])\n", "YES\n"),
    "DEMO-019": (
        "9\nPUSH 3\nPUSH 4\nPOP\nFRONT\nPUSH -2\nPOP\nFRONT\nPOP\nPOP\n",
        "3\n4\n4\n-2\n-2\nEMPTY\n",
    ),
    "DEMO-020": ("5\n0 6\n1 2\n2 4\n4 6\n5 7\n", "3\n"),
    # Days 1, 4, 6 and 8 yield 4+9+8+7=28; neither fixed parity achieves this.
    "DEMO-021": ("8\n4 1 1 9 2 8 0 7\n", "28\n"),
    "DEMO-022": ("3 11\n2 3 7\n", "3\n"),
    "DEMO-023": ("6 5\n1 2\n2 3\n3 1\n4 5\n5 5\n", "3\n"),
    # The two staggered walls force a 10-step detour, not Manhattan distance 6.
    "DEMO-024": ("3 5\n.#...\n.#.#.\n...#.\n", "10\n"),
}


def test_catalog_identity_and_topic_coverage():
    assert [problem["id"] for problem in DEMO_PROBLEMS] == EXPECTED_IDS
    assert set(SEED_SOLUTIONS) == set(GOLDEN) == set(EXPECTED_IDS)
    assert len({problem["title"] for problem in DEMO_PROBLEMS}) == 24
    tags = {tag for problem in DEMO_PROBLEMS for tag in problem["tags"]}
    assert {
        "整数运算",
        "条件判断",
        "循环",
        "字符串",
        "数组",
        "排序",
        "二分查找",
        "前缀和",
        "栈",
        "队列",
        "贪心",
        "动态规划",
        "图论",
    } <= tags
    assert sum(len(problem["testcases"]) for problem in DEMO_PROBLEMS) == 192


@pytest.mark.parametrize("problem", DEMO_PROBLEMS, ids=lambda problem: problem["id"])
def test_every_problem_meets_schema_samples_and_provenance(problem):
    core_problem = {key: value for key, value in problem.items() if key != "translations"}
    assert validate_problem(problem) == core_problem
    assert embedded_english_translation(problem) == problem["translations"]["en"]
    assert len(problem["samples"]) >= 2
    assert len(problem["testcases"]) >= 8
    assert len({case["input"] for case in problem["testcases"]}) >= 8
    assert all(sample in problem["testcases"] for sample in problem["samples"])
    assert "项目原创" in problem["source"] and "自建测试数据" in problem["source"]
    assert "solution" not in problem and "reference_code" not in problem
    for field in ("title", "description", "input_description", "output_description", "constraints"):
        assert (
            any("\u4e00" <= character <= "\u9fff" for character in problem[field])
            or field == "constraints"
        )
    code = SEED_SOLUTIONS[problem["id"]]
    compile(code, problem["id"], "exec")
    # The independently fixed golden case cannot accidentally be only a sample rerun.
    assert GOLDEN[problem["id"]][0] not in {case["input"] for case in problem["testcases"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", DEMO_PROBLEMS, ids=lambda problem: problem["id"])
async def test_all_reference_programs_pass_real_judge_and_independent_golden(problem):
    candidate = deepcopy(problem)
    source, expected = GOLDEN[problem["id"]]
    candidate["testcases"].append({"input": source, "output": expected})
    result = await judge_submission(candidate, PYTHON, SEED_SOLUTIONS[problem["id"]])
    assert result["status"] == "success", result
    assert result["counts"] == 90
    assert result["score"] == result["counts"], result
    assert [detail["result"] for detail in result["details"]] == ["AC"] * 9, result


def test_import_conflict_leaves_existing_problems_unchanged(capsys):
    requests = []

    def handle(request):
        assert request.method == "POST" and request.url.path == "/api/problems/"
        payload = json.loads(request.content)
        requests.append(payload)
        # Simulate the four existing IDs; no overwrite call is permitted afterward.
        status = 409 if payload["id"] in EXPECTED_IDS[:4] else 200
        return httpx.Response(status, json={"code": status, "msg": "fixture", "data": None})

    with httpx.Client(
        transport=httpx.MockTransport(handle), base_url="http://offline.test"
    ) as client:
        assert seed_problems(client) == {"created": 20, "existing": 4}
    assert requests == DEMO_PROBLEMS
    assert "20 created, 4 unchanged, 24 total" in capsys.readouterr().out


def test_import_stops_on_unexpected_failure_without_update_or_retry():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(403)

    with httpx.Client(
        transport=httpx.MockTransport(handle), base_url="http://offline.test"
    ) as client:
        with pytest.raises(SystemExit, match=r"DEMO-001.*403"):
            seed_problems(client)
    assert len(requests) == 1
    assert requests[0].method == "POST"
