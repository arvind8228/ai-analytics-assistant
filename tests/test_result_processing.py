from ai_analytics_assistant.result_processing import (
    DiagnosticSeverity,
    diagnose_result,
)

from ai_analytics_assistant.sql_safety import (
    SQLExecutionResult,
)


def test_normal_result_is_safe_to_explain():
    execution = SQLExecutionResult(
        success=True,
        columns=["order_count"],
        rows=[[23042]],
        rows_returned=1,
        result_truncated=False,
        error=None,
    )

    diagnostics = diagnose_result(
        execution
    )

    assert diagnostics.row_count == 1
    assert diagnostics.column_count == 1
    assert diagnostics.empty_result is False
    assert diagnostics.result_truncated is False
    assert diagnostics.safe_to_explain is True
    assert diagnostics.warnings == []


def test_empty_result_is_safe_with_info_warning():
    execution = SQLExecutionResult(
        success=True,
        columns=[
            "customer_id",
            "customer_name",
        ],
        rows=[],
        rows_returned=0,
        result_truncated=False,
        error=None,
    )

    diagnostics = diagnose_result(
        execution
    )

    assert diagnostics.empty_result is True
    assert diagnostics.safe_to_explain is True

    assert any(
        warning.code == "EMPTY_RESULT"
        and warning.severity
        == DiagnosticSeverity.INFO
        for warning in diagnostics.warnings
    )


def test_truncated_result_is_safe_with_warning():
    execution = SQLExecutionResult(
        success=True,
        columns=["customer_id"],
        rows=[
            [1],
            [2],
            [3],
        ],
        rows_returned=3,
        result_truncated=True,
        error=None,
    )

    diagnostics = diagnose_result(
        execution
    )

    assert diagnostics.result_truncated is True
    assert diagnostics.safe_to_explain is True

    assert any(
        warning.code == "RESULT_TRUNCATED"
        and warning.severity
        == DiagnosticSeverity.WARNING
        for warning in diagnostics.warnings
    )


def test_high_null_rate_creates_warning():
    execution = SQLExecutionResult(
        success=True,
        columns=[
            "customer_id",
            "customer_name",
        ],
        rows=[
            [1, None],
            [2, None],
            [3, "Asha"],
            [4, "Rahul"],
        ],
        rows_returned=4,
        result_truncated=False,
        error=None,
    )

    diagnostics = diagnose_result(
        execution
    )

    assert diagnostics.null_counts[
        "customer_name"
    ] == 2

    assert diagnostics.null_rates[
        "customer_name"
    ] == 0.5

    assert diagnostics.safe_to_explain is True

    assert any(
        warning.code == "HIGH_NULL_RATE"
        and warning.severity
        == DiagnosticSeverity.WARNING
        for warning in diagnostics.warnings
    )


def test_row_shape_mismatch_blocks_explanation():
    execution = SQLExecutionResult(
        success=True,
        columns=[
            "customer_id",
            "customer_name",
        ],
        rows=[
            [1, "Asha"],
            [2],
        ],
        rows_returned=2,
        result_truncated=False,
        error=None,
    )

    diagnostics = diagnose_result(
        execution
    )

    assert diagnostics.safe_to_explain is False

    assert any(
        warning.code == "ROW_SHAPE_MISMATCH"
        and warning.severity
        == DiagnosticSeverity.ERROR
        for warning in diagnostics.warnings
    )


def test_failed_execution_blocks_explanation():
    execution = SQLExecutionResult(
        success=False,
        columns=[],
        rows=[],
        rows_returned=0,
        result_truncated=False,
        error="Database execution failed.",
    )

    diagnostics = diagnose_result(
        execution
    )

    assert diagnostics.row_count == 0
    assert diagnostics.column_count == 0
    assert diagnostics.empty_result is True
    assert diagnostics.safe_to_explain is False

    assert any(
        warning.code == "EXECUTION_FAILED"
        and warning.severity
        == DiagnosticSeverity.ERROR
        for warning in diagnostics.warnings
    )