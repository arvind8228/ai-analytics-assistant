import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from openai import OpenAI

from ai_analytics_assistant.database import (
    get_db_connection,
    get_schema_context
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

GLOSSARY_PATH = (
    PROJECT_ROOT
    / "config"
    / "business_glossary.json"
)

SETTINGS_PATH = (
    PROJECT_ROOT
    / "config"
    / "project_settings.json"
)

BASELINE_LOG_PATH = (
    PROJECT_ROOT
    / "evaluation"
    / "day2_baseline_runs.jsonl"
)


NAIVE_PROMPT_VERSION = "naive_sql_v1"

MAX_RESULT_ROWS = 200
DB_STATEMENT_TIMEOUT = "5s"
DB_LOCK_TIMEOUT = "2s"


def load_project_context():
    with open(GLOSSARY_PATH, "r") as file:
        business_glossary = json.load(file)

    with open(SETTINGS_PATH, "r") as file:
        project_settings = json.load(file)

    analysis_reference_date = (
        project_settings["date_range"]
        ["analysis_reference_date"]
    )

    return (
        business_glossary,
        analysis_reference_date
    )


def build_baseline_instructions(
    schema_context,
    business_glossary,
    analysis_reference_date
):
    business_context = json.dumps(
        business_glossary,
        indent=2
    )

    return f"""
You are a PostgreSQL analyst.

Convert the user's business question directly into one PostgreSQL SELECT query.

Use only the tables, columns, relationships and constraints provided below.
Use exact database values when they are known.
Use the documented business definitions when a term has a defined meaning.

The analysis reference date is:
{analysis_reference_date}

Interpret relative dates such as "last month", "this year",
and "previous quarter" relative to this reference date.

Return only SQL.
Do not use Markdown.
Do not explain the query.
Do not generate INSERT, UPDATE, DELETE, DROP, ALTER,
TRUNCATE, CREATE or other write operations.

Database schema:

{schema_context}

Business glossary:

{business_context}
""".strip()


def run_baseline(
    question,
    case_id=None,
    category=None,
    save_log=True
):
    run_id = str(uuid.uuid4())

    generated_sql = None
    result = None
    execution_error = None

    execution_success = False
    result_truncated = False

    input_tokens = None
    output_tokens = None
    request_id = None

    llm_latency_ms = None
    database_latency_ms = None

    schema_context = get_schema_context()

    (
        business_glossary,
        analysis_reference_date
    ) = load_project_context()

    instructions = build_baseline_instructions(
        schema_context,
        business_glossary,
        analysis_reference_date
    )

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        timeout=20.0,
        max_retries=2
    )

    total_start = time.perf_counter()

    try:
        llm_start = time.perf_counter()

        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL"),
            instructions=instructions,
            input=question,
            store=False
        )

        llm_latency_ms = round(
            (
                time.perf_counter()
                - llm_start
            )
            * 1000,
            2
        )

        generated_sql = response.output_text.strip()

        request_id = getattr(
            response,
            "_request_id",
            None
        )

        if response.usage is not None:
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens


        db_start = time.perf_counter()

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    "SET TRANSACTION READ ONLY;"
                )

                cur.execute(
                    f"""
                    SET LOCAL statement_timeout =
                    '{DB_STATEMENT_TIMEOUT}';
                    """
                )

                cur.execute(
                    f"""
                    SET LOCAL lock_timeout =
                    '{DB_LOCK_TIMEOUT}';
                    """
                )

                cur.execute(generated_sql)

                if cur.description is None:
                    raise ValueError(
                        "Query did not return a result set."
                    )

                column_names = [
                    column.name
                    for column in cur.description
                ]

                rows = cur.fetchmany(
                    MAX_RESULT_ROWS + 1
                )

                if len(rows) > MAX_RESULT_ROWS:
                    result_truncated = True
                    rows = rows[:MAX_RESULT_ROWS]


        database_latency_ms = round(
            (
                time.perf_counter()
                - db_start
            )
            * 1000,
            2
        )

        result = pd.DataFrame(
            rows,
            columns=column_names
        )

        execution_success = True


    except Exception as error:
        execution_error = str(error)


    total_latency_ms = round(
        (
            time.perf_counter()
            - total_start
        )
        * 1000,
        2
    )


    log_record = {
        "run_id": run_id,
        "case_id": case_id,
        "category": category,
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),

        "prompt_version": NAIVE_PROMPT_VERSION,
        "model": os.getenv("OPENAI_MODEL"),
        "question": question,
        "generated_sql": generated_sql,

        "execution_success": execution_success,
        "execution_error": execution_error,

        "rows_returned": (
            len(result)
            if result is not None
            else None
        ),

        "result_truncated": result_truncated,

        "input_tokens": input_tokens,
        "output_tokens": output_tokens,

        "llm_latency_ms": llm_latency_ms,
        "database_latency_ms": database_latency_ms,
        "total_latency_ms": total_latency_ms,

        "openai_request_id": request_id
    }


    if save_log:
        BASELINE_LOG_PATH.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with open(
            BASELINE_LOG_PATH,
            "a"
        ) as file:

            file.write(
                json.dumps(log_record)
                + "\n"
            )


    return {
        "sql": generated_sql,
        "result": result,
        "log": log_record
    }
