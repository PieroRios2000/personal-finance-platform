"""Tests for ingestion.schema: Transaction/Statement models, hash_account and
normalize_description (T6, ADR 0005 and ADR 0009)."""

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from ingestion.schema import (
    MissingAccountKeyError,
    Statement,
    Transaction,
    hash_account,
    last4_of,
    normalize_description,
)

VALID_ACCOUNT_ID = hashlib.sha256(b"bcp:1234567890123456").hexdigest()
VALID_SHA256 = hashlib.sha256(b"a synthetic statement").hexdigest()


def _transaction_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "user_id": "piero",
        "bank": "BCP",
        "account_id": VALID_ACCOUNT_ID,
        "account_last4": "3456",
        "date": date(2026, 1, 15),
        "description": "COMPRA POS TIENDA",
        "amount": Decimal("-25.50"),
        "currency": "PEN",
        "source_file_sha256": VALID_SHA256,
    }
    kwargs.update(overrides)
    return kwargs


def _statement_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "user_id": "piero",
        "bank": "BCP",
        "account_id": VALID_ACCOUNT_ID,
        "account_last4": "3456",
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 1, 31),
        "opening_balance": Decimal("100.00"),
        "closing_balance": Decimal("74.50"),
        "declared_charges_total": Decimal("25.50"),
        "declared_credits_total": Decimal("0.00"),
        "account_kind": "asset",
        "transactions": [Transaction(**_transaction_kwargs())],
    }
    kwargs.update(overrides)
    return kwargs


# --- Transaction --------------------------------------------------------


def test_transaction_accepts_valid_data() -> None:
    transaction = Transaction(**_transaction_kwargs())
    assert transaction.amount == Decimal("-25.50")


def test_transaction_quantizes_amount_to_two_places() -> None:
    transaction = Transaction(**_transaction_kwargs(amount=Decimal("10.5")))
    assert transaction.amount == Decimal("10.50")


def test_transaction_has_no_full_account_number_field() -> None:
    assert "account_number" not in Transaction.model_fields


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", Decimal("10.123")),  # more than 2 decimal places
        ("amount", Decimal("0.00")),  # no monetary effect isn't a transaction
        ("currency", "EUR"),  # only PEN/USD are supported
        ("account_last4", "1234567890123456"),  # a full account number, not its last 4
        ("account_id", "not-a-hash"),  # account_id must be a sha256 hexdigest
        ("user_id", ""),
        ("bank", ""),
        ("description", ""),
    ],
)
def test_transaction_rejects_invalid_field(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Transaction(**_transaction_kwargs(**{field: value}))


def test_transaction_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Transaction(**_transaction_kwargs(account_number="1234567890123456"))


def test_transaction_is_immutable() -> None:
    transaction = Transaction(**_transaction_kwargs())
    with pytest.raises(ValidationError):
        transaction.amount = Decimal("1.00")


# --- Statement -----------------------------------------------------------


def test_statement_accepts_valid_data() -> None:
    statement = Statement(**_statement_kwargs())
    assert len(statement.transactions) == 1


def test_statement_quantizes_balances_to_two_places() -> None:
    statement = Statement(**_statement_kwargs(opening_balance=Decimal("100.5")))
    assert statement.opening_balance == Decimal("100.50")


def test_statement_allows_a_zero_or_negative_balance() -> None:
    statement = Statement(
        **_statement_kwargs(
            opening_balance=Decimal("0.00"), closing_balance=Decimal("-50.00")
        )
    )
    assert statement.closing_balance == Decimal("-50.00")


def test_statement_rejects_period_end_before_period_start() -> None:
    with pytest.raises(ValidationError):
        Statement(
            **_statement_kwargs(
                period_start=date(2026, 2, 1), period_end=date(2026, 1, 1)
            )
        )


def test_statement_rejects_a_transaction_from_a_different_account() -> None:
    other_account_id = hashlib.sha256(b"a different account").hexdigest()
    mismatched = Transaction(**_transaction_kwargs(account_id=other_account_id))
    with pytest.raises(ValidationError):
        Statement(**_statement_kwargs(transactions=[mismatched]))


def test_statement_accepts_an_asset_account_kind() -> None:
    statement = Statement(**_statement_kwargs(account_kind="asset"))
    assert statement.account_kind == "asset"


def test_statement_accepts_a_liability_account_kind() -> None:
    statement = Statement(**_statement_kwargs(account_kind="liability"))
    assert statement.account_kind == "liability"


def test_statement_rejects_an_unrecognized_account_kind() -> None:
    with pytest.raises(ValidationError):
        Statement(**_statement_kwargs(account_kind="checking"))


def test_statement_requires_account_kind() -> None:
    kwargs = _statement_kwargs()
    del kwargs["account_kind"]
    with pytest.raises(ValidationError):
        Statement(**kwargs)


def test_transaction_has_no_account_kind_field() -> None:
    # account_kind is a Statement-level concept (an account's kind doesn't
    # vary per transaction, the same reasoning opening_balance/closing_balance
    # already live only on Statement).
    assert "account_kind" not in Transaction.model_fields


# --- hash_account ----------------------------------------------------------


def test_hash_account_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")
    assert hash_account("BCP", "111") == hash_account("BCP", "111")


def test_hash_account_changes_with_the_bank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")
    assert hash_account("BCP", "111") != hash_account("SCOTIABANK", "111")


def test_hash_account_changes_with_the_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")
    assert hash_account("BCP", "111") != hash_account("BCP", "222")


def test_hash_account_changes_with_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "key-a")
    first = hash_account("BCP", "111")
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "key-b")
    second = hash_account("BCP", "111")
    assert first != second


def test_hash_account_result_is_a_sha256_hexdigest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PFP_ACCOUNT_KEY", "test-key")
    result = hash_account("BCP", "111")
    assert len(result) == 64
    int(result, 16)  # raises ValueError if it isn't hex


def test_hash_account_raises_a_specific_error_when_the_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PFP_ACCOUNT_KEY", raising=False)
    with pytest.raises(MissingAccountKeyError):
        hash_account("BCP", "111")


# --- last4_of ----------------------------------------------------------


def test_last4_of_takes_the_last_four_digits() -> None:
    assert last4_of("1234567890123456") == "3456"


def test_last4_of_strips_surrounding_whitespace_first() -> None:
    assert last4_of("  1234567890123456  ") == "3456"


def test_last4_of_ignores_dashes() -> None:
    # A real Peruvian bank account number, e.g. "191-48273615-0-37": the last
    # 4 DIGITS are what matters, not the last 4 raw characters ("0-37").
    assert last4_of("191-48273615-0-37") == "5037"


def test_last4_of_ignores_internal_whitespace() -> None:
    assert last4_of("1914 8273 6150 037") == "0037"


def test_last4_of_rejects_a_too_short_number() -> None:
    with pytest.raises(ValueError, match="at least 4 digits"):
        last4_of("12")


def test_last4_of_rejects_too_few_digits_even_with_extra_characters() -> None:
    # 3 digits total even though the raw string is longer than 4 characters.
    with pytest.raises(ValueError, match="at least 4 digits"):
        last4_of("1-2-3")


# --- normalize_description --------------------------------------------


def test_normalize_description_trims_and_uppercases() -> None:
    assert normalize_description("  compra pos  ") == "COMPRA POS"


def test_normalize_description_collapses_repeated_whitespace() -> None:
    assert normalize_description("COMPRA   POS") == "COMPRA POS"


def test_normalize_description_collapses_padding_characters() -> None:
    assert normalize_description("COMPRA POS....VISA") == "COMPRA POS VISA"


def test_normalize_description_same_movement_from_two_statements_matches() -> None:
    first = normalize_description("Compra Pos Tienda Xyz")
    second = normalize_description("COMPRA  POS   TIENDA XYZ")
    assert first == second


def test_normalize_description_is_idempotent() -> None:
    once = normalize_description("  Compra   Pos.... Tienda ")
    assert normalize_description(once) == once
