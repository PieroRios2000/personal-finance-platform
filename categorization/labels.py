"""The category-labels file's layout (T51, ADR 0043): the owner confirms or overrides a
suggested category for each distinct movement description that appears in gold, without
ever typing one from scratch or sending a single description to Claude.

Mirrors `ingestion/manual_layout.py`'s split: this module knows only the *shape* of the
file, never a real description or amount -- those are read and written by
`scripts/export_category_labels.py` and `scripts/import_category_labels.py`, which run
locally and connect straight to the owner's own Postgres.
"""

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from categorization.rules import UNKNOWN

SHEET = "Categorias"
COLUMNS = (
    "bank",
    "description",
    "movements",
    "suggested_category",
    "category",
)
# The owner's own call, kept short on purpose (2026-09-27): each one earns its own line
# in a chart, and "Gastos varios" is always available for anything that doesn't fit --
# narrow the list further only once these stop being enough ("después podemos
# desglosarlo"). Add here, never a random new string in the file --
# import_category_labels.py rejects anything else.
#
# "Alimentacion", "Ingresos" and "Transferencias" (2026-09-27, ADR 0043's amendment)
# fill the gap the original six left open: groceries, income and transfers to someone
# else's account genuinely have nowhere else to go. A transfer to the owner's *own*
# other account (including paying off his own credit card) never reaches this list at
# all -- `export_category_labels.py` excludes every `is_internal_transfer` movement
# before this file is even written (ADR 0017), so it needs no category of its own.
CATEGORIES = (
    "Servicios",
    "Restaurantes",
    "Alimentacion",
    "Viajes",
    "Transporte",
    "Deporte",
    "Ingresos",
    "Transferencias",
    "Gastos varios",
)


def write_template(path: Path, rows: list[tuple[str, str, int, str]]) -> None:
    """One row per (bank, description): `movements` is how many times it appears,
    `suggested_category` the cold-start guess, which may be "Sin categorizar" (no
    rule matched) -- not one of `CATEGORIES`, so never a valid final answer.
    `category` starts equal to the suggestion when it's a real one, "Gastos varios"
    otherwise: always something `read_completed` will accept unedited."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = SHEET
    sheet.append(list(COLUMNS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for bank, description, movements, suggested in rows:
        default = suggested if suggested in CATEGORIES else "Gastos varios"
        sheet.append([bank, description, movements, suggested, default])
    sheet.column_dimensions["B"].width = 60
    for letter in ("A", "C", "D", "E"):
        sheet.column_dimensions[letter].width = 20
    sheet.freeze_panes = "A2"

    instructions = workbook.create_sheet("Instrucciones")
    instructions.column_dimensions["A"].width = 100
    for line in (
        "Column 'category' starts equal to the suggested one: leave it if it's right,",
        "type over it (one of the list below) if it's wrong.",
        "",
        "Categories: " + ", ".join(CATEGORIES),
        "",
        "Rows are grouped by description, not one row per movement: 'movements' says",
        "how many transactions share that exact wording.",
    ):
        instructions.append([line])
    workbook.save(path)


def read_completed(
    path: Path,
) -> tuple[list[tuple[str, str, str, bool]], list[str]]:
    """`([(bank, description, category, is_trusted), ...], problems)`. A problem
    names a row number and what's wrong, never a value; on any problem the rows list
    is empty.

    `is_trusted` is false exactly when `category` still equals `suggested_category`
    and that suggestion wasn't `UNKNOWN` -- the owner accepted the rules-based
    guesser's opinion unreviewed. Measuring the rules baseline against a label the
    rules themselves proposed is circular (reviewer feedback, 2026-09-27): a
    corrected row, or a row the rules had no opinion on to begin with (`UNKNOWN`),
    carries the owner's own judgment and is trusted; an accepted non-`UNKNOWN`
    suggestion might just be the owner not looking closely."""
    try:
        workbook = load_workbook(path, data_only=True)
    except Exception:  # not a readable .xlsx workbook, any reason
        return [], ["the file is not a readable .xlsx workbook"]
    if SHEET not in workbook.sheetnames:
        return [], [f"the workbook has no '{SHEET}' sheet"]
    sheet: Worksheet = workbook[SHEET]
    header = tuple(c.value for c in sheet[1])
    if header[: len(COLUMNS)] != COLUMNS:
        return [], [f"{SHEET}: the columns are not the template's"]

    rows: list[tuple[str, str, str, bool]] = []
    problems: list[str] = []
    for row_number, cells in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
        if not any(cells):
            continue
        bank, description, _movements, suggested, category = cells[: len(COLUMNS)]
        if not bank or not description:
            problems.append(f"row {row_number}: bank or description is empty")
            continue
        if category not in CATEGORIES:
            problems.append(f"row {row_number}: category is not one of the list")
            continue
        is_trusted = category != suggested or suggested == UNKNOWN
        rows.append((str(bank), str(description), str(category), is_trusted))
    return ([], problems) if problems else (rows, [])
