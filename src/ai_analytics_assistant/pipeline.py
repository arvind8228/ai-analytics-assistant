from collections.abc import Callable
from time import perf_counter

from pydantic import BaseModel, ConfigDict

from .question_analyzer import (
    QUESTION_ANALYZER_VERSION,
    analyze_question,
)

from .sql_planner import (
    SQL_GENERATOR_VERSION,
    SQL_PLANNER_VERSION,
    SQL_REPAIR_VERSION,
    create_sql_plan,
    generate_sql,
    repair_sql,
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
    stream_explain_result,
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
    stream_explanation: bool = False,
    on_explanation_delta: Callable[[str], None] | None = None,
) -> ControlledPipelineResult:

    pipeline_start = perf_counter()

    latency_ms = {}

    prompt_versions = {
        "question_analyzer": QUESTION_ANALYZER_VERSION,
        "sql_planner": SQL_PLANNER_VERSION,
        "sql_generator": SQL_GENERATOR_VERSION,
        "sql_repair": SQL_REPAIR_VERSION,
        "business_explanation": EXPLANATION_VERSION,
    }

    repair_attempted = False


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
            repair_attempted=False,
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

    active_sql = generated.sql


    # 4. Deterministic SQL validation
    stage_start = perf_counter()

    validation = validate_sql(
        active_sql
    )

    latency_ms["sql_validation"] = (
        perf_counter() - stage_start
    ) * 1000


    # One bounded repair attempt for validation failure
    if not validation.is_valid:

        repair_attempted = True

        failure_details = "; ".join(
            validation.errors
        )

        stage_start = perf_counter()

        repaired = repair_sql(
            plan=sql_plan,
            failed_sql=active_sql,
            failure_stage="VALIDATION",
            failure_details=failure_details,
        )

        latency_ms["sql_repair"] = (
            perf_counter() - stage_start
        ) * 1000

        active_sql = repaired.sql

        stage_start = perf_counter()

        validation = validate_sql(
            active_sql
        )

        latency_ms["sql_revalidation"] = (
            perf_counter() - stage_start
        ) * 1000


    # Stop if validation still fails after one repair
    if not validation.is_valid:

        latency_ms["total"] = (
            perf_counter() - pipeline_start
        ) * 1000

        error = (
            "SQL failed deterministic validation"
        )

        if repair_attempted:
            error += " after one repair attempt"

        error += ": " + "; ".join(
            validation.errors
        )

        audit = build_audit_record(
            question=question,
            analysis=analysis,
            explanation_generated=False,
            generated_sql=active_sql,
            sql_validation_passed=False,
            prompt_versions=prompt_versions,
            latency_ms=latency_ms,
            repair_attempted=repair_attempted,
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
            generated_sql=active_sql,
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
        active_sql
    )

    latency_ms["preflight"] = (
        perf_counter() - stage_start
    ) * 1000


    # One bounded repair attempt for preflight failure,
    # only when repair has not already been attempted
    if (
        not preflight.passed
        and not repair_attempted
    ):

        repair_attempted = True

        stage_start = perf_counter()

        repaired = repair_sql(
            plan=sql_plan,
            failed_sql=active_sql,
            failure_stage="PREFLIGHT",
            failure_details=str(
                preflight.error
            ),
        )

        latency_ms["sql_repair"] = (
            perf_counter() - stage_start
        ) * 1000

        active_sql = repaired.sql


        # Repaired SQL must pass validation again
        stage_start = perf_counter()

        validation = validate_sql(
            active_sql
        )

        latency_ms["sql_revalidation"] = (
            perf_counter() - stage_start
        ) * 1000


        if validation.is_valid:

            stage_start = perf_counter()

            preflight = preflight_sql(
                active_sql
            )

            latency_ms[
                "repair_preflight"
            ] = (
                perf_counter() - stage_start
            ) * 1000

        else:

            latency_ms["total"] = (
                perf_counter() - pipeline_start
            ) * 1000

            error = (
                "Repaired SQL failed deterministic "
                "validation: "
                + "; ".join(
                    validation.errors
                )
            )

            audit = build_audit_record(
                question=question,
                analysis=analysis,
                explanation_generated=False,
                generated_sql=active_sql,
                sql_validation_passed=False,
                preflight_passed=False,
                prompt_versions=prompt_versions,
                latency_ms=latency_ms,
                repair_attempted=True,
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
                generated_sql=active_sql,
                validation_passed=False,
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


    # Stop if preflight still fails
    if not preflight.passed:

        latency_ms["total"] = (
            perf_counter() - pipeline_start
        ) * 1000

        error = str(
            preflight.error
        )

        if repair_attempted:
            error = (
                "SQL failed PostgreSQL preflight "
                "after one repair attempt: "
                + error
            )

        audit = build_audit_record(
            question=question,
            analysis=analysis,
            explanation_generated=False,
            generated_sql=active_sql,
            sql_validation_passed=True,
            preflight_passed=False,
            prompt_versions=prompt_versions,
            latency_ms=latency_ms,
            repair_attempted=repair_attempted,
            error=error,
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
            generated_sql=active_sql,
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
        active_sql
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
            generated_sql=active_sql,
            sql_validation_passed=True,
            preflight_passed=True,
            prompt_versions=prompt_versions,
            latency_ms=latency_ms,
            repair_attempted=repair_attempted,
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
            generated_sql=active_sql,
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


    # 9. Generate grounded business explanation.
    # Streaming is optional and only begins after every
    # upstream control has passed.
    stage_start = perf_counter()

    if stream_explanation:
        explanation = stream_explain_result(
            question,
            analysis,
            execution,
            diagnostics,
            on_delta=on_explanation_delta,
        )

    else:
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
        generated_sql=active_sql,
        sql_validation_passed=True,
        preflight_passed=True,
        prompt_versions=prompt_versions,
        latency_ms=latency_ms,
        repair_attempted=repair_attempted,
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
        generated_sql=active_sql,
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
