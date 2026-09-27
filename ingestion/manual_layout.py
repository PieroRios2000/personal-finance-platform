"""The manual Excel's layout and the checks that need no secret (T49, ADR 0041).

One workbook, sheets `Ahorros` (savings accounts) and `Inversiones` (funds and
platforms), with the columns the importer reads (docs/manual-data.md). This module
holds those names, builds the template, and checks a workbook's *structure*: the
right sheets and columns, no leftover example rows, a sane size. It does not know
whose workbook it is. The full reading (balances that reconcile, one row at a time)
is `ingestion/manual_excel.py`, which needs the account key. The upload portal, a
container without that key, uses only this file.
"""

import io
import zipfile
from collections.abc import Sequence
from datetime import date

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

SAVINGS_COLUMNS = ("cuenta", "fecha", "descripcion", "monto", "moneda", "saldo_final")
INVESTMENT_COLUMNS = (
    "lugar",
    "fecha",
    "tipo",
    "monto",
    "moneda",
    "saldo_final",
    "nota",
)
SHEET = "Ahorros"
INVESTMENT_SHEET = "Inversiones"
EXAMPLE_PREFIX = "EJEMPLO"

MAX_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # an .xlsx is a zip: refuse a bomb
MAX_ROWS = 20000
_CURRENCIES = ("PEN", "USD")
_TYPES = ("aporte", "retiro", "valorizacion")


def check_workbook(content: bytes) -> list[str]:
    """What is wrong with this workbook's structure, in words and row counts; [] if
    it can go on to the importer. Never a value, a name or a cell's content."""
    if len(content) > MAX_BYTES:
        return ["the file is larger than 5 MB"]
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                sum(e.file_size for e in entries) > MAX_UNCOMPRESSED_BYTES
                or len(entries) > 200
            ):
                return ["the file is far bigger than a workbook of this kind"]
            if any(e.filename.lower().endswith("vbaproject.bin") for e in entries):
                return ["the workbook has macros, which are not accepted"]
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return ["the file is not a readable .xlsx workbook"]
    problems: list[str] = []
    rows_found = 0
    for name, columns in (
        (SHEET, SAVINGS_COLUMNS),
        (INVESTMENT_SHEET, INVESTMENT_COLUMNS),
    ):
        if name not in workbook.sheetnames:
            problems.append(f"the workbook has no '{name}' sheet")
            continue
        sheet = workbook[name]
        rows = list(sheet.iter_rows(values_only=True, max_row=MAX_ROWS + 2))
        header = tuple(rows[0]) if rows else ()
        if header[: len(columns)] != columns:
            problems.append(f"{name}: the columns are not the template's")
            continue
        data = [r for r in rows[1:] if any(v is not None for v in r)]
        if len(data) > MAX_ROWS:
            problems.append(f"{name}: more than {MAX_ROWS} rows")
        examples = sum(
            1 for r in data if isinstance(r[0], str) and r[0].startswith(EXAMPLE_PREFIX)
        )
        if examples:
            problems.append(
                f"{name}: {examples} example row(s) are still in the sheet (EJEMPLO)"
            )
        rows_found += len(data)
    if not problems and rows_found == 0:
        problems.append("both sheets are empty: fill in at least one")
    return problems


_GENERIC_SAVINGS_EXAMPLES = (
    ("EJEMPLO Mi cuenta", date(2026, 1, 5), "deposito de ejemplo", 100, "PEN", 100),
    ("EJEMPLO Mi cuenta", date(2026, 1, 20), "intereses de ejemplo", 1, "PEN", 101),
    ("EJEMPLO Mi cuenta", date(2026, 1, 31), "cierre de mes", 0, "PEN", 101),
)
_GENERIC_INVESTMENT_EXAMPLES = (
    ("EJEMPLO Fondo A", date(2026, 1, 5), "aporte", 100, "PEN", 100, "EJEMPLO"),
    ("EJEMPLO Fondo A", date(2026, 1, 31), "valorizacion", 0, "PEN", 101, "EJEMPLO"),
    ("EJEMPLO Fondo A", date(2026, 2, 10), "retiro", 50, "PEN", 52, "EJEMPLO"),
    ("EJEMPLO Fondo A", date(2026, 2, 28), "valorizacion", 0, "PEN", 52, "EJEMPLO"),
)
GENERIC_INSTRUCTIONS = (
    "Llena al menos una hoja (Ahorros o Inversiones) y borra las filas de ejemplo "
    "(EJEMPLO). La otra hoja puede quedar solo con sus encabezados.",
    "Pon numeros y fechas de Excel, no texto. Un movimiento por fila.",
    "No escribas nombres, numeros de cuenta ni datos personales en ninguna celda.",
    "",
    "HOJA Ahorros (cuentas de ahorro)",
    "cuenta: el nombre de la cuenta, escrito siempre igual.",
    "fecha: la fecha del movimiento.",
    "descripcion: texto corto del movimiento (deposito, intereses, ...).",
    "monto: puede ir con signo (negativo si sale dinero) o sin signo: el sentido se "
    "lee del saldo (si el saldo baja, fue un retiro).",
    "moneda: PEN o USD.",
    "saldo_final: el saldo de la cuenta despues de ese movimiento.",
    "cierre de mes: si en un mes no hubo movimientos, agrega una fila con "
    "descripcion 'cierre de mes', monto 0 y el saldo a fin de mes.",
    "",
    "HOJA Inversiones (fondos y plataformas)",
    "lugar: el nombre del fondo o plataforma, escrito siempre igual.",
    "fecha: la fecha del movimiento o de la valorizacion.",
    "tipo: aporte (pusiste dinero), retiro (sacaste dinero) o valorizacion.",
    "monto: siempre positivo. En una valorizacion, 0.",
    "moneda: PEN o USD, fila por fila.",
    "saldo_final: el saldo total de esa inversion despues de ese movimiento.",
    "nota: opcional, sin datos personales.",
    "valorizacion: una fila por inversion al cierre de cada mes, aunque no hayas "
    "movido nada, con monto 0 y el saldo de ese dia. Sin ella no se puede calcular "
    "cuanto rindio el mes.",
)


def _fill(
    sheet: Worksheet, columns: Sequence[str], rows: Sequence[tuple[object, ...]]
) -> None:
    sheet.append(list(columns))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(list(row))
    for letter in "ABCDEFG"[: len(columns)]:
        sheet.column_dimensions[letter].width = 22
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, date):
                cell.number_format = "yyyy-mm-dd"
            elif isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0.00"
    sheet.freeze_panes = "A2"


def _dropdown(sheet: Worksheet, column: str, values: Sequence[str]) -> None:
    validation = DataValidation(
        type="list", formula1=f'"{",".join(values)}"', allow_blank=True
    )
    validation.error = "Usa uno de los valores de la lista."
    sheet.add_data_validation(validation)
    validation.add(f"{column}2:{column}2000")


def build_workbook(
    *,
    savings_examples: Sequence[tuple[object, ...]],
    investment_examples: Sequence[tuple[object, ...]],
    instructions: Sequence[str],
    places: Sequence[str] | None = None,
) -> Workbook:
    """The template. `places` limits the funds to a drop-down; None leaves them free."""
    workbook = Workbook()
    savings = workbook.active
    assert savings is not None
    savings.title = SHEET
    _fill(savings, SAVINGS_COLUMNS, savings_examples)
    _dropdown(savings, "E", _CURRENCIES)

    investments = workbook.create_sheet(INVESTMENT_SHEET)
    _fill(investments, INVESTMENT_COLUMNS, investment_examples)
    if places:
        _dropdown(investments, "A", places)
    _dropdown(investments, "C", _TYPES)
    _dropdown(investments, "E", _CURRENCIES)

    sheet = workbook.create_sheet("Instrucciones")
    sheet.column_dimensions["A"].width = 120
    for line in instructions:
        sheet.append([line])
    for row in sheet.iter_rows():
        if row[0].value and row[0].value.startswith("HOJA"):
            row[0].font = Font(bold=True)
    return workbook


def generic_template() -> bytes:
    """The template anyone can download from the portal (funds in free text)."""
    buffer = io.BytesIO()
    build_workbook(
        savings_examples=_GENERIC_SAVINGS_EXAMPLES,
        investment_examples=_GENERIC_INVESTMENT_EXAMPLES,
        instructions=GENERIC_INSTRUCTIONS,
    ).save(buffer)
    return buffer.getvalue()
