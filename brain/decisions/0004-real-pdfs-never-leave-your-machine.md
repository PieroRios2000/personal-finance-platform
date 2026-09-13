---
type: decision
phase: 1
status: accepted
date: 2026-09-12
---

# ADR 0004: Real PDFs never leave your machine

## Context

BCP and Scotiabank statements hold personal and financial data: name, account numbers,
balances and every movement. There are two paths they could leave the machine through: Git
(the repo is public) and the AI assistant, since anything it reads gets sent to its API. CI
also runs on GitHub-hosted machines.

## Decision

- PDFs live in `~/finance-data/` (inbox at `inbox/<user>/`, archive at `raw/<user>/`, since
  ADR 0009), outside the repo and readable only by their owner; the password lives in `.env`.
- Git can't receive them: `.gitignore` and the `forbid-data-files` hook.
- CI uses synthetic PDFs generated in the tests (T10), never real ones.
- Parsers are designed from a masked layout dump (T9) that the owner reviews before sharing it;
  the assistant never reads a real PDF unmasked (reconfirmed on 2026-09-12).
- Tests against real PDFs (`pytest -m real_pdf`, `make poc`) run only locally and show
  pass/fail and reconciliation differences, never extracted values.

## Alternatives considered

- **Upload anonymized PDFs to the repo**: anonymizing a PDF is easy to get wrong, and a binary
  committed to Git doesn't get erased from history.
- **Have the assistant read the real PDFs**: faster for designing parsers, but exposes all the
  content; rejected by the owner.
- **Encrypted PDFs in the repo**: adds key management, and the content still leaves the machine.

## Consequences

- Synthetic fixtures have to closely mimic the real layout; if they drift, the local
  `real_pdf` tests and reconciliation catch it.
- CI's ephemeral environments only use synthetic data (ADR 0007); real data only ever runs
  through local `make poc`.
- Designing a parser takes one extra step: run the inspector and review its output.

## Related

- [Security guards](../components/security-guards.md) — how they're kept from reaching Git.
- [Reconciliation](../concepts/reconciliation.md) — the only thing shown when testing against real PDFs.
- [Phase 1](../phases/phase-1.md)
