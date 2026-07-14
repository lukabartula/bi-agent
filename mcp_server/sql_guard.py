import re

# Statements a read-only tool must never execute, even inside a CTE
# (e.g. `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x`).
_FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "GRANT", "REVOKE", "COPY", "CALL", "VACUUM", "REFRESH",
    "LISTEN", "NOTIFY", "SECURITY",
)
_FORBIDDEN_RE = re.compile(
    r"\b(" + "|".join(_FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE
)

# `DO $$ ... $$` anonymous code blocks can run arbitrary procedural SQL.
_DO_BLOCK_RE = re.compile(r"\bDO\b", re.IGNORECASE)

# Restricted to the public schema; metadata questions should go through get_schema.
_OTHER_SCHEMA_RE = re.compile(r"\b(information_schema|pg_catalog|pg_\w+)\.", re.IGNORECASE)

_LEADING_RE = re.compile(r"^\s*(--[^\n]*\n|/\*.*?\*/\s*)*", re.DOTALL)
_STARTS_WITH_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


class QueryRejected(ValueError):
    """Raised when a query fails the read-only pre-filter."""


def validate_select(sql: str) -> str:
    """Rejects anything that isn't a single, plain SELECT/WITH read against the
    public schema. This is a fast-fail pre-filter for clear error messages —
    the authoritative enforcement is the read-only Postgres session/transaction
    set up in db.py, which rejects writes even if this filter has a gap.
    """
    if not sql or not sql.strip():
        raise QueryRejected("Empty query.")

    stripped = sql.strip()

    # Allow one optional trailing semicolon, but reject stacked statements.
    body = stripped[:-1] if stripped.endswith(";") else stripped
    if ";" in body:
        raise QueryRejected("Only a single SQL statement is allowed (no semicolons inside the query).")

    without_leading_comments = _LEADING_RE.sub("", body)
    if not _STARTS_WITH_RE.match(without_leading_comments):
        raise QueryRejected("Only SELECT (or WITH ... SELECT) statements are allowed.")

    if _DO_BLOCK_RE.search(body):
        raise QueryRejected("DO blocks are not allowed.")

    forbidden = _FORBIDDEN_RE.search(body)
    if forbidden:
        raise QueryRejected(f"Forbidden keyword in query: {forbidden.group(0).upper()}.")

    if _OTHER_SCHEMA_RE.search(body):
        raise QueryRejected(
            "Queries are restricted to the public schema. "
            "Use get_schema for table/column/key metadata."
        )

    return body
