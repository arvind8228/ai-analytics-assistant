import json
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from ai_analytics_assistant.pipeline import (
    run_controlled_pipeline,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(
    PROJECT_ROOT / ".env"
)



def load_ui_settings() -> dict:
    with open(
        PROJECT_ROOT
        / "config"
        / "project_settings.json",
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


PROJECT_SETTINGS = load_ui_settings()

CURRENCY_SETTINGS = (
    PROJECT_SETTINGS.get(
        "currency",
        {}
    )
)

CURRENCY_SYMBOL = (
    CURRENCY_SETTINGS.get(
        "symbol",
        "₹",
    )
)

CURRENCY_DECIMALS = int(
    CURRENCY_SETTINGS.get(
        "decimal_places",
        2,
    )
)


def is_currency_column(
    column_name: str,
) -> bool:
    normalized = (
        column_name
        .lower()
        .strip()
        .replace(" ", "_")
    )

    currency_terms = (
        "revenue",
        "sales",
        "discount",
        "refund",
        "price",
        "cost",
        "order_value",
        "aov",
    )

    non_currency_terms = (
        "count",
        "quantity",
        "units",
        "rate",
        "percent",
        "percentage",
        "pct",
        "_id",
    )

    return (
        any(
            term in normalized
            for term in currency_terms
        )
        and not any(
            term in normalized
            for term in non_currency_terms
        )
    )


def format_currency_value(
    value,
) -> str:
    if pd.isna(value):
        return "—"

    return (
        f"{CURRENCY_SYMBOL}"
        f"{float(value):,.{CURRENCY_DECIMALS}f}"
    )


def format_latency(
    milliseconds: float,
) -> str:
    if milliseconds >= 1000:
        return f"{milliseconds / 1000:.2f} s"

    return f"{milliseconds:.1f} ms"


EXAMPLE_QUESTIONS = {
    "clear": {
        "title": "Clear question",
        "question": (
            "What was net revenue by store in July 2026?"
        ),
        "badge": "Answerable",
        "color": "green",
        "icon": ":material/check_circle:",
    },
    "clarification": {
        "title": "Needs clarification",
        "question": (
            "Show me our best customers last month."
        ),
        "badge": "Ambiguous",
        "color": "orange",
        "icon": ":material/help:",
    },
    "unsupported": {
        "title": "Unsupported question",
        "question": (
            "Why did sales decrease in the South region?"
        ),
        "badge": "Unsupported",
        "color": "gray",
        "icon": ":material/block:",
    },
    "unsafe": {
        "title": "Unsafe request",
        "question": (
            "Delete all cancelled orders."
        ),
        "badge": "Rejected",
        "color": "red",
        "icon": ":material/shield:",
    },
}


SUCCESS_STATUSES = {
    "SUCCESS",
}

STOP_STATUSES = {
    "NEEDS_CLARIFICATION",
    "UNANSWERABLE",
    "REJECTED_UNSAFE",
}

FAILURE_STATUSES = {
    "SQL_VALIDATION_FAILED",
    "PREFLIGHT_FAILED",
    "EXECUTION_FAILED",
    "RESULT_DIAGNOSTICS_FAILED",
}


def get_clarification_question(
    result: dict,
) -> str | None:
    """
    Read the clarification question from the pipeline
    result without assuming it exists at only one level.
    """
    top_level_question = result.get(
        "clarification_question"
    )

    if top_level_question:
        return top_level_question

    analysis = (
        result.get("analysis")
        or {}
    )

    return analysis.get(
        "clarification_question"
    )


def build_clarified_pipeline_question(
    pending_clarification: dict,
    user_answer: str,
) -> tuple[str, list[dict]]:
    """
    Rebuild the original business request with every
    clarification answer supplied so far.

    This gives the controlled pipeline the full business
    context without introducing general conversational
    memory.
    """
    clarification_history = list(
        pending_clarification.get(
            "clarifications"
        )
        or []
    )

    current_clarification = (
        pending_clarification.get(
            "clarification_question"
        )
    )

    if current_clarification:
        clarification_history.append(
            {
                "question": (
                    current_clarification
                ),
                "answer": user_answer,
            }
        )

    original_question = (
        pending_clarification[
            "original_question"
        ]
    )

    lines = [
        "Original business question:",
        original_question,
        "",
        "User-provided clarification context:",
    ]

    for index, clarification in enumerate(
        clarification_history,
        start=1,
    ):
        lines.append(
            (
                f"{index}. Clarification asked: "
                f"{clarification['question']}"
            )
        )

        lines.append(
            (
                "   User answer: "
                f"{clarification['answer']}"
            )
        )

    lines.extend(
        [
            "",
            (
                "Treat these clarification answers as "
                "part of the original business request."
            ),
            (
                "Use them only to resolve the stated "
                "ambiguities, and do not treat a short "
                "clarification answer as a separate "
                "business question."
            ),
        ]
    )

    return (
        "\n".join(lines),
        clarification_history,
    )


def render_system_header():
    st.title(
        "AI Analytics Assistant"
    )

    st.markdown(
        """
        Ask business questions in natural language while keeping
        interpretation, SQL generation, and database execution
        controlled.
        """
    )

    status_column, control_column, database_column = (
        st.columns(3)
    )

    with status_column:
        st.badge(
            "System ready",
            icon=":material/check_circle:",
            color="green",
            width="stretch",
            help=(
                "The Streamlit application and controlled "
                "analytics pipeline are available."
            ),
        )

    with control_column:
        st.badge(
            "Controlled decision layer",
            icon=":material/shield:",
            color="violet",
            width="stretch",
            help=(
                "Every question is classified before "
                "SQL generation is allowed."
            ),
        )

    with database_column:
        st.badge(
            "Read-only database access",
            icon=":material/database:",
            color="blue",
            width="stretch",
            help=(
                "Approved SQL passes deterministic safety "
                "checks before PostgreSQL execution."
            ),
        )


def render_examples():
    st.subheader(
        "Try the controlled assistant"
    )

    st.caption(
        "These examples exercise the four main "
        "decision paths in the system."
    )

    left_column, right_column = (
        st.columns(2)
    )

    selected_question = None

    with left_column:
        selected = render_example_card(
            "clear"
        )

        if selected:
            selected_question = selected

        selected = render_example_card(
            "clarification"
        )

        if selected:
            selected_question = selected

    with right_column:
        selected = render_example_card(
            "unsupported"
        )

        if selected:
            selected_question = selected

        selected = render_example_card(
            "unsafe"
        )

        if selected:
            selected_question = selected

    return selected_question


def render_example_card(
    example_key: str,
):
    example = (
        EXAMPLE_QUESTIONS[
            example_key
        ]
    )

    with st.container(
        border=True,
    ):
        st.badge(
            example["badge"],
            icon=example["icon"],
            color=example["color"],
        )

        st.markdown(
            f"**{example['title']}**"
        )

        st.write(
            example["question"]
        )

        if st.button(
            "Run example",
            key=(
                f"example_{example_key}"
            ),
            icon=":material/play_arrow:",
            width="stretch",
        ):
            return example["question"]

    return None


def render_pipeline_trace(
    result: dict,
):
    audit = (
        result.get("audit")
        or {}
    )

    latency = (
        audit.get("latency_ms")
        or {}
    )

    total_latency = (
        latency.get("total")
    )

    expander_label = (
        "Execution trace"
    )

    if total_latency is not None:
        expander_label += (
            f" · {total_latency / 1000:.2f}s"
        )

    with st.expander(
        expander_label,
        icon=":material/account_tree:",
        expanded=False,
    ):
        st.caption(
            "Stage timings for this controlled pipeline run."
        )

        trace_rows = []

        stage_labels = {
            "question_analysis": (
                "Question analysis"
            ),
            "sql_planning": (
                "Structured SQL planning"
            ),
            "sql_generation": (
                "SQL generation"
            ),
            "sql_validation": (
                "Deterministic validation"
            ),
            "sql_repair": (
                "Bounded SQL repair"
            ),
            "sql_revalidation": (
                "SQL revalidation"
            ),
            "preflight": (
                "PostgreSQL preflight"
            ),
            "repair_preflight": (
                "Repair preflight"
            ),
            "execution": (
                "Read-only execution"
            ),
            "diagnostics": (
                "Result diagnostics"
            ),
            "explanation": (
                "Business explanation"
            ),
        }

        for key, label in (
            stage_labels.items()
        ):
            if key in latency:
                trace_rows.append(
                    {
                        "Stage": label,
                        "Latency": format_latency(
                            latency[key]
                        ),
                    }
                )

        if trace_rows:
            st.dataframe(
                trace_rows,
                width="stretch",
                hide_index=True,
            )

        if audit.get(
            "repair_attempted"
        ):
            st.badge(
                "One bounded SQL repair attempted",
                icon=":material/build:",
                color="orange",
            )

        prompt_versions = (
            audit.get(
                "prompt_versions"
            )
            or {}
        )

        if prompt_versions:
            with st.popover(
                "Developer details"
            ):
                st.caption(
                    "Versioned model/prompt components "
                    "used for this run."
                )

                st.json(
                    prompt_versions,
                    expanded=True,
                )

def render_control_summary(
    result: dict,
):
    validation_passed = (
        result.get(
            "validation_passed"
        )
    )

    preflight_passed = (
        result.get(
            "preflight_passed"
        )
    )

    execution_success = (
        result.get(
            "execution_success"
        )
    )

    controls = [
        (
            "AST validated",
            validation_passed,
            ":material/verified:",
        ),
        (
            "EXPLAIN passed",
            preflight_passed,
            ":material/fact_check:",
        ),
        (
            "Read-only execution",
            execution_success,
            ":material/database:",
        ),
    ]

    columns = st.columns(
        len(controls)
    )

    for column, (
        label,
        passed,
        icon,
    ) in zip(
        columns,
        controls,
    ):
        with column:
            if passed is True:
                st.badge(
                    label,
                    icon=icon,
                    color="green",
                    width="stretch",
                )

            elif passed is False:
                st.badge(
                    f"{label} failed",
                    icon=":material/error:",
                    color="red",
                    width="stretch",
                )

            else:
                st.badge(
                    f"{label} not run",
                    icon=":material/remove:",
                    color="gray",
                    width="stretch",
                )


def render_sql(
    result: dict,
):
    generated_sql = (
        result.get(
            "generated_sql"
        )
    )

    if not generated_sql:
        return

    with st.expander(
        "Generated SQL",
        icon=":material/code:",
        expanded=False,
    ):
        st.code(
            generated_sql,
            language="sql",
        )

        st.caption(
            "Shown for transparency. Execution is still "
            "restricted by deterministic validation, "
            "PostgreSQL preflight, and read-only access."
        )

def render_context(
    result: dict,
):
    context = (
        result.get(
            "response_context"
        )
        or {}
    )

    analysis = (
        result.get("analysis")
        or {}
    )

    assumptions = (
        context.get(
            "assumptions"
        )
        or analysis.get(
            "assumptions"
        )
        or []
    )

    defaults = (
        context.get(
            "defaults_applied"
        )
        or analysis.get(
            "defaults_applied"
        )
        or []
    )

    warnings = (
        context.get(
            "warnings"
        )
        or []
    )

    if not (
        assumptions
        or defaults
        or warnings
    ):
        return

    with st.expander(
        "Assumptions and warnings",
        icon=":material/info:",
    ):
        if defaults:
            st.markdown(
                "**Documented defaults**"
            )

            for item in defaults:
                st.markdown(
                    f"- {item}"
                )

        if assumptions:
            st.markdown(
                "**Assumptions**"
            )

            for item in assumptions:
                st.markdown(
                    f"- {item}"
                )

        if warnings:
            st.markdown(
                "**Warnings**"
            )

            for item in warnings:
                st.markdown(
                    f"- {item}"
                )


def render_result_table(
    result: dict,
):
    rows = (
        result.get(
            "result_rows"
        )
        or []
    )

    columns = (
        result.get(
            "result_columns"
        )
        or []
    )

    if not columns:
        return

    st.markdown(
        "**Query result**"
    )

    dataframe = pd.DataFrame(
        rows,
        columns=columns,
    )

    display_dataframe = (
        dataframe.copy()
    )

    for column in (
        display_dataframe.columns
    ):
        if is_currency_column(
            str(column)
        ):
            numeric_values = pd.to_numeric(
                display_dataframe[
                    column
                ],
                errors="coerce",
            )

            if numeric_values.notna().any():
                display_dataframe[
                    column
                ] = numeric_values.map(
                    format_currency_value
                )

    st.dataframe(
        display_dataframe,
        width="stretch",
        hide_index=True,
        height="auto",
    )

    diagnostics = (
        result.get(
            "diagnostics"
        )
        or {}
    )

    if diagnostics.get(
        "result_truncated"
    ):
        st.warning(
            "Only the first configured result rows "
            "are displayed."
        )

def render_success(
    result: dict,
    show_answer: bool = True,
    show_status: bool = True,
):
    if show_status:
        st.badge(
            "Answerable",
            icon=":material/check_circle:",
            color="green",
        )

    answer = (
        result.get("answer")
        or "The query completed successfully."
    )

    if show_answer:
        st.markdown(
            "**Business answer**"
        )

        st.markdown(
            answer
        )

    render_control_summary(
        result
    )

    render_result_table(
        result
    )

    render_sql(
        result
    )

    render_context(
        result
    )

    render_pipeline_trace(
        result
    )

def render_clarification(
    result: dict,
):
    st.badge(
        "Needs clarification",
        icon=":material/help:",
        color="orange",
    )

    question = (
        get_clarification_question(
            result
        )
        or (
            "More information is needed "
            "before SQL can be generated."
        )
    )

    st.warning(
        question
    )

    st.caption(
        "Reply in the chat box below. "
        "Your answer will continue the original question."
    )

    analysis = (
        result.get("analysis")
        or {}
    )

    reason = (
        analysis.get("reason")
    )

    if reason:
        st.caption(
            reason
        )

    st.badge(
        "No SQL generated",
        icon=":material/block:",
        color="gray",
    )

    with st.expander(
        "Decision details",
        icon=":material/psychology:",
    ):
        st.write(
            "Reason code:",
            analysis.get(
                "reason_code"
            ),
        )

        ambiguities = (
            analysis.get(
                "material_ambiguities"
            )
            or []
        )

        if ambiguities:
            st.markdown(
                "**Material ambiguities**"
            )

            for ambiguity in ambiguities:
                st.markdown(
                    f"- {ambiguity}"
                )


def render_unanswerable(
    result: dict,
):
    st.badge(
        "Unsupported",
        icon=":material/block:",
        color="orange",
    )

    analysis = (
        result.get("analysis")
        or {}
    )

    reason = (
        analysis.get("reason")
        or (
            "The requested answer cannot be "
            "supported by the available data "
            "or system capabilities."
        )
    )

    st.info(
        reason
    )

    missing_information = (
        analysis.get(
            "missing_information"
        )
        or []
    )

    if missing_information:
        with st.expander(
            "Why this cannot be answered",
            icon=":material/info:",
        ):
            for item in (
                missing_information
            ):
                st.markdown(
                    f"- {item}"
                )

    st.badge(
        "Stopped before SQL",
        icon=":material/shield:",
        color="gray",
    )


def render_rejected(
    result: dict,
):
    st.badge(
        "Rejected unsafe request",
        icon=":material/security:",
        color="red",
    )

    analysis = (
        result.get("analysis")
        or {}
    )

    reason = (
        analysis.get("reason")
        or (
            "The request was rejected by "
            "the safety layer."
        )
    )

    st.error(
        reason
    )

    st.badge(
        "Database not touched",
        icon=":material/database_off:",
        color="green",
    )

    with st.expander(
        "Safety decision",
        icon=":material/shield:",
    ):
        st.write(
            "Reason code:",
            analysis.get(
                "reason_code"
            ),
        )

        st.write(
            "No SQL was generated or executed."
        )


def render_pipeline_failure(
    result: dict,
):
    st.badge(
        "Pipeline stopped safely",
        icon=":material/error:",
        color="red",
    )

    st.error(
        "The controlled pipeline stopped before "
        "producing a business answer."
    )

    audit = (
        result.get("audit")
        or {}
    )

    error = (
        audit.get("error")
    )

    if error:
        with st.expander(
            "Technical details",
            icon=":material/bug_report:",
        ):
            st.code(
                error,
                language=None,
            )

    render_sql(
        result
    )

    render_pipeline_trace(
        result
    )


def render_assistant_result(
    result: dict,
    show_answer: bool = True,
    show_status: bool = True,
):
    status = (
        result.get("status")
    )

    if status in SUCCESS_STATUSES:
        render_success(
            result,
            show_answer=show_answer,
            show_status=show_status,
        )

    elif status == (
        "NEEDS_CLARIFICATION"
    ):
        render_clarification(
            result
        )

    elif status == "UNANSWERABLE":
        render_unanswerable(
            result
        )

    elif status == (
        "REJECTED_UNSAFE"
    ):
        render_rejected(
            result
        )

    elif status in FAILURE_STATUSES:
        render_pipeline_failure(
            result
        )

    else:
        st.error(
            "The pipeline returned an "
            "unexpected status."
        )

        st.code(
            str(status),
            language=None,
        )

def run_question(
    question: str,
    stream_explanation: bool = False,
):
    """
    Run the controlled analytics pipeline.

    When streaming is enabled, only the final business
    explanation is streamed. Question analysis, SQL planning,
    SQL generation, validation, PostgreSQL preflight,
    read-only execution and deterministic diagnostics all
    complete before the first answer token is shown.
    """
    pipeline_status = st.status(
        "Running controlled analytics pipeline...",
        expanded=True,
    )

    with pipeline_status:
        st.write(
            "Applying the question gate, "
            "structured planning, SQL safety, "
            "and controlled execution."
        )

    answer_status_placeholder = (
        st.empty()
        if stream_explanation
        else None
    )

    answer_heading_placeholder = (
        st.empty()
        if stream_explanation
        else None
    )

    answer_placeholder = (
        st.empty()
        if stream_explanation
        else None
    )

    streamed_answer = ""
    stream_started = False

    def on_explanation_delta(
        delta: str,
    ):
        nonlocal streamed_answer
        nonlocal stream_started

        streamed_answer += delta

        if not stream_started:
            stream_started = True

            if answer_status_placeholder is not None:
                answer_status_placeholder.badge(
                    "Answerable",
                    icon=":material/check_circle:",
                    color="green",
                )

            if answer_heading_placeholder is not None:
                answer_heading_placeholder.markdown(
                    "**Business answer**"
                )

        if answer_placeholder is not None:
            answer_placeholder.markdown(
                streamed_answer + "▌"
            )

    try:
        pipeline_result = (
            run_controlled_pipeline(
                question,
                stream_explanation=(
                    stream_explanation
                ),
                on_explanation_delta=(
                    on_explanation_delta
                    if stream_explanation
                    else None
                ),
            )
        )

    except Exception as exc:
        if answer_status_placeholder is not None:
            answer_status_placeholder.empty()

        if answer_heading_placeholder is not None:
            answer_heading_placeholder.empty()

        if answer_placeholder is not None:
            answer_placeholder.empty()

        pipeline_status.update(
            label=(
                "Pipeline could not "
                "complete"
            ),
            state="error",
            expanded=True,
        )

        st.error(
            "The request could not be completed."
        )

        with st.expander(
            "Technical details"
        ):
            st.code(
                (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                language=None,
            )

        return None

    result = (
        pipeline_result.model_dump(
            mode="json"
        )
    )

    status = (
        result.get("status")
    )

    if (
        answer_placeholder is not None
        and status == "SUCCESS"
    ):
        answer_placeholder.markdown(
            result.get("answer")
            or streamed_answer
            or "The query completed successfully."
        )

    elif answer_placeholder is not None:
        if answer_status_placeholder is not None:
            answer_status_placeholder.empty()

        if answer_heading_placeholder is not None:
            answer_heading_placeholder.empty()

        answer_placeholder.empty()

    if status == "SUCCESS":
        with pipeline_status:
            st.write(
                "Question approved."
            )

            st.write(
                "SQL validation passed."
            )

            st.write(
                "PostgreSQL preflight passed."
            )

            st.write(
                "Read-only execution completed."
            )

            if stream_explanation:
                st.write(
                    "Final business response streamed."
                )

        pipeline_status.update(
            label=(
                "Controlled analysis complete"
            ),
            state="complete",
            expanded=False,
        )

    elif status in STOP_STATUSES:
        with pipeline_status:
            st.write(
                "Question gate completed."
            )

            st.write(
                "The request was stopped "
                "before SQL execution."
            )

        pipeline_status.update(
            label=(
                "Stopped safely before SQL"
            ),
            state="complete",
            expanded=False,
        )

    else:
        pipeline_status.update(
            label=(
                "Pipeline stopped safely"
            ),
            state="error",
            expanded=True,
        )

    return result

def set_pending_clarification(
    result: dict,
    original_question: str,
    clarification_history: list[dict],
):
    clarification_question = (
        get_clarification_question(
            result
        )
    )

    if not clarification_question:
        raise ValueError(
            "Pipeline requested clarification "
            "without a clarification question."
        )

    st.session_state[
        "pending_clarification"
    ] = {
        "original_question": (
            original_question
        ),
        "clarifications": (
            clarification_history
        ),
        "clarification_question": (
            clarification_question
        ),
    }


render_system_header()


if "analytics_history" not in (
    st.session_state
):
    st.session_state[
        "analytics_history"
    ] = []


if "pending_clarification" not in (
    st.session_state
):
    st.session_state[
        "pending_clarification"
    ] = None


top_left, top_right = st.columns(
    [5, 1]
)

with top_left:
    st.subheader(
        "Ask a business question"
    )

with top_right:
    if (
        st.session_state[
            "analytics_history"
        ]
        or st.session_state[
            "pending_clarification"
        ]
    ):
        if st.button(
            "Clear",
            icon=":material/delete_sweep:",
            width="stretch",
        ):
            st.session_state[
                "analytics_history"
            ] = []

            st.session_state[
                "pending_clarification"
            ] = None

            st.rerun()


history = (
    st.session_state[
        "analytics_history"
    ]
)

pending_clarification = (
    st.session_state[
        "pending_clarification"
    ]
)


if pending_clarification:
    st.info(
        "A clarification is pending. "
        "Reply below to continue the original "
        "business question."
    )

    if st.button(
        "Cancel clarification",
        icon=":material/close:",
    ):
        st.session_state[
            "pending_clarification"
        ] = None

        st.rerun()


if not history:
    if pending_clarification:
        example_question = None
    else:
        example_question = (
            render_examples()
        )

elif pending_clarification:
    example_question = None

else:
    with st.expander(
        "Try another example",
        icon=":material/lightbulb:",
    ):
        example_question = (
            render_examples()
        )


for item in history:
    with st.chat_message(
        "user"
    ):
        st.markdown(
            item["question"]
        )

    with st.chat_message(
        "assistant"
    ):
        render_assistant_result(
            item["result"],
            show_answer=True,
            show_status=True,
        )


chat_placeholder = (
    "Answer the clarification..."
    if pending_clarification
    else "Ask a business question..."
)


typed_question = st.chat_input(
    chat_placeholder
)


submitted_question = (
    typed_question
    or example_question
)


if submitted_question:
    submitted_question = (
        submitted_question.strip()
    )

    if submitted_question:
        display_question = (
            submitted_question
        )

        clarification_history = []

        if pending_clarification:
            (
                pipeline_question,
                clarification_history,
            ) = build_clarified_pipeline_question(
                pending_clarification,
                display_question,
            )

            original_question = (
                pending_clarification[
                    "original_question"
                ]
            )

        else:
            pipeline_question = (
                display_question
            )

            original_question = (
                display_question
            )

        with st.chat_message(
            "user"
        ):
            st.markdown(
                display_question
            )

        with st.chat_message(
            "assistant"
        ):
            result = run_question(
                pipeline_question,
                stream_explanation=True,
            )

            if result is not None:
                is_success = (
                    result.get("status")
                    == "SUCCESS"
                )

                render_assistant_result(
                    result,
                    show_answer=not is_success,
                    show_status=not is_success,
                )

        if result is not None:
            st.session_state[
                "analytics_history"
            ].append(
                {
                    "question": (
                        display_question
                    ),
                    "result": result,
                }
            )

            if (
                result.get("status")
                == "NEEDS_CLARIFICATION"
            ):
                set_pending_clarification(
                    result=result,
                    original_question=(
                        original_question
                    ),
                    clarification_history=(
                        clarification_history
                    ),
                )

                st.rerun()

            else:
                st.session_state[
                    "pending_clarification"
                ] = None
