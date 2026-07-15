# Stock Superset image doesn't ship fastmcp — layer it on top so `superset mcp run`
# is available. Pinned to match the base image's Superset version so pip's extras
# resolve against the already-installed apache-superset rather than upgrading it.
FROM apache/superset:6.1.0

USER root

# The image's venv (/app/.venv, what `superset` actually runs under) is uv-managed
# and has no pip binary of its own — plain `pip install` hits system pip and installs
# into system site-packages, which the venv's python never sees. Must go through uv,
# pointed explicitly at that venv.
RUN uv pip install --python /app/.venv/bin/python "apache-superset[fastmcp]==6.1.0" psycopg2-binary

COPY docker/superset_config.py /app/pythonpath/superset_config.py
COPY docker/bootstrap.sh /app/docker/bootstrap.sh
RUN chmod +x /app/docker/bootstrap.sh

USER superset
