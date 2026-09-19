---
type: decision
phase: 7
status: accepted
date: 2026-09-19
---

# ADR 0026: Alerts: errors now, warnings in a weekly digest, names and counts only

## Context

After the first real run it was clear that failures were only visible if the owner opened a
terminal: a failing dbt test had skipped 93 of 127 nodes, silver and gold included, and the only
trace was in the output of one command. The owner asked to be told, by email or Microsoft Teams,
with two different urgencies: **errors as soon as they appear**, **warnings once a week**, to
review on the weekend.

An alert is data leaving the process, so [ADR 0004](0004-real-pdfs-never-leave-your-machine.md)
applies to it: dbt's own failure messages can quote a value, and a file name can hold an account
number.

## Decision

- **Errors are sent immediately.** A dbt test or model with status `error`/`fail`, and a
  summary of nodes skipped because of one (an error too: silver and gold were not built). `make
  poc` sends them right after its build; after any other build, `make alert`.
- **Warnings are queued and sent as one weekly digest.** dbt `warn` results (Elementary's
  anomaly test) and the count of files that need review go to a private JSON-lines file outside
  the repository (`~/finance-data/alerts/warnings.jsonl`, 0600). `make alert-digest` sends the
  queued warnings grouped by kind (total, number of runs, first and last date) and empties the
  queue, only if every channel accepted the message. The schedule is the owner's own (cron in
  WSL or Windows Task Scheduler, documented in SETUP.md).
- **Two channels, each on when its `ALERT_*` variables are set, both allowed at once:** email
  over SMTP with STARTTLS, and a Teams webhook (an Adaptive Card, the format Teams Workflows
  accepts).
- **Names and counts only.** The events are built from a dbt node's identifier and a row or file
  count; dbt's `message` field is never read; a name that is not a plain identifier is printed as
  `<unnamed>`; the queue file holds source, name, count and time and nothing else. A failed send
  reports the error type and never the webhook URL or the SMTP password.
- **Standalone package.** `alerting/` imports nothing from `ingestion`, `lakehouse` or
  `orchestration` (an import-linter contract), so it cannot reach statement data.

## Alternatives considered

- **Send warnings immediately too**: rejected by the owner; the volume would be noise, and they
  are for the weekend.
- **A Dagster sensor or schedule**: Dagster runs here as one-shot commands, with no daemon
  watching, so a sensor would never fire. A scheduler inside the project would also have to stay
  up; the OS scheduler the owner already has is simpler and visible.
- **Reading dbt's failure messages for more detail**: rejected; they can carry values. The test
  name and the failing-row count say where to look.
- **Only one channel**: the owner's tenant may or may not allow a Teams webhook, and email needs
  an app password; supporting both costs about 30 lines.

## Consequences

- The weekly digest only runs when the machine is on at the scheduled time; a missed week's
  warnings stay queued and go out in the next digest.
- `make poc` and `make alert` are the automatic triggers. A Dagster run started by hand needs
  `make alert` after it; wiring the pipeline itself to alert is a later step.
- Not decided here: which warnings deserve to become errors (the numeric CI rules leave
  warn-mode on 2026-09-26; that is a separate switch).

## Related

- [Alerting](../components/alerting.md)
- [Phase 7 — alerting](../phases/phase-7.md)
- [Elementary](../components/elementary.md) — a source of warnings
