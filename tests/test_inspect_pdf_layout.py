import io
from pathlib import Path

import pikepdf
import pytest
from fpdf import FPDF
from PIL import Image

from scripts.inspect_pdf_layout import main, mask

# Datos ficticios que nunca deben aparecer en la salida del inspector.
NAME = "ROSALINDA QUISPECAHUA"
ACCOUNT = "191-48273615-0-37"
MERCHANT = "BODEGA SANTA ROSITA"
AMOUNTS = ["1,234.56", "87.10", "10,480.02"]


def statement_pdf() -> bytes:
    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.text(40, 60, f"CLIENTE {NAME}")
    pdf.text(40, 75, f"CUENTA {ACCOUNT}")
    headers = [(40, "FECHA"), (110, "DESCRIPCIÓN"), (330, "CARGO"), (490, "SALDO")]
    for x, header in headers:
        pdf.text(x, 110, header)
    for row, amount in enumerate(AMOUNTS):
        y = 125 + 15 * row
        pdf.text(40, y, "03/05")
        pdf.text(110, y, MERCHANT)
        pdf.text(330, y, amount)
    return bytes(pdf.output())


def save_encrypted(path: Path, user_password: str) -> None:
    with pikepdf.open(io.BytesIO(statement_pdf())) as plain:
        plain.save(path, encryption=pikepdf.Encryption(owner="x", user=user_password))


def run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    main(list(args))
    return capsys.readouterr().out


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("DESCRIPCIÓN", "DESCRIPCIÓN"),
        ("Saldo:", "Saldo:"),
        ("QUISPE", "XXXXXX"),
        ("José", "XXXX"),
        ("S/1,234.56", "X/9,999.99"),
        ("03/05", "99/99"),
    ],
)
def test_mask_keeps_known_headers_and_hides_the_rest(word: str, expected: str) -> None:
    assert mask(word) == expected


def test_output_hides_synthetic_personal_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = tmp_path / f"estado {NAME}.pdf"
    pdf.write_bytes(statement_pdf())

    out = run(capsys, str(pdf))

    for secret in [*NAME.split(), ACCOUNT, *MERCHANT.split(), *AMOUNTS]:
        assert secret not in out
    assert "DESCRIPCIÓN" in out
    assert "9,999.99" in out


def test_opens_pdf_with_bytes_before_the_header(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = tmp_path / "prefijo.pdf"
    pdf.write_bytes(b"$BOP$" + statement_pdf())

    out = run(capsys, str(pdf))

    assert "Cifrado: no" in out
    assert "FECHA" in out


def test_unlocks_encrypted_pdf_with_password_from_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "cifrado.pdf"
    save_encrypted(pdf, "clave-sintetica")
    monkeypatch.setenv("BCP_PDF_PASSWORD", "clave-sintetica")

    out = run(capsys, str(pdf), "--password-env", "BCP_PDF_PASSWORD")

    assert "Cifrado: sí" in out
    assert "SALDO" in out


def test_encrypted_pdf_without_password_exits_with_a_hint(tmp_path: Path) -> None:
    pdf = tmp_path / "cifrado.pdf"
    save_encrypted(pdf, "clave-sintetica")

    with pytest.raises(SystemExit, match="contraseña"):
        main([str(pdf)])


def test_reports_pages_without_text_layer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.text(40, 60, "SALDO")
    pdf.add_page()
    pdf.image(Image.new("RGB", (200, 100), "gray"), x=40, y=60, w=400)
    path = tmp_path / "escaneado.pdf"
    path.write_bytes(bytes(pdf.output()))

    out = run(capsys, str(path))

    assert "Páginas sin capa de texto (escaneadas): 2" in out
