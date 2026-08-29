import os

import psycopg


def get_db_connection():
    return psycopg.connect(
        dbname=os.getenv("DB_NAME"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )


def get_schema_context():
    with get_db_connection() as conn:
        with conn.cursor() as cur:

            # Read tables, columns and data types
            cur.execute("""
                SELECT
                    table_name,
                    column_name,
                    data_type,
                    is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position;
            """)

            columns = cur.fetchall()


            # Read primary keys
            cur.execute("""
                SELECT
                    table_info.relname AS table_name,
                    column_info.attname AS column_name
                FROM pg_constraint constraint_info
                JOIN pg_class table_info
                    ON table_info.oid = constraint_info.conrelid
                JOIN pg_namespace schema_info
                    ON schema_info.oid = table_info.relnamespace
                JOIN unnest(constraint_info.conkey)
                    WITH ORDINALITY AS key_columns(attnum, position)
                    ON TRUE
                JOIN pg_attribute column_info
                    ON column_info.attrelid = table_info.oid
                    AND column_info.attnum = key_columns.attnum
                WHERE constraint_info.contype = 'p'
                  AND schema_info.nspname = 'public'
                ORDER BY table_info.relname;
            """)

            primary_keys = set(cur.fetchall())


            # Read foreign-key relationships
            cur.execute("""
                SELECT
                    source_table.relname AS table_name,
                    source_column.attname AS column_name,
                    target_table.relname AS referenced_table,
                    target_column.attname AS referenced_column
                FROM pg_constraint constraint_info
                JOIN pg_class source_table
                    ON source_table.oid = constraint_info.conrelid
                JOIN pg_namespace schema_info
                    ON schema_info.oid = source_table.relnamespace
                JOIN pg_class target_table
                    ON target_table.oid = constraint_info.confrelid

                JOIN unnest(constraint_info.conkey)
                    WITH ORDINALITY AS source_keys(attnum, position)
                    ON TRUE

                JOIN unnest(constraint_info.confkey)
                    WITH ORDINALITY AS target_keys(attnum, position)
                    ON target_keys.position = source_keys.position

                JOIN pg_attribute source_column
                    ON source_column.attrelid = source_table.oid
                    AND source_column.attnum = source_keys.attnum

                JOIN pg_attribute target_column
                    ON target_column.attrelid = target_table.oid
                    AND target_column.attnum = target_keys.attnum

                WHERE constraint_info.contype = 'f'
                  AND schema_info.nspname = 'public'

                ORDER BY source_table.relname, source_column.attname;
            """)

            foreign_keys = cur.fetchall()


            # Read CHECK constraints
            cur.execute("""
                SELECT
                    table_info.relname AS table_name,
                    pg_get_constraintdef(
                        constraint_info.oid,
                        true
                    ) AS constraint_definition
                FROM pg_constraint constraint_info
                JOIN pg_class table_info
                    ON table_info.oid = constraint_info.conrelid
                JOIN pg_namespace schema_info
                    ON schema_info.oid = table_info.relnamespace
                WHERE constraint_info.contype = 'c'
                  AND schema_info.nspname = 'public'
                ORDER BY table_info.relname;
            """)

            check_constraints = cur.fetchall()


    tables = {}

    for (
        table_name,
        column_name,
        data_type,
        is_nullable
    ) in columns:

        if table_name not in tables:
            tables[table_name] = []

        labels = []

        if (table_name, column_name) in primary_keys:
            labels.append("PK")

        if is_nullable == "NO":
            labels.append("NOT NULL")

        label_text = ""

        if labels:
            label_text = " [" + ", ".join(labels) + "]"

        tables[table_name].append(
            f"{column_name} ({data_type}){label_text}"
        )


    schema_lines = []

    for table_name, table_columns in tables.items():
        schema_lines.append(f"Table: {table_name}")

        for column in table_columns:
            schema_lines.append(f"  - {column}")

        schema_lines.append("")


    schema_lines.append("Foreign Keys:")

    for (
        table_name,
        column_name,
        referenced_table,
        referenced_column
    ) in foreign_keys:

        schema_lines.append(
            f"  - {table_name}.{column_name} "
            f"-> {referenced_table}.{referenced_column}"
        )


    schema_lines.append("")
    schema_lines.append("Check Constraints:")

    for (
        table_name,
        constraint_definition
    ) in check_constraints:

        schema_lines.append(
            f"  - {table_name}: {constraint_definition}"
        )


    return "\n".join(schema_lines)
