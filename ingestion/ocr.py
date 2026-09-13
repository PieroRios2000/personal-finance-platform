"""OCR fallback for scanned PDF pages with no text layer (T11b).

Some BCP statement pages are scanned images with no extractable text (T9 found at
least one in the owner's real PDFs). `extract_words()` reads `page` at 300 dpi
(pdfplumber's own `to_image`, backed by Pillow/pypdfium2 — no extra system
dependency) and hands the raster to Tesseract in Spanish.

The result is shaped exactly like `pdfplumber.page.Page.extract_words()`'s own
output — a list of dicts with `text`, `x0`, `x1`, `top` and `bottom` — so
`ingestion.parsers.bcp` can treat OCR'd words exactly like normal ones, with no
separate code path downstream (see `bcp.py`'s `_group_lines`/`_assign_columns`,
which only read `text`, `x0` and `top`).

Coordinate scaling: `extract_words()`'s positions are in PDF points, but the
raster Tesseract reads is in pixels. `page.to_image()` already knows the exact
pixels-per-point ratio for the image it produced (`PageImage.scale`, close to
but not exactly 300/72 — the render rounds to a whole pixel count), so every
Tesseract pixel position is divided by that same ratio, rather than assuming
the nominal 300/72 ≈ 4.1667, to land exactly on pdfplumber's own point-space
coordinates instead of accumulating a rounding error.
"""

from typing import Any

import pdfplumber.page
import pytesseract

Word = dict[str, Any]

_RESOLUTION = 300
_LANGUAGE = "spa"


def extract_words(page: pdfplumber.page.Page) -> list[Word]:
    """OCR `page` and return its words in `extract_words()`'s own shape.

    Skips whitespace-only entries, which Tesseract sometimes returns for
    detected-but-blank regions.
    """
    image = page.to_image(resolution=_RESOLUTION)
    scale = image.scale  # pixels per point, from the actual rendered image size
    data = pytesseract.image_to_data(
        image.original, lang=_LANGUAGE, output_type=pytesseract.Output.DICT
    )

    words: list[Word] = []
    for index, text in enumerate(data["text"]):
        if not text.strip():
            continue
        x0 = data["left"][index] / scale
        top = data["top"][index] / scale
        words.append(
            {
                "text": text,
                "x0": x0,
                "x1": x0 + data["width"][index] / scale,
                "top": top,
                "bottom": top + data["height"][index] / scale,
            }
        )
    return words
