import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import sql
from dotenv import load_dotenv

load_dotenv()

STATEMENT_TIMEOUT_MS = 15_000
MAX_QUERY_ROWS = 1000
MAX_SAMPLE_ROWS = 100


def _connect():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DATABASE"],
        user=os.environ["MCP_POSTGRES_USER"],
        password=os.environ["MCP_POSTGRES_PASSWORD"],
    )


@contextmanager
def read_only_cursor():
    """Yields a cursor on a connection whose session is set read-only at the
    Postgres level. This is the authoritative safety boundary: Postgres itself
    raises ReadOnlySqlTransaction for any write, regardless of what sql_guard
    did or didn't catch in the query text.
    """
    conn = _connect()
    try:
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
        cur.execute("SET search_path TO public")
        yield cur
        cur.close()
    finally:
        conn.close()


def list_public_tables(cur) -> list[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    return [row["table_name"] for row in cur.fetchall()]


def fetch_schema(cur) -> dict:
    """Live introspection of the public schema: columns, primary keys, foreign keys."""
    cur.execute(
        """
        SELECT table_name, column_name, data_type, is_nullable, column_default, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """
    )
    columns_by_table: dict[str, list[dict]] = {}
    for row in cur.fetchall():
        columns_by_table.setdefault(row["table_name"], []).append(
            {
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"] == "YES",
                "default": row["column_default"],
            }
        )

    # pg_catalog, not information_schema: table_constraints/key_column_usage are
    # privilege-filtered and return nothing for a SELECT-only role like the MCP
    # read-only user. pg_constraint has no such filtering.
    cur.execute(
        """
        SELECT
            con.conrelid::regclass::text AS table_name,
            att.attname AS column_name
        FROM pg_constraint con
        JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS u(attnum, ord) ON true
        JOIN pg_attribute att
          ON att.attrelid = con.conrelid AND att.attnum = u.attnum
        WHERE con.contype = 'p' AND con.connamespace = 'public'::regnamespace
        ORDER BY table_name, u.ord
        """
    )
    pk_by_table: dict[str, list[str]] = {}
    for row in cur.fetchall():
        pk_by_table.setdefault(row["table_name"], []).append(row["column_name"])

    cur.execute(
        """
        SELECT
            con.conrelid::regclass::text AS table_name,
            att.attname AS column_name,
            con.confrelid::regclass::text AS references_table,
            fatt.attname AS references_column
        FROM pg_constraint con
        JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS u(attnum, ord) ON true
        JOIN pg_attribute att
          ON att.attrelid = con.conrelid AND att.attnum = u.attnum
        JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS fu(attnum, ord) ON fu.ord = u.ord
        JOIN pg_attribute fatt
          ON fatt.attrelid = con.confrelid AND fatt.attnum = fu.attnum
        WHERE con.contype = 'f' AND con.connamespace = 'public'::regnamespace
        ORDER BY table_name, column_name
        """
    )
    fk_by_table: dict[str, list[dict]] = {}
    for row in cur.fetchall():
        fk_by_table.setdefault(row["table_name"], []).append(
            {
                "column": row["column_name"],
                "references_table": row["references_table"],
                "references_column": row["references_column"],
            }
        )

    schema = {}
    for table_name, columns in columns_by_table.items():
        schema[table_name] = {
            "columns": columns,
            "primary_key": pk_by_table.get(table_name, []),
            "foreign_keys": fk_by_table.get(table_name, []),
        }
    return schema


def run_read_only_query(validated_sql: str) -> dict:
    with read_only_cursor() as cur:
        cur.execute(validated_sql)
        rows = cur.fetchmany(MAX_QUERY_ROWS + 1)
        truncated = len(rows) > MAX_QUERY_ROWS
        rows = rows[:MAX_QUERY_ROWS]
        columns = [d.name for d in cur.description] if cur.description else []
        return {
            "columns": columns,
            "rows": [dict(r) for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }


def sample_table_rows(table_name: str, n: int) -> dict:
    n = max(1, min(n, MAX_SAMPLE_ROWS))
    with read_only_cursor() as cur:
        valid_tables = list_public_tables(cur)
        if table_name not in valid_tables:
            raise ValueError(
                f"Unknown table '{table_name}'. Known tables: {', '.join(valid_tables)}"
            )

        query = sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
            sql.Identifier("public"), sql.Identifier(table_name)
        )
        cur.execute(query, (n,))
        rows = cur.fetchall()
        columns = [d.name for d in cur.description] if cur.description else []
        return {
            "table": table_name,
            "columns": columns,
            "rows": [dict(r) for r in rows],
            "row_count": len(rows),
        }
