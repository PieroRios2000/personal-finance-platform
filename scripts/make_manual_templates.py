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

from ingestion.manual_layout import build_workbook

DEFAULT_OUT_DIR = Path.home() / "finance-data" / "manual"
TEMPLATE_NAME = "plantilla-finanzas-manual.xlsx"


_PLACES = ("Tyba fondo 1", "Tyba fondo 2", "Tyba fondo 3", "Flip")
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
    "monto: puede ir con signo (negativo si sale dinero) o sin signo: el sentido se "
    "lee del saldo (si el saldo baja, fue un retiro).",
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


def write_template(path: Path) -> None:
    build_workbook(
        savings_examples=_SAVINGS_EXAMPLES,
        investment_examples=_INVESTMENT_EXAMPLES,
        instructions=_INSTRUCTIONS,
        places=_PLACES,
    ).save(path)


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
