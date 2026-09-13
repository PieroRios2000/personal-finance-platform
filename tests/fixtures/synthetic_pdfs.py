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
    """Render a fictional, one-page BCP-style statement as PDF bytes.

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
        charge = _money(-movement.amount) if movement.amount < 0 else ""
        credit = _money(movement.amount) if movement.amount > 0 else ""
        pdf.text(40, row_y, f"{movement.when:%d/%m}")
        pdf.text(100, row_y, movement.description)
        pdf.text(280, row_y, charge)
        pdf.text(350, row_y, credit)
        pdf.text(460, row_y, _money(balance))

    pdf.text(40, row_y + 20, f"SALDO ACTUAL {_money(printed_closing)}")

    return bytes(pdf.output())
