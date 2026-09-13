"""BCP bank-statement parser (T11): turns a decrypted PDF into a reconciled Statement.

Column positions aren't hardcoded to one fixed layout: they're read from wherever
this specific PDF's own header row places its columns, and each row's words are
then assigned to the nearest header to their left. Everything here is derived
from *word positions* (`extract_words()`), not from regexing linearized text
(`extract_text()`) or from one fixture's pixel coordinates — a real BCP statement
doesn't share T10's synthetic fixture's exact wording or layout, but it does share
the column vocabulary (the same Spanish terms `scripts/inspect_pdf_layout.py`'s
HEADERS leaves unmasked), which is what all of this keys off instead.

Calibrated against a real masked layout dump (T9's inspector, 2026-09; see the PR
that added `bcp_real_layout_statement_pdf` in `tests/fixtures/synthetic_pdfs.py`
for the confirmed differences from the original T10 fixture): no "CUENTA NRO." or
"PERIODO" labels, a 2-digit year, two FECHA columns (processing then value date),
plural CARGOS/ABONOS with no SALDO column in the table, "DDMMM"-format row dates,
and a bare "SALDO" closing-balance label with its amount on a neighboring line
rather than beside it. The closing-balance search in particular is a best-evidenced
heuristic, not a certainty: `reconcile()` below is the actual backstop if it ever
picks the wrong amount — a wrong balance fails loudly as a ReconciliationError,
never silently.
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
    Statement,
    Transaction,
    hash_account,
    last4_of,
    normalize_description,
)

# The real BCP export has this 5-byte marker before its %PDF- header (found by
# inspecting the owner's real file with scripts/inspect_pdf_layout.py, T9).
# pikepdf tolerates it either way, so parsing doesn't need to special-case it.
_BOP_PREFIX = b"$BOP$"

_CARGO_WORDS = {"CARGO", "CARGOS"}
_ABONO_WORDS = {"ABONO", "ABONOS"}

# A BCP account number's own shape — four dash-separated all-digit groups, the
# second one long (found in the real dump: "NNN-NNNNNNNN-N-NN", 3-8-1-2 digit
# groups) — is distinctive enough to search for directly, rather than requiring
# an adjacent "CUENTA NRO." label the real statement doesn't have. The exact
# group lengths aren't pinned down further than that (the ≥6-digit second group
# is what actually sets an account number apart from, say, a phone number),
# since a real statement's grouping and T10's fixture's (which uses a wider
# last group on purpose, to make three test accounts easy to tell apart) don't
# have to match exactly.
_ACCOUNT_SHAPE_RE = re.compile(r"^\d{2,4}-\d{6,}-\d{1,2}-\d{2,4}$")
_AMOUNT_SHAPE_RE = re.compile(r"^-?[\d,]+\.\d{2}$")
_DATE_SLASH_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{2}|\d{4})$")
_ROW_DATE_SLASH_RE = re.compile(r"^(\d{2})/(\d{2})$")
_ROW_DATE_ABBR_RE = re.compile(r"^(\d{2})([A-Z]{3})\.?$")

# Spanish month abbreviations as BCP prints them on each row ("05ENE"); SET is
# BCP's own abbreviation for September (not the more common SEP), but SEP is
# accepted too in case a different statement uses it.
_MONTHS_ES = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SET": 9,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
}

Word = dict[str, Any]


def detect(path: Path) -> bool:
    """True if `path`'s raw bytes carry BCP's confirmed `$BOP$` prefix."""
    with path.open("rb") as handle:
        return handle.read(len(_BOP_PREFIX)) == _BOP_PREFIX


def _money(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _parse_date(text: str) -> date:
    """A full DD/MM/YY or DD/MM/YYYY date, as found in the statement's own
    period (the real layout uses a 2-digit year; T10's fixture used 4)."""
    match = _DATE_SLASH_RE.match(text)
    if not match:
        raise ValueError(f"unrecognized date format: {text!r}")
    day, month, year_text = int(match[1]), int(match[2]), match[3]
    year = int(year_text) if len(year_text) == 4 else 2000 + int(year_text)
    return date(year, month, day)


def _is_row_date(text: str) -> bool:
    """True for either row-date shape this parser accepts: "DD/MM" (T10's
    fixture) or "DDMMM" (the real layout's day + Spanish month abbreviation,
    e.g. "05ENE")."""
    return bool(_ROW_DATE_SLASH_RE.match(text) or _ROW_DATE_ABBR_RE.match(text))


def _row_date(text: str, period_start: date, period_end: date) -> date:
    """A row only prints a day and month, no year; infer the year from the
    statement's own period."""
    day: int
    month: int
    if slash_match := _ROW_DATE_SLASH_RE.match(text):
        day, month = int(slash_match[1]), int(slash_match[2])
    elif abbr_match := _ROW_DATE_ABBR_RE.match(text):
        day = int(abbr_match[1])
        found_month = _MONTHS_ES.get(abbr_match[2])
        if found_month is None:
            raise ValueError(f"unrecognized month abbreviation in row date {text!r}")
        month = found_month
    else:
        raise ValueError(f"unrecognized row date format: {text!r}")
    year = period_start.year if month >= period_start.month else period_end.year
    return date(year, month, day)


def _group_lines(words: list[Word]) -> list[list[Word]]:
    """Group words whose top edge is within 3 pt of each other into one line.

    Same grouping `scripts/inspect_pdf_layout.py` uses; kept as a small local
    copy rather than imported, since `scripts/` are standalone tools, not a
    library `ingestion` depends on.
    """
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and word["top"] - lines[-1][0]["top"] <= 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _find_header_columns(
    lines: list[list[Word]],
) -> tuple[int, dict[str, float]] | None:
    """Find the row containing FECHA, DESCRIPCION and CARGO(S)/ABONO(S), and
    return its index plus each column's x0. SALDO is optional: the real
    layout's transaction table has no running-balance column at all.

    A real BCP header row has FECHA *twice* (processing date, then value
    date, 46pt apart). Only the later one is kept as the "FECHA" column;
    earlier ones become throwaway `_fecha_ignored_N` columns so their words
    (the processing date) don't bleed into the value-date column that
    `parse()` actually reads — `_assign_columns` gives every word to the
    nearest column at or to its left, so without an explicit boundary there
    the processing-date column would otherwise have nowhere else to go.
    """
    for index, line in enumerate(lines):
        texts = {word["text"] for word in line}
        has_cargo = bool(_CARGO_WORDS & texts)
        has_abono = bool(_ABONO_WORDS & texts)
        has_basics = "FECHA" in texts and "DESCRIPCION" in texts
        if not (has_basics and has_cargo and has_abono):
            continue

        columns: dict[str, float] = {}
        fecha_words = sorted(
            (word for word in line if word["text"] == "FECHA"),
            key=lambda word: word["x0"],
        )
        for ignored_index, word in enumerate(fecha_words[:-1]):
            columns[f"_fecha_ignored_{ignored_index}"] = word["x0"]
        columns["FECHA"] = fecha_words[-1]["x0"]

        for word in line:
            text = word["text"]
            if text == "DESCRIPCION":
                columns["DESCRIPCION"] = word["x0"]
            elif text in _CARGO_WORDS:
                columns["CARGO"] = word["x0"]
            elif text in _ABONO_WORDS:
                columns["ABONO"] = word["x0"]
            elif text == "SALDO":
                columns["SALDO"] = word["x0"]
        return index, columns
    return None


def _find_account_number(words: list[Word]) -> str | None:
    """The first word matching a BCP account number's own shape
    (NNN-NNNNNNNN-N-NN), wherever it appears — the real layout has no
    "CUENTA NRO." label next to it (see the module docstring)."""
    for word in words:
        text: str = word["text"]
        if _ACCOUNT_SHAPE_RE.match(text):
            return text
    return None


def _find_period(lines: list[list[Word]]) -> tuple[date, date] | None:
    """A line containing both "DEL" and "AL", each followed by a date — the
    real layout has no leading "PERIODO" label."""
    for line in lines:
        del_word = next((word for word in line if word["text"] == "DEL"), None)
        al_word = next((word for word in line if word["text"] == "AL"), None)
        if not (del_word and al_word):
            continue
        after_del = [
            word
            for word in line
            if word["x0"] > del_word["x0"] and _DATE_SLASH_RE.match(word["text"])
        ]
        after_al = [
            word
            for word in line
            if word["x0"] > al_word["x0"] and _DATE_SLASH_RE.match(word["text"])
        ]
        if after_del and after_al:
            return _parse_date(after_del[0]["text"]), _parse_date(after_al[0]["text"])
    return None


def _find_balance(
    lines: list[list[Word]],
    *,
    require_word: str | None = None,
    exclude_word: str | None = None,
    skip_index: int | None = None,
    reverse: bool = False,
) -> Decimal | None:
    """A "SALDO" line's amount, optionally requiring or excluding another
    word on that same line (e.g. "ANTERIOR" for the opening balance).

    The amount isn't always on the same line as its label: the real closing
    balance's amount sits one line above the bare "SALDO" label (8pt apart,
    past `_group_lines`' 3pt same-line tolerance), so nearby lines are
    checked too. `reverse=True` scans from the bottom of the page up, for the
    closing balance: it's the *last* "SALDO" mention on the page, which also
    protects against a transaction description that happens to contain the
    word "SALDO" (e.g. a maintenance-fee line) being mistaken for it.
    `skip_index` excludes the transaction table's own header row, which (in
    the original T10 fixture) has "SALDO" as one of its column labels.
    """
    ordered = list(enumerate(lines))
    if reverse:
        ordered.reverse()
    for index, line in ordered:
        if index == skip_index:
            continue
        texts = {word["text"] for word in line}
        if "SALDO" not in texts:
            continue
        if require_word and require_word not in texts:
            continue
        if exclude_word and exclude_word in texts:
            continue
        amounts = [word for word in line if _AMOUNT_SHAPE_RE.match(word["text"])]
        if amounts:
            return _money(amounts[0]["text"])
        # Closest line first, alternating direction, so an unrelated amount
        # one line further away (e.g. the last transaction row's own amount)
        # never wins over the real one right next to the label.
        offsets = (-1, 1, -2, 2)
        neighbors = [
            lines[index + offset]
            for offset in offsets
            if 0 <= index + offset < len(lines)
        ]
        for neighbor in neighbors:
            nearby = [word for word in neighbor if _AMOUNT_SHAPE_RE.match(word["text"])]
            if nearby:
                return _money(nearby[0]["text"])
    return None


def _assign_columns(line: list[Word], columns: dict[str, float]) -> dict[str, str]:
    """Map each word in `line` to the nearest header column to its left."""
    boundaries = sorted(columns.items(), key=lambda item: item[1])
    cells: dict[str, list[str]] = {name: [] for name, _ in boundaries}
    for word in line:
        name = boundaries[0][0]
        for column_name, column_x in boundaries:
            if word["x0"] >= column_x - 5:
                name = column_name
        cells[name].append(word["text"])
    return {name: " ".join(words) for name, words in cells.items()}


def parse(
    path: Path, *, user_id: str, file_sha256: str, password: str = ""
) -> Statement:
    """Parse the BCP PDF at `path` into a `Statement`, reconciled against its own
    declared totals. Raises `ReconciliationError` if the numbers don't add up.
    """
    with pikepdf.open(path, password=password) as pdf:
        decrypted = io.BytesIO()
        pdf.save(decrypted)

    with pdfplumber.open(decrypted) as doc:
        words: list[Word] = []
        for page in doc.pages:
            # A scanned page (T9) has no text layer, so extract_words() comes back
            # empty; fall back to OCR (T11b) for that page's words only. The rest of
            # parsing (line-grouping, column-assignment, reconciliation) doesn't know
            # or care where a word came from — reconcile() below is what catches a
            # misread character, not this fallback itself.
            words.extend(page.extract_words() or ocr.extract_words(page))

    lines = _group_lines(words)
    header = _find_header_columns(lines)
    if header is None:
        raise ValueError("could not find the FECHA/DESCRIPCION/CARGO/ABONO header row")
    header_index, columns = header

    account_number = _find_account_number(words)
    period = _find_period(lines)
    opening_balance = _find_balance(
        lines, require_word="ANTERIOR", skip_index=header_index
    )
    closing_balance = _find_balance(
        lines, exclude_word="ANTERIOR", skip_index=header_index, reverse=True
    )
    if not (
        account_number
        and period
        and opening_balance is not None
        and closing_balance is not None
    ):
        raise ValueError(
            "could not find the account number, period or balances in this "
            "BCP statement"
        )

    account_id = hash_account("BCP", account_number)
    account_last4 = last4_of(account_number)
    period_start, period_end = period

    transactions = []
    for line in lines:
        cells = _assign_columns(line, columns)
        # A row's own description *data* can start to the left of where the
        # "DESCRIPCION" *header* word itself is drawn — closer to the FECHA
        # (value date) column than its own (confirmed in a second real
        # masked dump: 58pt left of the header). Naive column assignment
        # then swallows the first description word(s) into the FECHA cell.
        # The date is always the leftmost word there (words are assigned in
        # left-to-right order), so anything after it is leaked description,
        # moved to the front of the real DESCRIPCION cell instead.
        fecha_words = cells.get("FECHA", "").split()
        row_date = fecha_words[0] if fecha_words else ""
        stray_words = fecha_words[1:]
        if not _is_row_date(row_date):
            continue  # header row, or an info line like "SALDO ANTERIOR ..."

        charge = cells.get("CARGO", "").strip()
        credit = cells.get("ABONO", "").strip()
        # A printed "0.00" in either column has no monetary effect, same as
        # an empty one — treating it as absent handles both a literal-zero
        # informational row (the real layout prints one) and a row that
        # prints "0.00" in one column alongside the real amount in the
        # other, which would otherwise look like "both a charge and a
        # credit" even though only one of them is a real movement.
        if charge and _money(charge) == 0:
            charge = ""
        if credit and _money(credit) == 0:
            credit = ""
        if charge and credit:
            raise ValueError(f"row {row_date} has both a charge and a credit")
        if charge:
            amount = -_money(charge)
        elif credit:
            amount = _money(credit)
        else:
            continue  # a dated row with no amount isn't a movement

        description_words = [*stray_words, cells.get("DESCRIPCION", "")]
        transactions.append(
            Transaction(
                user_id=user_id,
                bank="BCP",
                account_id=account_id,
                account_last4=account_last4,
                date=_row_date(row_date, period_start, period_end),
                description=normalize_description(" ".join(description_words)),
                amount=amount,
                currency="PEN",
                source_file_sha256=file_sha256,
            )
        )

    statement = Statement(
        user_id=user_id,
        bank="BCP",
        account_id=account_id,
        account_last4=account_last4,
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        transactions=transactions,
    )
    reconcile(statement)
    return statement
