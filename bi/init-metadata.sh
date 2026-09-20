#!/bin/sh
# One-shot, idempotent: gives Superset its own role and database in PFP's Postgres.
# Runs as the Postgres owner (PFP_PG_USER) on every `make bi-up`, so it also works on a
# volume created before Superset existed (postgres/init-roles.sh only runs once).
set -e

: "${PFP_BI_DB_PASSWORD:?PFP_BI_DB_PASSWORD is required (see .env.example)}"

psql -v ON_ERROR_STOP=1 -v password="$PFP_BI_DB_PASSWORD" \
     -h postgres -U "$PFP_PG_USER" -d "$PFP_PG_DATABASE" <<'SQL'
select format('create role superset login password %L', :'password')
where not exists (select 1 from pg_roles where rolname = 'superset') \gexec
select format('alter role superset password %L', :'password') \gexec
select 'create database superset owner superset'
where not exists (select 1 from pg_database where datname = 'superset') \gexec
SQL
