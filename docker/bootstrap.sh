#!/bin/bash
# Entrypoint shared by both the webserver and MCP containers (see docker-compose.yml).
# Migrations/admin-user/init/database-registration only run in "webserver" mode so
# the two containers don't race writes against the shared SQLite metadata DB.
set -euo pipefail

MODE="$1"

if [ "$MODE" = "webserver" ]; then
  superset db upgrade

  superset fab create-admin \
    --username "$SUPERSET_ADMIN_USERNAME" \
    --firstname Superset \
    --lastname Admin \
    --email admin@example.com \
    --password "$SUPERSET_ADMIN_PASSWORD" || true

  superset init

  # Register the Supabase warehouse using the read-only olist_reader role —
  # Superset only ever reads, so it should never hold write credentials.
  ENCODED_PW="$(python -c "import urllib.parse,os;print(urllib.parse.quote(os.environ['MCP_POSTGRES_PASSWORD']))")"
  superset set-database-uri \
    -d "olist_warehouse" \
    -u "postgresql+psycopg2://${MCP_POSTGRES_USER}:${ENCODED_PW}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DATABASE}"

  exec superset run -h 0.0.0.0 -p 8088 --with-threads
elif [ "$MODE" = "mcp" ]; then
  exec superset mcp run --host 0.0.0.0 --port 5008
else
  echo "Unknown mode: $MODE (expected 'webserver' or 'mcp')" >&2
  exit 1
fi
