#!/bin/sh
# Runs once, when the Postgres volume is first created (docker-entrypoint-initdb.d).
# Creates dbt's two schemas and a read-only role for BI tools (Superset) that can
# read `gold` and nothing else, now and for every table dbt creates there later
# (postgres/grants.sql). The role is read-only at session level too.
set -e

: "${PFP_PG_BI_PASSWORD:?PFP_PG_BI_PASSWORD is required (see .env.example)}"

psql -v ON_ERROR_STOP=1 \
     -v bi_password="$PFP_PG_BI_PASSWORD" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
create schema if not exists silver;
create schema if not exists gold;

select format('create role pfp_bi login password %L', :'bi_password')
where not exists (select 1 from pg_roles where rolname = 'pfp_bi') \gexec

alter role pfp_bi set default_transaction_read_only = on;
SQL

psql -v ON_ERROR_STOP=1 \
     -v owner="$POSTGRES_USER" \
     -v database="$POSTGRES_DB" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -f /etc/pfp/grants.sql
