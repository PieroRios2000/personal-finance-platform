"""Writes the Excel template for data the banks do not export as statements:
savings-account movements (Banco Ripley) and investments (Tyba funds, Flip).

    uv run python -m scripts.make_manual_templates [--out-dir ~/finance-data/manual]

One workbook, three sheets: `Ahorros`, `Inversiones` and `Instrucciones`. Every
example row is invented (the `EJEMPLO` marker); the owner fills a copy named
`finanzas-manual.xlsx` in the same folder, and this script never writes that
name. The columns are what the importer will read (docs/manual-data.md).
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

DEFAULT_OUT_DIR = Path.home() / "finance-data" / "manual"
TEMPLATE_NAME = "plantilla-finanzas-manual.xlsx"

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

_PLACES = ("Tyba fondo 1", "Tyba fondo 2", "Tyba fondo 3", "Flip")
_TYPES = ("aporte", "retiro", "valorizacion")
_CURRENCIES = ("PEN", "USD")

_SAVINGS_EXAMPLES = (
    (
        "EJEMPLO Ripley ahorros",
        date(2026, 1, 5),
        "deposito de ejemplo",
        100,
        "PEN",
        100,
    ),
    (
        "EJEMPLO Ripley ahorros",
        date(2026, 1, 20),
        "intereses de ejemplo",
        1,
        "PEN",
        101,
    ),
    ("EJEMPLO Ripley ahorros", date(2026, 1, 31), "cierre de mes", 0, "PEN", 101),
)
_INVESTMENT_EXAMPLES = (
    ("Tyba fondo 1", date(2026, 1, 5), "aporte", 100, "PEN", 100, "EJEMPLO"),
    ("Tyba fondo 1", date(2026, 1, 31), "valorizacion", 0, "PEN", 101, "EJEMPLO"),
    ("Tyba fondo 1", date(2026, 2, 10), "retiro", 50, "PEN", 52, "EJEMPLO"),
    ("Tyba fondo 1", date(2026, 2, 28), "valorizacion", 0, "PEN", 52, "EJEMPLO"),
)

_INSTRUCTIONS = (
    "Rellena las hojas Ahorros e Inversiones. Borra las filas de ejemplo (EJEMPLO).",
    "Pon numeros y fechas de Excel, no texto. Un movimiento por fila.",
    "No escribas nombres, numeros de cuenta ni datos personales en ninguna celda.",
    "",
    "HOJA Ahorros (cuentas de ahorro: Banco Ripley y otras)",
    "cuenta: el nombre de la cuenta, escrito siempre igual.",
    "fecha: la fecha del movimiento.",
    "descripcion: texto corto del movimiento (deposito, intereses, ...).",
    "monto: con signo. Positivo si entra dinero, negativo si sale.",
    "moneda: PEN o USD.",
    "saldo_final: el saldo de la cuenta despues de ese movimiento.",
    "cierre de mes: si en un mes no hubo movimientos, agrega una fila con "
    "descripcion 'cierre de mes', monto 0 y el saldo a fin de mes. Asi se sabe que "
    "el mes existe y con que saldo cerro.",
    "",
    "HOJA Inversiones (fondos y plataformas)",
    "lugar: Tyba fondo 1, Tyba fondo 2, Tyba fondo 3 o Flip, escrito siempre igual.",
    "fecha: la fecha del movimiento o de la valorizacion.",
    "tipo: aporte (pusiste dinero), retiro (sacaste dinero) o valorizacion.",
    "monto: siempre positivo. En una valorizacion, 0.",
    "moneda: PEN o USD, fila por fila.",
    "saldo_final: el saldo total de esa inversion despues de ese movimiento.",
    "nota: opcional, sin datos personales.",
    "valorizacion: una fila por inversion al cierre de cada mes, aunque no hayas "
    "movido nada, con monto 0 y el saldo de ese dia. Sin ella no se puede calcular "
    "cuanto rindio el mes: el rendimiento es lo que cambia el saldo sin que tu "
    "pusieras o sacaras nada.",
    "",
    "Si un fondo cobra comision o hay impuestos, avisa: se agrega una columna.",
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


def write_template(path: Path) -> None:
    workbook = Workbook()
    savings = workbook.active
    assert savings is not None
    savings.title = "Ahorros"
    _fill(savings, SAVINGS_COLUMNS, _SAVINGS_EXAMPLES)
    _dropdown(savings, "E", _CURRENCIES)

    investments = workbook.create_sheet("Inversiones")
    _fill(investments, INVESTMENT_COLUMNS, _INVESTMENT_EXAMPLES)
    _dropdown(investments, "A", _PLACES)
    _dropdown(investments, "C", _TYPES)
    _dropdown(investments, "E", _CURRENCIES)

    instructions = workbook.create_sheet("Instrucciones")
    instructions.column_dimensions["A"].width = 120
    for line in _INSTRUCTIONS:
        instructions.append([line])
    for row in instructions.iter_rows():
        if row[0].value and row[0].value.startswith("HOJA"):
            row[0].font = Font(bold=True)
    workbook.save(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_manual_templates")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    out: Path = args.out_dir
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = out / TEMPLATE_NAME
    write_template(target)
    target.chmod(0o600)
    print(f"wrote {target}")
    print("Copy it as finanzas-manual.xlsx in the same folder and fill in that copy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
