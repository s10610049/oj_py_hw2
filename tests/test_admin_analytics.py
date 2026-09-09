"""Frontend contract, localization and escaping for cohort analytics."""

import inspect

from frontend import admin_analytics, ui
from frontend.styles import CSS


def payload():
    outcome_ids = (
        "pending",
        "accepted",
        "partial",
        "wrong_answer",
        "compile_error",
        "time_limit",
        "memory_limit",
        "runtime_error",
        "judge_error",
    )

    def outcomes(**counts):
        return [{"id": item, "count": counts.get(item, 0)} for item in outcome_ids]

    alice_outcomes = outcomes(accepted=2, compile_error=1)
    bob_outcomes = outcomes(partial=1, wrong_answer=1)
    idle_outcomes = outcomes()
    return {
        "schema_version": "oj.admin-learning-overview.v1",
        "generated_at": "2026-09-10T08:00:00+00:00",
        "timezone": "UTC",
        "summary": {
            "account_count": 3,
            "active_count": 2,
            "disabled_count": 1,
            "learner_count": 1,
            "engaged_count": 2,
            "submission_count": 5,
            "attempted_count": 3,
            "passed_count": 2,
            "earned_score": 35,
            "available_score": 60,
            "score_rate": 35 / 60,
            "pass_rate": 2 / 3,
        },
        "submission_outcomes": outcomes(accepted=2, partial=1, wrong_answer=1, compile_error=1),
        "users": [
            {
                "user_id": "u1",
                "username": "alice",
                "role": "admin",
                "account_status": "active",
                "join_time": "2026-09-01",
                "submission_count": 3,
                "attempted_count": 1,
                "passed_count": 1,
                "earned_score": 20,
                "available_score": 20,
                "score_rate": 1.0,
                "pass_rate": 1.0,
                "submission_outcomes": alice_outcomes,
                "code": "SECRET SOURCE",
            },
            {
                "user_id": "u2",
                "username": "bob",
                "role": "user",
                "account_status": "active",
                "join_time": "2026-09-02",
                "submission_count": 2,
                "attempted_count": 2,
                "passed_count": 1,
                "earned_score": 15,
                "available_score": 20,
                "score_rate": 0.75,
                "pass_rate": 0.5,
                "submission_outcomes": bob_outcomes,
            },
            {
                "user_id": "u3",
                "username": "<script>alert(1)</script>",
                "role": "banned",
                "account_status": "disabled",
                "join_time": "2026-09-03",
                "submission_count": 0,
                "attempted_count": 0,
                "passed_count": 0,
                "earned_score": 0,
                "available_score": 20,
                "score_rate": 0.0,
                "pass_rate": None,
                "submission_outcomes": idle_outcomes,
            },
        ],
        "password_hash": "SECRET HASH",
    }


def test_overview_contract_accepts_zero_activity_and_drops_unknown_sensitive_fields():
    view = admin_analytics.normalize_overview(payload())
    assert view is not None
    assert view["users"][2]["submission_count"] == 0
    assert view["users"][2]["pass_rate"] is None
    assert "code" not in str(view).lower()
    assert "secret" not in str(view).lower()


def test_overview_contract_rejects_mismatched_or_non_finite_aggregates():
    mismatched = payload()
    mismatched["summary"]["submission_count"] = 6
    assert admin_analytics.normalize_overview(mismatched) is None
    infinite = payload()
    infinite["users"][0]["score_rate"] = float("inf")
    assert admin_analytics.normalize_overview(infinite) is None
    missing_outcome = payload()
    missing_outcome["users"][0]["submission_outcomes"].pop()
    assert admin_analytics.normalize_overview(missing_outcome) is None


def test_bilingual_fragments_escape_accounts_and_show_verdict_comparison():
    chinese = admin_analytics.overview_fragments(payload(), "zh-CN")
    english = admin_analytics.overview_fragments(payload(), "en")
    assert chinese is not None and english is not None
    combined = "".join(chinese.values())
    assert "用户表现对比" in combined and "提交结果分布" in combined
    assert "部分通过" in combined and "CE" in combined
    assert "&lt;script&gt;" in combined and "<script>" not in combined
    translated = "".join(english.values())
    assert "User performance comparison" in translated
    assert "Submission outcome mix" in translated
    assert "Disabled" in translated and "已禁用" not in translated


def test_account_filters_are_case_insensitive_and_keep_idle_accounts():
    view = admin_analytics.normalize_overview(payload())
    assert view is not None
    assert [row["username"] for row in admin_analytics.filter_account_rows(view["users"])] == [
        "alice",
        "bob",
        "<script>alert(1)</script>",
    ]
    assert [
        row["username"] for row in admin_analytics.filter_account_rows(view["users"], "  ALI  ")
    ] == ["alice"]
    idle = admin_analytics.filter_account_rows(view["users"], role="banned", status="disabled")
    assert len(idle) == 1
    assert idle[0]["submission_count"] == 0


def test_account_filters_combine_and_render_bilingual_empty_state():
    view = admin_analytics.normalize_overview(payload())
    assert view is not None
    assert (
        admin_analytics.filter_account_rows(
            view["users"], username_query="bob", role="admin", status="active"
        )
        == []
    )
    empty_view = {"users": []}
    assert "没有符合当前筛选条件的账号" in admin_analytics.accounts_table_html(empty_view, "zh-CN")
    assert "No accounts match the current filters" in admin_analytics.accounts_table_html(
        empty_view, "en"
    )


def test_account_filter_labels_are_complete_in_both_languages():
    assert (
        admin_analytics._COPY["zh-CN"]["account_search"],
        admin_analytics._COPY["zh-CN"]["role_filter"],
        admin_analytics._COPY["zh-CN"]["status_filter"],
    ) == ("搜索账号", "角色筛选", "账号状态")
    assert (
        admin_analytics._COPY["en"]["account_search"],
        admin_analytics._COPY["en"]["role_filter"],
        admin_analytics._COPY["en"]["status_filter"],
    ) == ("Search accounts", "Role", "Account status")


def test_admin_overview_page_reads_exactly_one_admin_only_payload(monkeypatch):
    calls = []
    output = []
    fields = []

    class Client:
        def request(self, method, path):
            calls.append((method, path))
            return payload()

    class Column:
        def text_input(self, label, **kwargs):
            fields.append(("text_input", label, kwargs))
            return ""

        def selectbox(self, label, options, **kwargs):
            fields.append(("selectbox", label, options, kwargs))
            return options[0]

    monkeypatch.setattr(admin_analytics, "api", lambda: Client())
    monkeypatch.setattr(admin_analytics, "locale", lambda: "en")
    monkeypatch.setattr(admin_analytics.st, "subheader", output.append)
    monkeypatch.setattr(admin_analytics.st, "caption", output.append)
    monkeypatch.setattr(admin_analytics.st, "html", output.append)
    monkeypatch.setattr(admin_analytics.st, "error", output.append)
    monkeypatch.setattr(
        admin_analytics.st, "columns", lambda *args, **kwargs: [Column(), Column(), Column()]
    )
    admin_analytics.admin_overview_page()
    assert calls == [("GET", "/api/admin/learning-overview/")]
    assert output[0] == "Cohort overview"
    assert any("oj-admin-account-table" in item for item in output)
    assert [field[1] for field in fields] == ["Search accounts", "Role", "Account status"]
    assert fields[0][2]["placeholder"] == "Enter a username"
    assert fields[1][3]["format_func"]("all") == "All roles"
    assert fields[1][3]["format_func"]("admin") == "Administrator"
    assert fields[2][3]["format_func"]("all") == "All statuses"
    assert fields[2][3]["format_func"]("disabled") == "Disabled"


def test_topbar_groups_identity_language_and_assistant_at_the_right():
    source = inspect.getsource(ui.main)
    assert 'key="workspace_actions"' in source
    actions = source[source.index('key="workspace_actions"') :]
    assert actions.index("workspace_identity(") < actions.index("_language_control()")
    assert actions.index("_language_control()") < actions.index("chat_assistant(")
    assert ".st-key-workspace_actions {width:max-content" in CSS
    assert ".oj-command-identity" in CSS
    assert "margin-left:auto" in CSS
