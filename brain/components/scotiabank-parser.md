---
type: component
phase: 1
status: built
task: T18, feat/parser-scotiabank
---

# Scotiabank parser

Turns a Scotiabank credit-card statement PDF into one or more reconciled `Statement`s (T6's
schema) — one per currency the statement carries — reading bank, account and period from the
PDF's own content, never the file name (ADR 0009). The second bank parser, proving the
dispatcher/parser design (T11, T12) scales beyond BCP.

## Pieces

| Piece | What it does |
|---|---|
| [`ingestion/parsers/base.py`](../../ingestion/parsers/base.py) | `detect` is now optional; a bank with no cheap byte signature registers with `detect=None` (ADR 0012) |
| [`ingestion/parsers/scotiabank.py`](../../ingestion/parsers/scotiabank.py) | No `detect()` at all — found by `ingestion.dispatcher`'s password-fallback pass instead. `parse()` unlocks with pikepdf, reads words with pdfplumber, and builds a `list[Statement]` |
| [`ingestion/dispatcher.py`](../../ingestion/dispatcher.py) | Two-pass detection (ADR 0012): every fast, password-free `detect()` first, then a fallback pass that tries decrypting each remaining parser's file with its own `password_env` |
| [`tests/parsers/test_scotiabank.py`](../../tests/parsers/test_scotiabank.py) | Dual-currency split, debt sign convention, value-date column, account/card extraction, Total-mismatch detection, multi-page row isolation, single-currency statements, and one `real_pdf`-marked test |

## A bank with no byte signature, and a statement that isn't one account

Two real Scotiabank traits don't fit the shape T11/T12 built for BCP alone, both decided
*before* writing any parsing code (unlike BCP, which was calibrated against five real-data
rounds after the fact — see [BCP parser](bcp-parser.md)):

- **No `$BOP$`-style byte prefix.** A real Scotiabank PDF's raw bytes start with a plain
  `%PDF-`, indistinguishable from any other PDF without opening it. Detecting **is** decrypting
  for this bank — there's no cheaper question to ask first. See
  [ADR 0012](../decisions/0012-scotiabank-password-fallback-detection.md).
- **It's a credit card, not a checking account**, and it carries **two currencies at once**
  (Soles and Dólares) as two independent, separately-reconciled columns. `Statement` holds one
  `opening_balance`/`closing_balance`, not one per currency, so `parse()` returns a `list`, one
  `Statement` per currency that actually has activity — never zero, never both unconditionally.
  `BankParser.parse()`'s return type changed to `list[Statement]` project-wide for this; BCP
  always returns exactly one.

## How the layout is read

Position/shape-based from the start, applying the lesson BCP's five real-data rounds paid for:
never a fixed adjacent-phrase regex, always "find it by its own shape or position on the page."
Confirmed directly from a real masked dump (T9's inspector, 2026-09):

- **Account identification**: the real card number is partially masked by the bank itself
  (`9999-9999-****-9999`, literal asterisks) and never printed in full — nothing to HMAC the
  way BCP hashes its full account number. An unmasked 8-digit client/product code appears
  instead, confirmed by Piero to identify the account stably, and is what `hash_account()` is
  keyed on. `account_last4` comes from the masked card's own last group — the bank already
  treats those 4 digits as safe to print.
- **No "CUENTA NRO."/"PERIODO" label** next to either value; both found by shape, same
  principle as `bcp.py`.
- **Period**: `DD-MM-YYYY` (dashes), found via a `DEL ... AL ...` line with no leading label.
- **Row dates**: `DD/MM/YY`, two columns (processing, value) — only the later, value-date
  column is kept, the earlier one given a throwaway column so it can't bleed into it. Unlike
  BCP, each row carries its own year directly; no cross-new-year inference needed.
- **Two-line header**: `Fecha` (twice) and `Descripción` on one line, `Soles`/`Dólares` a few
  points below on the next — enough vertical gap to land in separate `_group_lines` groups.
  Title case with accents (`Descripción`, `Dólares`), not BCP's all-caps — matched exactly,
  since these are exact string comparisons.
- **Debt sign convention** (the mirror image of BCP's money-on-hand balance): a charge has no
  suffix, a payment/credit ends in a literal `-`. A charge *adds* to what's owed; a payment
  *subtracts*.
- **Per-page line grouping from the start** (`_group_lines(page_words)`, concatenated across
  pages, never once over the whole flattened document) — the exact bug BCP only caught after it
  broke a real 4-page statement, deliberately not repeated here since a real Scotiabank
  statement is also routinely multi-page.
- **Leftmost-bucket contamination in `_currency_amount()`**: the currency-columns dict only has
  two entries (PEN, USD), so whatever sits left of the *first* one — a row's dates/description,
  or a label like `SALDO`/`ANTERIOR`/`Total` — has no boundary to stop it and lands in that
  first cell too, the same "no boundary before the leftmost column" trait `bcp.py`'s
  `_assign_columns()` already has. Found by manual smoke-testing (not caught by the first
  test-writing pass): it silently dropped both the opening balance and every PEN transaction,
  since the regex never matched the whole contaminated string. Fixed by checking only the
  *last* whitespace-separated token of each cell, not the whole joined string.

## What's confirmed vs. inferred — read before trusting this against a real file

Everything above came directly from the masked dump or from Piero's explicit answers (account
identification: "es un código de cliente/producto"; multi-currency: "un PDF puede producir
varios Statements"; credit-card semantics: "no tiene saldo contable sino saldo de deuda").

**One piece did not come from confirmed data: no independently-declared closing/total-debt
figure was identifiable anywhere in the dump.** `SALDO`, `ANTERIOR`, `ACTUAL`, `FINAL`,
`DISPONIBLE` and `CONTABLE` are all words T9's masking tool leaves unmasked when present, and
only `SALDO ANTERIOR` ever showed up — the true total-debt figure almost certainly lives on the
statement's first, dashboard-style summary page, under labels (credit limit, minimum payment,
"deuda total" or similar) that were never confirmed and are out of scope here.

So `closing_balance` is **computed** (opening balance plus that currency's own transactions),
not checked against an independent number the way BCP's `SALDO ACTUAL` is — which means
`reconcile()` can **never actually fail** for this parser; it's tautologically true by
construction. The real protection is a separate, ad-hoc check: every `Total` line in the
document (a generic word appearing once per real page, with one Soles and one Dólares figure
next to it — read as that page's own subtotal) is summed per currency and compared against
this parser's own transaction sum, raising `ValueError` on a mismatch.

**This is the piece most likely to need a follow-up fix**, exactly like BCP's own five
real-data rounds. It has not been run against Piero's real PDF; only he can do that (ADR 0004),
using the same masked-dump-and-fix loop BCP went through — see
[`test_scotiabank.py`](../../tests/parsers/test_scotiabank.py)'s `real_pdf`-marked test.

## Account kind (T18a)

Every `Statement` this parser builds — including both currency statements from one file —
gets `account_kind="liability"`: a credit-card balance is debt owed, the opposite kind of
thing from BCP's checking-account balance. Hardcoded here, not read from the PDF; see
[ADR 0015](../decisions/0015-account-kind-asset-or-liability.md), including why the join that
carries this into `silver.transactions` had to be written with this parser's
one-file-two-statements shape specifically in mind.

## Currency, and the false positive it caused (T18c)

Each `Statement` this parser's loop builds gets that same iteration's own `currency` (`"PEN"` or
`"USD"`), not a hardcoded constant — the one parser where a constant would be wrong, since a
single file produces both. This is also *why* `Statement` needed a `currency` field at all:
Piero found, by actually running `dbt build` against synthetic dual-currency Scotiabank data,
that the continuity test read this parser's two same-period, different-currency
`bronze.statements` rows as a genuine duplicated period and failed. Full root cause and the
partition-by-currency fix in [ADR 0016](../decisions/0016-currency-aware-statement-continuity.md).

## How to use it and how to verify it

```python
from ingestion import dispatcher

parser = dispatcher.detect(path)  # tries BCP's byte prefix, then each password fallback
statements = parser.parse(
    path, user_id="piero", file_sha256=file_sha256, password=password
)
for statement in statements:
    ...  # one per currency (PEN, USD) that has activity
```

`uv run pytest` runs the synthetic tests. `uv run pytest -m real_pdf` additionally runs
`test_parses_and_reconciles_a_real_scotiabank_statement`, which searches
`~/finance-data/{inbox,raw}` for a PDF `dispatcher.detect()` resolves to Scotiabank and skips
itself if none is found or `SCOTIABANK_PDF_PASSWORD` isn't set — an approved floor-guard
exception covers its `pytest.skip()` calls, the same pattern already approved for
`test_bcp.py`'s equivalent test (see CONSTRAINTS.md). It never asserts or prints an extracted
value (ADR 0004).

## Related

- [ADR 0015: Account kind (asset/liability)](../decisions/0015-account-kind-asset-or-liability.md) — why this parser hardcodes `account_kind="liability"`.
- [ADR 0016: Currency-aware statement continuity](../decisions/0016-currency-aware-statement-continuity.md) — why this parser's dual-currency shape needed `Statement.currency`, and the false positive it caused before the fix.
- [ADR 0012: Password-fallback detection and `list[Statement]`](../decisions/0012-scotiabank-password-fallback-detection.md)
- [ADR 0004: Real PDFs](../decisions/0004-real-pdfs-never-leave-your-machine.md) — why the real-PDF test only checks pass/fail.
- [BCP parser](bcp-parser.md) — the position/shape-based parsing lesson this parser applies from the start, and the sibling parser's own real-data calibration history.
- [Quality bar](quality-bar.md) — the exceptions process this component uses.
- [Reconciliation](../concepts/reconciliation.md) — `parse()` calls `reconcile()` before returning, though it can never fail here (see above).
- [Users and accounts](../concepts/users-and-accounts.md) — content over file name.
- [Phase 1](../phases/phase-1.md)
