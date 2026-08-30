from sqlglot import exp
import sqlglot

from pydantic import BaseModel, ConfigDict

from .database import get_db_connection


ALLOWED_TABLES = {
    "customers",
    "stores",
    "categories",
    "products",
    "orders",
    "order_items",
    "payments",
    "returns",
    "promotions",
}


FORBIDDEN_SQL_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Copy,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Into,
    exp.Lock,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)


PREFLIGHT_STATEMENT_TIMEOUT_MS = 5000
PREFLIGHT_LOCK_TIMEOUT_MS = 2000

EXECUTION_STATEMENT_TIMEOUT_MS = 5000
EXECUTION_LOCK_TIMEOUT_MS = 2000

MAX_RESULT_ROWS = 200


class SQLValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    statement_type: str | None
    tables: list[str]
    columns: list[str]
    errors: list[str]


class SQLPreflightResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    plan_lines: list[str]
    error: str | None


class SQLExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    columns: list[str]
    rows: list[list]
    rows_returned: int
    result_truncated: bool
    error: str | None


def validate_sql(
    sql: str,
) -> SQLValidationResult:
    errors = []

    try:
        statements = [
            statement
            for statement in sqlglot.parse(
                sql,
                dialect="postgres",
            )
            if statement is not None
        ]

    except sqlglot.errors.ParseError as exc:
        return SQLValidationResult(
            is_valid=False,
            statement_type=None,
            tables=[],
            columns=[],
            errors=[
                f"SQL parsing failed: {exc}"
            ],
        )

    # Exactly one statement is allowed
    if len(statements) != 1:
        return SQLValidationResult(
            is_valid=False,
            statement_type=None,
            tables=[],
            columns=[],
            errors=[
                "Exactly one SQL statement is allowed."
            ],
        )

    tree = statements[0]

    statement_type = type(tree).__name__

    # V1 only allows SELECT queries
    if not isinstance(tree, exp.Select):
        errors.append(
            "Only SELECT queries are allowed."
        )

    # Reject forbidden operations anywhere in the AST
    for forbidden_type in FORBIDDEN_SQL_NODES:
        if tree.find(forbidden_type):
            errors.append(
                f"Forbidden SQL operation detected: "
                f"{forbidden_type.__name__}."
            )

    # Collect CTE names so they are not mistaken
    # for physical database tables
    cte_names = {
        cte.alias_or_name
        for cte in tree.find_all(exp.CTE)
    }

    database_tables = []

    for table in tree.find_all(exp.Table):
        table_name = table.name
        schema_name = table.db

        # References to CTEs are allowed
        if (
            table_name in cte_names
            and not schema_name
        ):
            continue

        database_tables.append(
            table_name
        )

        # V1 only allows the controlled public schema
        if (
            schema_name
            and schema_name != "public"
        ):
            errors.append(
                f"Schema is not allowed: "
                f"{schema_name}."
            )

        # Only approved ecommerce tables are allowed
        if table_name not in ALLOWED_TABLES:
            errors.append(
                f"Table is not allowed: "
                f"{table_name}."
            )

    tables = sorted(
        set(database_tables)
    )

    columns = sorted(
        {
            column.sql(
                dialect="postgres"
            )
            for column in tree.find_all(exp.Column)
        }
    )

    return SQLValidationResult(
        is_valid=not errors,
        statement_type=statement_type,
        tables=tables,
        columns=columns,
        errors=errors,
    )


def preflight_sql(
    sql: str,
) -> SQLPreflightResult:

    # Do not allow PostgreSQL preflight to bypass
    # deterministic SQL validation
    validation = validate_sql(sql)

    if not validation.is_valid:
        return SQLPreflightResult(
            passed=False,
            plan_lines=[],
            error=(
                "SQL failed deterministic validation: "
                + "; ".join(validation.errors)
            ),
        )

    try:
        with get_db_connection() as connection:

            with connection.cursor() as cursor:

                # Defence-in-depth at the transaction level
                cursor.execute(
                    "SET TRANSACTION READ ONLY"
                )

                # Apply statement timeout only to this transaction
                cursor.execute(
                    """
                    SELECT set_config(
                        'statement_timeout',
                        %s,
                        true
                    )
                    """,
                    (
                        f"{PREFLIGHT_STATEMENT_TIMEOUT_MS}ms",
                    ),
                )

                # Limit time spent waiting for locks
                cursor.execute(
                    """
                    SELECT set_config(
                        'lock_timeout',
                        %s,
                        true
                    )
                    """,
                    (
                        f"{PREFLIGHT_LOCK_TIMEOUT_MS}ms",
                    ),
                )

                # EXPLAIN creates a query plan
                # without executing the business query
                cursor.execute(
                    "EXPLAIN " + sql
                )

                rows = cursor.fetchall()

                plan_lines = [
                    row[0]
                    for row in rows
                ]

        return SQLPreflightResult(
            passed=True,
            plan_lines=plan_lines,
            error=None,
        )

    except Exception as exc:
        return SQLPreflightResult(
            passed=False,
            plan_lines=[],
            error=str(exc),
        )


def execute_read_only_sql(
    sql: str,
) -> SQLExecutionResult:

    # Layer 1: deterministic AST validation
    validation = validate_sql(sql)

    if not validation.is_valid:
        return SQLExecutionResult(
            success=False,
            columns=[],
            rows=[],
            rows_returned=0,
            result_truncated=False,
            error=(
                "SQL failed deterministic validation: "
                + "; ".join(validation.errors)
            ),
        )

    # Layer 2: PostgreSQL planning
    preflight = preflight_sql(sql)

    if not preflight.passed:
        return SQLExecutionResult(
            success=False,
            columns=[],
            rows=[],
            rows_returned=0,
            result_truncated=False,
            error=(
                "SQL failed PostgreSQL preflight: "
                + str(preflight.error)
            ),
        )

    try:
        with get_db_connection() as connection:

            with connection.cursor() as cursor:

                # Layer 3: database-level read-only protection
                cursor.execute(
                    "SET TRANSACTION READ ONLY"
                )

                # Limit query execution time
                cursor.execute(
                    """
                    SELECT set_config(
                        'statement_timeout',
                        %s,
                        true
                    )
                    """,
                    (
                        f"{EXECUTION_STATEMENT_TIMEOUT_MS}ms",
                    ),
                )

                # Limit lock waiting time
                cursor.execute(
                    """
                    SELECT set_config(
                        'lock_timeout',
                        %s,
                        true
                    )
                    """,
                    (
                        f"{EXECUTION_LOCK_TIMEOUT_MS}ms",
                    ),
                )

                # Execute only after every previous layer passed
                cursor.execute(sql)

                columns = [
                    column.name
                    for column in cursor.description
                ]

                # Fetch one extra row so we know whether
                # the returned result was truncated
                fetched_rows = cursor.fetchmany(
                    MAX_RESULT_ROWS + 1
                )

                result_truncated = (
                    len(fetched_rows)
                    > MAX_RESULT_ROWS
                )

                rows = [
                    list(row)
                    for row in fetched_rows[
                        :MAX_RESULT_ROWS
                    ]
                ]

        return SQLExecutionResult(
            success=True,
            columns=columns,
            rows=rows,
            rows_returned=len(rows),
            result_truncated=result_truncated,
            error=None,
        )

    except Exception as exc:
        return SQLExecutionResult(
            success=False,
            columns=[],
            rows=[],
            rows_returned=0,
            result_truncated=False,
            error=str(exc),
        )