-- What the read-only BI role (`pfp_bi`) may do, applied to one database (T26, ADR 0029).
-- psql variables: :"database" (this database) and :"owner" (the role dbt connects as,
-- which creates the tables). Run by init-roles.sh when the volume is first created, and
-- by the integration test against its throwaway database, so the test proves the very
-- statements the container runs.

revoke connect on database :"database" from public;
grant connect on database :"database" to pfp_bi;

grant usage on schema gold to pfp_bi;
grant select on all tables in schema gold to pfp_bi;
-- dbt drops and recreates tables: the privilege has to follow the new ones.
alter default privileges for role :"owner" in schema gold grant select on tables to pfp_bi;
