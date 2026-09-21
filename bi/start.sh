#!/bin/sh
# Superset's entrypoint (T32): migrate its metadata, create the admin, load the
# committed dashboards, then serve. Idempotent, so a restart is safe.
set -e

superset db upgrade
# create-admin fails when the user already exists; reset-password then makes sure
# the password is the current PFP_BI_ADMIN_PASSWORD (and fails if there is no admin).
superset fab create-admin --username admin --firstname PFP --lastname Admin \
    --email admin@example.com --password "$PFP_BI_ADMIN_PASSWORD" || true
superset fab reset-password --username admin --password "$PFP_BI_ADMIN_PASSWORD"
superset init

# The committed export masks the connection's password; put the real one (the read-only
# role's, URL-encoded) into a throwaway copy of the database file, never into the
# repository. No export yet (a fresh checkout that has not run `make bi-export`): start
# empty.
if [ -f /app/pfp-assets/metadata.yaml ]; then
    rm -rf /tmp/assets && cp -r /app/pfp-assets /tmp/assets
    python - <<'PY'
import glob
import os
from urllib.parse import quote

password = quote(os.environ["PFP_PG_BI_PASSWORD"], safe="")
for path in glob.glob("/tmp/assets/databases/*.yaml"):
    text = open(path).read()
    open(path, "w").write(text.replace("XXXXXXXXXX", password))
PY
    superset import-directory /tmp/assets --overwrite
    # Earlier imports left charts and datasets behind; drop what is not in this export.
    python /app/bi-cleanup.py /tmp/assets || echo "cleanup failed; the dashboard still works"
fi

exec gunicorn --bind 0.0.0.0:8088 --workers 2 --timeout 120 \
    "superset.app:create_app()"
