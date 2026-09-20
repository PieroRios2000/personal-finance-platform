# Quality-bar checks. Rules, thresholds and reasons live in CONSTRAINTS.md;
# if this file and CONSTRAINTS.md disagree, CONSTRAINTS.md wins.
# Lines with "-" are rules in warn mode until 2026-09-26: they show the failure but
# don't stop the recipe. That day the "-" comes off and they start blocking.

BASE ?= origin/develop

.PHONY: check-fast check-task check-full ci-local ci-local-full poc poc-up poc-down pg-check pg-up pg-down om-up om-sync om-down bi-up bi-down bi-reset bi-export alert alert-digest

# After every change (< 5 s): lint, format and types.
check-fast:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .

# When finishing a task (< 90 s): the above + tests with coverage, floor-guard and architecture.
check-task: check-fast
	uv run pytest --cov --cov-report=term-missing --cov-report=xml
	uv run python scripts/floor_guard.py --base $(BASE)
	-uv run lint-imports --no-logo

# Before the PR: the above + security and coverage of the changed lines. This is what CI
# runs except gitleaks, which runs in pre-commit on every commit (and in CI from T5 on).
check-full: check-task
	-uv run pip-audit
	-uv run bandit -q -r . -x ./.venv,./dbt/dbt_packages --severity-level high
	-uv run diff-cover coverage.xml --compare-branch=$(BASE) --fail-under=80

# Local S3 (SeaweedFS) for the lakehouse (ADR 0003, ADR 0007). Fixed project name:
# fine for one developer's machine; T17 gives each CI job its own project name.
# bucket-init runs separately (`run --rm`, not part of `up`'s set): see docker-compose.yml.
# `pg-check` first: with an empty PFP_PG_PASSWORD compose would start Postgres, it would
# exit, and `make poc` would abort before its teardown trap with a generic error.
poc-up: pg-check
	docker compose -p pfp-poc up -d --wait seaweedfs postgres
	docker compose -p pfp-poc run --rm bucket-init

poc-down:
	docker compose -p pfp-poc down -v
	# Elementary's file holds baselines for a database that no longer exists.
	rm -f dbt/elementary.duckdb

# PostgreSQL, dbt's store for silver and gold (ADR 0029, T26). Same project as the local
# S3, so `poc-down` removes its volume too. `pg-down` only stops it (data kept).
# Needs the PFP_PG_* variables in `.env`.
pg-check:
	@set -a && . ./.env && set +a && \
	missing="" && \
	{ [ -n "$$PFP_PG_PASSWORD" ] || missing="$$missing PFP_PG_PASSWORD"; } && \
	{ [ -n "$$PFP_PG_BI_PASSWORD" ] || missing="$$missing PFP_PG_BI_PASSWORD"; } && \
	{ [ -z "$$missing" ] || { echo "set$$missing in .env (see .env.example, SETUP.md section 6)" >&2; exit 2; }; }

pg-up: pg-check
	set -a && . ./.env && set +a && docker compose -p pfp-poc up -d --wait postgres

pg-down:
	docker compose -p pfp-poc stop postgres

# The same flow as CI's ephemeral-integration job (T17, ADR 0007), but against
# Piero's own real PDFs instead of the synthetic fixture, and only once, locally.
# scripts/poc.py never prints a raw pfp/dbt line, only the ones that are
# amount-free by construction (see its own docstring) -- the point is a report
# ADR 0004 allows, not a debugging transcript. Always tears the environment
# down, success or failure, the same way CI's `if: always()` does.
poc:
	$(MAKE) poc-up
	@trap '$(MAKE) poc-down' EXIT; \
	set -a && . .env && set +a && \
	uv run python -m scripts.poc

# OpenMetadata catalog and column-level lineage (T24, ADR 0023): optional, local only, never
# run by CI (~4.6 GiB of containers at idle). Its own fixed project name, distinct from
# pfp-poc, and `down -v` leaves nothing behind, like poc-down. openmetadata/artifacts is
# created here, not by Docker, so the ingestion container's read-only mount of it never
# makes Docker create it root-owned.
OM_COMPOSE = docker compose -f openmetadata/docker-compose.yml -p pfp-om

# The ingestion container joins the network of PFP's Postgres (T30): start it first
# (`make poc-up`, project pfp-poc), or set PFP_NETWORK to another project's network.
om-up:
	@docker network inspect "$${PFP_NETWORK:-pfp-poc_default}" >/dev/null 2>&1 || \
		{ echo "No Docker network $${PFP_NETWORK:-pfp-poc_default}: run 'make poc-up' first (PFP's Postgres must be up)." >&2; exit 1; }
	mkdir -p openmetadata/artifacts
	$(OM_COMPOSE) up -d --wait

# Needs `dbt build` to have run against the lake (`dbt docs generate` reads the built
# tables' columns), so: `make poc-up`, export .env, `dbt build`, then this. Registers
# bronze, ingests silver and gold with OpenMetadata's native Postgres connector, runs
# the dbt workflow (lineage), then fails unless gold.fact_transactions.amount traces
# back to bronze.transactions.amount.
om-sync:
	set -a && . ./.env && set +a && \
	uv run dbt docs generate --project-dir dbt --profiles-dir dbt
	set -a && . ./.env && set +a && uv run python -m scripts.openmetadata_sync sync
	$(OM_COMPOSE) exec -T ingestion metadata ingest -c /opt/pfp-artifacts/postgres-workflow.yaml
	$(OM_COMPOSE) exec -T ingestion metadata ingest -c /opt/pfp-artifacts/dbt-workflow.yaml
	uv run python -m scripts.openmetadata_sync check

om-down:
	$(OM_COMPOSE) down -v
	rm -rf openmetadata/artifacts

# Apache Superset (T32, ADR 0030): optional, local only, never run by CI. Its own project
# (`pfp-bi`), started by hand, not by `make poc-up`. It joins the network of PFP's Postgres
# (start that first) and reads gold as the read-only role; its metadata is in a `superset`
# database of the same Postgres. `bi-down` removes only Superset's container and image
# layers; its dashboards are in bi/assets (committed) and come back on the next `bi-up`.
BI_COMPOSE = docker compose -f bi/docker-compose.yml -p pfp-bi

bi-up:
	@docker network inspect "$${PFP_NETWORK:-pfp-poc_default}" >/dev/null 2>&1 || \
		{ echo "No Docker network $${PFP_NETWORK:-pfp-poc_default}: run 'make poc-up' first (PFP's Postgres must be up)." >&2; exit 1; }
	set -a && . ./.env && set +a && $(BI_COMPOSE) up -d --build --wait
	@echo "Superset: http://localhost:8088 (user admin, password PFP_BI_ADMIN_PASSWORD from .env)"

bi-down:
	set -a && . ./.env && set +a && $(BI_COMPOSE) down -v

# Forget Superset's users and dashboards too (its `superset` database in PFP's Postgres);
# the next `bi-up` re-imports bi/assets. Needed before `make bi-export` re-authors them.
bi-reset: bi-down
	set -a && . ./.env && set +a && docker compose -p pfp-poc exec -T postgres \
		psql -U "$$PFP_PG_USER" -d "$$PFP_PG_DATABASE" -c 'drop database if exists superset with (force)'

# Rewrites bi/assets from a fresh Superset: `rm bi/assets/*`, `make bi-reset bi-up`, this.
bi-export:
	set -a && . ./.env && set +a && uv run python bi/build_dashboards.py

# Phase 7 (alerting, SETUP.md section 11): send the errors of the last `dbt build`
# now and queue its warnings; `alert-digest` sends the queued warnings as one
# message (schedule it weekly). Both need the ALERT_* variables in .env.
alert:
	set -a && . ./.env && set +a && uv run python -m alerting dbt

alert-digest:
	set -a && . ./.env && set +a && uv run python -m alerting digest

# CI's own jobs, run locally the way CI runs them (scripts/ci_local.py): the steps and
# environment come from .github/workflows/ci.yml, in a clean clone of what is committed
# and with only that job's variables. `ci-local` is the fast jobs (lint-types, tests,
# architecture, floor-guard); `ci-local-full` adds ephemeral-integration (Docker, and
# the ports 8333 and 5432 free: `make poc-down` first if your stack is up).
ci-local:
	uv run python -m scripts.ci_local

ci-local-full:
	uv run python -m scripts.ci_local --full
