---
type: decision
phase: 1
status: accepted
date: 2026-09-14
---

# ADR 0017: Internal-transfer matching as mutual nearest neighbor, plus a currency-relaxed candidate definition

## Context

T18b needs to match a real transfer between two accounts of the same user (an outflow on one,
an inflow on the other) so it never counts as income or expense, and needs to do it with **at
most one pair per movement** — a bank statement's own transaction rows have no guarantee of
uniqueness beyond their full content (`bronze/transactions` has no surrogate key, ADR 0006), and
more than one plausible candidate can legitimately exist near a given amount/date. The
account_kind-aware sign rule itself (opposite signs for two `asset` or two `liability` accounts,
same sign for an `asset`-to-`liability` pair) was already decided in ADR 0015, before this task
was even built. Two things were still open: **how to implement the one-to-one matching itself**,
and **what "candidate" means** for the unmatched-review table T18b's acceptance criteria ask for.

## Decision

**A single shared model, `dbt/models/silver/internal_transfer_matches.sql`, computes matching
exactly once.** `internal_transfers.sql` (one row per matched pair) and `unmatched_transfers.sql`
(one row per unmatched candidate) both just reshape its output; `transactions.sql`'s own
`is_internal_transfer` flag is a `left join` back to it. It reads `bronze.transactions`/
`bronze.statements` directly, never `ref('transactions')` — the one way to let `transactions.sql`
depend on the matching result without creating a `transactions.sql` → `internal_transfer_matches`
→ `transactions.sql` cycle (dbt refuses to compile one; found by actually running
`dbt compile` against an early draft that read `ref('transactions')` instead, immediately).
A `movement_id` macro (`dbt/macros/movement_id.sql`, an md5 hash of every
`bronze.transactions` column except `ingested_at`) gives each bronze row a stable, content-based
identity two of these models — `internal_transfer_matches.sql` and `transactions.sql` — need to
agree on; a macro instead of copy-pasting the same hash formula twice, so the two can never
silently drift out of step (the failure mode of drift here is silent, not a compile error: every
row would just read as unmatched, with nothing to say why).

**Matching algorithm: mutual nearest neighbor**, not a true maximum-cardinality bipartite
matching. Every candidate pair is ranked from each side by closeness (smallest amount
difference, then smallest date difference, then a deterministic tie-break on the hash key), and
a pair is only selected when each side is the *other's own best* candidate too — a self-join of
the per-movement best-candidate ranking onto itself. This guarantees the one-to-one property by
construction (a movement's own best candidate is a single row, so it can be *someone's* mutual
match at most once) without a solver: the real maximum-cardinality bipartite matching problem is
solvable in polynomial time, but not in a single declarative SQL statement without recursion or
a procedural loop, and this project's own scale (thousands of rows, realistically at most a
handful of candidates sharing one amount/date neighborhood) doesn't justify that complexity.
The trade-off is real and accepted: mutual nearest neighbor can leave a movement unmatched even
when *some* valid pairing existed for it — three same-amount, opposite-sign candidates on three
different accounts is the minimal case, proven by
`tests/test_dbt_internal_transfers_integration.py::test_three_same_amount_candidates_produce_at_most_one_pair_each`
and guarded permanently by the singular test below. Never a false positive (a wrong pair), only
ever a movement that stays a visible, reviewable candidate instead of getting paired — consistent
with this project's own "never silently drop a row" principle (ADR 0015's `left join` reasoning,
`ingestion/reconciliation.py`'s "fail loudly" language).

**"Candidate" (what lands in `unmatched_transfers`) is the same account_kind-aware sign/amount
rule as real matching, minus the currency requirement.** Two movements are candidates of each
other whenever they'd satisfy the day-window and sign/amount-tolerance rule regardless of
whether their currencies agree; *matching* additionally requires the same currency. This is
deliberately not "any row within N days of any amount on another account" (that would flood the
table with every ordinary transaction that happens to share a nearby date with something
unrelated) and not "every unmatched row" (same problem, worse) — currency is the one axis this
task explicitly asks to relax: a cross-currency pair that's otherwise a dead ringer for a
transfer (same day, same numeric amount, right sign shape) must surface for a human to look at
rather than silently vanish, since nothing in this project does FX conversion (rejected
project-wide, `tasks/plan-phase2.md`'s architecture decisions).

**A genuinely isolated movement — nothing else anywhere in the lake near it in amount, date and
sign shape — is not a candidate, full stop**, and correctly never appears in
`unmatched_transfers`. This follows directly from candidacy being relative to *actual* data:
there is no principled, data-driven way to flag a row as a plausible transfer half when nothing
else in the lake gives any signal that it might be one — doing so would mean flagging every
ordinary transaction, which is exactly what `unmatched_transfers` exists to avoid. This reading
was the one genuine ambiguity in T18b's own acceptance criteria ("removing the inflow makes it
show up in unmatched_transfers" reads, taken fully literally, as if the outflow alone, with
nothing else in the lake, should be flagged) — resolved conservatively here and covered from two
angles instead: `test_three_same_amount_candidates_produce_at_most_one_pair_each` (a real
candidate loses the mutual-match tie-break to a closer one) and
`test_cross_currency_same_amount_is_not_matched_but_lands_in_unmatched` (the intended,
correctly-denominated counterpart was never recorded, but a wrong-currency near-miss was) both
exercise "an orphaned leg lands in `unmatched_transfers`, never silently dropped" through a
legitimate, data-driven candidate signal;
`test_an_ordinary_transaction_with_no_plausible_partner_is_not_a_candidate` proves the boundary
the other way. Full reasoning on why this particular reading was chosen is in this PR's own body
(Notes section).

## Alternatives considered

- **A true maximum-cardinality bipartite matching** (e.g. via a recursive CTE implementing an
  augmenting-path algorithm). Rejected: real, non-trivial SQL complexity for a guarantee this
  project's own scale doesn't need — in practice, at most a small handful of candidates ever
  share one amount/date neighborhood, so the two algorithms agree on every realistic case; the
  gap only shows up in contrived multi-candidate scenarios like the three-way test above, where
  losing to a closer candidate (never a wrong match, never a silent drop) is an acceptable
  outcome.
- **Duplicating the matching CTEs into `internal_transfers.sql` and `unmatched_transfers.sql`
  separately**, each reading bronze directly. Rejected: ~80 lines of matching logic (candidate
  generation, ranking, mutual-match selection) would need to stay byte-for-byte identical across
  two files with nothing enforcing that, the exact kind of drift `account_kind`'s own dedup'd
  join (ADR 0015) was written once, precisely to avoid.
- **Reading `ref('transactions')` from `internal_transfer_matches.sql`**, instead of bronze
  directly. Simpler to write (`account_kind` already joined in, no need to duplicate that CTE),
  but creates the dependency cycle described above the moment `transactions.sql` also needs to
  join back to it for `is_internal_transfer` — confirmed by `dbt compile` refusing to build.
- **"Candidate" = any unmatched row whose account has another account for the same user**, with
  no amount/date proximity at all. Rejected: with this project's synthetic data every user has
  both a BCP and a Scotiabank account by construction, so this reduces to "every unmatched
  transaction" — exactly the flood `unmatched_transfers` exists to avoid, explicitly warned
  against in T18b's own task description ("not every transaction in the ledger").
- **A separate, wider tolerance/day-window just for candidacy** (e.g. candidates get 2x the
  match day-window). Considered as a way to make a "removed inflow" landing in
  `unmatched_transfers` less contrived, but rejected as an unprincipled knob with nothing in the
  task asking for it — currency is the one relaxation the task itself calls out explicitly
  (cross-currency transfers "show up as unmatched, not silently ignored"), so that's the one
  implemented.
- **`is_internal_transfer` added directly to `transactions.sql` by inlining the matching CTEs**
  instead of joining to a separate model. Rejected for the same duplication reason as the second
  alternative above, and because it would make `transactions.sql` — a model three other
  tasks (T16, T18a, T18c) already depend on being narrow and well-understood — responsible for
  logic that has nothing to do with what it otherwise does (typing and re-normalizing one row per
  bank movement).

## Consequences

- Four new/changed files in `dbt/models/silver/`: `internal_transfer_matches.sql` (new, the one
  place matching logic lives), `internal_transfers.sql` (new, matched pairs),
  `unmatched_transfers.sql` (new, unmatched candidates), `transactions.sql` (changed, one new
  `left join` and one new column). Plus `dbt/macros/movement_id.sql` (new) and
  `dbt/tests/assert_internal_transfers_are_one_to_one.sql` (new, the same kind of standing
  insurance `assert_statement_continuity.sql` already provides for its own rule).
- Two new dbt vars, both overridable per run: `internal_transfer_day_window_days` (default 3)
  and `internal_transfer_amount_tolerance` (default 0), per T18b's own acceptance criteria.
- A known, accepted limitation shared with every other content-identified row in this project
  (ADR 0009's own "content over file name" principle): two genuinely byte-identical bronze
  transaction rows (same user, account, date, amount, currency, description, source file) hash
  to the same `movement_id` and collapse into one for matching purposes.
  `bronze/transactions` has no column that could tell them apart even in principle — no PDF
  row/line number is captured anywhere in this project — so this is a pre-existing gap in the
  bronze schema, not something T18b introduces or could fix on its own.
  **Found by an independent `code-review` pass to be worse than that framing implied**: without
  a dedup step, `internal_transfer_matches.sql`'s own output had *two* rows sharing that
  movement_id (one per underlying bronze row, un-deduplicated) — and `transactions.sql`'s `left
  join` on `movement_id` isn't a 1:1 join by construction the way `account_kinds`' own join is,
  so two duplicate bronze rows fanned out to **four** `silver.transactions` rows, silently
  doubling that account's transaction count and any downstream sum. Fixed with a `select
  distinct` in `internal_transfer_matches.sql`'s own `tx` CTE — every other selected column is
  already determined by the columns the hash is built from (`bank`/`account_last4`/
  `account_kind` all follow from `account_id`), so `distinct` correctly collapses true
  duplicates to exactly one row, making `movement_id` unique in `internal_transfer_matches` by
  construction and every downstream join against it (this one, and `internal_transfers.sql`'s
  own leg self-join) safe without needing its own defensive dedup too. The remaining, genuinely
  accepted limitation is narrower than first framed: a duplicate pair now surfaces as exactly
  one row in `internal_transfer_matches`/`unmatched_transfers`/`internal_transfers` (matching or
  candidacy can't tell the two apart), not two — but `silver.transactions` itself, the table
  most things read, always keeps the correct one-row-per-bronze-row count, proven by
  `tests/test_dbt_internal_transfers_integration.py::test_duplicate_bronze_rows_do_not_multiply_silver_transactions_rows`.

## Related

- [ADR 0015: `account_kind` (asset/liability) on `Statement`, joined into silver](0015-account-kind-asset-or-liability.md) —
  the sign-matching rule this ADR's algorithm implements; written specifically so T18b could get
  it right on the first attempt.
- [ADR 0011: `delta_scan()` as a dbt source](0011-delta-scan-as-a-dbt-source.md) — the source
  declarations `internal_transfer_matches.sql`'s own `tx` CTE reads from.
- [ADR 0009: Content over file name](0009-multi-user-multi-account-content-over-filename.md) —
  the same content-identity principle `movement_id` follows, and the shared limitation.
- [dbt silver](../components/dbt-silver.md) — where these models live alongside `transactions.sql`.
- [Reconciliation](../concepts/reconciliation.md) — the "never silently drop a row" principle
  behind `left join`s and the unmatched-review table.
- [Phase 1](../phases/phase-1.md)
