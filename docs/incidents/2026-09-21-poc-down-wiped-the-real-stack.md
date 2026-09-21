# 2026-09-21: `make poc-down` wiped the real stack while testing on a throwaway one

**Status:** resolved · **Severity:** data loss (derived data only)

## Summary

While verifying the one-command stack (T37, [ADR 0032](../../brain/decisions/0032-one-compose-project-one-command.md))
on a throwaway Compose project (`pfp-t46`, its own ports), I ran `make poc-down PFP_PROJECT=pfp-t46`.
The target still named the real project (`-p pfp-poc`), ignored my override, and ran `down -v` on the
**owner's real stack**: the lake, Postgres and Superset's metadata were deleted. Nothing original was lost
(the archived PDFs and the manual Excel were untouched); everything derived was rebuilt the same day and
the movement counts came back identical.

## Impact

- **Deleted:** the S3 lake (bronze), PostgreSQL (`silver`, `gold`, Superset's `superset` database), and
  therefore the dashboards' users and anything made by hand in Superset's UI.
- **Not deleted:** the 83 archived statement PDFs in `~/finance-data/raw/<user>/`, the manual Excel in
  `~/finance-data/manual/`, `.env`, the repository (the dashboards are code in `bi/assets/`).
- **Lost for good:** Superset's own metadata (users; nothing else was known to exist) and Elementary's
  anomaly baselines (they referred to a database that no longer existed anyway).
- **Downtime:** about an hour of the owner's dashboard.

## Timeline

| Step | What happened |
|---|---|
| 1 | T37 branch: Compose files merged into one project; a live check on `pfp-t46` (`make up`, `make up-catalog`, `make down`) passed |
| 2 | To check the teardown, I ran `make om-down` then `make poc-down PFP_PROJECT=pfp-t46` on the real Docker daemon, **without reading the recipe** |
| 3 | `poc-down` was `docker compose -p pfp-poc ... down -v`: the variable was not used. The real `pfp-poc-postgres-1`, `pfp-poc-seaweedfs-1` and their two volumes disappeared |
| 4 | Noticed right after, by `docker ps -a` and `docker volume ls` (my own test project still listed, the real one gone) |
| 5 | Stopped, reported to the owner, and rebuilt (see Recovery) |

## Root cause

1. **The Makefile hardcoded the real project name** in `poc-up`, `poc-down`, `pg-up` and `pg-down`
   (`docker compose -p pfp-poc ...`), while the new `PFP_PROJECT` variable only existed for the new
   targets. I assumed the override applied to all of them.
2. **I ran a volume-deleting target on a shared daemon without reading its recipe.** `make -n
   poc-down PFP_PROJECT=pfp-t46` would have printed `-p pfp-poc` and shown the problem.
3. **No test guarded the project name**, and the destructive targets had no confirmation.

## Recovery

All on the owner's machine, printing counts only ([ADR 0004](../../brain/decisions/0004-real-pdfs-never-leave-your-machine.md)),
following [`../runbook-rebuild-from-archive.md`](../runbook-rebuild-from-archive.md):

1. Stopped the orphaned old Superset (`make bi-down`) and started storage and Postgres empty (`make poc-up`).
2. Moved the 83 archived PDFs back to the inbox and ran `pfp ingest`: **83 archived, 0 duplicates, 0 needing
   review, 88 statements in bronze**.
3. `pfp import-manual` on the manual Excel: 3 savings statements and 7 investment months.
4. `dbt build`: **166/166**, no errors.
5. `make bi-up`: Superset healthy, dashboards re-imported from `bi/assets/`.

**Verified:** the movement count per account was identical to the count taken before the incident
(77, 144, 689, 9, 389, 261, 36, 22 = 1,627) and `gold.rpt_reconciliation` reports 8 accounts with 0
differences.

## What went well / what went wrong

- Well: the sources were never in the volumes (PDFs are archived, never deleted), the dashboards are code,
  and the rebuild path was already documented and deterministic. The damage was noticed within minutes.
- Wrong: a destructive command run on a shared daemon without reading it; an assumption about a variable
  instead of a check; no guard in the repository.

## Prevention

| Action | Where | Status |
|---|---|---|
| Every `docker compose` call in the Makefile goes through `$(PFP)`; the project name is written once | `Makefile` (PR #116) | done |
| A test fails if a literal project name or a bare `docker compose` line comes back | `tests/test_single_stack_config.py` | done |
| Rule: read the recipe (`make -n <target> <overrides>`) and use only a throwaway project name before any target that deletes volumes; never run those on the real project | `CLAUDE.md` | done |
| The rebuild steps are a runbook, so a rebuild is routine | `docs/runbook-rebuild-from-archive.md` | done |
| Operations run on the owner's environment are logged | `docs/operations-log.md` | done |
| Incidents get a post-mortem in the PR that fixes them | PR template, `docs/incidents/` | done |

## Lessons

- A variable that "should" redirect a command is not evidence until the command is printed.
- On a shared machine, a test environment is only isolated if every command it can run is.
- Keeping the originals outside the deletable volumes is what turned a disaster into a repeatable rebuild.
