"""Verifies a Statement's numbers add up against what the PDF itself declares (T8).

`reconcile()` checks that the opening balance plus every transaction's signed amount
equals the closing balance, and — only when the statement declares them, since not
every bank prints both — that the total charges and total credits match too. Any
mismatch raises `ReconciliationError` with the expected value, the actual one, and
their difference, so a caller can report exactly what's off instead of just "it
doesn't match."
"""

from decimal import Decimal

from ingestion.schema import Statement


class ReconciliationError(Exception):
    """A statement's declared numbers don't match what its transactions add up to."""

    def __init__(self, check: str, expected: Decimal, actual: Decimal) -> None:
        self.check = check
        self.expected = expected
        self.actual = actual
        self.difference = actual - expected
        super().__init__(
            f"{check}: expected {expected}, got {actual} "
            f"(difference {self.difference:+})"
        )


def reconcile(statement: Statement) -> None:
    """Raise `ReconciliationError` if `statement`'s numbers don't add up.

    Checks the closing balance unconditionally. Checks the declared charges and
    credits totals only when the statement actually declares them.
    """
    total_movement = sum(
        (transaction.amount for transaction in statement.transactions), Decimal("0")
    )
    actual_closing = statement.opening_balance + total_movement
    if actual_closing != statement.closing_balance:
        raise ReconciliationError(
            "closing balance", statement.closing_balance, actual_closing
        )

    if statement.declared_charges_total is not None:
        actual_charges = -sum(
            (t.amount for t in statement.transactions if t.amount < 0), Decimal("0")
        )
        if actual_charges != statement.declared_charges_total:
            raise ReconciliationError(
                "charges total", statement.declared_charges_total, actual_charges
            )

    if statement.declared_credits_total is not None:
        actual_credits = sum(
            (t.amount for t in statement.transactions if t.amount > 0), Decimal("0")
        )
        if actual_credits != statement.declared_credits_total:
            raise ReconciliationError(
                "credits total", statement.declared_credits_total, actual_credits
            )
