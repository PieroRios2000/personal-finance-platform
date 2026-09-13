"""Tests for ingestion.reconciliation: a Statement's numbers must add up (T8)."""

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from ingestion.reconciliation import ReconciliationError, reconcile
from ingestion.schema import Statement, Transaction

VALID_ACCOUNT_ID = hashlib.sha256(b"bcp:reconciliation-tests").hexdigest()
VALID_SHA256 = hashlib.sha256(b"a synthetic statement").hexdigest()


def _statement(**overrides: Any) -> Statement:
    kwargs: dict[str, Any] = {
        "user_id": "piero",
        "bank": "BCP",
        "account_id": VALID_ACCOUNT_ID,
        "account_last4": "1234",
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 1, 31),
        "opening_balance": Decimal("100.00"),
        "closing_balance": Decimal("100.00"),
        "transactions": [],
    }
    kwargs.update(overrides)
    return Statement(**kwargs)


def _transaction(amount: Decimal, **overrides: Any) -> Transaction:
    kwargs: dict[str, Any] = {
        "user_id": "piero",
        "bank": "BCP",
        "account_id": VALID_ACCOUNT_ID,
        "account_last4": "1234",
        "date": date(2026, 1, 15),
        "description": "TEST MOVEMENT",
        "amount": amount,
        "currency": "PEN",
        "source_file_sha256": VALID_SHA256,
    }
    kwargs.update(overrides)
    return Transaction(**kwargs)


def test_reconcile_passes_on_an_exact_match() -> None:
    statement = _statement(
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("74.50"),
        transactions=[_transaction(Decimal("-25.50"))],
    )

    reconcile(statement)  # must not raise


def test_reconcile_fails_on_a_one_cent_mismatch() -> None:
    statement = _statement(
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("74.51"),
        transactions=[_transaction(Decimal("-25.50"))],
    )

    with pytest.raises(ReconciliationError) as exc_info:
        reconcile(statement)

    error = exc_info.value
    assert error.check == "closing balance"
    assert error.expected == Decimal("74.51")
    assert error.actual == Decimal("74.50")
    assert error.difference == Decimal("-0.01")


def test_reconcile_passes_on_a_statement_with_no_transactions() -> None:
    statement = _statement(
        opening_balance=Decimal("100.00"), closing_balance=Decimal("100.00")
    )

    reconcile(statement)


def test_reconcile_checks_declared_charges_total_when_present() -> None:
    statement = _statement(
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("74.50"),
        declared_charges_total=Decimal("30.00"),  # the transaction only charges 25.50
        transactions=[_transaction(Decimal("-25.50"))],
    )

    with pytest.raises(ReconciliationError) as exc_info:
        reconcile(statement)

    assert exc_info.value.check == "charges total"
    assert exc_info.value.expected == Decimal("30.00")
    assert exc_info.value.actual == Decimal("25.50")


def test_reconcile_checks_declared_credits_total_when_present() -> None:
    statement = _statement(
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("150.00"),
        declared_credits_total=Decimal("60.00"),  # the transaction only credits 50.00
        transactions=[_transaction(Decimal("50.00"))],
    )

    with pytest.raises(ReconciliationError) as exc_info:
        reconcile(statement)

    assert exc_info.value.check == "credits total"
    assert exc_info.value.expected == Decimal("60.00")
    assert exc_info.value.actual == Decimal("50.00")


def test_reconcile_skips_totals_the_statement_does_not_declare() -> None:
    statement = _statement(
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("74.50"),
        transactions=[_transaction(Decimal("-25.50"))],
    )  # declared_charges_total / declared_credits_total left as None

    reconcile(statement)  # nothing to compare them against, so nothing fails
