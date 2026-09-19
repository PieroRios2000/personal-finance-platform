---
type: decision
phase: 2
status: accepted
date: 2026-09-19
---

# ADR 0024: A regenerated PDF with identical content is a duplicate, not a new version

## Context

The inbox organizer ([Inbox organizer](../components/inbox-organizer.md), T12b) told a duplicate
apart from a regenerated statement by the file's *bytes*: same destination and same hash meant
duplicate, same destination and a different hash meant a new version (`..._v2.pdf`). Its own report
already described `_v2` as "regenerated: content differs from the archived one", but nothing ever
compared content.

Running the platform on a real inbox (the owner's 60 BCP statements) showed why that matters. A
bank hands out a fresh PDF on every download, so the same month arrives twice with different bytes.
Four months were like that, each pair with **identical** opening balance, closing balance and
movements. Each second copy was filed as `_v2`, reached bronze as a second statement for the same
period, and `assert_statement_continuity` rejected it (a duplicated period is as wrong as a missing
one). Because that test runs on a *source*, dbt then skipped every downstream node: 93 of 127,
including all of silver and gold. Four harmless re-downloads meant no data at all.

## Decision

`organize()` now compares what was **parsed**, not the bytes, whenever the destination is already
taken by a file with a different hash:

- It parses the archived file(s) of that period — the base file and every `_vN` — with the same
  parser and password, and compares everything the parser read (`Statement.model_dump`: account,
  currency, period, balances, the declared totals a credit-card statement carries, and every
  movement) except `source_file_sha256`, the one field that names the file. The order of the
  movements counts, which is safe: a re-download keeps the PDF's order, and if it ever didn't
  the file would just become a new version.
- **Same content** → `_duplicates/`, with a reason that says the bytes differ (a re-download).
- **Different content** → a new version (`_v2`, `_v3`, …), exactly as before: a real correction
  still reaches the continuity test, which is where a human should look at it.
- **The archived copy can't be parsed** any more (wrong password, damaged file, the parser changed
  and now rejects it) → not a match, so the file becomes a new version. Never a guess.

Comparing against every version, not just the base, is what stops a re-download of a *correction*
from becoming a `_v3`.

## Alternatives considered

- **Leave it and delete the extra PDFs by hand.** Works once. It comes back every time a statement
  is downloaded twice, and the failure (no silver, no gold) is far out of proportion to the cause.
- **Relax `assert_statement_continuity` to tolerate a duplicated period.** Rejected: the test also
  catches a period that really arrived twice with *different* numbers, which is exactly the case a
  person must look at. The fix belongs where the two files are still distinguishable, before bronze.
- **Deduplicate in dbt (silver) by business key.** Too late for this test, which reads bronze
  statements, and it would hide the duplicate instead of removing it from the lake.
- **Hash the PDF's extracted text instead of parsing.** Cheaper, but sensitive to layout noise
  (a re-saved footer, a page number) that leaves every number unchanged, and it can't say *what*
  differs. The parsed statement is already the project's definition of "the same statement", and it
  is reconciled before it is ever compared.
- **Compare only when the balances match.** Weaker: two different statements can share a closing
  balance. The whole movement list is compared.

## Consequences

- One extra parse per collision, only when a file lands on an already-taken destination with a
  different hash. Negligible next to OCR, and it doesn't happen on a normal run.
- The rule is strict on purpose: any difference in a movement's description, amount, date or
  position makes it a new version, and a field added to `Statement` later is compared for free. If a bank ever re-words a description between downloads, the file becomes a
  `_v2` and the continuity test flags it, which is the safe direction to fail in.
- Archives built **before** this change keep their `_v2` files. Move them back to the inbox and
  ingest again ([walkthrough](../../docs/ingesting-your-own-pdfs.md), section 5): the second copy
  of each pair is now recognized as a duplicate.
- `dbt/tests/assert_statement_continuity.sql`'s comment is updated: what still fails there is a
  period that arrived twice with different numbers.
- `tasks/plan.md`'s Phase 1 risk row ("filed as `_v2` with a warning") describes the earlier
  behavior and is left as the historical plan.

## Related

- [Inbox organizer](../components/inbox-organizer.md) — the component this changes.
- [File-level dedup](../concepts/file-level-dedup.md) — the concept; its "Limit" section now points here.
- [Business key](../concepts/business-key.md) — the layer that keeps a real correction's movements
  from duplicating in silver.
- [ADR 0016: Currency-aware statement continuity](0016-currency-aware-statement-continuity.md) —
  the test that rejected the duplicated periods.
- [ADR 0009: Content over file name](0009-multi-user-multi-account-content-over-filename.md) — the
  same principle, applied to the duplicate check.
