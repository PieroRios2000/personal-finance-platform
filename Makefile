# Quality-bar checks. Rules, thresholds and reasons live in CONSTRAINTS.md;
# if this file and CONSTRAINTS.md disagree, CONSTRAINTS.md wins.
# Lines with "-" are rules in warn mode until 2026-09-26: they show the failure but
# don't stop the recipe. That day the "-" comes off and they start blocking.

BASE ?= origin/develop

# Environments on one machine (T38, ADR 0033). `PFP_ENV` picks the Compose project, the env
# file and the ports; each environment has its own volumes, database, Superset and catalog:
#     poc   (default)  project pfp-poc,  .env       ports as in .env.example: today's stack
#     dev              project pfp-dev,  .env.dev   ports +100: real data, the code of develop
#     prod             project pfp-prod, .env.prod  ports +200: artificial data, the code of main
# Try a change in dev; when it is right, merge develop into main and start prod from a checkout
# of main. `make env PFP_ENV=dev` writes that environment's env file. Any other name works
# with its own PORT_OFFSET (e.g. `make up PFP_ENV=test PORT_OFFSET=300`).
PFP_ENV ?= poc
PORT_OFFSET ?= $(if $(filter dev,$(PFP_ENV)),100,$(if $(filter prod,$(PFP_ENV)),200,0))
ENV_FILE = $(if $(filter poc,$(PFP_ENV)),.env,.env.$(PFP_ENV))
LOAD_ENV = set -a && . ./$(ENV_FILE) && set +a

# The one Compose project of the platform (ADR 0032). Every `docker compose` call below goes
# through $(PFP): the project name is written here once, so a throwaway one can be tried with
# `make <target> PFP_PROJECT=pfp-test` without ever touching the real stack (`poc-down` and
# `down -v` delete volumes: never run them without checking the project).
PFP_PROJECT ?= pfp-$(PFP_ENV)
PFP = docker compose -p $(PFP_PROJECT)
# Each environment's OpenMetadata artifacts (they hold a token and the Postgres password).
export PFP_OM_ARTIFACTS = ./artifacts/$(PFP_ENV)

.PHONY: check-fast check-task check-full ci-local ci-local-full poc poc-up poc-down pg-check pg-up pg-down env env-guard guard-user ingest build demo up up-catalog down status bi-check legacy-down om-up om-sync om-down bi-up bi-down bi-reset bi-export dex-add-user alert alert-digest

# After every change (< 5 s): lint, format and types.
check-fast:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .
	uv run python -m scripts.check_docs_links

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
	@$(LOAD_ENV) && \
	missing="" && \
	{ [ -n "$$PFP_PG_PASSWORD" ] || missing="$$missing PFP_PG_PASSWORD"; } && \
	{ [ -n "$$PFP_PG_BI_PASSWORD" ] || missing="$$missing PFP_PG_BI_PASSWORD"; } && \
	{ [ -z "$$missing" ] || { echo "set$$missing in .env (see .env.example, SETUP.md section 6)" >&2; exit 2; }; }

pg-up: pg-check
	$(LOAD_ENV) && $(PFP) up -d --wait postgres

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
	$(LOAD_ENV) && \
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
BI_SERVICES = bi-init dex superset
CATALOG_SERVICES = postgresql elasticsearch execute-migrate-all openmetadata-server ingestion
OM_VOLUMES = om-postgres-data es-data ingestion-volume-dag-airflow ingestion-volume-dags ingestion-volume-tmp

# A clean clone: `make env` writes a .env with generated secrets (never overwrites yours),
# `make up` starts the platform, `make demo` loads artificial data and builds the tables, and
# the dashboard opens at the Superset URL `make status` prints (T33).
ENV_USER = $(or $(USER_NAME),$(if $(filter dev,$(PFP_ENV)),$(USER),demo))

env:
	uv run python -m scripts.init_env --out $(ENV_FILE) --port-offset $(PORT_OFFSET) --user $(ENV_USER)

# Where an environment may run: prod only on the code of main, dev never on main (FORCE=1
# overrides). Keeps a change from reaching the environment that is meant to be stable.
env-guard:
	@branch=$$(git branch --show-current); \
	case "$(PFP_ENV)" in \
	  prod) [ "$$branch" = main ] || { echo "prod runs the code of main; this checkout is on '$$branch' (use a checkout of main, or FORCE=1)" >&2; [ -n "$(FORCE)" ] || exit 2; } ;; \
	  dev) [ "$$branch" != main ] || { echo "dev is for develop and feature branches; this checkout is on main (or FORCE=1)" >&2; [ -n "$(FORCE)" ] || exit 2; } ;; \
	esac

# Demo data and real data never share an environment: `make demo` needs PFP_USER=demo in the
# env file, `make ingest` refuses it. Called with TARGET=demo|ingest.
guard-user:
	@test -f $(ENV_FILE) || { echo "no $(ENV_FILE): run 'make env PFP_ENV=$(PFP_ENV)' first" >&2; exit 2; }
	@$(LOAD_ENV) && case "$(TARGET)" in \
	  demo) [ "$$PFP_USER" = demo ] || { echo "make demo writes fictional data, but PFP_USER in $(ENV_FILE) is '$$PFP_USER', not 'demo': use a demo environment (prod)." >&2; exit 2; } ;; \
	  ingest) [ "$$PFP_USER" != demo ] || { echo "make ingest loads real statements, but PFP_USER in $(ENV_FILE) is 'demo': use another user (dev)." >&2; exit 2; } ;; \
	esac

# Your real statements (the inbox of PFP_USER) into bronze, then silver and gold: `make ingest
# build`. Needs `make up`. Refuses the demo user.
ingest:
	@$(MAKE) --no-print-directory guard-user TARGET=ingest
	$(LOAD_ENV) && uv run pfp ingest --user "$$PFP_USER"

build:
	$(LOAD_ENV) && uv run dbt deps --project-dir dbt --profiles-dir dbt && \
	uv run dbt build --project-dir dbt --profiles-dir dbt

# Eight closed months of a fictional person, straight to bronze (scripts/seed_demo.py), then
# silver and gold. Needs `make up` first. Idempotent; real data can be loaded next to it (use
# a different PFP_USER for it) or the demo removed with `make poc-down`.
demo: env-guard
	@$(MAKE) --no-print-directory guard-user TARGET=demo
	$(LOAD_ENV) && uv run python -m scripts.seed_demo && \
	uv run dbt deps --project-dir dbt --profiles-dir dbt && \
	uv run dbt build --project-dir dbt --profiles-dir dbt
	@echo "Open the dashboard: make status shows the Superset URL (user admin)."

bi-check: pg-check
	@$(LOAD_ENV) && \
	missing="" && \
	{ [ -n "$$PFP_BI_DB_PASSWORD" ] || missing="$$missing PFP_BI_DB_PASSWORD"; } && \
	{ [ -n "$$PFP_BI_ADMIN_PASSWORD" ] || missing="$$missing PFP_BI_ADMIN_PASSWORD"; } && \
	{ [ -n "$$PFP_BI_SECRET_KEY" ] || missing="$$missing PFP_BI_SECRET_KEY"; } && \
	{ [ -n "$$PFP_BI_OAUTH_CLIENT_SECRET" ] || missing="$$missing PFP_BI_OAUTH_CLIENT_SECRET"; } && \
	{ [ -z "$$missing" ] || { echo "set$$missing in .env (see .env.example, SETUP.md section 12)" >&2; exit 2; }; }

# Before T37 Superset and OpenMetadata ran as their own projects (`pfp-bi`, `pfp-om`), on
# their own ports: stop any left over so the ports are free for the one project.
legacy-down:
	@[ "$(PFP_ENV)" = poc ] || exit 0; for p in pfp-bi pfp-om; do \
		ids=$$(docker ps -aq --filter "label=com.docker.compose.project=$$p"); \
		if [ -n "$$ids" ]; then echo "stopping the old $$p project"; docker rm -f $$ids >/dev/null; \
			docker network rm "$${p}_default" >/dev/null 2>&1 || true; fi; \
	done

up: env-guard bi-check legacy-down
	$(LOAD_ENV) && $(PFP) --profile bi up -d --build --wait seaweedfs postgres $(BI_SERVICES)
	$(LOAD_ENV) && $(PFP) run --rm bucket-init
	@$(MAKE) --no-print-directory status

up-catalog: up
	mkdir -p openmetadata/artifacts/$(PFP_ENV)
	$(LOAD_ENV) && $(PFP) --profile bi --profile catalog up -d --wait $(CATALOG_SERVICES)
	@$(MAKE) --no-print-directory status

status:
	@$(LOAD_ENV) && $(PFP) --profile bi --profile catalog ps --format 'table {{.Name}}\t{{.Status}}'
	@$(LOAD_ENV) && \
	echo "" && echo "Storage (S3):  http://localhost:$${SEAWEEDFS_S3_PORT:-8333}" && \
	echo "Superset:      http://localhost:$${PFP_BI_PORT:-8088}   (sign in with your email, via Dex)" && \
	echo "Dex:           http://localhost:$${PFP_DEX_PORT:-5556}/dex   (make dex-add-user EMAIL=...)" && \
	echo "OpenMetadata:  http://localhost:$${OPENMETADATA_PORT:-8585}   (only after make up-catalog)" && \
	echo "Dagster:       uv run dagster dev  ->  http://localhost:3000"

down:
	$(LOAD_ENV) && $(PFP) --profile bi --profile catalog down --remove-orphans

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
	$(LOAD_ENV) && \
	uv run dbt docs generate --project-dir dbt --profiles-dir dbt
	$(LOAD_ENV) && uv run python -m scripts.openmetadata_sync --host http://localhost:$${OPENMETADATA_PORT:-8585} sync --out openmetadata/artifacts/$(PFP_ENV)
	$(PFP) --profile catalog exec -T ingestion metadata ingest -c /opt/pfp-artifacts/postgres-workflow.yaml
	$(PFP) --profile catalog exec -T ingestion metadata ingest -c /opt/pfp-artifacts/dbt-workflow.yaml
	$(LOAD_ENV) && uv run python -m scripts.openmetadata_sync --host http://localhost:$${OPENMETADATA_PORT:-8585} check

om-down:
	$(LOAD_ENV) && $(PFP) --profile catalog rm -sf $(CATALOG_SERVICES)
	docker volume rm -f $(foreach v,$(OM_VOLUMES),$(PFP_PROJECT)_$(v)) >/dev/null
	rm -rf openmetadata/artifacts/$(PFP_ENV)

# Apache Superset (T32, ADR 0030): optional, local only, never run by CI. `bi-up` starts
# just Superset next to a running Postgres (`make up` starts everything); `bi-down` removes
# its containers. Its dashboards are in bi/assets (committed) and come back on the next start.
bi-up: bi-check legacy-down
	$(LOAD_ENV) && $(PFP) --profile bi up -d --build --wait $(BI_SERVICES)
	@$(LOAD_ENV) && echo "Superset: http://localhost:$${PFP_BI_PORT:-8088} (sign in with your email, via Dex: make dex-add-user EMAIL=...)"

bi-down:
	$(LOAD_ENV) && $(PFP) --profile bi rm -sf $(BI_SERVICES)

# DROPS the `superset` database in PFP's Postgres: Superset's users and dashboards (only
# re-importable state; `pfp` is untouched). The next `bi-up` re-imports bi/assets. Needed
# before `make bi-export` re-authors them.
bi-reset: bi-down
	$(LOAD_ENV) && $(PFP) exec -T postgres \
		psql -U "$$PFP_PG_USER" -d "$$PFP_PG_DATABASE" -c 'drop database if exists superset with (force)'

# Rewrites bi/assets from a fresh Superset: `rm bi/assets/*`, `make bi-reset bi-up`, this.
bi-export:
	$(LOAD_ENV) && uv run python bi/build_dashboards.py

# Dex (T39, ADR 0034): hash a chosen password and print the line to add to
# DEX_STATIC_PASSWORDS in .env, then `make up` (or bi-up) to pick it up.
dex-add-user:
	@test -n "$(EMAIL)" || { echo "usage: make dex-add-user EMAIL=you@example.com" >&2; exit 2; }
	uv run python -m scripts.dex_add_user "$(EMAIL)"

# Phase 7 (alerting, SETUP.md section 11): send the errors of the last `dbt build`
# now and queue its warnings; `alert-digest` sends the queued warnings as one
# message (schedule it weekly). Both need the ALERT_* variables in .env.
alert:
	$(LOAD_ENV) && uv run python -m alerting dbt

alert-digest:
	$(LOAD_ENV) && uv run python -m alerting digest

# CI's own jobs, run locally the way CI runs them (scripts/ci_local.py): the steps and
# environment come from .github/workflows/ci.yml, in a clean clone of what is committed
# and with only that job's variables. `ci-local` is the fast jobs (lint-types, tests,
# architecture, floor-guard); `ci-local-full` adds ephemeral-integration (Docker, and
# the ports 8333 and 5432 free: `make poc-down` first if your stack is up).
ci-local:
	uv run python -m scripts.ci_local

ci-local-full:
	uv run python -m scripts.ci_local --full
