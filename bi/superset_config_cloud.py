"""Superset settings for the Phase 4 GCP demo slice (T70, ADR 0050).

No Dex/OAuth here (option A, ADR 0050's scope): nobody but the owner needs to
authenticate against a screenshot-only deployment, so Superset's default AUTH_DB backs
a single Gamma viewer (bi/start_cloud.sh) instead of bi/superset_config.py's
DexSecurityManager and row-level security.

Superset's own metadata (users, the imported dashboard) lives in the default local
SQLite file, not a separate Postgres role: infra/terraform/database.tf provisions
only the gold-reader copy, no second database for this. A short apply-then-destroy
demo (ADR 0050's uptime answer) can tolerate losing it on a cold start -- bi/
start_cloud.sh redoes the whole setup every time, idempotently, same as the local
image's start.sh does for its own Postgres-backed metadata.
"""

import os
from typing import Any

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

FEATURE_FLAGS = {"ENABLE_TEMPLATE_PROCESSING": True}
# No upload portal in this scope (ADR 0050); the committed dashboard's "Upload your
# files" chart still renders (its own metric is a constant string, confirmed by
# bi/superset_config.py's own test to survive 0 rows), it just links nowhere useful.
JINJA_CONTEXT_ADDONS: dict[str, Any] = {"upload_url": lambda: ""}

# Same as bi/superset_config.py: the KPI cards' Handlebars templates and <style> blocks
# need these to render (see that file's own comments for why each one is needed).
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
    "force_https": False,  # Cloud Run terminates TLS in front of the container
    "session_cookie_secure": True,  # Cloud Run's own URL is always https
}
HTML_SANITIZATION_SCHEMA_EXTENSIONS = {
    "tagNames": ["style"],
    "attributes": {"*": ["className", "style"]},
}

# Cloud Run also sits behind a proxy (its own, not Cloudflare's).
ENABLE_PROXY_FIX = True
PROXY_FIX_CONFIG = {"x_for": 1, "x_proto": 1, "x_host": 1, "x_prefix": 0}

# AUTH_DB is Superset's own default (no assignment needed): bi/start_cloud.sh creates
# the one Gamma viewer; nobody registers themselves or signs in any other way.
AUTH_USER_REGISTRATION = False
