"""Describe el layout de un PDF sin exponer datos personales (T9).

Imprime por página cada línea (y) y sus palabras con posición horizontal (x0-x1, en
puntos). Los dígitos salen como 9 y todo texto fuera de HEADERS sale como X. No
imprime la ruta ni los metadatos del archivo.

    uv run --env-file .env scripts/inspect_pdf_layout.py <pdf> \
        --password-env BCP_PDF_PASSWORD
"""

import argparse
import io
import os
import string
import sys
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pdfplumber
import pikepdf

# Solo palabras genéricas de estados de cuenta, sin tildes y en mayúsculas.
# Nunca nombres propios (tampoco de bancos) ni nada que identifique a alguien.
HEADERS = frozenset(
    """
    FECHA FEC PROC VALOR DESCRIPCION DETALLE CONCEPTO OPERACION REFERENCIA NRO NUMERO
    CARGO CARGOS ABONO ABONOS DEBITO CREDITO MONTO IMPORTE MONEDA SOLES DOLARES PEN USD
    SALDO SALDOS INICIAL ANTERIOR FINAL ACTUAL DISPONIBLE CONTABLE TOTAL TOTALES
    ESTADO CUENTA PERIODO PAGINA RESUMEN MOVIMIENTOS DE DEL AL
    """.split()
)


def mask(word: str) -> str:
    """Dígitos → 9, puntuación igual y lo demás → X, salvo encabezados conocidos."""
    plain = unicodedata.normalize("NFKD", word)
    key = "".join(c for c in plain if not unicodedata.combining(c))
    if key.upper().strip(string.punctuation) in HEADERS:
        return word
    return "".join(
        "9" if c.isdigit() else c if c in string.punctuation else "X" for c in word
    )


def _lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Agrupa palabras cuya parte superior está a 3 pt o menos en la misma línea."""
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and word["top"] - lines[-1][0]["top"] <= 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def describe(path: Path, password: str = "") -> str:
    # pikepdf tolera bytes antes de %PDF- y descifra; pdfplumber lee la copia limpia.
    with pikepdf.open(path, password=password) as pdf:
        encrypted = pdf.is_encrypted
        clean = io.BytesIO()
        pdf.save(clean)

    body: list[str] = []
    no_text: list[int] = []
    with pdfplumber.open(clean) as doc:
        for number, page in enumerate(doc.pages, start=1):
            body.append(
                f"\n== Página {number} · {page.width:.0f}x{page.height:.0f} pt =="
            )
            words = page.extract_words()
            if not words:
                no_text.append(number)
                body.append("(sin capa de texto)")
            for line in _lines(words):
                cells = " | ".join(
                    f"x={w['x0']:.0f}-{w['x1']:.0f} {mask(w['text'])}" for w in line
                )
                body.append(f"y={line[0]['top']:.0f} | {cells}")

        pages = len(doc.pages)

    scanned = ", ".join(map(str, no_text)) or "ninguna"
    summary = [
        f"Cifrado: {'sí' if encrypted else 'no'}",
        f"Páginas: {pages}",
        f"Páginas sin capa de texto (escaneadas): {scanned}",
    ]
    return "\n".join(summary + body)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--password-env",
        metavar="VAR",
        help="variable de entorno con la contraseña, p. ej. BCP_PDF_PASSWORD",
    )
    args = parser.parse_args(argv)

    password = ""
    if args.password_env:
        password = os.environ.get(args.password_env, "")
        if not password:
            sys.exit(
                f"{args.password_env} está vacía: corre con `uv run --env-file .env`"
            )
    try:
        print(describe(args.pdf, password))
    except pikepdf.PasswordError:
        sys.exit("El PDF pide contraseña o no es la correcta: usa --password-env VAR")


if __name__ == "__main__":
    main()
