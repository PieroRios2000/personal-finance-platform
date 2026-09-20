"""Superset settings (T32, ADR 0030). Everything secret comes from the environment."""

import os
from urllib.parse import quote

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# Superset's own metadata (users, charts, dashboards) lives in its own database of
# PFP's Postgres, owned by its own role -- never in `pfp`, where dbt writes. The
# password is URL-encoded, so any character is safe in `.env`.
SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://superset:"
    f"{quote(os.environ['PFP_BI_DB_PASSWORD'], safe='')}@postgres:5432/superset"
)
