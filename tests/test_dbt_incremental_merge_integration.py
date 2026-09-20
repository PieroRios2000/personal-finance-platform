"""silver.transactions' incremental MERGE, keyed on the business key (T20):
`brain/concepts/business-key.md` -- date + amount + normalized description +
account_id + occurrence_number, `dbt/macros/occurrence_number.sql`.

Reuses tests/test_dbt_silver_integration.py's own `_dbt_build()` runner and
lake-wiping logic (`_skip_reason`/`_wipe_test_lake`, plain functions, not the
`lake` fixture object -- see that module's own docstring for why a fixture
used across files is still redefined here, not imported) rather than
re-inventing them: this is the exact same "seed bronze directly, run
`dbt build`, check what comes out" pattern T16/T18a/T18b/T18c already
established.

`_dbt_build` is called more than once per test with the *same* `tmp_path` in
several tests here on purpose: the second call reuses the same on-disk
`pfp.duckdb`, so it genuinely exercises the incremental MERGE path (the
target table already exists) rather than a fresh full build -- that's the
whole point of this file.

Deselected by default, like the rest of the dbt integration suite: needs
SeaweedFS running (`make poc-up`, T13) with `.env` exported into the shell.
Run with `pytest -m integration`.
"""

import hashlib
import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ingestion.schema import Statement, Transaction
from lakehouse import bronze
from tests import pg_store
from tests.test_dbt_silver_integration import (
    _ACCOUNT_ID,
    _BANK,
    _LAST4,
    _TEST_LAKE_SUFFIX,
    _USER_ID,
    _dbt_build,
    _skip_reason,
    _wipe_test_lake,
)

pytestmark = pytest.mark.integration

_PERIOD_START = date(2026, 5, 1)
_PERIOD_END = date(2026, 5, 31)


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


def _statement(
    *,
    file_sha256: str,
    movements: list[tuple[str, str]],
    opening_balance: str = "1000.00",
    closing_balance: str | None = None,
) -> Statement:
    """A reconciled statement whose transactions are `(description, amount)`
    pairs, every one dated `_PERIOD_START` -- T20's own scenarios only care
    about several movements sharing one file and one date; the statement
    period shape itself is incidental.

    `closing_balance` can be forced to a value that does *not* match the
    movements, for the reconciliation test's own negative case -- `Statement`
    itself never enforces that its numbers add up (only
    `ingestion/reconciliation.py`'s `reconcile()`, a separate call, does).
    """
    transactions = [
        Transaction(
            user_id=_USER_ID,
            bank=_BANK,
            account_id=_ACCOUNT_ID,
            account_last4=_LAST4,
            date=_PERIOD_START,
            description=description,
            amount=Decimal(amount),
            currency="PEN",
            source_file_sha256=file_sha256,
        )
        for description, amount in movements
    ]
    total = sum((t.amount for t in transactions), Decimal("0"))
    return Statement(
        user_id=_USER_ID,
        bank=_BANK,
        account_id=_ACCOUNT_ID,
        account_last4=_LAST4,
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        opening_balance=Decimal(opening_balance),
        closing_balance=(
            Decimal(closing_balance)
            if closing_balance is not None
            else Decimal(opening_balance) + total
        ),
        account_kind="asset",
        currency="PEN",
        transactions=transactions,
    )


def _silver_snapshot(tmp_path: Path) -> list[tuple[Any, ...]]:
    """Every column of every `silver.transactions` row, in a stable order --
    used to prove a rebuild changed *nothing* (not just that row counts
    match, which a delete-one/insert-one pair would also satisfy)."""

    with pg_store.connect() as connection:
        return connection.execute(
            "select user_id, bank, account_id, account_last4, date, amount, "
            "currency, source_file_sha256, ingested_at, occurrence_number, "
            "account_kind, is_internal_transfer, description "
            "from silver.transactions "
            "order by amount, occurrence_number, source_file_sha256"
        ).fetchall()


def _descriptions(tmp_path: Path) -> list[str]:

    with pg_store.connect() as connection:
        rows = connection.execute(
            "select description from silver.transactions order by description"
        ).fetchall()
    return [row[0] for row in rows]


def test_two_identical_transactions_in_one_statement_land_as_two_silver_rows(
    lake: str, tmp_path: Path
) -> None:
    """T20's own headline scenario: two genuinely identical movements (same
    date/amount/description/account) in *one* statement are two real
    purchases, not a duplicate -- `occurrence_number` must keep both."""
    file_sha256 = hashlib.sha256(b"t20-two-identical-transactions").hexdigest()
    statement = _statement(
        file_sha256=file_sha256,
        movements=[("COMPRA POS VISA", "-25.00"), ("COMPRA POS VISA", "-25.00")],
    )
    bronze.write_statement(statement, file_sha256)

    result = _dbt_build(tmp_path)
    assert result.returncode == 0, result.stdout

    with pg_store.connect() as connection:
        rows = connection.execute(
            "select description, occurrence_number from silver.transactions "
            "where account_id = ? and amount = -25.00 order by occurrence_number",
            [_ACCOUNT_ID],
        ).fetchall()

    assert rows == [("COMPRA POS VISA", 1), ("COMPRA POS VISA", 2)]


def test_second_dbt_build_with_no_bronze_changes_touches_nothing(
    lake: str, tmp_path: Path
) -> None:
    """A rebuild with no new bronze data must be a genuine no-op: the
    incremental filter (`(source_file_sha256, ingested_at)` not already in
    `silver.transactions`) selects zero rows, so the MERGE's own source is
    empty and neither branch can fire for any row. Proven here by full-row
    content identity before and after, since dbt-duckdb's own
    `AdapterResponse` never reports a rows-affected count (confirmed by
    reading `dbt/adapters/duckdb/connections.py::get_response`, which always
    returns a bare "OK") -- there is no dbt-level counter to assert on
    instead."""
    file_sha256 = hashlib.sha256(b"t20-no-op-rebuild").hexdigest()
    statement = _statement(
        file_sha256=file_sha256,
        movements=[("COMPRA POS VISA", "-40.00")],
    )
    bronze.write_statement(statement, file_sha256)

    first = _dbt_build(tmp_path)
    assert first.returncode == 0, first.stdout
    before = _silver_snapshot(tmp_path)
    assert before  # sanity: the first build actually wrote something

    second = _dbt_build(tmp_path)
    assert second.returncode == 0, second.stdout
    after = _silver_snapshot(tmp_path)

    assert after == before


def test_backfill_with_a_corrected_description_updates_the_row_in_place(
    lake: str, tmp_path: Path
) -> None:
    """The trickiest T20 behavior: `pfp backfill` (ADR 0010) re-parses a file
    and a parser fix changes one row's description, and so its business key.
    The *old* row's key doesn't exist anywhere in the fresh parse, so a plain
    MERGE alone would leave it behind, orphaned, forever. `transactions.sql`'s
    own `pre_hook` (`purge_reprocessed_files.sql`) must purge it first."""
    file_sha256 = hashlib.sha256(b"t20-backfill-corrected-description").hexdigest()
    original = _statement(
        file_sha256=file_sha256,
        movements=[("COMPRA POS####VISA", "-60.00")],
    )
    bronze.write_statement(original, file_sha256)

    first = _dbt_build(tmp_path)
    assert first.returncode == 0, first.stdout
    assert _descriptions(tmp_path) == ["COMPRA POS VISA"]

    corrected = _statement(
        file_sha256=file_sha256,
        movements=[("SUPERMERCADO EL SOL", "-60.00")],
    )
    bronze.replace_statement(corrected, file_sha256)

    second = _dbt_build(tmp_path)
    assert second.returncode == 0, second.stdout

    descriptions = _descriptions(tmp_path)
    assert descriptions == ["SUPERMERCADO EL SOL"], (
        "the old description must be gone, not duplicated alongside the new one"
    )


def test_a_replaced_file_that_ends_with_no_transactions_leaves_nothing_in_silver(
    lake: str, tmp_path: Path
) -> None:
    """A corrected manual-Excel month can end with only a balance marker: bronze
    then holds the statement but no transaction row for that file, so no fresh
    `(sha, ingested_at)` pair ever tells the purge about it. The old silver rows
    of a file bronze no longer has any transaction for must go too."""
    file_sha256 = hashlib.sha256(b"manual-month-emptied").hexdigest()
    bronze.write_statement(
        _statement(file_sha256=file_sha256, movements=[("DEPOSITO", "100.00")]),
        file_sha256,
    )
    first = _dbt_build(tmp_path)
    assert first.returncode == 0, first.stdout
    assert _descriptions(tmp_path) == ["DEPOSITO"]

    bronze.replace_statement(
        _statement(file_sha256=file_sha256, movements=[]), file_sha256
    )

    second = _dbt_build(tmp_path)

    assert second.returncode == 0, second.stdout
    assert _descriptions(tmp_path) == []


def test_backfill_of_unchanged_content_does_not_duplicate(
    lake: str, tmp_path: Path
) -> None:
    """A backfill that re-parses a file to the *same* content (e.g. a parser
    version bump that changes nothing about this particular statement) must
    still land as exactly one row per movement -- the MERGE naturally updates
    in place (same business key), never appends a second copy."""
    file_sha256 = hashlib.sha256(b"t20-backfill-unchanged-content").hexdigest()
    statement = _statement(
        file_sha256=file_sha256,
        movements=[("COMPRA POS VISA", "-15.00")],
    )
    bronze.write_statement(statement, file_sha256)

    first = _dbt_build(tmp_path)
    assert first.returncode == 0, first.stdout

    bronze.replace_statement(statement, file_sha256)

    second = _dbt_build(tmp_path)
    assert second.returncode == 0, second.stdout

    assert _descriptions(tmp_path) == ["COMPRA POS VISA"]


def test_regenerated_file_with_the_same_business_key_updates_in_place(
    lake: str, tmp_path: Path
) -> None:
    """A *different* case that can look similar to a backfill but isn't one:
    a bank regenerating a statement PDF (different bytes, past T7's
    file-level dedup, so a genuinely new `source_file_sha256`) that parses
    back to the exact same business key as a period already in silver. This
    is deliberately *not* purged by `purge_reprocessed_files()` (that file's
    own `source_file_sha256` was never in silver before) -- the MERGE's own
    `WHEN MATCHED` branch, matching on the business key itself, is what
    updates the row in place instead. See ADR 0018.

    Two `bronze.statements` rows for the very same account/currency/period is
    also, correctly, exactly what `assert_statement_continuity.sql` already
    treats as a genuine duplicate period (its own documented behavior, T16) --
    confirmed below: the full `dbt build` still fails *that* test, unchanged
    from Phase 1. This test's own point is one level below that:
    `silver.transactions` itself must still merge to one row, not two,
    regardless of what the separate continuity test goes on to say about the
    two statement rows. Checked with a second, `--select transactions`-scoped
    build: this project's dbt version skips *every* node once an earlier one
    in the same invocation fails (confirmed directly against `manifest.json`'s
    `child_map` -- not a real dependency edge on `silver.transactions`, see
    `_dbt_build`'s own docstring), so the full, unscoped build alone could
    never observe this model's own result once the continuity test fails
    first.
    """
    original_sha256 = hashlib.sha256(b"t20-regenerated-pdf-original").hexdigest()
    statement = _statement(
        file_sha256=original_sha256,
        movements=[("COMPRA POS VISA", "-30.00")],
    )
    bronze.write_statement(statement, original_sha256)

    first = _dbt_build(tmp_path)
    assert first.returncode == 0, first.stdout

    regenerated_sha256 = hashlib.sha256(b"t20-regenerated-pdf-reprint").hexdigest()
    regenerated = _statement(
        file_sha256=regenerated_sha256,
        movements=[("COMPRA POS VISA", "-30.00")],
    )
    bronze.write_statement(regenerated, regenerated_sha256)

    full_build = _dbt_build(tmp_path)
    assert full_build.returncode != 0, full_build.stdout
    assert "assert_statement_continuity" in full_build.stdout

    # Excludes the new balance-reconciliation test on purpose: two
    # bronze.statements rows for one period is *also*, correctly, something
    # it would flag (the same transaction reconciles against two declared
    # periods at once) -- a second, valid symptom of the very problem
    # assert_statement_continuity already exists to catch, not a reason to
    # doubt the MERGE mechanism this test is actually about.
    scoped_build = _dbt_build(
        tmp_path,
        select="transactions",
        exclude="assert_statement_balance_reconciliation",
    )
    assert scoped_build.returncode == 0, scoped_build.stdout
    assert "OK created sql incremental model silver.transactions" in scoped_build.stdout

    with pg_store.connect() as connection:
        rows = connection.execute(
            "select source_file_sha256 from silver.transactions "
            "where account_id = ? and amount = -30.00",
            [_ACCOUNT_ID],
        ).fetchall()

    assert rows == [(regenerated_sha256,)], (
        "one row, now pointing at the regenerated file -- not two rows"
    )


def test_balance_reconciliation_passes_on_a_normal_statement(
    lake: str, tmp_path: Path
) -> None:
    file_sha256 = hashlib.sha256(b"t20-reconciliation-passes").hexdigest()
    statement = _statement(
        file_sha256=file_sha256,
        movements=[("COMPRA POS VISA", "-20.00"), ("ABONO SUELDO", "500.00")],
    )
    bronze.write_statement(statement, file_sha256)

    result = _dbt_build(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "assert_statement_balance_reconciliation" in result.stdout


def test_balance_reconciliation_fails_when_the_merge_drops_a_row(
    lake: str, tmp_path: Path
) -> None:
    """Proves the new test actually catches something, not just that it
    runs: a statement whose declared closing balance doesn't match what its
    own transactions add up to -- standing in for what this task's own MERGE
    could get wrong (a silently dropped or duplicated row) that
    `ingestion/reconciliation.py`'s parse-time check would never see, since
    that check runs before anything reaches bronze at all."""
    file_sha256 = hashlib.sha256(b"t20-reconciliation-fails").hexdigest()
    broken = _statement(
        file_sha256=file_sha256,
        movements=[("COMPRA POS VISA", "-20.00")],
        opening_balance="1000.00",
        closing_balance="999.00",  # should be 980.00 -- a "dropped row" stand-in
    )
    bronze.write_statement(broken, file_sha256)

    result = _dbt_build(tmp_path)

    assert result.returncode != 0, result.stdout
    assert "assert_statement_balance_reconciliation" in result.stdout
    assert "FAIL 1" in result.stdout
