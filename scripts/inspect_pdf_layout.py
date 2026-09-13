"""Describes a PDF's layout without exposing personal data (T9).

Prints each line (y) per page and its words with horizontal position (x0-x1, in
points). Digits come out as 9 and any text outside HEADERS comes out as X. Never
prints the file's path or its metadata.

    uv run --env-file .env scripts/inspect_pdf_layout.py <pdf> \\
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

# Generic bank-statement words only, with no accents and in uppercase. Never a
# proper name (not even a bank's) or anything that could identify someone.
# Intentionally left in Spanish: these are the literal words printed on the real
# BCP/Scotiabank statements this inspector reads (see CLAUDE.md).
HEADERS = frozenset(
    """
    FECHA FEC PROC VALOR DESCRIPCION DETALLE CONCEPTO OPERACION REFERENCIA NRO NUMERO
    CARGO CARGOS ABONO ABONOS DEBITO CREDITO MONTO IMPORTE MONEDA SOLES DOLARES PEN USD
    SALDO SALDOS INICIAL ANTERIOR FINAL ACTUAL DISPONIBLE CONTABLE TOTAL TOTALES
    ESTADO CUENTA PERIODO PAGINA RESUMEN MOVIMIENTOS DE DEL AL
    """.split()
)


def mask(word: str) -> str:
    """Digits → 9, punctuation unchanged, everything else → X, except known headers."""
    plain = unicodedata.normalize("NFKD", word)
    key = "".join(c for c in plain if not unicodedata.combining(c))
    if key.upper().strip(string.punctuation) in HEADERS:
        return word
    return "".join(
        "9" if c.isdigit() else c if c in string.punctuation else "X" for c in word
    )


def _lines(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group words whose top edge is within 3 pt of each other into the same line."""
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and word["top"] - lines[-1][0]["top"] <= 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def describe(path: Path, password: str = "") -> str:
    # pikepdf tolerates bytes before %PDF- and decrypts; pdfplumber reads the clean copy
    # it produces.
    with pikepdf.open(path, password=password) as pdf:
        encrypted = pdf.is_encrypted
        clean = io.BytesIO()
        pdf.save(clean)

    body: list[str] = []
    no_text: list[int] = []
    with pdfplumber.open(clean) as doc:
        for number, page in enumerate(doc.pages, start=1):
            size = f"{page.width:.0f}x{page.height:.0f} pt"
            body.append(f"\n== Page {number} · {size} ==")
            words = page.extract_words()
            if not words:
                no_text.append(number)
                body.append("(no text layer)")
            for line in _lines(words):
                cells = " | ".join(
                    f"x={w['x0']:.0f}-{w['x1']:.0f} {mask(w['text'])}" for w in line
                )
                body.append(f"y={line[0]['top']:.0f} | {cells}")

        pages = len(doc.pages)

    scanned = ", ".join(map(str, no_text)) or "none"
    summary = [
        f"Encrypted: {'yes' if encrypted else 'no'}",
        f"Pages: {pages}",
        f"Pages without a text layer (scanned): {scanned}",
    ]
    return "\n".join(summary + body)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--password-env",
        metavar="VAR",
        help="environment variable holding the password, e.g. BCP_PDF_PASSWORD",
    )
    args = parser.parse_args(argv)

    password = ""
    if args.password_env:
        password = os.environ.get(args.password_env, "")
        if not password:
            sys.exit(f"{args.password_env} is empty: run with `uv run --env-file .env`")
    try:
        print(describe(args.pdf, password))
    except pikepdf.PasswordError:
        sys.exit("The PDF needs a password, or it's wrong: use --password-env VAR")


if __name__ == "__main__":
    main()
