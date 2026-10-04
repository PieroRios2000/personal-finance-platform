# 2026-10-04: `uv run dagster dev` failed because the web UI was never installed

**Status:** resolved · **Severity:** near miss (a documented command did not work; no data affected)

## Summary

While writing the guide to the platform's web UIs, `uv run dagster dev` stopped with
"The dagster-webserver Python package must be installed in order to use the dagster dev command".
SETUP.md, the Makefile's `make status` and the Dagster brain note all told the reader to run it.

## Impact

The Dagster UI could not be opened by anyone following the docs. Nothing in the pipeline depends on
it (CI and `make poc` use `dagster asset materialize`, which needs no UI), so no data or run was affected.

## Timeline

| When | What happened |
|---|---|
| T21/T31 | Dagster was added with `dagster` and `dagster-dbt`; the docs were written from the CLI's own help and source, and `dagster dev` was never started |
| 2026-10-04 | The guide's verification started the UI for the first time and it failed at startup |

## Root cause

1. `dagster` does not include the UI: it is the separate `dagster-webserver` package.
2. The docs described `dagster dev` without anyone running it, because no test or CI job starts it.

## Recovery

`uv add --dev dagster-webserver` (1.13.23, the version of `dagster`). Verified: `uv run dagster dev`
serves on `127.0.0.1:3000`, `/server_info` answers, and the API reports 52 assets, 0 schedules and 0 sensors.

## What went well / what went wrong

Went well: the failure was found by running the command before documenting it. Wrong: two tasks
described a command that had never been run.

## Prevention

| Action | Where | Status |
|---|---|---|
| Add the dependency and say so in the docs | `pyproject.toml`, `SETUP.md`, `brain/components/dagster.md` | done |
| Document each web UI only after starting it | [`docs/where-to-look.md`](../where-to-look.md) | done |

## Lessons

A command in the docs is a claim; run it once before writing it down.
