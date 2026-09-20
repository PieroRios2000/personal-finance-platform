"""gold.fact_transactions and gold.dim_date/dim_account/dim_bank/dim_user (T23).

Reuses tests/test_dbt_silver_integration.py's own `_write()` helper, `_dbt_build()`
runner and lake-wiping logic (`_skip_reason`/`_wipe_test_lake`, plain functions, not
the `lake` fixture object itself -- see `lake` below), the same "seed bronze
directly, run `dbt build`, check what comes out" pattern T16/T18a/T18b/T20 already
established, just against the new gold layer. The cross-bank transfer scenario
below follows the same hand-crafted-statements pattern
tests/test_dbt_internal_transfers_integration.py built for T18b (a BCP checking
outflow and a Scotiabank credit-card payment, same day, same absolute amount,
matched by T18b's own mutual-nearest-neighbor logic) -- this file consumes that
match (`is_internal_transfer`), it does not rebuild it.

`lake` is redefined here rather than imported, for the same reason
test_dbt_internal_transfers_integration.py's own docstring gives: a fixture used
across files still has to appear under that exact parameter name for pytest's
dependency injection to find it, and importing a fixture object under the name a
test signature must also use trips ruff's F811 ("redefinition") on every test that
takes it.

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
    _FEBRUARY,
    _JANUARY,
    _LAST4,
    _MARCH,
    _SCOTIABANK_ACCOUNT_ID,
    _TEST_LAKE_SUFFIX,
    _USER_ID,
    _dbt_build,
    _skip_reason,
    _wipe_test_lake,
    _write,
)

pytestmark = pytest.mark.integration

# The two _t23-gold-*_ ids below are new and distinct from every other test
# file's; the other two deliberately reuse test_dbt_silver_integration.py's
# own _ACCOUNT_ID/_SCOTIABANK_ACCOUNT_ID, since a collision is harmless here
# -- each test file shares the one `_t16_dbt_tests` lake prefix (see `lake`
# below), but `lake` wipes it clean before and after every single test, and
# nothing in this project runs dbt integration tests in parallel.
_ASSET_INGRESO_ACCOUNT_ID = _ACCOUNT_ID
_ASSET_EGRESO_ACCOUNT_ID = hashlib.sha256(b"t23-gold-asset-egreso").hexdigest()
_LIABILITY_EGRESO_ACCOUNT_ID = _SCOTIABANK_ACCOUNT_ID
_LIABILITY_PAGO_ACCOUNT_ID = hashlib.sha256(b"t23-gold-liability-pago").hexdigest()

_BCP_CHECKING_ACCOUNT_ID = hashlib.sha256(b"t23-gold-bcp-checking").hexdigest()
_SCOTIABANK_CREDIT_CARD_ACCOUNT_ID = hashlib.sha256(
    b"t23-gold-scotiabank-credit-card"
).hexdigest()


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


def _write_multi_transaction_statement(
    *,
    account_id: str,
    bank: str,
    account_kind: AccountKind,
    currency: Currency,
    when: date,
    opening_balance: str,
    amounts: list[str],
    file_sha256: str,
) -> None:
    """One statement with one transaction per amount in `amounts`, all dated
    `when` and reconciled by construction (closing_balance = opening_balance +
    sum(amounts)) -- `_write()` only ever writes zero or one transaction per
    statement, and the cross-bank scenario below needs several per account.
    Every amount is given its own description, so none of them can collide on
    T20's business key (`account_id + date + amount + description +
    occurrence_number`) within the one statement/file this writes.
    """
    transactions = [
        Transaction(
            user_id=_USER_ID,
            bank=bank,
            account_id=account_id,
            account_last4=_LAST4,
            date=when,
            description=f"t23 gold fixture movement {index}",
            amount=Decimal(amount),
            currency=currency,
            source_file_sha256=file_sha256,
        )
        for index, amount in enumerate(amounts)
    ]
    closing_balance = Decimal(opening_balance) + sum(
        (Decimal(amount) for amount in amounts), start=Decimal("0")
    )
    statement = Statement(
        user_id=_USER_ID,
        bank=bank,
        account_id=account_id,
        account_last4=_LAST4,
        period_start=when,
        period_end=when,
        opening_balance=Decimal(opening_balance),
        closing_balance=closing_balance,
        account_kind=account_kind,
        currency=currency,
        transactions=transactions,
    )
    bronze.write_statement(statement, file_sha256)


def _write_cross_bank_transfer_scenario() -> None:
    """T23's own required proof scenario: one BCP checking (asset) account and
    one Scotiabank credit-card (liability) account, both dated 2026-01-15, with
    a real transfer between them -- the BCP outflow funding the Scotiabank
    payment, same day, same absolute amount (300.00), the exact
    ADR-0015/T18b shape (`test_asset_to_liability_transfer_matches_on_the_same_sign`
    in tests/test_dbt_internal_transfers_integration.py) that makes T18b match
    and flag both legs `is_internal_transfer = true`.

    BCP checking (asset):
    - -50.00 grocery purchase (an ordinary expense, not a transfer)
    - -300.00 the transfer, funding the Scotiabank payment below
    - +1000.00 salary deposit (an ordinary inflow, not a transfer)

    Scotiabank credit card (liability):
    - -300.00 the payment (a debt-reducing credit; the transfer's other leg)
    - +120.00 dining charge (an ordinary expense, not a transfer)
    - +45.00 purchase charge (an ordinary expense, not a transfer)

    None of the non-transfer amounts above can accidentally match each other
    under T18b's own account_kind-aware sign rule (checked by hand against
    internal_transfer_matches.sql's own rule: same account_kind needs opposite
    signs and equal magnitude, asset-vs-liability needs *both* negative and
    equal magnitude) -- the only pair that matches is the intended -300.00/
    -300.00 one.

    By hand: egreso, filtered to is_internal_transfer = false, is
    50.00 (BCP grocery) + 120.00 (Scotiabank dining) + 45.00 (Scotiabank
    purchase) = 215.00. Without the filter the BCP transfer's own -300.00 leg
    would also read as egreso by the raw account_kind+sign mapping alone
    (asset, negative), inflating the total to 515.00 -- proving the filter is
    load-bearing, not redundant with flow_type itself.
    """
    bcp_file_sha256 = hashlib.sha256(b"t23-gold-bcp-checking-january").hexdigest()
    _write_multi_transaction_statement(
        account_id=_BCP_CHECKING_ACCOUNT_ID,
        bank="BCP",
        account_kind="asset",
        currency="PEN",
        when=date(2026, 1, 15),
        opening_balance="2000.00",
        amounts=["-50.00", "-300.00", "1000.00"],
        file_sha256=bcp_file_sha256,
    )
    scotiabank_file_sha256 = hashlib.sha256(
        b"t23-gold-scotiabank-credit-card-january"
    ).hexdigest()
    _write_multi_transaction_statement(
        account_id=_SCOTIABANK_CREDIT_CARD_ACCOUNT_ID,
        bank="Scotiabank",
        account_kind="liability",
        currency="PEN",
        when=date(2026, 1, 15),
        opening_balance="500.00",
        amounts=["-300.00", "120.00", "45.00"],
        file_sha256=scotiabank_file_sha256,
    )


def _row_count(connection: Any, relation: str) -> int:
    row = connection.execute(f"select count(*) from {relation}").fetchone()
    assert row is not None
    return int(row[0])


def test_fact_transactions_row_count_matches_silver_transactions_exactly(
    lake: str, tmp_path: Path
) -> None:
    """T23's own "1:1 fact" acceptance criterion: fact_transactions must have
    exactly one row per silver.transactions row, no fan-out from any
    dimension join."""
    for period in (_JANUARY, _FEBRUARY, _MARCH):
        _write(*period)

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        silver_count = _row_count(connection, "silver.transactions")
        fact_count = _row_count(connection, "gold.fact_transactions")

    assert silver_count == 3
    assert fact_count == silver_count


def test_every_foreign_key_in_fact_transactions_resolves_via_relationships_tests(
    lake: str, tmp_path: Path
) -> None:
    """`dbt build` runs every `relationships` test in schema.yml as part of the
    same run; a green `dbt build` is already proof every FK resolved. This
    test also greps the raw output for each relationships test's own node
    name, so a future schema.yml edit that silently drops one of the four
    tests (rather than the join itself breaking) still fails loudly here,
    not just look green because nothing ran."""
    for period in (_JANUARY, _FEBRUARY, _MARCH):
        _write(*period)

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout
    for fk_column in ("user_id", "account_id", "bank", "date"):
        assert f"relationships_fact_transactions_{fk_column}" in result.stdout, (
            f"expected a relationships test on fact_transactions.{fk_column} "
            f"to have run; got:\n{result.stdout}"
        )


def test_flow_type_mapping_follows_account_kind_and_sign_not_raw_bank_convention(
    lake: str, tmp_path: Path
) -> None:
    """The exact mapping T23's acceptance criteria specify, verbatim: asset +
    positive -> ingreso, asset + negative -> egreso, liability + positive (a
    charge) -> egreso, liability + negative (a payment/credit) -> pago. Four
    distinct accounts, one statement each, so none of them can be mistaken
    for a T18b transfer candidate of another (checked by hand against
    internal_transfer_matches.sql's own sign rule)."""
    _write(
        date(2026, 2, 1),
        date(2026, 2, 1),
        "0.00",
        "500.00",
        account_id=_ASSET_INGRESO_ACCOUNT_ID,
        account_kind="asset",
    )
    _write(
        date(2026, 2, 1),
        date(2026, 2, 1),
        "0.00",
        "-75.00",
        account_id=_ASSET_EGRESO_ACCOUNT_ID,
        account_kind="asset",
    )
    _write(
        date(2026, 2, 1),
        date(2026, 2, 1),
        "0.00",
        "60.00",
        bank="Scotiabank",
        account_id=_LIABILITY_EGRESO_ACCOUNT_ID,
        account_kind="liability",
    )
    _write(
        date(2026, 2, 1),
        date(2026, 2, 1),
        "0.00",
        "-40.00",
        bank="Scotiabank",
        account_id=_LIABILITY_PAGO_ACCOUNT_ID,
        account_kind="liability",
    )

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        rows = dict(
            connection.execute(
                "select account_id, flow_type from gold.fact_transactions"
            ).fetchall()
        )

    assert rows[_ASSET_INGRESO_ACCOUNT_ID] == "ingreso"
    assert rows[_ASSET_EGRESO_ACCOUNT_ID] == "egreso"
    assert rows[_LIABILITY_EGRESO_ACCOUNT_ID] == "egreso"
    assert rows[_LIABILITY_PAGO_ACCOUNT_ID] == "pago"


def test_cross_bank_egreso_sum_excludes_the_internal_transfer(
    lake: str, tmp_path: Path
) -> None:
    """T23's own required proof: summed egreso across a BCP checking account
    and a Scotiabank credit card, filtered to is_internal_transfer = false,
    matches the expected total by hand -- proving flow_type gives a coherent
    cross-bank answer despite BCP and Scotiabank's opposite raw sign
    conventions, and that the transfer itself doesn't inflate it."""
    _write_cross_bank_transfer_scenario()

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        # sum(abs(amount)), not abs(sum(amount)): BCP's egreso amounts are
        # negative (asset) and Scotiabank's are positive (liability) --
        # summing the raw signed amounts would partly cancel them out
        # instead of accumulating "how much was spent" as one coherent
        # number, which is the exact cross-bank sign mismatch flow_type
        # exists to paper over.
        filtered = connection.execute(
            "select sum(abs(amount)) from gold.fact_transactions "
            "where flow_type = 'egreso' and is_internal_transfer = false "
            "and account_id in (?, ?)",
            [_BCP_CHECKING_ACCOUNT_ID, _SCOTIABANK_CREDIT_CARD_ACCOUNT_ID],
        ).fetchone()
        unfiltered = connection.execute(
            "select sum(abs(amount)) from gold.fact_transactions "
            "where flow_type = 'egreso' "
            "and account_id in (?, ?)",
            [_BCP_CHECKING_ACCOUNT_ID, _SCOTIABANK_CREDIT_CARD_ACCOUNT_ID],
        ).fetchone()
        transfer_legs = connection.execute(
            "select account_id, amount, flow_type from gold.fact_transactions "
            "where is_internal_transfer = true "
            "and account_id in (?, ?)",
            [_BCP_CHECKING_ACCOUNT_ID, _SCOTIABANK_CREDIT_CARD_ACCOUNT_ID],
        ).fetchall()

    assert filtered is not None and unfiltered is not None
    filtered_total = filtered[0]
    unfiltered_total = unfiltered[0]
    assert filtered_total == Decimal("215.00")
    # Without the is_internal_transfer filter, the BCP transfer's own -300.00
    # leg reads as egreso too (asset, negative) and inflates the total --
    # this is exactly the failure mode the filter exists to prevent.
    assert unfiltered_total == Decimal("515.00")
    assert len(transfer_legs) == 2
    assert {row[2] for row in transfer_legs} == {"egreso", "pago"}


def test_spend_by_bank_by_month_query_joins_all_four_dimensions(
    lake: str, tmp_path: Path
) -> None:
    """The synthetic "spend by bank by month" query T23's acceptance criteria
    ask for, run for real against the built tables -- joining
    fact_transactions to all four dimensions (dim_user, dim_account, dim_bank,
    dim_date), not just modeled."""
    _write_cross_bank_transfer_scenario()

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        rows = connection.execute(
            """
            select
                dim_bank.bank,
                dim_date.year_number,
                dim_date.month_number,
                sum(abs(fact_transactions.amount)) as spend
            from gold.fact_transactions as fact_transactions
            inner join gold.dim_user as dim_user
                on fact_transactions.user_id = dim_user.user_id
            inner join gold.dim_account as dim_account
                on fact_transactions.account_id = dim_account.account_id
            inner join gold.dim_bank as dim_bank
                on fact_transactions.bank = dim_bank.bank
            inner join gold.dim_date as dim_date
                on fact_transactions.date = dim_date.date
            where
                fact_transactions.flow_type = 'egreso'
                and fact_transactions.is_internal_transfer = false
                and fact_transactions.account_id in (?, ?)
            group by dim_bank.bank, dim_date.year_number, dim_date.month_number
            order by dim_bank.bank
            """,
            [_BCP_CHECKING_ACCOUNT_ID, _SCOTIABANK_CREDIT_CARD_ACCOUNT_ID],
        ).fetchall()

    assert rows == [
        ("BCP", 2026, 1, Decimal("50.00")),
        ("Scotiabank", 2026, 1, Decimal("165.00")),
    ]
