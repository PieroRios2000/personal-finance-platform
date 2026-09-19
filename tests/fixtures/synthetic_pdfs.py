"""Builds a fictional BCP-style bank statement PDF for tests (T10).

No real PDF ever gets committed to Git: this module renders one at test time with
fpdf2, reusing the header vocabulary that `scripts/inspect_pdf_layout.py`'s HEADERS
leaves unmasked, so the output looks like a plausible BCP statement without holding
any personal data.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class Movement:
    """One fictional transaction row.

    `amount` is signed: negative for a charge (CARGO), positive for a credit (ABONO).
    """

    when: date
    description: str
    amount: Decimal


DEFAULT_MOVEMENTS: tuple[Movement, ...] = (
    Movement(date(2026, 1, 5), "COMPRA TIENDA FICTICIA", Decimal("-120.50")),
    Movement(date(2026, 1, 12), "DEPOSITO SUELDO FICTICIO", Decimal("2500.00")),
    Movement(date(2026, 1, 20), "PAGO SERVICIO FICTICIO", Decimal("-85.30")),
    Movement(date(2026, 1, 28), "TRANSFERENCIA RECIBIDA FICTICIA", Decimal("300.00")),
)

# Obviously-fake account number: never resembles a real one.
_ACCOUNT_NUMBER = "000-00000000-0-00"

# Fixed, non-zero drift used to break the printed closing balance when
# reconciles=False. Its exact value doesn't matter, only that it isn't zero.
_BROKEN_DRIFT = Decimal("37.00")

_COLUMNS = (
    (40, "FECHA"),
    (100, "DESCRIPCION"),
    (280, "CARGO"),
    (350, "ABONO"),
    (460, "SALDO"),
)

# Last y a row may use before the table continues on a new page, comfortably
# inside the default A4 page (841.89 pt tall). A real statement is several
# pages long and repeats its header row on each one, which is what the parser
# groups per page (see ingestion/parsers/bcp.py); without this, extra rows keep
# being drawn past the bottom edge — still extractable, but on an invisible
# single page, which is not what a many-row statement really looks like.
_LAST_ROW_Y = 780


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def bcp_statement_pdf(
    *,
    opening_balance: Decimal = Decimal("1000.00"),
    movements: Sequence[Movement] = DEFAULT_MOVEMENTS,
    closing_balance: Decimal | None = None,
    reconciles: bool = True,
    account_number: str = _ACCOUNT_NUMBER,
) -> bytes:
    """Render a fictional BCP-style statement as PDF bytes.

    One page for the handful of `DEFAULT_MOVEMENTS`; enough movements and the
    table continues on a new page with its header row repeated, the way a real
    multi-page statement does (T15's parsing benchmark renders one).

    By default the statement is coherent: `opening_balance + sum(m.amount for m in
    movements)` equals the closing balance printed at the bottom (SALDO ACTUAL), and
    each row's running balance (SALDO) is consistent with the ones before it. That
    makes it usable to test a parser's reconciliation logic against a *correct*
    statement (T11).

    Pass `reconciles=False` to keep the per-row running balances correct but skew
    the printed closing balance, simulating a statement that fails reconciliation.
    Pass an explicit `closing_balance` to control the printed value directly
    (takes precedence over `reconciles`).

    Pass `account_number` to render a different (still obviously fake) account,
    e.g. to build several statements that a test can tell apart by account (T12b).
    """
    rows: list[tuple[Movement, Decimal]] = []
    running = opening_balance
    for movement in movements:
        running += movement.amount
        rows.append((movement, running))
    computed_closing = running

    if closing_balance is not None:
        printed_closing = closing_balance
    elif reconciles:
        printed_closing = computed_closing
    else:
        printed_closing = computed_closing + _BROKEN_DRIFT

    dates = [movement.when for movement, _ in rows] or [date.today()]
    period_start, period_end = min(dates), max(dates)

    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)

    pdf.text(40, 50, "ESTADO DE CUENTA")
    pdf.text(40, 65, f"CUENTA NRO. {account_number}")
    pdf.text(40, 80, f"PERIODO DEL {period_start:%d/%m/%Y} AL {period_end:%d/%m/%Y}")
    pdf.text(40, 100, f"SALDO ANTERIOR {_money(opening_balance)}")

    header_y = 120
    for x, header in _COLUMNS:
        pdf.text(x, header_y, header)

    row_y = header_y
    for movement, balance in rows:
        row_y += 15
        if row_y > _LAST_ROW_Y:
            pdf.add_page()
            for x, header in _COLUMNS:
                pdf.text(x, header_y, header)
            row_y = header_y + 15
        charge = _money(-movement.amount) if movement.amount < 0 else ""
        credit = _money(movement.amount) if movement.amount > 0 else ""
        pdf.text(40, row_y, f"{movement.when:%d/%m}")
        pdf.text(100, row_y, movement.description)
        pdf.text(280, row_y, charge)
        pdf.text(350, row_y, credit)
        pdf.text(460, row_y, _money(balance))

    if row_y + 20 > _LAST_ROW_Y:
        pdf.add_page()
        row_y = header_y
    pdf.text(40, row_y + 20, f"SALDO ACTUAL {_money(printed_closing)}")

    return bytes(pdf.output())


# Arbitrary scale for the rasterized table image below (T11b); only needs to be
# self-consistent within that one image, since the OCR fallback recovers
# point-space positions from whatever pixels-per-point ratio the *page* (not this
# source image) was actually rendered at — see ingestion/ocr.py.
_SCAN_PX_PER_PT = 4
_SCAN_FONT_SIZE = 32


def _garble(amount: str) -> str:
    """Change the last digit of `amount`, deterministically, standing in for a
    misread character an OCR pass could plausibly produce (T11b)."""
    digits = [c for c in amount if c.isdigit()]
    target = digits[-1]
    replacement = "1" if target != "1" else "2"
    index = amount.rindex(target)
    return amount[:index] + replacement + amount[index + 1 :]


def _table_image(
    rows: Sequence[tuple[Movement, Decimal]],
    page_w: float,
    page_h: float,
    *,
    garble_charge: bool,
) -> Image.Image:
    """Render the FECHA/DESCRIPCION/CARGO/ABONO/SALDO table as one raster image
    sized to exactly cover a page, simulating a scanned page with no text layer.
    """
    image = Image.new(
        "RGB",
        (round(page_w * _SCAN_PX_PER_PT), round(page_h * _SCAN_PX_PER_PT)),
        "white",
    )
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=_SCAN_FONT_SIZE)

    def put(x: float, y: float, text: str) -> None:
        pixel_xy = (x * _SCAN_PX_PER_PT, y * _SCAN_PX_PER_PT)
        draw.text(pixel_xy, text, fill="black", font=font)

    header_y = 120
    for x, header in _COLUMNS:
        put(x, header_y, header)

    row_y = header_y
    garbled = False
    for movement, balance in rows:
        row_y += 15
        charge = _money(-movement.amount) if movement.amount < 0 else ""
        credit = _money(movement.amount) if movement.amount > 0 else ""
        if garble_charge and charge and not garbled:
            charge = _garble(charge)
            garbled = True
        put(40, row_y, f"{movement.when:%d/%m}")
        put(100, row_y, movement.description)
        put(280, row_y, charge)
        put(350, row_y, credit)
        put(460, row_y, _money(balance))

    return image


_SPANISH_MONTH_ABBR = {
    1: "ENE",
    2: "FEB",
    3: "MAR",
    4: "ABR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AGO",
    9: "SET",
    10: "OCT",
    11: "NOV",
    12: "DIC",
}

_REAL_ACCOUNT_NUMBER = "000-00000000-0-00"


def bcp_real_layout_statement_pdf(
    *,
    opening_balance: Decimal = Decimal("1000.00"),
    movements: Sequence[Movement] = DEFAULT_MOVEMENTS,
    closing_balance: Decimal | None = None,
    reconciles: bool = True,
    account_number: str = _REAL_ACCOUNT_NUMBER,
    row_description_x: float = 240,
    zero_and_real_row: Decimal | None = None,
    garble_first_row_charge: bool = False,
) -> bytes:
    """Render a fictional BCP statement matching the *real* layout found in
    T9's masked inspection of the owner's own statement (2026-09), which
    differs from `bcp_statement_pdf`'s original (T10) assumptions in several
    ways confirmed from that masked dump:

    - No "CUENTA NRO." or "PERIODO" labels: the account number is a bare
      `NNN-NNNNNNNN-N-NN`-shaped token near "CUENTA"/"MONEDA" column headers,
      and the date range is just "DEL <date> AL <date>" with no leading label.
    - The period uses a 2-digit year ("DD/MM/YY"), not 4.
    - The transaction table's header row has FECHA *twice* (processing date,
      then value date) and "CARGOS"/"ABONOS" (plural), with no SALDO column.
    - Each row's own date is "DDMMM" (day + 3-letter Spanish month
      abbreviation, no separator, e.g. "05ENE"), not "DD/MM".
    - The closing balance is a bare "SALDO" (no "ACTUAL"/"FINAL" qualifier),
      with its amount one line *above* the label rather than beside it — the
      real dump showed them 8pt apart, past `_group_lines`' 3pt tolerance.
    - A row's own description *data* starts to the left of where the
      "DESCRIPCION" *header* word itself is drawn (58pt left of it in the
      real dump: header at x=181, row data at x=123) — closer to the FECHA
      (value date) header than to its own. `row_description_x` reproduces
      this: it defaults to the DESCRIPCION header's own x (no misalignment,
      matching every other test), but a caller can move it left of that,
      independently of the header, to exercise this specific real trait.
    - A real row can print "0.00" in one of CARGO/ABONO alongside a real
      amount in the other — a third real statement had a row that did
      exactly this. `zero_and_real_row` appends one such row (a "0.00"
      charge plus the given credit amount) after `movements`.
    - Non-numeric text can land in the CARGO/ABONO cell too (a fourth real
      statement crashed the parser outright with a raw `decimal.
      InvalidOperation`, from some other column's boundary mismatch bleeding
      stray text into it). `garble_first_row_charge` reproduces that by
      drawing extra non-numeric text at the CARGO column's position on the
      first row.

    `bcp_statement_pdf` (the original T10 fixture) is left untouched since
    dozens of other tests depend on its exact shape; this is a separate,
    additive fixture used only to test the parser against the real layout.
    """
    rows: list[tuple[Movement, Decimal]] = []
    running = opening_balance
    for movement in movements:
        running += movement.amount
        rows.append((movement, running))
    if zero_and_real_row is not None:
        extra = Movement(
            (movements[-1].when if movements else date.today()),
            "AJUSTE A CERO FICTICIO",
            zero_and_real_row,
        )
        running += extra.amount
        rows.append((extra, running))
    computed_closing = running

    if closing_balance is not None:
        printed_closing = closing_balance
    elif reconciles:
        printed_closing = computed_closing
    else:
        printed_closing = computed_closing + _BROKEN_DRIFT

    dates = [movement.when for movement, _ in rows] or [date.today()]
    period_start, period_end = min(dates), max(dates)

    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)

    pdf.text(40, 50, "ESTADO DE CUENTA")
    pdf.text(40, 65, "TIPO DE CUENTA MONEDA")
    pdf.text(40, 80, f"{account_number} SOLES")
    pdf.text(
        40,
        95,
        f"DEL {period_start:%d/%m/%y} AL {period_end:%d/%m/%y}",
    )
    pdf.text(40, 110, f"SALDO ANTERIOR {_money(opening_balance)}")

    header_y = 130
    pdf.text(40, header_y, "FECHA")
    pdf.text(90, header_y, "PROC.")
    pdf.text(140, header_y, "FECHA")
    pdf.text(190, header_y, "VALOR")
    pdf.text(240, header_y, "DESCRIPCION")
    pdf.text(400, header_y, "CARGOS")
    pdf.text(460, header_y, "ABONOS")

    row_y = header_y
    for row_index, (movement, _) in enumerate(rows):
        row_y += 15
        charge = _money(-movement.amount) if movement.amount < 0 else ""
        credit = _money(movement.amount) if movement.amount > 0 else ""
        if zero_and_real_row is not None and movement.amount == zero_and_real_row:
            charge = _money(Decimal("0.00"))
        if garble_first_row_charge and row_index == 0:
            charge = "REF.A1B2"
        # A different processing date than the value date, so a test can
        # prove the parser reads the *second* FECHA column, not the first.
        proc_date = movement.when.replace(day=max(1, movement.when.day - 1))
        proc_abbr = _SPANISH_MONTH_ABBR[proc_date.month]
        pdf.text(40, row_y, f"{proc_date.day:02d}{proc_abbr}")
        pdf.text(
            140,
            row_y,
            f"{movement.when.day:02d}{_SPANISH_MONTH_ABBR[movement.when.month]}",
        )
        pdf.text(row_description_x, row_y, movement.description)
        pdf.text(400, row_y, charge)
        pdf.text(460, row_y, credit)

    # The amount one line *above* its bare "SALDO" label, mirroring the real
    # dump (y=680 amount, y=688 label — 8pt apart, past the 3pt same-line
    # tolerance `_group_lines` uses).
    pdf.text(400, row_y + 30, _money(printed_closing))
    pdf.text(40, row_y + 40, "SALDO")

    return bytes(pdf.output())


_SCOTIABANK_ACCOUNT_CODE = "00000000"
_SCOTIABANK_CARD_MASKED = "0000-0000-****-0000"


@dataclass(frozen=True)
class ScotiabankMovement:
    """One fictional credit-card movement.

    `amount` is signed for a *debt* balance, the opposite convention from
    `Movement` above: positive for a charge/consumo (increases what's owed),
    negative for a payment/pago (decreases it) — mirroring the real statement's
    own trailing "-" on a payment row, which `scotiabank.py` reads as a sign,
    not a hyphen. `currency` picks which of the statement's two columns
    (Soles/Dólares) the row prints under.
    """

    when: date
    description: str
    currency: str  # "PEN" or "USD"
    amount: Decimal


DEFAULT_SCOTIABANK_MOVEMENTS: tuple[ScotiabankMovement, ...] = (
    ScotiabankMovement(
        date(2026, 1, 5), "COMPRA TIENDA FICTICIA", "PEN", Decimal("150.00")
    ),
    ScotiabankMovement(
        date(2026, 1, 12), "PAGO TARJETA FICTICIO", "PEN", Decimal("-100.00")
    ),
    ScotiabankMovement(
        date(2026, 1, 20), "COMPRA ONLINE FICTICIA", "USD", Decimal("25.50")
    ),
)

_SCOTIA_HEADER_Y = 100
_SCOTIA_CURRENCY_HEADER_Y = 110  # 10pt below: a separate _group_lines line
_SCOTIA_FECHA_PROC_X = 40
_SCOTIA_FECHA_VALOR_X = 140
_SCOTIA_DESCRIPTION_X = 240
_SCOTIA_SOLES_X = 451
_SCOTIA_DOLARES_X = 520


def _scotia_money(amount: Decimal) -> str:
    text = f"{abs(amount):,.2f}"
    return f"{text}-" if amount < 0 else text


def scotiabank_statement_pdf(
    *,
    opening_pen: Decimal | None = Decimal("500.00"),
    opening_usd: Decimal | None = Decimal("0.00"),
    movements: Sequence[ScotiabankMovement] = DEFAULT_SCOTIABANK_MOVEMENTS,
    account_code: str = _SCOTIABANK_ACCOUNT_CODE,
    reconciles: bool = True,
    stray_tags: bool = False,
) -> bytes:
    """Render a fictional, one-page Scotiabank credit-card statement.

    Matches the real layout confirmed from a masked dump (T9, T18): no
    "CUENTA NRO."/"PERIODO" adjacency the way BCP has, a two-line header
    (FECHA x2 + DESCRIPCION, then SOLES/DOLARES on the *next* line), a
    DD-MM-YYYY period, DD/MM/YY row dates (two columns, only the second one
    used, same "value date wins" rule as BCP), a bare 8-digit account code
    (no adjacent label — found by shape) sitting next to a card number the
    bank itself already masks (`0000-0000-****-0000`, present as realistic
    noise the parser must *not* mistake for the account code), "Saldo
    Anterior" with one amount per currency, and a debt balance: a charge has
    no suffix, a payment ends in "-".

    By default the statement reconciles: for each currency, opening + that
    currency's own movements equals the closing balance `Total` declares.
    `reconciles=False` breaks Soles' total by a fixed, non-zero drift, the
    same "keep the per-row math honest, only the printed summary lies"
    contract `bcp_statement_pdf(reconciles=False)` uses.

    `stray_tags=True` adds what a real statement carries on some rows: a
    `(abc:12)` tag to the right of the amount, on the same line (confirmed from
    a real masked dump: `(XXX:99)` past the last column).
    """
    pen_moves = [m for m in movements if m.currency == "PEN"]
    usd_moves = [m for m in movements if m.currency == "USD"]
    pen_total = sum((m.amount for m in pen_moves), Decimal("0.00"))
    usd_total = sum((m.amount for m in usd_moves), Decimal("0.00"))
    # The real "Total" line is the closing balance (opening + the movements),
    # confirmed against real statements: it is what the parser cross-checks.
    printed_pen_total = (
        (opening_pen or Decimal("0.00"))
        + pen_total
        + (_BROKEN_DRIFT if not reconciles else Decimal("0"))
    )
    printed_usd_total = (opening_usd or Decimal("0.00")) + usd_total

    dates = [m.when for m in movements] or [date.today()]
    period_start, period_end = min(dates), max(dates)

    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)

    pdf.text(40, 20, account_code)
    pdf.text(140, 20, _SCOTIABANK_CARD_MASKED)
    pdf.text(
        40,
        50,
        f"PERIODO DE TARJETA DEL {period_start:%d-%m-%Y} AL {period_end:%d-%m-%Y}",
    )
    pdf.text(40, 70, "Saldo Anterior")
    if opening_pen is not None:
        pdf.text(_SCOTIA_SOLES_X, 70, _scotia_money(opening_pen))
    if opening_usd is not None:
        pdf.text(_SCOTIA_DOLARES_X, 70, _scotia_money(opening_usd))

    pdf.text(_SCOTIA_FECHA_PROC_X, _SCOTIA_HEADER_Y, "Fecha")
    pdf.text(_SCOTIA_FECHA_VALOR_X, _SCOTIA_HEADER_Y, "Fecha")
    pdf.text(_SCOTIA_DESCRIPTION_X, _SCOTIA_HEADER_Y, "Descripción")
    pdf.text(_SCOTIA_SOLES_X, _SCOTIA_CURRENCY_HEADER_Y, "Soles")
    pdf.text(_SCOTIA_DOLARES_X, _SCOTIA_CURRENCY_HEADER_Y, "Dólares")

    row_y = _SCOTIA_CURRENCY_HEADER_Y
    for movement in movements:
        row_y += 15
        proc_date = movement.when.replace(day=max(1, movement.when.day - 1))
        pdf.text(_SCOTIA_FECHA_PROC_X, row_y, f"{proc_date:%d/%m/%y}")
        pdf.text(_SCOTIA_FECHA_VALOR_X, row_y, f"{movement.when:%d/%m/%y}")
        pdf.text(_SCOTIA_DESCRIPTION_X, row_y, movement.description)
        amount_x = _SCOTIA_SOLES_X if movement.currency == "PEN" else _SCOTIA_DOLARES_X
        pdf.text(amount_x, row_y, _scotia_money(movement.amount))
        if stray_tags:
            pdf.text(555, row_y, "(abc:12)")

    row_y += 20
    pdf.text(40, row_y, "Total")
    pdf.text(_SCOTIA_SOLES_X, row_y, _scotia_money(printed_pen_total))
    pdf.text(_SCOTIA_DOLARES_X, row_y, _scotia_money(printed_usd_total))

    return bytes(pdf.output())


def bcp_scanned_statement_pdf(
    *,
    opening_balance: Decimal = Decimal("1000.00"),
    movements: Sequence[Movement] = DEFAULT_MOVEMENTS,
    closing_balance: Decimal | None = None,
    reconciles: bool = True,
    garble_amount: bool = False,
) -> bytes:
    """Render the same fictional BCP statement as `bcp_statement_pdf`, but with
    the transaction table on its own page, as a rasterized image with no text
    layer, simulating a scanned page (T11b).

    Page 1 carries the account/period/balance summary as normal vector text:
    `bcp.py` reads those with a regex over `extract_text()`, which the OCR
    fallback doesn't cover — only `extract_words()` does. Page 2 is the scanned
    table; it's only readable through that OCR fallback, so a test parsing this
    fixture successfully exercises it end to end.

    `garble_amount=True` renders one CARGO amount with one digit changed from
    what page 1's declared balances assume, standing in for a misread character
    that `reconcile()` (not this fixture) must catch as `ReconciliationError`.
    """
    rows: list[tuple[Movement, Decimal]] = []
    running = opening_balance
    for movement in movements:
        running += movement.amount
        rows.append((movement, running))
    computed_closing = running

    if closing_balance is not None:
        printed_closing = closing_balance
    elif reconciles:
        printed_closing = computed_closing
    else:
        printed_closing = computed_closing + _BROKEN_DRIFT

    dates = [movement.when for movement, _ in rows] or [date.today()]
    period_start, period_end = min(dates), max(dates)

    pdf = FPDF(unit="pt")
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    pdf.text(40, 50, "ESTADO DE CUENTA")
    pdf.text(40, 65, f"CUENTA NRO. {_ACCOUNT_NUMBER}")
    pdf.text(40, 80, f"PERIODO DEL {period_start:%d/%m/%Y} AL {period_end:%d/%m/%Y}")
    pdf.text(40, 100, f"SALDO ANTERIOR {_money(opening_balance)}")
    pdf.text(40, 115, f"SALDO ACTUAL {_money(printed_closing)}")

    pdf.add_page()
    page_w, page_h = pdf.w, pdf.h
    image = _table_image(rows, page_w, page_h, garble_charge=garble_amount)
    pdf.image(image, x=0, y=0, w=page_w)

    return bytes(pdf.output())
