#!/bin/sh
# Runs once, when the Postgres volume is first created (docker-entrypoint-initdb.d).
# Creates dbt's two schemas and a read-only role for BI tools (Superset) that can
# read `gold` and nothing else, now and for every table dbt creates there later.
set -e

: "${PFP_PG_BI_PASSWORD:?PFP_PG_BI_PASSWORD is required (see .env.example)}"

psql -v ON_ERROR_STOP=1 \
     -v owner="$POSTGRES_USER" \
     -v bi_password="$PFP_PG_BI_PASSWORD" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
create schema if not exists silver;
create schema if not exists gold;

create role pfp_bi login password :'bi_password';
grant usage on schema gold to pfp_bi;
grant select on all tables in schema gold to pfp_bi;
-- dbt drops and recreates tables: the privilege has to follow the new ones.
alter default privileges for role :"owner" in schema gold grant select on tables to pfp_bi;
SQL
