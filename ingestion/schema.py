"""Transaction and Statement schema, shared across every bank parser (T6).

Design decisions are recorded as ADR 0005 and ADR 0009 in `brain/decisions/`.
In short:

- No field ever holds a full, untruncated account number. Only `account_id` (an
  HMAC-SHA256 of the bank and the real number, keyed by the `PFP_ACCOUNT_KEY`
  secret) and `account_last4` exist on these models, so there's nothing to leak
  by construction: a caller can't even accidentally pass the full number where
  `account_last4` is expected, since that field is validated to be exactly 4
  digits.
- `amount` is a signed `Decimal`, quantized to exactly 2 decimal places:
  negative for a debit, positive for a credit. A zero amount is rejected (a
  movement with no monetary effect isn't a transaction); more than 2 decimal
  places is rejected rather than silently rounded, since extra precision on a
  bank statement almost always signals a parsing bug, not real data.
- `currency` is restricted to the two currencies this project handles
  (`PEN`, `USD`); anything else is rejected at validation time.
- `Statement.account_kind` says what an account's balance *represents*: `"asset"` for
  money on hand (BCP checking), `"liability"` for debt owed (Scotiabank credit card).
  It lives on `Statement`, not `Transaction` — a bank's product type doesn't vary per
  statement, the same reasoning `opening_balance`/`closing_balance` already follow.
  See ADR 0014.
"""

import hashlib
import hmac
import os
import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Currency = Literal["PEN", "USD"]
AccountKind = Literal["asset", "liability"]

# A sha256 hexdigest; account_id is one too, being an HMAC-SHA256.
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"
_LAST4_PATTERN = r"^\d{4}$"


class MissingAccountKeyError(RuntimeError):
    """Raised by `hash_account` when `PFP_ACCOUNT_KEY` isn't set.

    See SETUP.md for how to generate and back up this secret: losing it changes
    every `account_id` derived from it, i.e. re-processing everything from the
    original PDFs (risk noted in `tasks/plan.md`).
    """


def hash_account(bank: str, number: str) -> str:
    """Derive an `account_id`: HMAC-SHA256 of `bank` and `number`.

    Keyed by the `PFP_ACCOUNT_KEY` secret, read from the environment and never
    hardcoded, so the same bank + number always maps to the same id on this
    installation, and nobody without the key can recover `number` from it — a
    plain, unkeyed hash wouldn't do, since there are few possible account
    numbers and they could all be tried.
    """
    key = os.environ.get("PFP_ACCOUNT_KEY")
    if not key:
        raise MissingAccountKeyError(
            "PFP_ACCOUNT_KEY is not set. Copy .env.example to .env, generate a "
            "key (see SETUP.md, e.g. `openssl rand -hex 32`), and back it up "
            "outside the repo: losing it changes every account_id."
        )
    # A null byte can't appear in a bank name or account number, so it can't be
    # used to make two different (bank, number) pairs collide the way a plain
    # separator like ":" theoretically could.
    message = bank.encode() + b"\x00" + number.encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def last4_of(number: str) -> str:
    """Return the last 4 digits of a real account number.

    Real account numbers can include separators (e.g. a Peruvian format like
    "191-48273615-0-37"), so this ignores anything that isn't a digit rather
    than taking the last 4 raw characters, which could be mostly punctuation.
    Applied to the number before it's hashed and discarded: nothing longer
    than this ever reaches a `Transaction` or `Statement`.
    """
    digits = re.sub(r"\D", "", number)
    if len(digits) < 4:
        raise ValueError("account number must have at least 4 digits")
    return digits[-4:]


# Characters some banks use to pad a fixed-width description column
# ("COMPRA POS....VISA"). Deliberately conservative: without T9's masked
# layout dump we can't tell an embedded reference number apart from a
# merchant name that happens to contain digits, so digits are never touched.
_PADDING_RUN = re.compile(r"[.\-_*#]{2,}")
_WHITESPACE = re.compile(r"\s+")


def normalize_description(description: str) -> str:
    """Normalize a transaction description so the same movement always
    produces the same string, even across two different statements.

    Rules, in order:
    1. Collapse runs of 2+ fixed-width padding characters (`_PADDING_RUN`)
       into one space.
    2. Collapse repeated whitespace into one space.
    3. Strip leading/trailing whitespace.
    4. Upper case (banks are inconsistent about case between statements).
    """
    text = _PADDING_RUN.sub(" ", description)
    text = _WHITESPACE.sub(" ", text)
    return text.strip().upper()


def _quantize_money(value: Decimal) -> Decimal:
    """Round to at most 2 decimal places, rejecting anything more precise."""
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise ValueError("amount cannot have more than 2 decimal places")
    return value.quantize(Decimal("0.01"))


class Transaction(BaseModel):
    """One bank movement, already attributed to a user and an account."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(min_length=1)
    bank: str = Field(min_length=1)
    account_id: str = Field(pattern=_SHA256_HEX_PATTERN)
    account_last4: str = Field(pattern=_LAST4_PATTERN)
    date: date
    description: str = Field(min_length=1)
    amount: Decimal
    currency: Currency
    source_file_sha256: str = Field(pattern=_SHA256_HEX_PATTERN)

    @field_validator("amount")
    @classmethod
    def _validate_amount(cls, value: Decimal) -> Decimal:
        quantized = _quantize_money(value)
        if quantized == 0:
            raise ValueError("a transaction amount cannot be zero")
        return quantized


class Statement(BaseModel):
    """One statement period for a user's account, with its transactions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str = Field(min_length=1)
    bank: str = Field(min_length=1)
    account_id: str = Field(pattern=_SHA256_HEX_PATTERN)
    account_last4: str = Field(pattern=_LAST4_PATTERN)
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    declared_charges_total: Decimal | None = None
    declared_credits_total: Decimal | None = None
    account_kind: AccountKind
    transactions: list[Transaction] = Field(default_factory=list)

    @field_validator(
        "opening_balance",
        "closing_balance",
        "declared_charges_total",
        "declared_credits_total",
    )
    @classmethod
    def _validate_balance(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return _quantize_money(value)

    @model_validator(mode="after")
    def _validate_consistency(self) -> "Statement":
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot be before period_start")
        for transaction in self.transactions:
            if (transaction.user_id, transaction.bank, transaction.account_id) != (
                self.user_id,
                self.bank,
                self.account_id,
            ):
                raise ValueError(
                    "every transaction in a statement must belong to the "
                    "same user, bank and account as the statement"
                )
        return self
