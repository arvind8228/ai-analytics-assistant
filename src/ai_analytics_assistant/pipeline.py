from time import perf_counter

from pydantic import BaseModel, ConfigDict

from .question_analyzer import (
    QUESTION_ANALYZER_VERSION,
    analyze_question,
)

from .sql_planner import (
    SQL_GENERATOR_VERSION,
    SQL_PLANNER_VERSION,
    create_sql_plan,
    generate_sql,
)

from .sql_safety import (
    execute_read_only_sql,
    preflight_sql,
    validate_sql,
)

from .result_processing import (
    EXPLANATION_VERSION,
    build_audit_record,
    build_response_context,
    diagnose_result,
    explain_result,
)


class ControlledPipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str

    answer: str | None
    clarification_question: str | None

    analysis: dict

    sql_plan: dict | None
    generated_sql: str | None

    validation_passed: bool | None
    preflight_passed: bool | None
    execution_success: bool | None

    result_columns: list[str]
    result_rows: list[list]

    diagnostics: dict | None
    response_context: dict | None
    explanation: dict | None

    audit: dict


def run_controlled_pipeline(
    question: str,
) -> ControlledPipelineResult:

    pipeline_start = perf_counter()

    latency_ms = {}

    prompt_versions = {
        "question_analyzer": QUESTION_ANALYZER_VERSION,
        "sql_planner": SQL_PLANNER_VERSION,
        "sql_generator": SQL_GENERATOR_VERSION,
        "business_explanation": EXPLANATION_VERSION,
    }


    # 1. Analyze the business question
    stage_start = perf_counter()

    analysis = analyze_question(
        question
    )

    latency_ms["question_analysis"] = (
        perf_counter() - stage_start
    ) * 1000


    # Stop before SQL for clarification,
    # unsupported or unsafe questions
    if analysis.status.value != "ANSWERABLE":

        latency_ms["total"] = (
            perf_counter() - pipeline_start
        ) * 1000

        audit = build_audit_record(
            question=question,
            analysis=analysis,
            explanation_generated=False,
            prompt_versions=prompt_versions,
            latency_ms=latency_ms,
        )

        return ControlledPipelineResult(
            status=analysis.status.value,
            answer=None,

            clarification_question=(
                analysis.clarification_question
            ),

            analysis=analysis.model_dump(
                mode="json"
            ),

            sql_plan=None,
            generated_sql=None,

            validation_passed=None,
            preflight_passed=None,
            execution_success=None,

            result_columns=[],
            result_rows=[],

            diagnostics=None,
            response_context=None,
            explanation=None,

            audit=audit.model_dump(
                mode="json"
            ),
        )


    # 2. Create structured SQL plan
    stage_start = perf_counter()

    sql_plan = create_sql_plan(
        question,
        analysis,
    )

    latency_ms["sql_planning"] = (
        perf_counter() - stage_start
    ) * 1000


    # 3. Generate PostgreSQL
    stage_start = perf_counter()

    generated = generate_sql(
        sql_plan
    )

    latency_ms["sql_generation"] = (
        perf_counter() - stage_start
    ) * 1000


    # 4. Deterministic SQL validation
    stage_start = perf_counter()

    validation = validate_sql(
        generated.sql
    )

    latency_ms["sql_validation"] = (
        perf_counter() - stage_start
    ) * 1000


    if not validation.is_valid:

        latency_ms["total"] = (
            perf_counter() - pipeline_start
        ) * 1000

        error = (
            "SQL failed deterministic validation: "
            + "; ".join(validation.errors)
        )

        audit = build_audit_record(
            question=question,
            analysis=analysis,
            explanation_generated=False,
            generated_sql=generated.sql,
            sql_validation_passed=False,
            prompt_versions=prompt_versions,
            latency_ms=latency_ms,
            error=error,
        )

        return ControlledPipelineResult(
            status="SQL_VALIDATION_FAILED",
            answer=None,
            clarification_question=None,

            analysis=analysis.model_dump(
                mode="json"
            ),

            sql_plan=sql_plan.model_dump(
                mode="json"
            ),

            generated_sql=generated.sql,

            validation_passed=False,
            preflight_passed=None,
            execution_success=None,

            result_columns=[],
            result_rows=[],

            diagnostics=None,
            response_context=None,
            explanation=None,

            audit=audit.model_dump(
                mode="json"
            ),
        )


    # 5. PostgreSQL EXPLAIN preflight
    stage_start = perf_counter()

    preflight = preflight_sql(
        generated.sql
    )

    latency_ms["preflight"] = (
        perf_counter() - stage_start
    ) * 1000


    if not preflight.passed:

        latency_ms["total"] = (
            perf_counter() - pipeline_start
        ) * 1000

        audit = build_audit_record(
            question=question,
            analysis=analysis,
            explanation_generated=False,
            generated_sql=generated.sql,
            sql_validation_passed=True,
            preflight_passed=False,
            prompt_versions=prompt_versions,
            latency_ms=latency_ms,
            error=preflight.error,
        )

        return ControlledPipelineResult(
            status="PREFLIGHT_FAILED",
            answer=None,
            clarification_question=None,

            analysis=analysis.model_dump(
                mode="json"
            ),

            sql_plan=sql_plan.model_dump(
                mode="json"
            ),

            generated_sql=generated.sql,

            validation_passed=True,
            preflight_passed=False,
            execution_success=None,

            result_columns=[],
            result_rows=[],

            diagnostics=None,
            response_context=None,
            explanation=None,

            audit=audit.model_dump(
                mode="json"
            ),
        )


    # 6. Controlled read-only execution
    stage_start = perf_counter()

    execution = execute_read_only_sql(
        generated.sql
    )

    latency_ms["execution"] = (
        perf_counter() - stage_start
    ) * 1000


    # 7. Deterministic result diagnostics
    stage_start = perf_counter()

    diagnostics = diagnose_result(
        execution
    )

    latency_ms["diagnostics"] = (
        perf_counter() - stage_start
    ) * 1000


    if (
        not execution.success
        or not diagnostics.safe_to_explain
    ):

        latency_ms["total"] = (
            perf_counter() - pipeline_start
        ) * 1000

        audit = build_audit_record(
            question=question,
            analysis=analysis,
            execution=execution,
            diagnostics=diagnostics,
            explanation_generated=False,
            generated_sql=generated.sql,
            sql_validation_passed=True,
            preflight_passed=True,
            prompt_versions=prompt_versions,
            latency_ms=latency_ms,
        )

        failure_status = (
            "EXECUTION_FAILED"
            if not execution.success
            else "RESULT_DIAGNOSTICS_FAILED"
        )

        return ControlledPipelineResult(
            status=failure_status,
            answer=None,
            clarification_question=None,

            analysis=analysis.model_dump(
                mode="json"
            ),

            sql_plan=sql_plan.model_dump(
                mode="json"
            ),

            generated_sql=generated.sql,

            validation_passed=True,
            preflight_passed=True,
            execution_success=execution.success,

            result_columns=execution.columns,
            result_rows=execution.rows,

            diagnostics=diagnostics.model_dump(
                mode="json"
            ),

            response_context=None,
            explanation=None,

            audit=audit.model_dump(
                mode="json"
            ),
        )


    # 8. Collect assumptions, defaults and warnings
    response_context = build_response_context(
        analysis,
        diagnostics,
    )


    # 9. Generate grounded business explanation
    stage_start = perf_counter()

    explanation = explain_result(
        question,
        analysis,
        execution,
        diagnostics,
    )

    latency_ms["explanation"] = (
        perf_counter() - stage_start
    ) * 1000


    latency_ms["total"] = (
        perf_counter() - pipeline_start
    ) * 1000


    # 10. Create final audit record
    audit = build_audit_record(
        question=question,
        analysis=analysis,
        execution=execution,
        diagnostics=diagnostics,
        explanation_generated=True,
        generated_sql=generated.sql,
        sql_validation_passed=True,
        preflight_passed=True,
        prompt_versions=prompt_versions,
        latency_ms=latency_ms,
    )


    return ControlledPipelineResult(
        status="SUCCESS",
        answer=explanation.answer,
        clarification_question=None,

        analysis=analysis.model_dump(
            mode="json"
        ),

        sql_plan=sql_plan.model_dump(
            mode="json"
        ),

        generated_sql=generated.sql,

        validation_passed=True,
        preflight_passed=True,
        execution_success=True,

        result_columns=execution.columns,
        result_rows=execution.rows,

        diagnostics=diagnostics.model_dump(
            mode="json"
        ),

        response_context=response_context.model_dump(
            mode="json"
        ),

        explanation=explanation.model_dump(
            mode="json"
        ),

        audit=audit.model_dump(
            mode="json"
        ),
    )