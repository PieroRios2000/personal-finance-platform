#!/bin/sh
# Superset's entrypoint (T32): migrate its metadata, create the admin, load the
# committed dashboards, then serve. Idempotent, so a restart is safe.
set -e

superset db upgrade
superset fab create-admin --username admin --firstname PFP --lastname Admin \
    --email admin@example.com --password "$PFP_BI_ADMIN_PASSWORD" || true
superset init

# The committed export masks the connection's password; put the real one (the read-only
# role's) into a throwaway copy, never into the repository. No export yet (a fresh
# checkout that has not run `make bi-export`): start empty.
if [ -f /app/pfp-assets/metadata.yaml ]; then
    rm -rf /tmp/assets && cp -r /app/pfp-assets /tmp/assets
    find /tmp/assets -name '*.yaml' -exec sed -i "s/XXXXXXXXXX/${PFP_PG_BI_PASSWORD}/g" {} +
    superset import-directory /tmp/assets --overwrite
fi

exec gunicorn --bind 0.0.0.0:8088 --workers 2 --timeout 120 \
    "superset.app:create_app()"
