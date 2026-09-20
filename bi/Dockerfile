# Apache Superset with the PostgreSQL driver (T32, ADR 0030). The official image ships
# without one, and Superset needs it twice: for its own metadata database and for the
# read-only connection to PFP's gold schema.
FROM apache/superset:5.0.0
USER root
RUN uv pip install --python /app/.venv/bin/python psycopg2-binary==2.9.10
USER superset
