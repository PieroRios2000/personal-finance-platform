---
type: phase
phase: 7
status: planned
---

# Phase 7 — Alerting (planned)

Errors and warnings from the pipeline (failed `dbt` tests, Dagster run failures, Elementary
anomalies, files that need review) delivered to the owner **by email or to Microsoft Teams**,
instead of only being visible when they open a terminal. Nothing here is built.

## Scope

| Piece | What | Status |
|---|---|---|
| Notifier | One small component that takes an event (level, source, short message) and sends it to the configured channels | planned |
| Channels | Email and Microsoft Teams; either or both | planned |
| Sources | dbt build results (tests with `error` or `warn` severity), Dagster run failures, ingest's "needs review" count | planned |
| `make poc` output | Fix: `scripts/poc.py` shows no dbt lines on real output (dbt prefixes lines with a timestamp and ANSI colours, which its filter does not expect). Same "only safe lines" rule; done with this phase | planned |

## One constraint it inherits

An alert is data leaving the process, so [ADR 0004](../decisions/0004-real-pdfs-never-leave-your-machine.md)
applies to it: a message carries **names and counts only** (the failing test's name, how many
rows, how many files need review), never an amount, an account, a description or a file name
taken from a real statement. The same rule `scripts/poc.py` already follows when it prints
results.

## Open questions

- How Teams is reached (an incoming webhook or a Power Automate workflow, which depends on the
  tenant) and where the webhook URL and SMTP credentials live (`.env`, like every other secret).
- Whether the notifier is a Dagster sensor, a step at the end of the run, or both.
- Which warnings are worth a message versus a line in a daily summary.

## Related

- [Phase 2](phase-2.md) — Dagster, dbt tests and Elementary, the sources of the events
- [Phase 6 — savings-goal projection](phase-6.md)
