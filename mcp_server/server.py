import datetime
import decimal

from mcp.server.fastmcp import FastMCP

import db
from sql_guard import QueryRejected, validate_select

mcp = FastMCP("olist-warehouse")


def _jsonify(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    return value


@mcp.tool()
def get_schema() -> dict:
    """Returns the full Olist star schema read live from information_schema:
    every public table with its columns (name, type, nullable, default),
    primary key, and foreign keys (column -> referenced table.column)."""
    with db.read_only_cursor() as cur:
        return _jsonify(db.fetch_schema(cur))


@mcp.tool()
def run_query(sql: str) -> dict:
    """Executes a read-only SQL query against the Olist warehouse (public schema
    only) and returns the result rows. Only a single SELECT (or WITH ... SELECT)
    statement is allowed — no writes, no DDL, no multi-statement queries. Results
    are capped at 1000 rows; check the `truncated` flag in the response."""
    try:
        validated = validate_select(sql)
    except QueryRejected as e:
        return {"error": str(e)}
    result = db.run_read_only_query(validated)
    return _jsonify(result)


@mcp.tool()
def sample_rows(table_name: str, n: int = 10) -> dict:
    """Returns the first N rows (default 10, max 100) of a table in the public
    schema. table_name is validated against information_schema before use."""
    try:
        result = db.sample_table_rows(table_name, n)
    except ValueError as e:
        return {"error": str(e)}
    return _jsonify(result)


if __name__ == "__main__":
    mcp.run()
