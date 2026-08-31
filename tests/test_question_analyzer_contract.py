import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_analytics_assistant.question_analyzer import (
    QuestionAnalysis,
    QuestionStatus,
    ReasonCode,
    build_metric_clarification,
    canonical_metric_name,
    eligible_clarification_metrics,
    enforce_semantic_contract,
    normalize_contract_name,
    normalize_entity,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def business_glossary():
    with open(
        PROJECT_ROOT
        / "config"
        / "business_glossary.json",
        "r",
    ) as file:
        return json.load(file)


@pytest.fixture
def project_settings():
    with open(
        PROJECT_ROOT
        / "config"
        / "project_settings.json",
        "r",
    ) as file:
        return json.load(file)


def make_analysis(
    *,
    status=QuestionStatus.ANSWERABLE,
    reason_code=ReasonCode.CLEAR_QUESTION,
    requested_metric="gross_sales",
    requested_entity="product",
    time_period="July 2026",
    material_ambiguities=None,
    missing_information=None,
    clarification_question=None,
):
    return QuestionAnalysis(
        status=status,
        reason_code=reason_code,
        reason="Test analysis.",
        requested_metric=requested_metric,
        requested_entity=requested_entity,
        time_period=time_period,
        grouping=None,
        ranking=None,
        filters=[],
        assumptions=[],
        defaults_applied=[],
        material_ambiguities=(
            material_ambiguities
            if material_ambiguities is not None
            else []
        ),
        missing_information=(
            missing_information
            if missing_information is not None
            else []
        ),
        evidence=[],
        clarification_question=clarification_question,
    )


def test_normalize_contract_name():
    assert (
        normalize_contract_name(
            "  Gross__Units-Sold  "
        )
        == "gross units sold"
    )


def test_canonical_metric_name_for_gross_units_sold(
    business_glossary,
):
    assert (
        canonical_metric_name(
            "Gross Units Sold",
            business_glossary,
        )
        == "gross_units_sold"
    )


def test_normalize_entity_alias():
    assert normalize_entity("Categories") == "category"


def test_product_clarification_metrics_follow_contract(
    business_glossary,
):
    metrics = eligible_clarification_metrics(
        business_glossary,
        "products",
    )

    assert metrics == [
        "net_revenue",
        "gross_sales",
        "gross_units_sold",
    ]


def test_product_clarification_does_not_offer_invalid_metrics(
    business_glossary,
):
    metrics = eligible_clarification_metrics(
        business_glossary,
        "products",
    )

    question = build_metric_clarification(
        "products",
        metrics,
    )

    assert "net revenue" in question
    assert "gross sales" in question
    assert "gross units sold" in question

    assert "average order value" not in question
    assert "completed order count" not in question


def test_product_average_order_value_is_rejected(
    business_glossary,
    project_settings,
):
    analysis = make_analysis(
        requested_metric="average order value",
        requested_entity="products",
    )

    result = enforce_semantic_contract(
        "Show average order value by product in July 2026.",
        analysis,
        business_glossary,
        project_settings,
    )

    assert result.status == QuestionStatus.UNANSWERABLE
    assert (
        result.reason_code
        == ReasonCode.MISSING_CAPABILITY
    )
    assert result.clarification_question is None
    assert result.material_ambiguities == []
    assert result.missing_information


def test_return_rate_is_not_a_controlled_v1_metric(
    business_glossary,
    project_settings,
):
    analysis = make_analysis(
        requested_metric="return rate",
        requested_entity="product",
    )

    result = enforce_semantic_contract(
        "Show return rate by product in July 2026.",
        analysis,
        business_glossary,
        project_settings,
    )

    assert result.status == QuestionStatus.UNANSWERABLE
    assert (
        result.reason_code
        == ReasonCode.MISSING_CAPABILITY
    )
    assert result.clarification_question is None
    assert result.missing_information


def test_recently_requires_time_clarification(
    business_glossary,
    project_settings,
):
    analysis = make_analysis(
        requested_metric="gross_sales",
        requested_entity="product",
        time_period="recently",
    )

    result = enforce_semantic_contract(
        "Show gross sales by product recently.",
        analysis,
        business_glossary,
        project_settings,
    )

    assert (
        result.status
        == QuestionStatus.NEEDS_CLARIFICATION
    )
    assert (
        result.reason_code
        == ReasonCode.AMBIGUOUS_TIME_PERIOD
    )
    assert result.clarification_question is not None
    assert "recently" in (
        result.clarification_question.lower()
    )


def test_resolved_recently_does_not_trigger_again(
    business_glossary,
    project_settings,
):
    analysis = make_analysis(
        requested_metric="gross_sales",
        requested_entity="product",
        time_period="July 2026",
    )

    question = """
Original question:
Show gross sales by product recently.

User-provided clarification context:
Clarification asked: What time period should 'recently' represent?
User answer: July 2026
""".strip()

    result = enforce_semantic_contract(
        question,
        analysis,
        business_glossary,
        project_settings,
    )

    assert result.status == QuestionStatus.ANSWERABLE
    assert result.reason_code == ReasonCode.CLEAR_QUESTION
    assert result.material_ambiguities == []
    assert result.clarification_question is None


def test_question_analysis_rejects_inconsistent_answerable_state():
    with pytest.raises(ValidationError):
        make_analysis(
            status=QuestionStatus.ANSWERABLE,
            reason_code=ReasonCode.CLEAR_QUESTION,
            material_ambiguities=[
                "The metric is unresolved."
            ],
        )
