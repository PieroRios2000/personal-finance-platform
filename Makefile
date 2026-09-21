# Quality-bar checks. Rules, thresholds and reasons live in CONSTRAINTS.md;
# if this file and CONSTRAINTS.md disagree, CONSTRAINTS.md wins.
# Lines with "-" are rules in warn mode until 2026-09-26: they show the failure but
# don't stop the recipe. That day the "-" comes off and they start blocking.

BASE ?= origin/develop

# The one Compose project of the platform (ADR 0032). Every `docker compose` call below goes
# through $(PFP): the project name is written here once, so a throwaway one can be tried with
# `make <target> PFP_PROJECT=pfp-test` without ever touching the real stack (`poc-down` and
# `down -v` delete volumes: never run them without checking the project).
PFP_PROJECT = pfp-poc
PFP = docker compose -p $(PFP_PROJECT)

.PHONY: check-fast check-task check-full ci-local ci-local-full poc poc-up poc-down pg-check pg-up pg-down up up-catalog down status bi-check legacy-down om-up om-sync om-down bi-up bi-down bi-reset bi-export alert alert-digest

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
	$(PFP) up -d --wait seaweedfs postgres
	$(PFP) run --rm bucket-init

poc-down:
	$(PFP) --profile bi --profile catalog down -v --remove-orphans
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
	set -a && . ./.env && set +a && $(PFP) up -d --wait postgres

pg-down:
	$(PFP) stop postgres

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

# The whole platform as one Compose project, `pfp-poc` (T37, ADR 0032): storage (SeaweedFS),
# Postgres and, behind the `bi` and `catalog` profiles, Superset and OpenMetadata. One group
# in Docker Desktop, one network, one command:
#     make up           storage + Postgres + Superset (T32, ADR 0030)
#     make up-catalog   ... plus OpenMetadata (T24, ADR 0023; ~4.6 GiB of RAM)
#     make status       what is running and where
#     make down         stop everything, keep the data (the lake, the tables, the dashboards)
#     make poc-down     stop everything and DELETE the data (volumes), as before
# Compose's `include` reads every file even for a stopped profile, so `${VAR:?}` cannot live
# in them: `bi-check` verifies the Superset variables before `up`. The project name did not
# change, so the volumes of an existing install (lake, Postgres) are kept.
BI_SERVICES = bi-init superset
CATALOG_SERVICES = postgresql elasticsearch execute-migrate-all openmetadata-server ingestion
OM_VOLUMES = om-postgres-data es-data ingestion-volume-dag-airflow ingestion-volume-dags ingestion-volume-tmp

bi-check: pg-check
	@set -a && . ./.env && set +a && \
	missing="" && \
	{ [ -n "$$PFP_BI_DB_PASSWORD" ] || missing="$$missing PFP_BI_DB_PASSWORD"; } && \
	{ [ -n "$$PFP_BI_ADMIN_PASSWORD" ] || missing="$$missing PFP_BI_ADMIN_PASSWORD"; } && \
	{ [ -n "$$PFP_BI_SECRET_KEY" ] || missing="$$missing PFP_BI_SECRET_KEY"; } && \
	{ [ -z "$$missing" ] || { echo "set$$missing in .env (see .env.example, SETUP.md section 12)" >&2; exit 2; }; }

# Before T37 Superset and OpenMetadata ran as their own projects (`pfp-bi`, `pfp-om`), on
# their own ports: stop any left over so the ports are free for the one project.
legacy-down:
	@for p in pfp-bi pfp-om; do \
		ids=$$(docker ps -aq --filter "label=com.docker.compose.project=$$p"); \
		if [ -n "$$ids" ]; then echo "stopping the old $$p project"; docker rm -f $$ids >/dev/null; \
			docker network rm "$${p}_default" >/dev/null 2>&1 || true; fi; \
	done

up: bi-check legacy-down
	set -a && . ./.env && set +a && $(PFP) --profile bi up -d --build --wait seaweedfs postgres $(BI_SERVICES)
	set -a && . ./.env && set +a && $(PFP) run --rm bucket-init
	@$(MAKE) --no-print-directory status

up-catalog: up
	mkdir -p openmetadata/artifacts
	set -a && . ./.env && set +a && $(PFP) --profile bi --profile catalog up -d --wait $(CATALOG_SERVICES)
	@$(MAKE) --no-print-directory status

status:
	@set -a && . ./.env && set +a && $(PFP) --profile bi --profile catalog ps --format 'table {{.Name}}\t{{.Status}}'
	@set -a && . ./.env && set +a && \
	echo "" && echo "Storage (S3):  http://localhost:$${SEAWEEDFS_S3_PORT:-8333}" && \
	echo "Superset:      http://localhost:$${PFP_BI_PORT:-8088}   (admin / PFP_BI_ADMIN_PASSWORD)" && \
	echo "OpenMetadata:  http://localhost:$${OPENMETADATA_PORT:-8585}   (only after make up-catalog)" && \
	echo "Dagster:       uv run dagster dev  ->  http://localhost:3000"

down:
	set -a && . ./.env && set +a && $(PFP) --profile bi --profile catalog down --remove-orphans

# OpenMetadata catalog and column-level lineage (T24, ADR 0023): optional, local only, never
# run by CI (~4.6 GiB of containers at idle). `om-up` is `up-catalog`; `om-down` stops the
# catalog and DELETES its volumes and artifacts (Postgres and Superset keep running).
om-up: up-catalog

# Needs `dbt build` to have run against the lake (`dbt docs generate` reads the built
# tables' columns), so: `make up`, export .env, `dbt build`, then this. Registers
# bronze, ingests silver and gold with OpenMetadata's native Postgres connector, runs
# the dbt workflow (lineage), then fails unless gold.fact_transactions.amount traces
# back to bronze.transactions.amount.
om-sync:
	set -a && . ./.env && set +a && \
	uv run dbt docs generate --project-dir dbt --profiles-dir dbt
	set -a && . ./.env && set +a && uv run python -m scripts.openmetadata_sync sync
	$(PFP) --profile catalog exec -T ingestion metadata ingest -c /opt/pfp-artifacts/postgres-workflow.yaml
	$(PFP) --profile catalog exec -T ingestion metadata ingest -c /opt/pfp-artifacts/dbt-workflow.yaml
	uv run python -m scripts.openmetadata_sync check

om-down:
	set -a && . ./.env && set +a && $(PFP) --profile catalog rm -sf $(CATALOG_SERVICES)
	docker volume rm -f $(foreach v,$(OM_VOLUMES),$(PFP_PROJECT)_$(v)) >/dev/null
	rm -rf openmetadata/artifacts

# Apache Superset (T32, ADR 0030): optional, local only, never run by CI. `bi-up` starts
# just Superset next to a running Postgres (`make up` starts everything); `bi-down` removes
# its containers. Its dashboards are in bi/assets (committed) and come back on the next start.
bi-up: bi-check legacy-down
	set -a && . ./.env && set +a && $(PFP) --profile bi up -d --build --wait $(BI_SERVICES)
	@echo "Superset: http://localhost:8088 (user admin, password PFP_BI_ADMIN_PASSWORD from .env)"

bi-down:
	set -a && . ./.env && set +a && $(PFP) --profile bi rm -sf $(BI_SERVICES)

# DROPS the `superset` database in PFP's Postgres: Superset's users and dashboards (only
# re-importable state; `pfp` is untouched). The next `bi-up` re-imports bi/assets. Needed
# before `make bi-export` re-authors them.
bi-reset: bi-down
	set -a && . ./.env && set +a && $(PFP) exec -T postgres \
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
