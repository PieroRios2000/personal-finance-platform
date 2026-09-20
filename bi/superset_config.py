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

# Handlebars charts (the KPI cards) compile their template with `new Function`, which
# Superset's default Content-Security-Policy forbids: allow 'unsafe-eval' for scripts.
# Everything else is Superset's default policy minus the analytics and map-tile hosts.
TALISMAN_CONFIG = {
    "content_security_policy": {
        "base-uri": ["'self'"],
        "default-src": ["'self'"],
        "img-src": ["'self'", "blob:", "data:"],
        "worker-src": ["'self'", "blob:"],
        "connect-src": ["'self'"],
        "object-src": "'none'",
        "style-src": ["'self'", "'unsafe-inline'"],
        "script-src": ["'self'", "'strict-dynamic'", "'unsafe-eval'"],
    },
    "content_security_policy_nonce_in": ["script-src"],
    "force_https": False,
    "session_cookie_secure": False,
}

# The KPI cards also use classes and a <style> block. Superset sanitizes chart HTML by
# default and strips both; allow exactly these two (no scripts, no event handlers).
# Only people who can edit charts (admins here) can write such HTML.
HTML_SANITIZATION_SCHEMA_EXTENSIONS = {
    "tagNames": ["style"],
    "attributes": {"*": ["className", "style"]},
}
