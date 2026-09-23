# Apache Superset with the PostgreSQL driver (T32, ADR 0030) and authlib (T39, ADR 0034).
# The official image ships without either: psycopg2 for its own metadata database and the
# read-only connection to PFP's gold schema, authlib for signing in through Dex
# (flask-appbuilder's OAuth code imports it lazily -- Superset's own pinned requirements
# never list it, since it's flask-appbuilder's own `[oauth]` extra, `Authlib<2.0.0,>=0.14`
# per its PyPI metadata; 1.8.0 is its latest 1.x release).
FROM apache/superset:5.0.0
USER root
RUN uv pip install --python /app/.venv/bin/python psycopg2-binary==2.9.10 authlib==1.8.0
USER superset
