import math
import re

import pytest

from frontend import analytics


def payload():
    return {
        "schema_version": "oj.learning-stats.v1",
        "context_epoch": "epoch",
        "generated_at": "2026-09-09T10:00:00Z",
        "scope": {
            "user_id": "alice",
            "catalog_problem_count": 2,
            "submission_count": 5,
            "orphan_submission_count": 0,
            "version_unknown_count": 0,
            "timezone": "UTC",
        },
        "kpis": {
            "earned_score": 130,
            "available_score": 200,
            "attempted_count": 2,
            "passed_count": 1,
            "pass_rate": 0.5,
        },
        "submission_outcomes": [
            {"id": "pending", "count": 1},
            {"id": "judge_error", "count": 0},
            {"id": "zero_score", "count": 1},
            {"id": "partial", "count": 2},
            {"id": "full", "count": 1},
        ],
        "timeline": [
            {
                "date": "2026-09-09",
                "submissions": 3,
                "completed": 3,
                "best_score_delta": 80,
                "cumulative_score": 130,
            },
            {
                "date": "2026-09-08",
                "submissions": 2,
                "completed": 1,
                "best_score_delta": 50,
                "cumulative_score": 50,
            },
        ],
        "difficulty": [
            {
                "difficulty_id": "luogu.6",
                "difficulty_label": "提高+/省选-",
                "attempted": 1,
                "passed": 0,
                "earned_score": 30,
                "available_score": 100,
                "rate": 0,
            },
            {
                "difficulty_id": "luogu.1",
                "difficulty_label": "入门",
                "attempted": 1,
                "passed": 1,
                "earned_score": 100,
                "available_score": 100,
                "rate": 1,
            },
        ],
        "knowledge_points": [
            {
                "tag": "字符串与超长中文知识点名称用于检验自然换行",
                "attempted": 2,
                "passed": 1,
                "earned_score": 130,
                "available_score": 200,
                "rate": 0.5,
            }
        ],
        "problems": [
            {
                "problem_id": "P-002",
                "title": "最长公共子序列 <script>alert(1)</script>",
                "current_problem_version": "v2",
                "state": "partial",
                "latest_pending": None,
                "best": None,
                "latest_terminal": None,
                "historical_best": None,
                "version_unknown": False,
                "available_score": 100,
                "best_score": 30,
                "difficulty_id": "luogu.6",
                "difficulty_label": "提高+/省选-",
                "tags": ["动态规划", "<img src=x onerror=alert(1)>", "动态规划"],
                "code": "SECRET_SOURCE",
                "testcases": ["SECRET_CASE"],
                "details": "SECRET_DETAIL",
            },
            {
                "problem_id": "P-001",
                "title": "两数之和",
                "current_problem_version": "v1",
                "state": "passed",
                "latest_pending": None,
                "best": None,
                "latest_terminal": None,
                "historical_best": None,
                "version_unknown": False,
                "available_score": 100,
                "best_score": 100,
                "difficulty_id": "luogu.1",
                "difficulty_label": "入门",
                "tags": ["数组"],
            },
        ],
    }


def test_normalize_orders_timeline_difficulty_knowledge_and_preserves_problem_order():
    source = payload()
    source["knowledge_points"].append(
        {
            "tag": "数组",
            "attempted": 5,
            "passed": 4,
            "earned_score": 40,
            "available_score": 50,
            "rate": 0.8,
        }
    )

    result = analytics.normalize_stats(source)

    assert [row["date"] for row in result["timeline"]] == ["2026-09-08", "2026-09-09"]
    assert [row["id"] for row in result["difficulty"]] == ["luogu.1", "luogu.6"]
    assert [row["tag"] for row in result["knowledge"]] == [
        "数组",
        "字符串与超长中文知识点名称用于检验自然换行",
    ]
    assert [row["id"] for row in result["problems"]] == ["P-002", "P-001"]


def test_timeline_svg_has_finite_bounded_geometry_and_accessible_text():
    result = analytics.normalize_stats(payload())
    rendered = analytics.timeline_svg(result["timeline"])

    assert "role='img'" in rendered
    assert "<title id='oj-timeline-title'>" in rendered
    assert "<desc id='oj-timeline-desc'>" in rendered
    assert "2026-09-08" in rendered and "2026-09-09" in rendered
    assert "nan" not in rendered.lower()
    assert "inf" not in rendered.lower()
    coordinates = [float(value) for value in re.findall(r"(?:cx|cy)='([0-9.]+)'", rendered)]
    assert coordinates
    assert all(math.isfinite(value) and 0 <= value <= 760 for value in coordinates)
    assert "M 54.00 131.23 L 742.00 18.00" in rendered


def test_empty_payload_renders_zero_kpis_and_meaningful_empty_states():
    source = payload()
    source["scope"]["catalog_problem_count"] = 0
    source["scope"]["submission_count"] = 0
    source["kpis"] = {
        "earned_score": 0,
        "available_score": 0,
        "attempted_count": 0,
        "passed_count": 0,
        "pass_rate": None,
    }
    source["timeline"] = []
    source["difficulty"] = []
    source["knowledge_points"] = []
    source["problems"] = []
    source["submission_outcomes"] = [
        {"id": outcome, "count": 0} for outcome in analytics.OUTCOME_ORDER
    ]

    fragments = analytics.dashboard_fragments(source)

    assert "0 / 0" in fragments["kpis"]
    assert "—" in fragments["kpis"]
    assert "成长曲线" in fragments["timeline"]
    assert "题库中暂无题目" in fragments["problems"]
    assert fragments["issues"] == "0"


def test_problem_projection_escapes_values_and_drops_sensitive_unknown_fields():
    fragments = analytics.dashboard_fragments(payload())
    rendered = fragments["problems"]

    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<img" not in rendered
    assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert rendered.count("动态规划") == 1
    assert "SECRET_SOURCE" not in rendered
    assert "SECRET_CASE" not in rendered
    assert "SECRET_DETAIL" not in rendered


def test_null_denominator_never_outputs_nan_and_long_chinese_is_retained():
    source = payload()
    source["kpis"]["attempted_count"] = 0
    source["kpis"]["passed_count"] = 0
    source["kpis"]["pass_rate"] = None
    source["difficulty"][0]["rate"] = None
    fragments = analytics.dashboard_fragments(source)
    combined = "".join(fragments.values())

    assert "—" in fragments["kpis"]
    assert "暂无尝试" in fragments["difficulty"]
    assert "字符串与超长中文知识点名称用于检验自然换行" in fragments["knowledge"]
    assert "nan" not in combined.lower()
    assert "infinity" not in combined.lower()


@pytest.mark.parametrize(
    "bad_value",
    [float("nan"), float("inf"), -1, True, "12"],
)
def test_malformed_numbers_are_omitted_without_unsafe_geometry(bad_value):
    source = payload()
    source["timeline"][0]["cumulative_score"] = bad_value

    result = analytics.normalize_stats(source)
    rendered = analytics.timeline_svg(result["timeline"])

    assert result["issues"] >= 1
    assert [row["date"] for row in result["timeline"]] == ["2026-09-08"]
    assert "2026-09-09" not in rendered
    assert "nan" not in rendered.lower()
    assert "inf" not in rendered.lower()


def test_unknown_schema_and_non_monotonic_timeline_fail_closed():
    assert analytics.normalize_stats({"schema_version": "future.v9"}) is None
    source = payload()
    source["timeline"][0]["cumulative_score"] = 10
    result = analytics.normalize_stats(source)
    assert result["timeline"] == []
    assert result["issues"] >= 1


def test_malformed_kpi_and_scope_are_safe_and_reported():
    source = payload()
    source["scope"]["submission_count"] = "many"
    source["kpis"]["earned_score"] = float("nan")

    result = analytics.normalize_stats(source)

    assert result["scope"]["submissions"] == 0
    assert result["kpis"]["earned"] == 0
    assert result["issues"] == 2


def test_extremely_large_number_is_rejected_without_overflow():
    source = payload()
    source["timeline"][0]["cumulative_score"] = 10**1000

    result = analytics.normalize_stats(source)

    assert [row["date"] for row in result["timeline"]] == ["2026-09-08"]
    assert result["issues"] >= 1


def test_outcome_order_is_stable_even_when_backend_rows_are_shuffled():
    source = payload()
    source["submission_outcomes"].reverse()
    result = analytics.normalize_stats(source)

    assert [row["id"] for row in result["outcomes"]] == list(analytics.OUTCOME_ORDER)


def test_difficulty_classes_are_allow_listed_and_not_derived_from_raw_input():
    source = payload()
    source["difficulty"][0]["difficulty_id"] = "x' onclick='alert(1)"
    source["difficulty"][0]["difficulty_label"] = "未知 <b>难度</b>"
    fragments = analytics.dashboard_fragments(source)

    assert "onclick" not in fragments["difficulty"]
    assert "difficulty-neutral" in fragments["difficulty"]
    assert "未知 &lt;b&gt;难度&lt;/b&gt;" in fragments["difficulty"]


def test_analytics_page_uses_one_backend_payload(monkeypatch):
    requests = []
    output = []

    class Client:
        def request(self, method, path):
            requests.append((method, path))
            return payload()

    monkeypatch.setattr(analytics, "api", lambda: Client())
    monkeypatch.setattr(analytics, "_current_locale", lambda: "zh-CN")
    monkeypatch.setattr(analytics.st, "title", lambda value: output.append(value))
    monkeypatch.setattr(analytics.st, "caption", lambda value: output.append(value))
    monkeypatch.setattr(analytics.st, "subheader", lambda value: output.append(value))
    monkeypatch.setattr(analytics.st, "html", lambda value: output.append(value))
    monkeypatch.setattr(analytics.st, "warning", lambda value: output.append(value))
    monkeypatch.setattr(analytics.st, "error", lambda value: output.append(value))

    analytics.analytics_page()

    assert requests == [("GET", "/api/me/learning-stats/")]
    assert any("oj-analytics-kpis" in item for item in output)
    assert any("oj-analytics-table" in item for item in output)


def test_english_fixed_copy_and_taxonomy_are_consistent():
    fragments = analytics.dashboard_fragments(payload(), "en")

    assert "Total score" in fragments["kpis"]
    assert "Intermediate+ / Provincial−" in fragments["difficulty"]
    assert "部分得分" not in fragments["outcomes"]
    assert "Partially passed" in fragments["problems"]
