import json
import os
from enum import Enum
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, model_validator

from .database import get_schema_context
from .question_analyzer import (
    QuestionAnalysis,
    QuestionStatus,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SQL_PLANNER_VERSION = "sql_planner_v2"
SQL_GENERATOR_VERSION = "sql_generator_v2"
SQL_REPAIR_VERSION = "sql_repair_v1"


class JoinType(str, Enum):
    INNER = "INNER"
    LEFT = "LEFT"


class FilterOperator(str, Enum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    IN = "IN"
    NOT_IN = "NOT_IN"
    BETWEEN = "BETWEEN"
    IS_NULL = "IS_NULL"
    IS_NOT_NULL = "IS_NOT_NULL"


class SortDirection(str, Enum):
    ASC = "ASC"
    DESC = "DESC"


class SQLJoin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_table: str
    right_table: str
    left_column: str
    right_column: str
    join_type: JoinType


class SQLFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    operator: FilterOperator
    values: list[str]

    @model_validator(mode="after")
    def validate_filter(self):
        null_operators = {
            FilterOperator.IS_NULL,
            FilterOperator.IS_NOT_NULL,
        }

        scalar_operators = {
            FilterOperator.EQ,
            FilterOperator.NE,
            FilterOperator.GT,
            FilterOperator.GTE,
            FilterOperator.LT,
            FilterOperator.LTE,
        }

        if self.operator in null_operators:
            if self.values:
                raise ValueError(
                    "NULL filters must not contain values."
                )

        elif self.operator == FilterOperator.BETWEEN:
            if len(self.values) != 2:
                raise ValueError(
                    "BETWEEN requires exactly two values."
                )

        elif self.operator in scalar_operators:
            if len(self.values) != 1:
                raise ValueError(
                    "Scalar filters require exactly one value."
                )

        elif not self.values:
            raise ValueError(
                "IN and NOT_IN require at least one value."
            )

        return self


class SQLOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    direction: SortDirection


class SQLTimePeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    start_date: str
    end_date: str


class SQLPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str

    metric: str | None
    entity: str | None

    required_tables: list[str]
    joins: list[SQLJoin]
    filters: list[SQLFilter]

    dimensions: list[str]
    group_by: list[str]
    order_by: list[SQLOrder]
    limit: int | None

    time_period: SQLTimePeriod | None

    assumptions: list[str]

    @model_validator(mode="after")
    def validate_plan(self):
        if not self.required_tables:
            raise ValueError(
                "SQLPlan requires at least one table."
            )

        if self.limit is not None and self.limit < 1:
            raise ValueError(
                "SQLPlan limit must be greater than zero."
            )

        return self


class GeneratedSQL(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str


def load_sql_context():
    schema_context = get_schema_context()

    with open(
        PROJECT_ROOT / "config" / "business_glossary.json",
        "r",
    ) as file:
        business_glossary = json.load(file)

    return schema_context, business_glossary


def create_sql_plan(
    question: str,
    analysis: QuestionAnalysis,
) -> SQLPlan:

    if analysis.status != QuestionStatus.ANSWERABLE:
        raise ValueError(
            "SQL planning is only allowed for "
            "ANSWERABLE questions."
        )

    schema_context, business_glossary = (
        load_sql_context()
    )

    instructions = f"""
You are the SQL planning layer of an AI analytics assistant.

Your task is to convert an APPROVED business-question analysis into
a structured SQL plan.

Do NOT generate SQL.

The plan will later be passed to a separate SQL generator and
deterministic SQL validator.


PLANNING RULES

1. APPROVED ANALYSIS

Treat the supplied question analysis as the approved business
interpretation.

Do not reclassify the question.

Do not introduce a new interpretation that conflicts with the
approved analysis.


2. DATABASE SCHEMA

Use only tables and columns that exist in the supplied PostgreSQL
schema.

Do not invent:
- tables
- columns
- relationships
- status values


3. BUSINESS METRICS

Use the documented business glossary when planning metrics.

Preserve the documented business meaning of metrics such as:
- net_revenue
- gross_sales
- discount_amount
- refund_amount
- order_count
- average_order_value


4. TABLES

required_tables must contain every table required to answer the
question and no unrelated tables.


5. JOINS

Create joins only when multiple tables are required.

Every join must correspond to a real relationship in the supplied
schema.

Prefer the smallest set of joins required to answer the question.


6. FILTERS

Represent non-date restrictions using structured filters.

Examples include:
- completed order status
- store
- category
- product
- region


7. TIME PERIODS

When the approved analysis contains a concrete date range,
represent it using SQLTimePeriod.

Use the actual database date column that should enforce the period.

Do not duplicate the same date restriction inside filters.


8. GROUPING

Use dimensions and group_by only when the requested answer requires
results split by an entity or category.

Do not add grouping to a question asking for one aggregate value.


9. ORDERING

Use order_by only when ordering is required.

For ranking requests, preserve the approved ranking direction.


10. LIMITS

Use the approved or harmless-default result limit for ranking
requests when appropriate.

Do not add a limit to a single aggregate result unless needed.


11. ASSUMPTIONS

Do not introduce unnecessary assumptions.

If the approved analysis already resolved a documented default,
preserve that interpretation rather than recording it again as a
new planning assumption.


12. NEGATIVE EXISTENCE AND ABSENCE

Some questions ask for entities for which no related record satisfies
a set of conditions.

Examples include:
- products with no completed sales in a period
- customers with no returns
- stores without completed orders
- entities that never had a matching related event

For these questions:

- make the absence requirement explicit in objective
- include the parent and related tables in required_tables
- include the real relationships needed to test existence
- use filters and time_period to define exactly which related records
  would disqualify the parent entity

The joins list describes the relationships needed to evaluate the
condition. It does not require the SQL generator to express every
relationship as a top-level JOIN.

Do not plan absence logic that can keep a parent entity merely because
it has some unrelated or non-matching child rows.

The intended meaning must be:

return the parent entity only when no related row exists that satisfies
all of the disqualifying conditions.


13. SAFETY

This planner is strictly read-only.

Never create a plan for:
- INSERT
- UPDATE
- DELETE
- DROP
- ALTER
- CREATE
- TRUNCATE
- database administration


DATABASE SCHEMA

{schema_context}


BUSINESS GLOSSARY

{json.dumps(business_glossary, indent=2)}
""".strip()

    approved_context = {
        "user_question": question,
        "approved_analysis": analysis.model_dump(
            mode="json"
        ),
    }

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=20.0,
        max_retries=2,
    )

    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL"),
        instructions=instructions,
        input=json.dumps(
            approved_context,
            indent=2,
        ),
        text_format=SQLPlan,
        store=False,
    )

    if response.output_parsed is None:
        raise ValueError(
            "SQL planner returned no parsed output."
        )

    return response.output_parsed


def generate_sql(
    plan: SQLPlan,
) -> GeneratedSQL:

    schema_context, business_glossary = (
        load_sql_context()
    )

    instructions = f"""
You are the PostgreSQL generation layer of an AI analytics assistant.

Your only task is to translate an APPROVED structured SQL plan into
one PostgreSQL read-only query.

Do not reinterpret the original business question.

Follow the structured plan exactly.


GENERATION RULES

1. POSTGRESQL

Generate PostgreSQL syntax only.


2. READ-ONLY QUERY

Generate exactly one read-only query.

Allowed top-level forms:
- SELECT
- WITH ... SELECT

Never generate:
- INSERT
- UPDATE
- DELETE
- DROP
- ALTER
- CREATE
- TRUNCATE
- MERGE
- CALL
- COPY
- transaction commands
- administrative commands


3. APPROVED PLAN

Use the structured SQL plan as the source of truth.

Do not:
- add new business assumptions
- change the requested metric
- change the requested filters
- change the requested time period
- introduce unrelated tables


4. DATABASE SCHEMA

Use only tables and columns that exist in the supplied schema.

Do not invent schema objects.


5. BUSINESS METRICS

Follow the documented business glossary exactly.

Preserve documented definitions for metrics such as:
- net_revenue
- gross_sales
- discount_amount
- refund_amount
- order_count
- average_order_value


6. JOINS

Use only joins required by the approved plan.

Use real relationships from the database schema.


7. NEGATIVE EXISTENCE AND ANTI-JOIN LOGIC

When the approved plan asks for entities that have no related records
matching a condition, implement the absence test safely.

Prefer a correlated NOT EXISTS subquery.

The NOT EXISTS subquery must contain all conditions that define the
disqualifying related record, including relevant:
- status filters
- date filters
- entity relationships
- other approved restrictions

Example pattern:

SELECT parent_columns
FROM parent_table AS p
WHERE NOT EXISTS (
    SELECT 1
    FROM child_table AS c
    WHERE c.parent_id = p.parent_id
      AND matching_conditions
);

Do not implement multi-level absence logic using a chain of LEFT JOINs
followed only by:

WHERE final_child.id IS NULL

when the same parent can have both matching and non-matching related
rows.

That pattern can incorrectly retain a parent because one unrelated
child row fails to match even though another child row satisfies the
condition.

A LEFT JOIN anti-join is acceptable only when the right-hand relation
has already been restricted to exactly the records whose existence
would disqualify the parent.

For absence questions, the joins in the structured plan describe the
required relationships. They do not force those relationships to
appear as top-level joins if a correlated NOT EXISTS expression is
semantically safer.


8. FILTERS

Translate structured filters into PostgreSQL predicates.

Preserve documented values exactly, including lowercase status
values such as 'completed' and 'cancelled'.


9. TIME PERIODS

Use the approved start and end dates exactly.

For DATE columns, use an inclusive date range unless the plan
specifies otherwise.


10. AGGREGATION

Use aggregation, GROUP BY and ordering only when required by
the plan.

For order_count, preserve the documented meaning of distinct
completed orders.


11. RESULT LIMIT

Apply LIMIT only when the approved plan contains a limit.


12. OUTPUT

Return only the structured GeneratedSQL response.

The sql field must contain exactly one PostgreSQL query.

Do not include:
- Markdown fences
- explanations
- comments
- alternative queries


DATABASE SCHEMA

{schema_context}


BUSINESS GLOSSARY

{json.dumps(business_glossary, indent=2)}
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
            plan.model_dump(mode="json"),
            indent=2,
        ),
        text_format=GeneratedSQL,
        store=False,
    )

    if response.output_parsed is None:
        raise ValueError(
            "SQL generator returned no parsed output."
        )

    return response.output_parsed


def repair_sql(
    plan: SQLPlan,
    failed_sql: str,
    failure_stage: str,
    failure_details: str,
) -> GeneratedSQL:

    schema_context, business_glossary = (
        load_sql_context()
    )

    instructions = f"""
You are the bounded SQL repair layer of an AI analytics assistant.

A PostgreSQL query was generated from an APPROVED structured SQL plan,
but it failed deterministic SQL validation or PostgreSQL EXPLAIN
preflight.

Your task is to produce one corrected PostgreSQL query.

This is the ONLY repair attempt.


REPAIR RULES

1. APPROVED PLAN

The structured SQL plan remains the source of truth.

Do not:
- reinterpret the original business question
- change the requested metric
- change the requested filters
- change the requested time period
- introduce new business assumptions


2. FAILURE FEEDBACK

Use the supplied failed SQL, failure stage and failure details only to
correct the technical problem.

Do not weaken or bypass the safety controls that rejected the query.


3. READ ONLY

Return exactly one read-only PostgreSQL query.

Allowed top-level forms:
- SELECT
- WITH ... SELECT

Never generate:
- INSERT
- UPDATE
- DELETE
- DROP
- ALTER
- CREATE
- TRUNCATE
- MERGE
- CALL
- COPY
- transaction commands
- administrative commands


4. DATABASE SCHEMA

Use only tables and columns that exist in the supplied schema.

Do not invent schema objects.


5. BUSINESS DEFINITIONS

Preserve the documented business glossary exactly.


6. NEGATIVE EXISTENCE

When the approved plan requires entities for which no related row
matches a condition, prefer a correlated NOT EXISTS query.

All conditions that define the disqualifying related row must stay
inside the NOT EXISTS test.


7. OUTPUT

Return only the structured GeneratedSQL response.

The sql field must contain exactly one PostgreSQL query.

Do not include:
- Markdown
- explanations
- comments
- multiple alternatives


DATABASE SCHEMA

{schema_context}


BUSINESS GLOSSARY

{json.dumps(business_glossary, indent=2)}
""".strip()

    repair_context = {
        "approved_sql_plan": plan.model_dump(
            mode="json"
        ),
        "failed_sql": failed_sql,
        "failure_stage": failure_stage,
        "failure_details": failure_details,
    }

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=20.0,
        max_retries=2,
    )

    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL"),
        instructions=instructions,
        input=json.dumps(
            repair_context,
            indent=2,
        ),
        text_format=GeneratedSQL,
        store=False,
    )

    if response.output_parsed is None:
        raise ValueError(
            "SQL repair returned no parsed output."
        )

    return response.output_parsed