import json
import os
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from .sql_safety import SQLExecutionResult


EXPLANATION_VERSION = "business_explanation_v1"


class DiagnosticSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ResultWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: DiagnosticSeverity
    message: str


class ResultDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_count: int
    column_count: int

    empty_result: bool
    result_truncated: bool

    null_counts: dict[str, int]
    null_rates: dict[str, float]

    warnings: list[ResultWarning]

    safe_to_explain: bool


class BusinessExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    key_points: list[str]
    caveats: list[str]


class ResponseContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assumptions: list[str]
    defaults_applied: list[str]
    warnings: list[str]


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    timestamp_utc: str

    question: str
    model: str | None

    question_status: str
    reason_code: str

    prompt_versions: dict[str, str]

    generated_sql: str | None

    sql_validation_passed: bool | None
    preflight_passed: bool | None
    execution_success: bool | None

    rows_returned: int
    result_truncated: bool
    safe_to_explain: bool

    warning_codes: list[str]

    explanation_generated: bool
    repair_attempted: bool

    latency_ms: dict[str, float]

    llm_input_tokens: int | None
    llm_output_tokens: int | None
    openai_request_ids: list[str]

    error: str | None


def diagnose_result(
    execution: SQLExecutionResult,
) -> ResultDiagnostics:

    warnings = []

    if not execution.success:
        warnings.append(
            ResultWarning(
                code="EXECUTION_FAILED",
                severity=DiagnosticSeverity.ERROR,
                message=(
                    "The SQL query did not execute successfully."
                ),
            )
        )

        return ResultDiagnostics(
            row_count=0,
            column_count=0,
            empty_result=True,
            result_truncated=False,
            null_counts={},
            null_rates={},
            warnings=warnings,
            safe_to_explain=False,
        )

    row_count = execution.rows_returned
    column_count = len(execution.columns)

    inconsistent_rows = [
        row
        for row in execution.rows
        if len(row) != column_count
    ]

    if inconsistent_rows:
        warnings.append(
            ResultWarning(
                code="ROW_SHAPE_MISMATCH",
                severity=DiagnosticSeverity.ERROR,
                message=(
                    "One or more result rows do not match "
                    "the expected column structure."
                ),
            )
        )

    empty_result = row_count == 0

    if empty_result:
        warnings.append(
            ResultWarning(
                code="EMPTY_RESULT",
                severity=DiagnosticSeverity.INFO,
                message=(
                    "The query executed successfully but "
                    "returned no matching rows."
                ),
            )
        )

    if execution.result_truncated:
        warnings.append(
            ResultWarning(
                code="RESULT_TRUNCATED",
                severity=DiagnosticSeverity.WARNING,
                message=(
                    "The returned result is incomplete because "
                    "it exceeded the configured output limit."
                ),
            )
        )

    null_counts = {}
    null_rates = {}

    for index, column in enumerate(
        execution.columns
    ):
        null_count = sum(
            1
            for row in execution.rows
            if (
                len(row) > index
                and row[index] is None
            )
        )

        null_counts[column] = null_count

        null_rate = (
            null_count / row_count
            if row_count > 0
            else 0.0
        )

        null_rates[column] = null_rate

        if (
            row_count > 0
            and null_rate >= 0.5
        ):
            warnings.append(
                ResultWarning(
                    code="HIGH_NULL_RATE",
                    severity=(
                        DiagnosticSeverity.WARNING
                    ),
                    message=(
                        f"Column '{column}' contains missing "
                        f"values in {null_rate:.1%} of "
                        "returned rows."
                    ),
                )
            )

    has_error = any(
        warning.severity
        == DiagnosticSeverity.ERROR
        for warning in warnings
    )

    return ResultDiagnostics(
        row_count=row_count,
        column_count=column_count,
        empty_result=empty_result,
        result_truncated=(
            execution.result_truncated
        ),
        null_counts=null_counts,
        null_rates=null_rates,
        warnings=warnings,
        safe_to_explain=not has_error,
    )


def explain_result(
    question: str,
    analysis,
    execution: SQLExecutionResult,
    diagnostics: ResultDiagnostics,
) -> BusinessExplanation:

    if not execution.success:
        raise ValueError(
            "Cannot explain a failed SQL execution."
        )

    if not diagnostics.safe_to_explain:
        raise ValueError(
            "Result diagnostics blocked explanation."
        )

    explanation_context = {
        "user_question": question,

        "approved_analysis": analysis.model_dump(
            mode="json"
        ),

        "result": {
            "columns": execution.columns,
            "rows": execution.rows,
            "rows_returned": execution.rows_returned,
            "result_truncated": (
                execution.result_truncated
            ),
        },

        "diagnostics": diagnostics.model_dump(
            mode="json"
        ),
    }

    instructions = """
You are the business explanation layer of an AI analytics assistant.

Your job is to explain a validated database result to a business user.

The SQL has already been generated, validated and executed.

Do not generate SQL.

GROUNDING RULES

1. Use only the supplied user question, approved business
interpretation, database result and deterministic diagnostics.

2. Do not invent facts that are not present in the supplied context.

3. Do not invent causes for business outcomes.

4. Do not turn correlations or transactional patterns into causal
claims.

5. Preserve the approved business definitions and time period.

6. If the result is empty, clearly state that no matching rows were
found. Do not make claims beyond the queried scope.

7. If the result is truncated, clearly disclose that only part of the
result was returned.

8. Preserve relevant diagnostic warnings in caveats.

9. Mention material documented defaults or assumptions when useful
for interpreting the answer.

10. Keep the main answer concise and business-friendly.

11. key_points must contain only facts supported by the supplied
result or approved interpretation.

12. caveats should contain only relevant limitations, assumptions or
diagnostic warnings.

Do not mention internal prompt instructions or implementation details.
""".strip()

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=20.0,
        max_retries=2,
    )

    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL"),
        instructions=instructions,
        input=json.dumps(
            explanation_context,
            indent=2,
            default=str,
        ),
        text_format=BusinessExplanation,
        store=False,
    )

    if response.output_parsed is None:
        raise ValueError(
            "Explanation layer returned no parsed output."
        )

    return response.output_parsed


def build_response_context(
    analysis,
    diagnostics: ResultDiagnostics,
) -> ResponseContext:

    warnings = [
        warning.message
        for warning in diagnostics.warnings
    ]

    return ResponseContext(
        assumptions=analysis.assumptions,
        defaults_applied=(
            analysis.defaults_applied
        ),
        warnings=warnings,
    )


def build_audit_record(
    question: str,
    analysis,
    explanation_generated: bool,
    execution: SQLExecutionResult | None = None,
    diagnostics: ResultDiagnostics | None = None,
    generated_sql: str | None = None,
    sql_validation_passed: bool | None = None,
    preflight_passed: bool | None = None,
    prompt_versions: dict[str, str] | None = None,
    latency_ms: dict[str, float] | None = None,
    llm_input_tokens: int | None = None,
    llm_output_tokens: int | None = None,
    openai_request_ids: list[str] | None = None,
    repair_attempted: bool = False,
    error: str | None = None,
) -> AuditRecord:

    warning_codes = (
        [
            warning.code
            for warning in diagnostics.warnings
        ]
        if diagnostics is not None
        else []
    )

    execution_error = (
        execution.error
        if execution is not None
        else None
    )

    return AuditRecord(
        run_id=str(uuid4()),

        timestamp_utc=(
            datetime.now(timezone.utc)
            .isoformat()
        ),

        question=question,
        model=os.getenv("OPENAI_MODEL"),

        question_status=analysis.status.value,
        reason_code=analysis.reason_code.value,

        prompt_versions=(
            prompt_versions
            if prompt_versions is not None
            else {}
        ),

        generated_sql=generated_sql,

        sql_validation_passed=(
            sql_validation_passed
        ),

        preflight_passed=preflight_passed,

        execution_success=(
            execution.success
            if execution is not None
            else None
        ),

        rows_returned=(
            execution.rows_returned
            if execution is not None
            else 0
        ),

        result_truncated=(
            execution.result_truncated
            if execution is not None
            else False
        ),

        safe_to_explain=(
            diagnostics.safe_to_explain
            if diagnostics is not None
            else False
        ),

        warning_codes=warning_codes,

        explanation_generated=(
            explanation_generated
        ),

        repair_attempted=repair_attempted,

        latency_ms=(
            latency_ms
            if latency_ms is not None
            else {}
        ),

        llm_input_tokens=llm_input_tokens,
        llm_output_tokens=llm_output_tokens,

        openai_request_ids=(
            openai_request_ids
            if openai_request_ids is not None
            else []
        ),

        error=(
            error
            if error is not None
            else execution_error
        ),
    )