import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# Single-user student demo, but SQLite can't hold up here: superset-mcp writes
# on every chart/dashboard creation while superset (webserver) is also writing,
# and two processes against one SQLite file hit "database is locked" under any
# concurrency. A local postgres:16 container for metadata only — separate from
# the Olist warehouse on Supabase — avoids that for one extra minimal service.
SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{os.environ['SUPERSET_DB_USER']}:"
    f"{os.environ['SUPERSET_DB_PASSWORD']}@{os.environ['SUPERSET_DB_HOST']}:"
    f"{os.environ['SUPERSET_DB_PORT']}/{os.environ['SUPERSET_DB_NAME']}"
)

# MCP service, local-dev auth mode: no JWT, every call is impersonated as this
# fixed, pre-existing Superset user. Fine for a single-user demo that never
# leaves localhost; do not run this way on anything internet-facing.
MCP_AUTH_ENABLED = False
MCP_DEV_USERNAME = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
MCP_SERVICE_HOST = "0.0.0.0"
MCP_SERVICE_PORT = 5008
