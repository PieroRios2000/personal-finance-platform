# Quality-bar checks. Rules, thresholds and reasons live in CONSTRAINTS.md;
# if this file and CONSTRAINTS.md disagree, CONSTRAINTS.md wins.
# Lines with "-" are rules in warn mode until 2026-09-26: they show the failure but
# don't stop the recipe. That day the "-" comes off and they start blocking.

BASE ?= origin/develop

.PHONY: check-fast check-task check-full poc poc-up poc-down om-up om-sync om-down alert alert-digest

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
poc-up:
	docker compose -p pfp-poc up -d --wait seaweedfs
	docker compose -p pfp-poc run --rm bucket-init

poc-down:
	docker compose -p pfp-poc down -v

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

om-up:
	mkdir -p openmetadata/artifacts
	$(OM_COMPOSE) up -d --wait

# Needs `dbt build` to have run against the lake (`dbt docs generate` reads the built
# tables' columns), so: `make poc-up`, export .env, `dbt build`, then this. Registers the
# tables, runs the dbt ingestion workflow inside the ingestion container, then fails
# unless gold.fact_transactions.amount traces back to bronze.transactions.amount.
om-sync:
	set -a && . ./.env && set +a && \
	uv run dbt docs generate --project-dir dbt --profiles-dir dbt
	uv run python -m scripts.openmetadata_sync sync
	$(OM_COMPOSE) exec -T ingestion metadata ingest -c /opt/pfp-artifacts/dbt-workflow.yaml
	uv run python -m scripts.openmetadata_sync check

om-down:
	$(OM_COMPOSE) down -v
	rm -rf openmetadata/artifacts

# Phase 7 (alerting, SETUP.md section 11): send the errors of the last `dbt build`
# now and queue its warnings; `alert-digest` sends the queued warnings as one
# message (schedule it weekly). Both need the ALERT_* variables in .env.
alert:
	set -a && . ./.env && set +a && uv run python -m alerting dbt

alert-digest:
	set -a && . ./.env && set +a && uv run python -m alerting digest
