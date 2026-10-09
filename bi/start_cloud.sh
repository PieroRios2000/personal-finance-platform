#!/bin/sh
# Cloud variant of bi/start.sh (T70, ADR 0050): one Gamma viewer (AUTH_DB) instead of
# Dex-mapped admin/owner roles, and the committed export's connection string replaced
# wholesale, not just its password -- Cloud SQL's host and database name both differ
# from the local Postgres service the export was written against. Idempotent, so a
# cold start after Cloud Run scales back up from zero is safe, same as start.sh.
set -e

# Shared by both gunicorn workers below (set once, here, not computed inside
# superset_config_cloud.py at import time -- each worker would get a different value).
export SUPERSET_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

superset db upgrade
superset init
# create-user fails when the user already exists; reset-password then makes sure the
# password is the current PFP_DEMO_VIEWER_PASSWORD (and fails if there is no such user).
superset fab create-user --username viewer --firstname PFP --lastname Viewer \
    --email viewer@example.com --role Gamma --password "$PFP_DEMO_VIEWER_PASSWORD" || true
superset fab reset-password --username viewer --password "$PFP_DEMO_VIEWER_PASSWORD"

if [ -f /app/pfp-assets/metadata.yaml ]; then
    rm -rf /tmp/assets && cp -r /app/pfp-assets /tmp/assets
    python - <<'PY'
import glob
import os

uri = os.environ["PFP_DEMO_DB_CONNECTION_STRING"]
if uri.startswith("postgresql://"):
    uri = "postgresql+psycopg2://" + uri[len("postgresql://") :]
placeholder = "postgresql+psycopg2://pfp_bi:XXXXXXXXXX@postgres:5432/pfp"
for path in glob.glob("/tmp/assets/databases/*.yaml"):
    text = open(path).read()
    open(path, "w").write(text.replace(placeholder, uri))
PY
    superset import-directory /tmp/assets --overwrite
    # Earlier imports left charts and datasets behind; drop what is not in this export.
    python /app/bi-cleanup.py /tmp/assets || echo "cleanup failed; the dashboard still works"
    # Gamma's base read access on the gold datasets (no per-user row-level filter here:
    # a single shared viewer needs no such thing).
    python /app/grant_gamma_access.py
fi

exec gunicorn --bind "0.0.0.0:${PORT:-8080}" --workers 2 --timeout 120 \
    "superset.app:create_app()"
