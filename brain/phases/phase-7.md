---
type: phase
phase: 7
status: built
---

# Phase 7 — Alerting

Errors and warnings from the pipeline (failed `dbt` tests, Elementary anomalies, files that need
review) delivered to the owner **by email or to Microsoft Teams**, instead of only being visible
when they open a terminal. **Errors are sent the moment they appear; warnings are queued and sent
once a week** as one digest, to review on the weekend. Built in
[Alerting](../components/alerting.md); decisions in
[ADR 0026](../decisions/0026-alerts-errors-now-warnings-weekly-names-and-counts-only.md).

## Scope

| Piece | What | Status |
|---|---|---|
| Notifier | Events (level, source, name, count) rendered and sent to the configured channels | built |
| Channels | Email (SMTP, STARTTLS) and Microsoft Teams (webhook); either or both | built |
| Sources | dbt build results (`error`/`fail` now, `warn` weekly), nodes skipped, ingest's "needs review" count | built. Dagster run failures: not wired (Dagster runs as one-shot commands here; run `make alert` after it) |
| Weekly digest | `make alert-digest`; scheduling is the owner's cron / Task Scheduler entry | built, schedule documented |
| `make poc` output | `scripts/poc.py` now shows dbt's result lines on real output (it stripped neither the ANSI colours nor the timestamps dbt prints) and calls alerting after the build when a channel is configured | built |

## One constraint it inherits

An alert is data leaving the process, so [ADR 0004](../decisions/0004-real-pdfs-never-leave-your-machine.md)
applies to it: a message carries **names and counts only** (the failing test's name, how many
rows, how many files need review), never an amount, an account, a description or a file name
taken from a real statement. The same rule `scripts/poc.py` already follows when it prints
results.

## Still open

- Whether the owner's Teams tenant allows the Workflows webhook (email works regardless).
- Which warnings deserve to become errors (the numeric CI rules leave warn-mode on 2026-09-26; a
  separate switch).
- Wiring alerts into Dagster itself instead of `make alert` after a run.

## Related

- [Phase 2](phase-2.md) — Dagster, dbt tests and Elementary, the sources of the events
- [Phase 6 — savings-goal projection](phase-6.md)
