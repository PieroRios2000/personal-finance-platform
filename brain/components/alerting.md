---
type: component
phase: 7
status: built
task: Phase 7, feat/alerting-email-teams
---

# Alerting

Tells the owner by email and/or Microsoft Teams when something fails: **errors immediately,
warnings in a weekly digest**. Decisions and reasons in
[ADR 0026](../decisions/0026-alerts-errors-now-warnings-weekly-names-and-counts-only.md); setup in
[SETUP.md section 11](../../SETUP.md#11-alerts-by-email-or-microsoft-teams-phase-7).

## Pieces

| Piece | What it does |
|---|---|
| [`alerting/events.py`](../../alerting/events.py) | `Event(level, source, name, count)`; builds events from dbt's `run_results.json` (status `error`/`fail` → error, `warn` → warn, skipped nodes → one error) and from ingest's needs-review count. Never reads dbt's `message` |
| [`alerting/render.py`](../../alerting/render.py) | The text: subject `[pfp] 1 error, 2 warnings`, one line per event; the weekly digest grouped by kind. A name that is not a plain identifier prints as `<unnamed>` |
| [`alerting/channels.py`](../../alerting/channels.py) | `EmailChannel` (SMTP + STARTTLS) and `TeamsChannel` (Adaptive Card POST), each configured from `ALERT_*` variables; a failed send returns the error type, never the URL or password |
| [`alerting/queue.py`](../../alerting/queue.py) | The warnings waiting for the digest: a 0600 JSON-lines file under a 0700 directory, outside the repo, holding source, name, count and time |
| [`alerting/cli.py`](../../alerting/cli.py) | `python -m alerting dbt` (errors now, warnings queued) and `python -m alerting digest` (send the queue, empty it if it went out) |
| `make alert`, `make alert-digest` | The two commands with `.env` loaded; `make poc` calls the first itself when a channel is configured |
| `[[tool.importlinter.contracts]]` in `pyproject.toml` | `alerting` may not import `ingestion`, `lakehouse` or `orchestration` |

## How to verify it

The unit tests (`tests/alerting/`) cover events, rendering, both channels (a fake SMTP and a local
HTTP server standing in for the Teams webhook), the queue, the digest and the CLI, including that
no dbt message, amount or free text reaches a message. To try it for real, set one channel in
`.env`, run `make alert` after a `dbt build` (it reports "No alerts" on a clean run), and
`make alert-digest`.

## Not built

- A scheduler: the weekly run is the owner's cron or Task Scheduler entry (SETUP.md).
- Dagster-triggered alerts: Dagster runs here as one-shot commands (no daemon), so a sensor would
  never fire; run `make alert` after a Dagster run.
- Per-warning severity rules (which warning should become an error).

## Related

- [ADR 0026](../decisions/0026-alerts-errors-now-warnings-weekly-names-and-counts-only.md)
- [Phase 7 — alerting](../phases/phase-7.md)
- [Elementary](elementary.md) and [dbt silver](dbt-silver.md) — where the warnings and errors come from
- [ADR 0004](../decisions/0004-real-pdfs-never-leave-your-machine.md) — why only names and counts
