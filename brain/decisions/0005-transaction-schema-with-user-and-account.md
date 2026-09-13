---
type: decision
phase: 1
status: accepted
date: 2026-09-12
---

# ADR 0005: `Transaction`/`Statement` schema scoped to a user and an account

## Context

Every bank parser (BCP, Scotiabank, and whatever comes after) needs to hand ingestion the same
shape of data, so bronze, reconciliation (T8) and the silver MERGE (T16) don't special-case a
bank. That shared schema has to work for several users and several accounts per user (ADR 0009)
without ever storing a real account number, must not lose a cent to floating-point rounding, and
must give reconciliation and the business key a stable, well-typed value to work with.

## Decision

`ingestion/schema.py` (pydantic, both models frozen and `extra="forbid"`):

- **`Transaction`**: `user_id`, `bank`, `account_id`, `account_last4`, `date`, `description`,
  `amount` (`Decimal`, exactly 2 places), `currency` (`Literal["PEN", "USD"]`),
  `source_file_sha256`.
  - `amount` is signed: negative for a debit, positive for a credit. Zero is rejected — a
    movement with no monetary effect isn't a transaction. More than 2 decimal places is
    rejected rather than silently rounded: extra precision on a bank statement almost always
    means a parsing bug, not real data.
  - `currency` outside `PEN`/`USD` is rejected by the `Literal` type itself.
  - There is no "full account number" field anywhere. Only `account_id` (see below) and
    `account_last4`, the latter pattern-validated to exactly 4 digits — so a caller that
    accidentally passes the full number where `account_last4` belongs gets a `ValidationError`,
    not a silently truncated or leaked value.
- **`Statement`**: `user_id`, `bank`, `account_id`, `account_last4`, `period_start`,
  `period_end`, `opening_balance`, `closing_balance`, `declared_charges_total` and
  `declared_credits_total` (both optional — a bank doesn't always print them, T8 uses whichever
  are present), and `transactions: list[Transaction]`. Balances aren't restricted to nonzero:
  a balance of `0.00` or a negative one (overdraft) is legitimate. A model validator rejects a
  `period_end` before `period_start`, and rejects any transaction whose `user_id`/`bank`/
  `account_id` doesn't match the statement's — a parser bug that mixes accounts fails at
  construction, not somewhere downstream in bronze.
- **`hash_account(bank, number)`**: `account_id` is an HMAC-SHA256 of `bank` and the real
  `number`, keyed by the `PFP_ACCOUNT_KEY` secret (read from `os.environ`, never hardcoded).
  Missing the key raises `MissingAccountKeyError`, a specific exception with actionable
  guidance, not a bare `KeyError`. `bank` and `number` are joined with a `\x00` separator before
  hashing, so two different `(bank, number)` pairs can't be made to collide the way a plain
  string-concatenation or `:`-joined message theoretically could.
- **`last4_of(number)`**: the last 4 characters of the real number, taken before it's hashed and
  discarded — it's the only trace of the number this schema ever keeps.
- **`normalize_description(description)`**: trims, collapses repeated whitespace, collapses
  runs of 2+ fixed-width padding characters (`. - _ * #`), and upper-cases. Deliberately doesn't
  touch embedded digits: without T9's masked layout dump there's no reliable way to tell a
  reference/operation number apart from a merchant name that happens to contain digits, and
  guessing wrong would corrupt the business key silently.

## Alternatives considered

- **`float` for `amount`**: rounding errors accumulate exactly where reconciliation (T8) needs
  exact equality; rejected outright.
- **Integer cents instead of `Decimal`**: avoids float error too, but needs a conversion layer
  at every boundary (parsing, display, dbt) for no real benefit over `Decimal`, which already
  prints and compares naturally.
- **Round an over-precise amount instead of rejecting it**: hides a likely parser bug behind a
  plausible-looking number; failing loudly is more useful here than being permissive.
- **A single unsigned `amount` plus a separate charge/credit `type` field**: forces every
  consumer (T8's sum, T16's silver model) to branch on `type` before it can add anything; a
  signed `Decimal` keeps `opening_balance + Σ amounts == closing_balance` a one-line check.
- **Store the account number encrypted at rest instead of hashing it**: still needs key
  management, and a decryptable value is a stronger, not weaker, thing to leak than a keyed
  hash that can't be reversed even with the schema in hand.
- **Aggressively strip digit runs from `description` as "filler codes"**: risks destroying a
  real merchant name or reference that legitimately matters; deferred until T9's masked dump
  shows what these codes actually look like on a real statement.

## Consequences

- Every parser (T11, T18) must resolve the real account number from the PDF's content, call
  `hash_account` and `last4_of` itself, and never pass the real number any further — it only
  ever exists in memory during parsing.
- Reconciliation (T8) sums signed amounts directly against `opening_balance`/`closing_balance`.
- The business key (`date + amount + normalize_description(description) + account_id`, see
  [Business key](../concepts/business-key.md)) is stable across statements as long as
  `normalize_description` is, which is why it's tested for idempotency and for two differently
  formatted inputs of the same movement.
- `normalize_description`'s conservative scope is an open item: if T9's real dump surfaces a
  clear, safe pattern for embedded reference codes, this ADR's rule gets revisited then, not
  guessed at now.

## Related

- [ADR 0009: Multiple users and accounts, content over filename](0009-multi-user-multi-account-content-over-filename.md)
- [Users and accounts](../concepts/users-and-accounts.md)
- [Business key](../concepts/business-key.md)
- [Reconciliation](../concepts/reconciliation.md)
- [Phase 1](../phases/phase-1.md)
