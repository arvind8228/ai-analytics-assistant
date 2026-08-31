from ai_analytics_assistant.sql_safety import validate_sql


def test_normal_select_is_allowed():
    result = validate_sql(
        """
        SELECT COUNT(*)
        FROM orders
        WHERE order_status = 'completed'
        """
    )

    assert result.is_valid is True
    assert result.errors == []


def test_safe_aggregate_query_is_allowed():
    result = validate_sql(
        """
        SELECT
            DATE_TRUNC('month', order_date),
            COUNT(*)
        FROM orders
        GROUP BY DATE_TRUNC('month', order_date)
        """
    )

    assert result.is_valid is True


def test_safe_cte_is_allowed():
    result = validate_sql(
        """
        WITH completed_orders AS (
            SELECT order_id
            FROM orders
            WHERE order_status = 'completed'
        )
        SELECT COUNT(*)
        FROM completed_orders
        """
    )

    assert result.is_valid is True


def test_delete_is_rejected():
    result = validate_sql(
        "DELETE FROM orders"
    )

    assert result.is_valid is False

    assert any(
        "Delete" in error
        for error in result.errors
    )


def test_multiple_statements_are_rejected():
    result = validate_sql(
        """
        SELECT * FROM orders;
        SELECT * FROM customers;
        """
    )

    assert result.is_valid is False

    assert (
        "Exactly one SQL statement is allowed."
        in result.errors
    )


def test_unapproved_table_is_rejected():
    result = validate_sql(
        "SELECT * FROM secret_table"
    )

    assert result.is_valid is False

    assert any(
        "Table is not allowed" in error
        for error in result.errors
    )


def test_unapproved_schema_is_rejected():
    result = validate_sql(
        "SELECT * FROM pg_catalog.pg_tables"
    )

    assert result.is_valid is False

    assert any(
        "Schema is not allowed" in error
        for error in result.errors
    )


def test_pg_sleep_is_rejected():
    result = validate_sql(
        "SELECT pg_sleep(10)"
    )

    assert result.is_valid is False

    assert any(
        "pg_sleep" in error
        for error in result.errors
    )


def test_pg_read_file_is_rejected():
    result = validate_sql(
        "SELECT pg_read_file('/etc/passwd')"
    )

    assert result.is_valid is False

    assert any(
        "pg_read_file" in error
        for error in result.errors
    )


def test_pg_ls_dir_is_rejected():
    result = validate_sql(
        "SELECT pg_ls_dir('.')"
    )

    assert result.is_valid is False

    assert any(
        "pg_ls_dir" in error
        for error in result.errors
    )


def test_pg_terminate_backend_is_rejected():
    result = validate_sql(
        "SELECT pg_terminate_backend(123)"
    )

    assert result.is_valid is False

    assert any(
        "pg_terminate_backend" in error
        for error in result.errors
    )


def test_advisory_lock_is_rejected():
    result = validate_sql(
        "SELECT pg_advisory_lock(123)"
    )

    assert result.is_valid is False

    assert any(
        "pg_advisory_lock" in error
        for error in result.errors
    )


def test_current_database_is_allowed():
    result = validate_sql(
        "SELECT current_database()"
    )

    assert result.is_valid is True