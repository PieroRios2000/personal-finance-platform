"""Superset settings (T32, ADR 0030). Everything secret comes from the environment."""

import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# Superset's own metadata (users, charts, dashboards) lives in its own database of
# PFP's Postgres, owned by its own role -- never in `pfp`, where dbt writes.
SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://superset:"
    f"{os.environ['PFP_BI_DB_PASSWORD']}@postgres:5432/superset"
)

# Local, single-user: no CSRF token round trip for the CLI-driven import, and the
# default in-memory cache instead of Redis.
WTF_CSRF_ENABLED = True
