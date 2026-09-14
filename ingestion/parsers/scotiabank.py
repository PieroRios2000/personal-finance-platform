"""Scotiabank credit-card statement parser (T18): turns a decrypted PDF into
one reconciled `Statement` *per currency* it carries.

No `detect()` is exposed here (see `ingestion.parsers.base`'s module docstring):
unlike BCP's real export, a real Scotiabank PDF's raw bytes start with a plain
`%PDF-` — there is no cheap, password-free signature to check. `ingestion.
dispatcher` finds this bank by trying to decrypt with `SCOTIABANK_PDF_PASSWORD`
instead, once every parser with a fast `detect()` has failed to match.

Calibrated against a real masked layout dump (T9's inspector, 2026-09) of the
owner's own Scotiabank credit-card statement — a materially different layout
from BCP's checking-account one, confirmed from that dump:

- It's a **credit-card** statement: the printed balance is debt owed, not money
  on hand, and it carries **two currencies at once** (Soles and Dólares) as two
  separate amount columns, each independently reconciled (`ingestion.schema.
  Statement` holds one `opening_balance`/`closing_balance`, not one per
  currency) — so `parse()` returns a *list*, one `Statement` per currency that
  actually has an opening balance and/or transactions to report.
- The real card number is **partially masked by the bank itself**
  (`9999-9999-****-9999`, literal asterisks) and never printed in full, so
  there's nothing to HMAC the way BCP hashes its full account number. An
  8-digit, unmasked client/product code appears instead — confirmed by the
  owner to identify the account stably — and is what `hash_account()` is keyed
  on here. `account_last4` comes from the masked card's own last group, the
  closest real analogue: the bank already considers those 4 digits safe to
  print in full.
- No "CUENTA NRO."/"PERIODO" label sits next to either value; both are found by
  shape, the same principle `bcp.py` already uses (see its own module
  docstring), never a fixed adjacent phrase.
- The period is `DD-MM-YYYY` (dashes), found via a `DEL ... AL ...` line with no
  leading label, the same shape-based technique `bcp.py`'s `_find_period` uses.
- Each row carries its own 2-digit year directly (`DD/MM/YY`, two date
  columns — only the later one, the value date, is kept; the earlier one is
  given a throwaway column so it can't bleed into it, the exact same problem
  and fix as `bcp.py`'s two FECHA columns).
- The header spans **two lines**: `Fecha` (twice) and `Descripción` on one,
  `Soles`/`Dólares` a few points below on the next — real statements print
  them with just enough vertical gap to land in separate `_group_lines`
  groups. Column headers are title case with accents (`Descripción`,
  `Dólares`), not BCP's all-caps — matched exactly, since these are exact
  string comparisons, not case-normalized ones.
- A charge has no suffix; a payment/credit ends in a literal `-` (the mirror
  image of BCP's leading-sign charges, since this balance is debt: a charge
  *adds* to what's owed, a payment *subtracts*). `_money()` reads the sign
  from that trailing character.
- **Lines are grouped per page from the start** (`_group_lines(page_words)`,
  concatenated across pages) — never once over the whole document's words
  combined. That specific bug (two different pages' rows silently merging
  because they land at the same y) was found and fixed in `bcp.py` only after
  it broke one of the owner's real 4-page statements; there is no reason to
  make the same mistake here when a real Scotiabank statement is *also*
  routinely multi-page.

**What's confirmed vs. inferred — read before trusting this against a real
file.** Everything above came directly from the masked dump or from the
owner's explicit answers. One piece did not: **no independently-declared
closing/total-debt figure was identifiable anywhere in the dump.** `SALDO`,
`ANTERIOR`, `ACTUAL`, `FINAL`, `DISPONIBLE` and `CONTABLE` are all words this
project's masking tool leaves unmasked when present, and only `SALDO ANTERIOR`
ever showed up — the true total-debt figure almost certainly lives on the
statement's first, dashboard-style summary page, under labels (credit limit,
minimum payment, "deuda total" or similar) that were never confirmed and are
out of scope here. So `closing_balance` is **computed** — opening balance plus
that currency's own transactions — rather than checked against an independent
number the same way BCP's `SALDO ACTUAL` is. The one independent check this
parser *does* have is `Total`, a generic word that already appears once per
page in the real dump with one Soles and one Dólares figure next to it, read
here as a page-level subtotal of that page's own transactions; every `Total`
line found across the whole document is summed and compared against this
parser's own transaction sum, per currency, raising `ValueError` on a
mismatch — real protection, but not the same guarantee as an independently
declared closing balance. **This is the piece most likely to need a follow-up
fix**, exactly like BCP's own five real-data rounds — see
`brain/components/scotiabank-parser.md`. It has not been run against the
owner's real PDF; only he can do that (ADR 0004), and this parser should be
treated as unverified until he does.
"""

import io
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pdfplumber
import pikepdf

from ingestion import ocr
from ingestion.reconciliation import reconcile
from ingestion.schema import (
    Currency,
    Statement,
    Transaction,
    hash_account,
    normalize_description,
)

_CURRENCY_WORDS: dict[Currency, str] = {"PEN": "Soles", "USD": "Dólares"}
_CURRENCIES: tuple[Currency, ...] = ("PEN", "USD")

_ACCOUNT_CODE_RE = re.compile(r"^\d{8}$")
_MASKED_CARD_RE = re.compile(r"^\d{4}-\d{4}-\*{4}-(\d{4})$")
_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}-?$")
_PERIOD_DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
_ROW_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{2})$")

Word = dict[str, Any]


def _to_currency(text: str) -> Currency:
    if text == "PEN":
        return "PEN"
    if text == "USD":
        return "USD"
    raise ValueError(f"unrecognized currency column: {text!r}")


def _money(text: str) -> Decimal:
    """A Soles/Dólares amount: a trailing "-" means a payment/credit (negative
    — reduces debt owed); its absence means a charge (positive — adds to
    debt). The mirror image of `bcp.py`'s charge-is-negative convention, since
    a checking account's balance is money on hand, not debt."""
    if text.endswith("-"):
        return -Decimal(text[:-1].replace(",", ""))
    return Decimal(text.replace(",", ""))


def _parse_period_date(text: str) -> date:
    match = _PERIOD_DATE_RE.match(text)
    if not match:
        raise ValueError(f"unrecognized period date format: {text!r}")
    day, month, year = int(match[1]), int(match[2]), int(match[3])
    return date(year, month, day)


def _row_date(text: str) -> date:
    """A row prints its own day, month and 2-digit year directly — unlike
    BCP's row dates, there's no year to infer from the statement's period."""
    match = _ROW_DATE_RE.match(text)
    if not match:
        raise ValueError(f"unrecognized row date format: {text!r}")
    day, month, year = int(match[1]), int(match[2]), int(match[3])
    return date(2000 + year, month, day)


def _group_lines(words: list[Word]) -> list[list[Word]]:
    """Group words whose top edge is within 3 pt of each other into one line.

    Same grouping `bcp.py` and `scripts/inspect_pdf_layout.py` use; kept as a
    local copy rather than shared, matching `bcp.py`'s own reasoning (parsers
    don't depend on `scripts/`, and a shared helper isn't worth a new module
    for two callers).
    """
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and word["top"] - lines[-1][0]["top"] <= 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _assign_columns(line: list[Word], columns: dict[str, float]) -> dict[str, str]:
    """Map each word in `line` to the nearest header column to its left. The
    same technique `bcp.py` uses for the same reason: a real statement's row
    data doesn't always start exactly under its column header's own text."""
    boundaries = sorted(columns.items(), key=lambda item: item[1])
    cells: dict[str, list[str]] = {name: [] for name, _ in boundaries}
    for word in line:
        name = boundaries[0][0]
        for column_name, column_x in boundaries:
            if word["x0"] >= column_x - 5:
                name = column_name
        cells[name].append(word["text"])
    return {name: " ".join(words) for name, words in cells.items()}


def _find_account_code(words: list[Word]) -> str | None:
    """The first bare 8-digit token anywhere on the page — the owner-confirmed
    stable client/product code, printed with no adjacent label to key off."""
    for word in words:
        text: str = word["text"]
        if _ACCOUNT_CODE_RE.match(text):
            return text
    return None


def _find_account_last4(words: list[Word]) -> str | None:
    """The last group of a bank-masked card number (`9999-9999-****-9999`):
    the only 4-digit sequence the statement itself already considers safe to
    print in full."""
    for word in words:
        match = _MASKED_CARD_RE.match(word["text"])
        if match:
            return match[1]
    return None


def _find_period(lines: list[list[Word]]) -> tuple[date, date] | None:
    """A line with "DEL" and "AL", each followed by a `DD-MM-YYYY` date — no
    leading "PERIODO" label required, same shape-based approach as `bcp.py`."""
    for line in lines:
        del_word = next((w for w in line if w["text"] == "DEL"), None)
        al_word = next((w for w in line if w["text"] == "AL"), None)
        if not (del_word and al_word):
            continue
        after_del = [
            w
            for w in line
            if w["x0"] > del_word["x0"] and _PERIOD_DATE_RE.match(w["text"])
        ]
        after_al = [
            w
            for w in line
            if w["x0"] > al_word["x0"] and _PERIOD_DATE_RE.match(w["text"])
        ]
        if after_del and after_al:
            return (
                _parse_period_date(after_del[0]["text"]),
                _parse_period_date(after_al[0]["text"]),
            )
    return None


def _find_header_columns(
    lines: list[list[Word]],
) -> tuple[int, dict[str, float]] | None:
    """Find the "Fecha ... Fecha ... Descripción" line, then the nearest line
    below it carrying "Soles"/"Dólares", and return the *first* line's index
    plus every column's x0. The header spans two lines in the real layout, not
    one the way BCP's does.

    A real header has "Fecha" *twice* (processing date, then value date, the
    same situation `bcp.py`'s `_find_header_columns` already solved): only
    the later occurrence becomes the "FECHA" column; earlier ones get a
    throwaway column so their words don't bleed into it.
    """
    for index, line in enumerate(lines):
        texts = {w["text"] for w in line}
        if not ("Fecha" in texts and "Descripción" in texts):
            continue

        columns: dict[str, float] = {}
        fecha_words = sorted(
            (w for w in line if w["text"] == "Fecha"), key=lambda w: w["x0"]
        )
        for ignored_index, word in enumerate(fecha_words[:-1]):
            columns[f"_fecha_ignored_{ignored_index}"] = word["x0"]
        columns["FECHA"] = fecha_words[-1]["x0"]
        columns["DESCRIPCION"] = next(
            w["x0"] for w in line if w["text"] == "Descripción"
        )

        for offset in (1, 2):
            if index + offset >= len(lines):
                break
            neighbor = lines[index + offset]
            neighbor_by_text = {w["text"]: w["x0"] for w in neighbor}
            if _CURRENCY_WORDS["PEN"] in neighbor_by_text:
                columns["PEN"] = neighbor_by_text[_CURRENCY_WORDS["PEN"]]
            if _CURRENCY_WORDS["USD"] in neighbor_by_text:
                columns["USD"] = neighbor_by_text[_CURRENCY_WORDS["USD"]]
            if "PEN" in columns or "USD" in columns:
                break

        if "PEN" not in columns and "USD" not in columns:
            continue  # not the real header: no currency line found nearby
        return index, columns
    return None


def _currency_amount(
    line: list[Word], currency_columns: dict[str, float]
) -> dict[str, Decimal]:
    """The amount under each currency column on `line`.

    `currency_columns` only ever has two entries (PEN, USD): whatever sits to
    the left of the *first* one (a row's dates and description, or a label
    like "SALDO"/"ANTERIOR"/"Total") has no column of its own to fall into and
    lands in that first bucket too, the same "no boundary before the leftmost
    column" trait `_assign_columns` already has for `bcp.py`. Rather than add
    a boundary for everything that could sit there, only the *last*
    whitespace-separated token of each cell is checked against the amount
    shape — the real amount, when a currency has one, is always the last
    token in its own cell, whatever leaked in ahead of it.
    """
    cells = _assign_columns(line, currency_columns)
    amounts: dict[str, Decimal] = {}
    for currency in currency_columns:
        tokens = cells.get(currency, "").split()
        if tokens and _AMOUNT_RE.match(tokens[-1]):
            amounts[currency] = _money(tokens[-1])
    return amounts


def _find_opening_balances(
    lines: list[list[Word]], currency_columns: dict[str, float], skip_index: int
) -> dict[str, Decimal]:
    """The "SALDO ANTERIOR" line's amount(s), one per currency present."""
    for index, line in enumerate(lines):
        if index == skip_index:
            continue
        texts = {w["text"] for w in line}
        if "SALDO" in texts and "ANTERIOR" in texts:
            return _currency_amount(line, currency_columns)
    return {}


def _sum_declared_totals(
    lines: list[list[Word]], currency_columns: dict[str, float], skip_index: int
) -> dict[str, Decimal] | None:
    """Every "Total" line's amount(s), summed per currency across the whole
    document. A real statement prints one per page (this parser doesn't track
    page boundaries once lines are flattened, so a per-page check and a
    summed-across-all-pages check are mathematically the same as long as each
    page's own "Total" really is that page's own subtotal — the read this
    parser's module docstring documents). `None` if no "Total" line was found
    at all, so the caller can skip the check rather than comparing against a
    false zero.
    """
    totals: dict[str, Decimal] = {}
    found = False
    for index, line in enumerate(lines):
        if index == skip_index:
            continue
        if "Total" not in {w["text"] for w in line}:
            continue
        found = True
        for currency, amount in _currency_amount(line, currency_columns).items():
            totals[currency] = totals.get(currency, Decimal("0.00")) + amount
    return totals if found else None


def parse(
    path: Path, *, user_id: str, file_sha256: str, password: str = ""
) -> list[Statement]:
    """Parse the Scotiabank PDF at `path` into one reconciled `Statement` per
    currency it carries (Soles and/or Dólares). Raises `ReconciliationError`
    if a currency's extracted transactions don't add up to its own balance.
    """
    with pikepdf.open(path, password=password) as pdf:
        decrypted = io.BytesIO()
        pdf.save(decrypted)

    with pdfplumber.open(decrypted) as doc:
        words: list[Word] = []
        lines: list[list[Word]] = []
        for page in doc.pages:
            page_words = page.extract_words() or ocr.extract_words(page)
            words.extend(page_words)
            lines.extend(_group_lines(page_words))

    header = _find_header_columns(lines)
    if header is None:
        raise ValueError(
            "could not find the Fecha/Descripción/Soles/Dólares header row"
        )
    header_index, columns = header
    currency_columns = {k: v for k, v in columns.items() if k in ("PEN", "USD")}

    account_code = _find_account_code(words)
    account_last4 = _find_account_last4(words)
    period = _find_period(lines)
    if not (account_code and account_last4 and period):
        raise ValueError(
            "could not find the account code, card number or period in this "
            "Scotiabank statement"
        )
    account_id = hash_account("Scotiabank", account_code)
    period_start, period_end = period

    opening_balances = _find_opening_balances(lines, currency_columns, header_index)

    transactions_by_currency: dict[Currency, list[Transaction]] = {"PEN": [], "USD": []}
    for line in lines:
        cells = _assign_columns(line, columns)
        # A row's description can start left of its own header, the same
        # trait `bcp.py` found and fixed (see its module docstring): the date
        # is always the leftmost word in the FECHA cell, so anything after it
        # is leaked description, not part of the date.
        fecha_words = cells.get("FECHA", "").split()
        row_date_text = fecha_words[0] if fecha_words else ""
        stray_words = fecha_words[1:]
        if not _ROW_DATE_RE.match(row_date_text):
            continue  # a header row, or an info line like "SALDO ANTERIOR"

        amounts = _currency_amount(line, currency_columns)
        if len(amounts) > 1:
            raise ValueError(
                f"row {row_date_text} has both a Soles and a Dólares amount"
            )
        if not amounts:
            continue  # a dated row with no amount isn't a movement
        currency_text, amount = next(iter(amounts.items()))
        currency = _to_currency(currency_text)

        description_words = [*stray_words, cells.get("DESCRIPCION", "")]
        transactions_by_currency[currency].append(
            Transaction(
                user_id=user_id,
                bank="Scotiabank",
                account_id=account_id,
                account_last4=account_last4,
                date=_row_date(row_date_text),
                description=normalize_description(" ".join(description_words)),
                amount=amount,
                currency=currency,
                source_file_sha256=file_sha256,
            )
        )

    declared_totals = _sum_declared_totals(lines, currency_columns, header_index)

    statements: list[Statement] = []
    for currency in _CURRENCIES:
        transactions = transactions_by_currency[currency]
        opening_balance = opening_balances.get(currency)
        if opening_balance is None and not transactions:
            continue  # nothing for this currency in this statement at all
        if opening_balance is None:
            raise ValueError(
                f"found {currency} transactions but no opening balance for it"
            )

        if declared_totals is not None and currency in declared_totals:
            actual_total = sum((t.amount for t in transactions), Decimal("0.00"))
            if actual_total != declared_totals[currency]:
                raise ValueError(
                    f"{currency} Total does not match the sum of its own "
                    f"transactions: declared {declared_totals[currency]}, "
                    f"got {actual_total}"
                )

        closing_balance = opening_balance + sum(
            (t.amount for t in transactions), Decimal("0.00")
        )
        statement = Statement(
            user_id=user_id,
            bank="Scotiabank",
            account_id=account_id,
            account_last4=account_last4,
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            # A Scotiabank statement is always a credit card: its balance is
            # debt owed, never money on hand -- true for every currency this
            # loop builds a Statement for, not just the one shown above
            # (T18a, ADR 0015).
            account_kind="liability",
            transactions=transactions,
        )
        reconcile(statement)
        statements.append(statement)

    if not statements:
        raise ValueError(
            "no Soles or Dólares activity found in this Scotiabank statement"
        )
    return statements
