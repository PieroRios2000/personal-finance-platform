"""silver.internal_transfers / silver.unmatched_transfers, and the
is_internal_transfer flag on silver.transactions (T18b).

Reuses tests/test_dbt_silver_integration.py's own `_write()` helper,
`_dbt_build()` runner and lake-wiping logic (`_skip_reason`/`_wipe_test_lake`,
plain functions, not the `lake` fixture object itself -- see `lake` below)
rather than re-inventing them: this is the exact same "seed bronze directly,
run `dbt build`, check what comes out" pattern T16/T18a/T18c already
established, just against a new set of models. See that file's own docstring
for why a dedicated lake prefix is what makes this deterministic.

`lake` is redefined here rather than imported: a fixture used across files
still has to appear as that exact parameter name in every test signature for
pytest's own dependency injection to find it, and importing a fixture object
under the name a test signature must also use trips ruff's F811
("redefinition") on every test that takes it. Two independent `lake`
fixtures, each named the same but scoped to their own module, is the
ordinary, conflict-free way two test files share a fixture's *shape* without
either importing the other's fixture object.

Deselected by default, like the rest of the dbt integration suite: needs SeaweedFS
running (`make poc-up`, T13) with `.env` exported into the shell. Run with
`pytest -m integration`.
"""

import hashlib
import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ingestion.schema import AccountKind, Currency, Statement, Transaction
from lakehouse import bronze
from tests import pg_store
from tests.test_dbt_silver_integration import (
    _ACCOUNT_ID,
    _BANK,
    _LAST4,
    _SCOTIABANK_ACCOUNT_ID,
    _TEST_LAKE_SUFFIX,
    _USER_ID,
    _dbt_build,
    _skip_reason,
    _wipe_test_lake,
    _write,
)

pytestmark = pytest.mark.integration

_BCP_ACCOUNT_B_ID = hashlib.sha256(b"t18b-bcp-account-b").hexdigest()
_BCP_ACCOUNT_C_ID = hashlib.sha256(b"t18b-bcp-account-c").hexdigest()
_BCP_ACCOUNT_D_ID = hashlib.sha256(b"t18b-bcp-account-d").hexdigest()


@pytest.fixture
def lake() -> Iterator[str]:
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)

    uri = f"{os.environ['LAKEHOUSE_URI'].rstrip('/')}/{_TEST_LAKE_SUFFIX}"
    previous = os.environ["LAKEHOUSE_URI"]
    os.environ["LAKEHOUSE_URI"] = uri
    try:
        _wipe_test_lake()
        yield uri
        _wipe_test_lake()
    finally:
        os.environ["LAKEHOUSE_URI"] = previous


def _movement(
    *,
    when: date,
    amount: str,
    bank: str = "BCP",
    account_id: str = _ACCOUNT_ID,
    account_kind: AccountKind = "asset",
    currency: Currency = "PEN",
) -> None:
    """One statement whose only transaction is dated `when`, for exactly `amount`.

    A thin, single-purpose wrapper over `_write()`: T18b's matching logic only
    cares about a movement's own date/amount/account/currency/account_kind, never
    the statement period it belongs to (period_start == period_end == `when` is
    a perfectly valid one-day period, and there's no continuity rule spanning
    *different* accounts for this test file to worry about breaking).
    """
    _write(
        when,
        when,
        "0.00",
        amount,
        bank=bank,
        account_id=account_id,
        account_kind=account_kind,
        currency=currency,
    )


def _write_duplicate_pair(*, when: date, amount: str) -> None:
    """Two genuinely identical transactions (same user/account/date/amount/
    currency/description/source file) in *one* statement -- the exact
    movement_id-collision scenario ADR 0017 documents as an accepted
    matching-precision limitation. One statement with two transactions, not
    two separate `_write()` calls: two statements for the same account and
    period would trip the pre-existing continuity check (T16) as a genuine
    duplicate period, a different failure than the one this test targets.
    """
    file_sha256 = hashlib.sha256(f"duplicate-pair:{when}:{amount}".encode()).hexdigest()
    amount_decimal = Decimal(amount)
    transaction = Transaction(
        user_id=_USER_ID,
        bank=_BANK,
        account_id=_ACCOUNT_ID,
        account_last4=_LAST4,
        date=when,
        description="  compra pos....visa  ",
        amount=amount_decimal,
        currency="PEN",
        source_file_sha256=file_sha256,
    )
    statement = Statement(
        user_id=_USER_ID,
        bank=_BANK,
        account_id=_ACCOUNT_ID,
        account_last4=_LAST4,
        period_start=when,
        period_end=when,
        opening_balance=Decimal("0.00"),
        closing_balance=amount_decimal * 2,
        account_kind="asset",
        currency="PEN",
        transactions=[transaction, transaction],
    )
    bronze.write_statement(statement, file_sha256)


def _is_internal_transfer(connection: Any, account_id: str, amount: str) -> bool:
    rows = connection.execute(
        "select is_internal_transfer from silver.transactions "
        "where account_id = ? and amount = ?",
        [account_id, amount],
    ).fetchall()
    assert len(rows) == 1, f"expected 1 row for {account_id}/{amount}, got {rows}"
    return bool(rows[0][0])


def _unmatched_account_ids(connection: Any) -> set[str]:
    rows = connection.execute(
        "select account_id from silver.unmatched_transfers"
    ).fetchall()
    return {row[0] for row in rows}


def _pair_count(connection: Any) -> int:
    row = connection.execute(
        "select count(*) from silver.internal_transfers"
    ).fetchone()
    assert row is not None
    return int(row[0])


def _the_one_pair_account_ids(connection: Any) -> set[str]:
    """Both accounts of the single pair in `silver.internal_transfers`, order-
    independent: which leg sorts "first" is an arbitrary tie-break (see that
    model's own docstring), never a semantic outflow/inflow distinction."""
    rows = connection.execute(
        "select first_leg_account_id, second_leg_account_id "
        "from silver.internal_transfers"
    ).fetchall()
    assert len(rows) == 1
    return {rows[0][0], rows[0][1]}


def test_asset_to_liability_transfer_matches_on_the_same_sign(
    lake: str,
    tmp_path: Path,
) -> None:
    """ADR 0015's own scenario: a BCP checking outflow funding a Scotiabank
    payment is the *same* sign on both sides (both negative), not opposite."""
    _movement(when=date(2026, 1, 10), amount="-300.00", account_kind="asset")
    _movement(
        when=date(2026, 1, 10),
        amount="-300.00",
        bank="Scotiabank",
        account_id=_SCOTIABANK_ACCOUNT_ID,
        account_kind="liability",
    )

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        assert _is_internal_transfer(connection, _ACCOUNT_ID, "-300.00") is True
        assert (
            _is_internal_transfer(connection, _SCOTIABANK_ACCOUNT_ID, "-300.00") is True
        )
        assert _the_one_pair_account_ids(connection) == {
            _ACCOUNT_ID,
            _SCOTIABANK_ACCOUNT_ID,
        }


def test_two_asset_accounts_transfer_matches_on_opposite_signs(
    lake: str,
    tmp_path: Path,
) -> None:
    """Two BCP checking accounts: money leaves one (negative) and arrives in
    the other (positive) -- opposite signs, same account_kind on both sides."""
    _movement(when=date(2026, 2, 5), amount="-250.00", account_id=_ACCOUNT_ID)
    _movement(when=date(2026, 2, 6), amount="250.00", account_id=_BCP_ACCOUNT_B_ID)

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        assert _is_internal_transfer(connection, _ACCOUNT_ID, "-250.00") is True
        assert _is_internal_transfer(connection, _BCP_ACCOUNT_B_ID, "250.00") is True


def test_transfer_at_day_window_boundary_matches_one_day_more_does_not(
    lake: str,
    tmp_path: Path,
) -> None:
    """Default day window is 3: exactly 3 days apart still matches; a second,
    amount-distinct pair 4 days apart falls entirely outside the neighborhood
    (not a candidate at all, not just unmatched -- see unmatched_transfers.sql's
    own docstring for why "candidate" already requires the day window)."""
    _movement(when=date(2026, 3, 1), amount="-111.11", account_id=_ACCOUNT_ID)
    _movement(when=date(2026, 3, 4), amount="111.11", account_id=_BCP_ACCOUNT_B_ID)

    _movement(when=date(2026, 3, 1), amount="-222.22", account_id=_BCP_ACCOUNT_C_ID)
    _movement(when=date(2026, 3, 5), amount="222.22", account_id=_BCP_ACCOUNT_D_ID)

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        assert _is_internal_transfer(connection, _ACCOUNT_ID, "-111.11") is True
        assert _is_internal_transfer(connection, _BCP_ACCOUNT_B_ID, "111.11") is True
        assert _is_internal_transfer(connection, _BCP_ACCOUNT_C_ID, "-222.22") is False
        assert _is_internal_transfer(connection, _BCP_ACCOUNT_D_ID, "222.22") is False
        unmatched = _unmatched_account_ids(connection)
        assert _BCP_ACCOUNT_C_ID not in unmatched
        assert _BCP_ACCOUNT_D_ID not in unmatched


def test_three_same_amount_candidates_produce_at_most_one_pair_each(
    lake: str,
    tmp_path: Path,
) -> None:
    """A appears within the neighborhood of *two* opposite-sign candidates (B
    and C); every movement can be in at most one pair, so only the closer one
    (B, same day) wins. C is exactly the acceptance criteria's own "removing
    the inflow" scenario in miniature -- the counterpart that would have
    completed *its* transfer went to a closer account instead, so C's own
    intended pairing never happened -- and it stays visible as an unmatched
    candidate, never dropped."""
    _movement(when=date(2026, 4, 10), amount="-100.00", account_id=_ACCOUNT_ID)
    _movement(when=date(2026, 4, 10), amount="100.00", account_id=_BCP_ACCOUNT_B_ID)
    _movement(when=date(2026, 4, 12), amount="100.00", account_id=_BCP_ACCOUNT_C_ID)

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        assert _is_internal_transfer(connection, _ACCOUNT_ID, "-100.00") is True
        assert _is_internal_transfer(connection, _BCP_ACCOUNT_B_ID, "100.00") is True
        assert _is_internal_transfer(connection, _BCP_ACCOUNT_C_ID, "100.00") is False
        assert _the_one_pair_account_ids(connection) == {
            _ACCOUNT_ID,
            _BCP_ACCOUNT_B_ID,
        }
        assert _BCP_ACCOUNT_C_ID in _unmatched_account_ids(connection)


def test_an_ordinary_transaction_with_no_plausible_partner_is_not_a_candidate(
    lake: str,
    tmp_path: Path,
) -> None:
    """unmatched_transfers is for plausible-but-unpaired transfer halves, not
    every transaction in the ledger -- a lone grocery purchase with *nothing*
    else anywhere in the lake near it in amount/date never shows up there at
    all, the same as a transfer's counterpart that was simply never written
    with nothing else nearby either: "candidate" only ever means something
    relative to data that actually exists."""
    _movement(when=date(2026, 6, 1), amount="-19.90", account_id=_ACCOUNT_ID)

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        assert _is_internal_transfer(connection, _ACCOUNT_ID, "-19.90") is False
        assert _ACCOUNT_ID not in _unmatched_account_ids(connection)


def test_cross_currency_same_amount_is_not_matched_but_lands_in_unmatched(
    lake: str,
    tmp_path: Path,
) -> None:
    """Cross-currency transfers are explicitly out of scope (no FX conversion
    anywhere in this project) -- they must never be silently auto-matched on a
    numeric coincidence, and must never be silently dropped either. Also one
    reading of the acceptance criteria's own "removing the inflow" scenario:
    the BCP outflow's intended Scotiabank payment was never correctly
    recorded (e.g. logged in the wrong currency), so it must land here rather
    than vanish or attach itself to a row it doesn't actually belong with."""
    _movement(when=date(2026, 7, 1), amount="-100.00", currency="PEN")
    _movement(
        when=date(2026, 7, 1),
        amount="-100.00",
        bank="Scotiabank",
        account_id=_SCOTIABANK_ACCOUNT_ID,
        account_kind="liability",
        currency="USD",
    )

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        assert _is_internal_transfer(connection, _ACCOUNT_ID, "-100.00") is False
        assert (
            _is_internal_transfer(connection, _SCOTIABANK_ACCOUNT_ID, "-100.00")
            is False
        )
        unmatched = _unmatched_account_ids(connection)
        assert _ACCOUNT_ID in unmatched
        assert _SCOTIABANK_ACCOUNT_ID in unmatched
        assert _pair_count(connection) == 0


def test_duplicate_bronze_rows_do_not_multiply_silver_transactions_rows(
    lake: str,
    tmp_path: Path,
) -> None:
    """Code-review finding: two genuinely identical bronze.transactions rows
    share one movement_id (ADR 0017's own documented, accepted limitation --
    they can't be told apart for *matching* purposes), but transactions.sql's
    left join on that shared movement_id must still produce exactly one
    silver.transactions row per bronze row, never a 2x2 fan-out to 4."""
    _write_duplicate_pair(when=date(2026, 9, 1), amount="-50.00")

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        rows = connection.execute(
            "select is_internal_transfer from silver.transactions "
            "where account_id = ? and amount = ?",
            [_ACCOUNT_ID, "-50.00"],
        ).fetchall()
        assert len(rows) == 2, f"expected 2 rows (one per bronze row), got {rows}"
        assert rows == [(False,), (False,)]
