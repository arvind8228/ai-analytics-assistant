import ai_analytics_assistant.pipeline as pipeline

from ai_analytics_assistant.question_analyzer import (
    QuestionAnalysis,
    QuestionStatus,
    ReasonCode,
)

from ai_analytics_assistant.sql_planner import (
    GeneratedSQL,
    SQLPlan,
)

from ai_analytics_assistant.sql_safety import (
    SQLExecutionResult,
    SQLPreflightResult,
)

from ai_analytics_assistant.result_processing import (
    BusinessExplanation,
)


def make_analysis():
    return QuestionAnalysis(
        status=QuestionStatus.ANSWERABLE,
        reason_code=ReasonCode.CLEAR_QUESTION,
        reason="The question is clear.",
        requested_metric="order_count",
        requested_entity="orders",
        time_period=None,
        grouping=None,
        ranking=None,
        filters=["order_status = completed"],
        assumptions=[],
        defaults_applied=[],
        material_ambiguities=[],
        missing_information=[],
        evidence=[],
        clarification_question=None,
    )


def make_plan():
    return SQLPlan(
        objective="Count completed orders.",
        metric="order_count",
        entity="orders",
        required_tables=["orders"],
        joins=[],
        filters=[],
        dimensions=[],
        group_by=[],
        order_by=[],
        limit=None,
        time_period=None,
        assumptions=[],
    )


def mock_execution():
    return SQLExecutionResult(
        success=True,
        columns=["order_count"],
        rows=[[23042]],
        rows_returned=1,
        result_truncated=False,
        error=None,
    )


def mock_explanation():
    return BusinessExplanation(
        answer="There are 23,042 completed orders.",
        key_points=[],
        caveats=[],
    )


def apply_common_mocks(
    monkeypatch,
):
    monkeypatch.setattr(
        pipeline,
        "analyze_question",
        lambda question: make_analysis(),
    )

    monkeypatch.setattr(
        pipeline,
        "create_sql_plan",
        lambda question, analysis: make_plan(),
    )

    monkeypatch.setattr(
        pipeline,
        "execute_read_only_sql",
        lambda sql: mock_execution(),
    )

    monkeypatch.setattr(
        pipeline,
        "explain_result",
        lambda question,
        analysis,
        execution,
        diagnostics: mock_explanation(),
    )


def test_validation_failure_is_repaired_once(
    monkeypatch,
):
    apply_common_mocks(
        monkeypatch
    )

    monkeypatch.setattr(
        pipeline,
        "generate_sql",
        lambda plan: GeneratedSQL(
            sql="DELETE FROM orders"
        ),
    )

    monkeypatch.setattr(
        pipeline,
        "preflight_sql",
        lambda sql: SQLPreflightResult(
            passed=True,
            plan_lines=[
                "Mock EXPLAIN passed"
            ],
            error=None,
        ),
    )

    repair_calls = {
        "count": 0
    }

    def successful_repair(
        plan,
        failed_sql,
        failure_stage,
        failure_details,
    ):
        repair_calls["count"] += 1

        return GeneratedSQL(
            sql=(
                "SELECT "
                "COUNT(DISTINCT order_id) "
                "AS order_count "
                "FROM orders "
                "WHERE order_status = 'completed'"
            )
        )

    monkeypatch.setattr(
        pipeline,
        "repair_sql",
        successful_repair,
    )

    result = (
        pipeline.run_controlled_pipeline(
            "How many completed orders do we have?"
        )
    )

    assert result.status == "SUCCESS"
    assert repair_calls["count"] == 1
    assert result.audit[
        "repair_attempted"
    ] is True

    assert result.validation_passed is True
    assert result.preflight_passed is True
    assert result.execution_success is True


def test_failed_repair_does_not_retry(
    monkeypatch,
):
    apply_common_mocks(
        monkeypatch
    )

    monkeypatch.setattr(
        pipeline,
        "generate_sql",
        lambda plan: GeneratedSQL(
            sql="DELETE FROM orders"
        ),
    )

    repair_calls = {
        "count": 0
    }

    def failed_repair(
        plan,
        failed_sql,
        failure_stage,
        failure_details,
    ):
        repair_calls["count"] += 1

        return GeneratedSQL(
            sql="DELETE FROM orders"
        )

    monkeypatch.setattr(
        pipeline,
        "repair_sql",
        failed_repair,
    )

    result = (
        pipeline.run_controlled_pipeline(
            "How many completed orders do we have?"
        )
    )

    assert (
        result.status
        == "SQL_VALIDATION_FAILED"
    )

    assert repair_calls["count"] == 1

    assert result.audit[
        "repair_attempted"
    ] is True

    assert result.validation_passed is False
    assert result.execution_success is None

    assert (
        "after one repair attempt"
        in result.audit["error"]
    )


def test_preflight_failure_is_repaired_once(
    monkeypatch,
):
    apply_common_mocks(
        monkeypatch
    )

    monkeypatch.setattr(
        pipeline,
        "generate_sql",
        lambda plan: GeneratedSQL(
            sql=(
                "SELECT missing_column "
                "FROM orders"
            )
        ),
    )

    preflight_calls = {
        "count": 0
    }

    repair_calls = {
        "count": 0
    }

    def mock_preflight(
        sql,
    ):
        preflight_calls["count"] += 1

        if "missing_column" in sql:
            return SQLPreflightResult(
                passed=False,
                plan_lines=[],
                error=(
                    'column "missing_column" '
                    "does not exist"
                ),
            )

        return SQLPreflightResult(
            passed=True,
            plan_lines=[
                "Mock EXPLAIN passed"
            ],
            error=None,
        )

    def successful_repair(
        plan,
        failed_sql,
        failure_stage,
        failure_details,
    ):
        repair_calls["count"] += 1

        assert (
            failure_stage
            == "PREFLIGHT"
        )

        return GeneratedSQL(
            sql=(
                "SELECT "
                "COUNT(DISTINCT order_id) "
                "AS order_count "
                "FROM orders "
                "WHERE order_status = 'completed'"
            )
        )

    monkeypatch.setattr(
        pipeline,
        "preflight_sql",
        mock_preflight,
    )

    monkeypatch.setattr(
        pipeline,
        "repair_sql",
        successful_repair,
    )

    result = (
        pipeline.run_controlled_pipeline(
            "How many completed orders do we have?"
        )
    )

    assert result.status == "SUCCESS"

    assert repair_calls["count"] == 1
    assert preflight_calls["count"] == 2

    assert result.audit[
        "repair_attempted"
    ] is True

    assert result.validation_passed is True
    assert result.preflight_passed is True
    assert result.execution_success is True
    