"""Tests for lakehouse.bronze: bronze's Delta tables (T14) and the backfill
replace path (T14c)."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ingestion.schema import Statement, Transaction
from lakehouse import bronze

VALID_ACCOUNT_ID = hashlib.sha256(b"bcp:bronze-tests").hexdigest()
VALID_SHA256 = hashlib.sha256(b"a synthetic statement").hexdigest()


@pytest.fixture(autouse=True)
def lakehouse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A disk-backed lake for each test: LAKEHOUSE_URI unset means no S3
    storage_options get built (lakehouse.storage.storage_options() returns
    None for a plain path)."""
    lake = tmp_path / "lake"
    monkeypatch.setenv("LAKEHOUSE_URI", str(lake))
    return lake


def _statement(*, user_id: str = "piero", **overrides: Any) -> Statement:
    kwargs: dict[str, Any] = {
        "user_id": user_id,
        "bank": "BCP",
        "account_id": VALID_ACCOUNT_ID,
        "account_last4": "1234",
        "period_start": date(2026, 1, 1),
        "period_end": date(2026, 1, 31),
        "opening_balance": Decimal("100.00"),
        "closing_balance": Decimal("74.50"),
        "account_kind": "asset",
        "currency": "PEN",
        "transactions": [
            Transaction(
                user_id=user_id,
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description="TEST MOVEMENT",
                amount=Decimal("-25.50"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            )
        ],
    }
    kwargs.update(overrides)
    return Statement(**kwargs)


def test_is_ingested_is_false_before_anything_is_written() -> None:
    assert bronze.is_ingested("piero", VALID_SHA256) is False


def test_write_statement_makes_is_ingested_true() -> None:
    bronze.write_statement(_statement(), VALID_SHA256)

    assert bronze.is_ingested("piero", VALID_SHA256) is True


def test_write_statement_is_scoped_to_the_user(lakehouse: Path) -> None:
    bronze.write_statement(_statement(user_id="piero"), VALID_SHA256)

    assert bronze.is_ingested("piero", VALID_SHA256) is True
    assert bronze.is_ingested("someone-else", VALID_SHA256) is False


def test_write_statement_adds_one_row_per_transaction(lakehouse: Path) -> None:
    from deltalake import DeltaTable

    statement = _statement(
        transactions=[
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description="ONE",
                amount=Decimal("-25.50"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            ),
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 20),
                description="TWO",
                amount=Decimal("300.00"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            ),
        ]
    )

    bronze.write_statement(statement, VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows == 2
    amounts = sorted(table.column("amount").to_pylist())
    assert amounts == [Decimal("-25.50"), Decimal("300.00")]


def test_write_statement_preserves_decimal_precision_across_different_batches(
    lakehouse: Path,
) -> None:
    """A real bug found while building this: pyarrow infers a decimal128
    precision from each batch's own values, and deltalake rejects an append
    whose inferred precision differs from the table's existing one
    (`SchemaMismatchError: Cannot cast field amount from Decimal128(8, 2) to
    Decimal128(4, 2)`, reproduced directly against deltalake 1.6.3 before this
    was fixed with a fixed, explicit pyarrow schema)."""
    from deltalake import DeltaTable

    small = _statement(
        transactions=[
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description="SMALL",
                amount=Decimal("-12.34"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            )
        ]
    )
    large_sha256 = hashlib.sha256(b"a second synthetic statement").hexdigest()
    large = _statement(
        transactions=[
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 2, 15),
                description="LARGE",
                amount=Decimal("123456.78"),
                currency="PEN",
                source_file_sha256=large_sha256,
            )
        ]
    )

    bronze.write_statement(small, VALID_SHA256)
    bronze.write_statement(large, large_sha256)  # must not raise SchemaMismatchError

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows == 2


def test_write_statement_adds_one_row_to_bronze_statements(lakehouse: Path) -> None:
    from deltalake import DeltaTable

    bronze.write_statement(_statement(), VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert table.num_rows == 1
    row = table.to_pylist()[0]
    assert row["opening_balance"] == Decimal("100.00")
    assert row["closing_balance"] == Decimal("74.50")
    assert row["period_start"] == date(2026, 1, 1)


def test_write_statement_carries_account_kind_into_bronze_statements(
    lakehouse: Path,
) -> None:
    """T18a: account_kind lives on Statement, not Transaction (an account's
    kind doesn't vary per movement), so only bronze/statements needs it --
    bronze/transactions has no balance/kind concept at all."""
    from deltalake import DeltaTable

    bronze.write_statement(_statement(account_kind="liability"), VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert table.to_pylist()[0]["account_kind"] == "liability"

    transactions = DeltaTable(
        str(lakehouse / "bronze" / "transactions")
    ).to_pyarrow_table()
    assert "account_kind" not in transactions.column_names


def test_write_statement_carries_currency_into_bronze_statements(
    lakehouse: Path,
) -> None:
    """T18c: bronze/statements needs its own currency column to partition the
    continuity test by -- unlike account_kind, bronze/transactions already has
    one (Transaction always has), so this only adds it to statements."""
    from deltalake import DeltaTable

    usd_transaction = Transaction(
        user_id="piero",
        bank="BCP",
        account_id=VALID_ACCOUNT_ID,
        account_last4="1234",
        date=date(2026, 1, 15),
        description="TEST MOVEMENT",
        amount=Decimal("-25.50"),
        currency="USD",
        source_file_sha256=VALID_SHA256,
    )
    bronze.write_statement(
        _statement(currency="USD", transactions=[usd_transaction]), VALID_SHA256
    )

    table = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert table.to_pylist()[0]["currency"] == "USD"


def test_write_statement_never_stores_a_file_name(lakehouse: Path) -> None:
    """Only the sha256 identifies the source file (ADR 0009): nothing in bronze
    should carry the original inbox filename."""
    from deltalake import DeltaTable

    bronze.write_statement(_statement(), VALID_SHA256)

    for table_name in ("transactions", "statements", "ingested_files"):
        table = DeltaTable(str(lakehouse / "bronze" / table_name)).to_pyarrow_table()
        assert "file_name" not in table.column_names
        assert "path" not in table.column_names


def test_ingesting_twice_does_not_duplicate_rows_when_the_caller_checks_first(
    lakehouse: Path,
) -> None:
    """write_statement() itself always appends — it's the caller's job to check
    is_ingested() first (see ingestion.cli._run_ingest); this test proves the
    idempotency contract holds when that's respected."""
    from deltalake import DeltaTable

    statement = _statement()
    if not bronze.is_ingested("piero", VALID_SHA256):
        bronze.write_statement(statement, VALID_SHA256)
    if not bronze.is_ingested("piero", VALID_SHA256):
        bronze.write_statement(statement, VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows == 1


def test_replace_statement_removes_the_old_transaction_rows(lakehouse: Path) -> None:
    """A backfill (T14c) re-parses a file already in bronze: the rows the
    previous (buggy) parse wrote are gone, and only the fresh ones remain."""
    from deltalake import DeltaTable

    bronze.write_statement(_statement(), VALID_SHA256)

    corrected = _statement(
        transactions=[
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description="CORRECTED ONE",
                amount=Decimal("-10.00"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            ),
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 16),
                description="CORRECTED TWO",
                amount=Decimal("-15.50"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            ),
        ]
    )
    bronze.replace_statement(corrected, VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert sorted(table.column("description").to_pylist()) == [
        "CORRECTED ONE",
        "CORRECTED TWO",
    ]


def test_replace_statement_replaces_the_statements_row(lakehouse: Path) -> None:
    from deltalake import DeltaTable

    bronze.write_statement(_statement(closing_balance=Decimal("74.50")), VALID_SHA256)

    bronze.replace_statement(_statement(closing_balance=Decimal("80.00")), VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert table.num_rows == 1
    assert table.to_pylist()[0]["closing_balance"] == Decimal("80.00")


def test_replace_statement_writes_a_file_that_was_never_ingested(
    lakehouse: Path,
) -> None:
    """Nothing to delete (a fresh lake has no tables at all) is a normal case,
    not an error: the statement is just written."""
    from deltalake import DeltaTable

    bronze.replace_statement(_statement(), VALID_SHA256)

    assert bronze.is_ingested("piero", VALID_SHA256) is True
    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert table.num_rows == 1


def test_replace_statement_keeps_the_original_ingested_files_row(
    lakehouse: Path,
) -> None:
    """A backfill corrects a file's *interpretation*, not the fact that the file
    itself was ingested at some earlier moment: `ingested_files` keeps its one
    row, with the `ingested_at` it already had."""
    from deltalake import DeltaTable

    bronze.write_statement(_statement(), VALID_SHA256)
    uri = str(lakehouse / "bronze" / "ingested_files")
    before = DeltaTable(uri).to_pyarrow_table().to_pylist()

    bronze.replace_statement(_statement(), VALID_SHA256)

    after = DeltaTable(uri).to_pyarrow_table().to_pylist()
    assert len(after) == 1
    assert after == before


def test_replace_statement_only_touches_the_given_users_rows(
    lakehouse: Path,
) -> None:
    """The same PDF can legitimately belong to two users (ADR 0009: a joint
    account lands as two independent copies, one per user), and both copies
    share one sha256 — so the delete has to be scoped by `user_id`, exactly like
    `is_ingested()` already is."""
    from deltalake import DeltaTable

    bronze.write_statement(_statement(user_id="piero"), VALID_SHA256)
    bronze.write_statement(_statement(user_id="ana"), VALID_SHA256)

    bronze.replace_statement(_statement(user_id="piero"), VALID_SHA256)

    table = DeltaTable(str(lakehouse / "bronze" / "transactions")).to_pyarrow_table()
    assert sorted(table.column("user_id").to_pylist()) == ["ana", "piero"]
    statements = DeltaTable(str(lakehouse / "bronze" / "statements")).to_pyarrow_table()
    assert sorted(statements.column("user_id").to_pylist()) == ["ana", "piero"]


def test_transactions_for_file_is_empty_on_a_fresh_lake() -> None:
    assert bronze.transactions_for_file("piero", VALID_SHA256) == []


def test_transactions_for_file_returns_only_that_files_rows(lakehouse: Path) -> None:
    """What `pfp backfill --dry-run` compares a fresh parse against (T14c):
    date, description and amount for one file, and nothing else's."""
    other_sha256 = hashlib.sha256(b"another statement").hexdigest()
    bronze.write_statement(_statement(), VALID_SHA256)
    bronze.write_statement(
        _statement(
            transactions=[
                Transaction(
                    user_id="piero",
                    bank="BCP",
                    account_id=VALID_ACCOUNT_ID,
                    account_last4="1234",
                    date=date(2026, 2, 15),
                    description="ANOTHER FILE'S MOVEMENT",
                    amount=Decimal("-1.00"),
                    currency="PEN",
                    source_file_sha256=other_sha256,
                )
            ]
        ),
        other_sha256,
    )

    assert bronze.transactions_for_file("piero", VALID_SHA256) == [
        (date(2026, 1, 15), "TEST MOVEMENT", Decimal("-25.50"))
    ]


def test_two_users_land_in_separate_partitions_and_are_independent(
    lakehouse: Path,
) -> None:
    """Verifies partitioning by user_id (T14's acceptance criteria): both users'
    data lands under a `user_id=<id>` directory, and deleting one partition's
    files on disk leaves the other user's data fully readable."""
    import shutil

    from deltalake import DeltaTable

    piero_sha = VALID_SHA256
    ana_sha = hashlib.sha256(b"ana's statement").hexdigest()
    bronze.write_statement(_statement(user_id="piero"), piero_sha)
    bronze.write_statement(_statement(user_id="ana"), ana_sha)

    table_path = lakehouse / "bronze" / "transactions"
    partition_dirs = sorted(p.name for p in table_path.glob("user_id=*"))
    assert partition_dirs == ["user_id=ana", "user_id=piero"]

    shutil.rmtree(table_path / "user_id=ana")

    remaining = DeltaTable(str(table_path)).to_pyarrow_table(
        partitions=[("user_id", "=", "piero")]
    )
    assert remaining.num_rows == 1
    assert remaining.column("user_id").to_pylist() == ["piero"]


def test_replace_category_labels_writes_one_row_per_label(lakehouse: Path) -> None:
    from deltalake import DeltaTable

    bronze.replace_category_labels(
        "piero",
        [
            ("BCP", "PLAZA VEA SAN MIGUEL", "Alimentacion", True),
            ("BCP", "UBER TRIP", "Transporte", True),
        ],
    )

    table = DeltaTable(str(lakehouse / "bronze" / "category_labels")).to_pyarrow_table()
    assert sorted(table.column("category").to_pylist()) == [
        "Alimentacion",
        "Transporte",
    ]
    assert set(table.column("user_id").to_pylist()) == {"piero"}


def test_replace_category_labels_replaces_the_whole_set_not_appends(
    lakehouse: Path,
) -> None:
    from deltalake import DeltaTable

    bronze.replace_category_labels(
        "piero", [("BCP", "PLAZA VEA SAN MIGUEL", "Alimentacion", True)]
    )
    bronze.replace_category_labels(
        "piero", [("BCP", "PLAZA VEA SAN MIGUEL", "Otros", True)]
    )

    table = DeltaTable(str(lakehouse / "bronze" / "category_labels")).to_pyarrow_table()
    assert table.column("category").to_pylist() == ["Otros"]


def test_replace_category_labels_is_scoped_to_the_user(lakehouse: Path) -> None:
    from deltalake import DeltaTable

    bronze.replace_category_labels("ana", [("BCP", "X", "Otros", True)])
    bronze.replace_category_labels("bea", [("BCP", "Y", "Alimentacion", True)])
    bronze.replace_category_labels("ana", [("BCP", "X", "Transporte", True)])

    table = DeltaTable(str(lakehouse / "bronze" / "category_labels")).to_pyarrow_table()
    rows = sorted(
        zip(
            table.column("user_id").to_pylist(),
            table.column("category").to_pylist(),
            strict=True,
        )
    )
    assert rows == [("ana", "Transporte"), ("bea", "Alimentacion")]


def test_replace_category_labels_with_an_empty_set_deletes_and_writes_nothing(
    lakehouse: Path,
) -> None:
    from deltalake import DeltaTable

    bronze.replace_category_labels("piero", [("BCP", "X", "Otros", True)])

    bronze.replace_category_labels("piero", [])

    table = DeltaTable(str(lakehouse / "bronze" / "category_labels")).to_pyarrow_table()
    assert table.num_rows == 0


def test_replace_category_labels_on_a_fresh_lake_deletes_nothing_first(
    lakehouse: Path,
) -> None:
    """No table exists yet: the delete-before-write guard must not error."""
    bronze.replace_category_labels("piero", [("BCP", "X", "Otros", True)])

    from deltalake import DeltaTable

    table = DeltaTable(str(lakehouse / "bronze" / "category_labels")).to_pyarrow_table()
    assert table.num_rows == 1


def test_replace_category_predictions_writes_one_row_per_prediction(
    lakehouse: Path,
) -> None:
    from deltalake import DeltaTable

    bronze.replace_category_predictions(
        "piero",
        [
            ("BCP", "PLAZA VEA SAN MIGUEL", "Alimentacion"),
            ("BCP", "UBER TRIP", "Transporte"),
        ],
    )

    table = DeltaTable(
        str(lakehouse / "bronze" / "category_predictions")
    ).to_pyarrow_table()
    assert sorted(table.column("category").to_pylist()) == [
        "Alimentacion",
        "Transporte",
    ]
    assert set(table.column("user_id").to_pylist()) == {"piero"}


def test_replace_category_predictions_replaces_the_whole_set_not_appends(
    lakehouse: Path,
) -> None:
    from deltalake import DeltaTable

    bronze.replace_category_predictions(
        "piero", [("BCP", "PLAZA VEA SAN MIGUEL", "Alimentacion")]
    )
    bronze.replace_category_predictions(
        "piero", [("BCP", "PLAZA VEA SAN MIGUEL", "Otros")]
    )

    table = DeltaTable(
        str(lakehouse / "bronze" / "category_predictions")
    ).to_pyarrow_table()
    assert table.column("category").to_pylist() == ["Otros"]


def test_replace_category_predictions_is_scoped_to_the_user(lakehouse: Path) -> None:
    from deltalake import DeltaTable

    bronze.replace_category_predictions("ana", [("BCP", "X", "Otros")])
    bronze.replace_category_predictions("bea", [("BCP", "Y", "Alimentacion")])

    table = DeltaTable(
        str(lakehouse / "bronze" / "category_predictions")
    ).to_pyarrow_table()
    rows = sorted(
        zip(
            table.column("user_id").to_pylist(),
            table.column("category").to_pylist(),
            strict=True,
        )
    )
    assert rows == [("ana", "Otros"), ("bea", "Alimentacion")]


def test_replace_category_predictions_with_an_empty_set_writes_nothing(
    lakehouse: Path,
) -> None:
    from deltalake import DeltaTable

    bronze.replace_category_predictions("piero", [("BCP", "X", "Otros")])

    bronze.replace_category_predictions("piero", [])

    table = DeltaTable(
        str(lakehouse / "bronze" / "category_predictions")
    ).to_pyarrow_table()
    assert table.num_rows == 0


def test_replace_category_predictions_on_a_fresh_lake_deletes_nothing_first(
    lakehouse: Path,
) -> None:
    bronze.replace_category_predictions("piero", [("BCP", "X", "Otros")])

    from deltalake import DeltaTable

    table = DeltaTable(
        str(lakehouse / "bronze" / "category_predictions")
    ).to_pyarrow_table()
    assert table.num_rows == 1


def test_distinct_bank_descriptions_is_empty_on_a_fresh_lake() -> None:
    assert bronze.distinct_bank_descriptions("piero") == []


def test_distinct_bank_descriptions_returns_sorted_unique_pairs_for_the_user(
    lakehouse: Path,
) -> None:
    # Two separate statements: a Statement's own transactions must all share its
    # bank (ADR 0012), so a multi-bank scenario needs one statement per bank.
    bcp_statement = _statement(
        user_id="piero",
        bank="BCP",
        transactions=[
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 10),
                description="UBER TRIP",
                amount=Decimal("-10.00"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            ),
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 20),
                description="UBER TRIP",  # a repeat, must collapse to one pair
                amount=Decimal("-12.00"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            ),
        ],
    )
    other_sha256 = hashlib.sha256(b"a second synthetic statement").hexdigest()
    scotiabank_statement = _statement(
        user_id="piero",
        bank="Scotiabank",
        transactions=[
            Transaction(
                user_id="piero",
                bank="Scotiabank",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description="NETFLIX.COM",
                amount=Decimal("-30.00"),
                currency="PEN",
                source_file_sha256=other_sha256,
            ),
        ],
    )
    bronze.write_statement(bcp_statement, VALID_SHA256)
    bronze.write_statement(scotiabank_statement, other_sha256)

    assert bronze.distinct_bank_descriptions("piero") == [
        ("BCP", "UBER TRIP"),
        ("Scotiabank", "NETFLIX.COM"),
    ]


def test_distinct_bank_descriptions_is_scoped_to_the_user(lakehouse: Path) -> None:
    bronze.write_statement(_statement(user_id="piero"), VALID_SHA256)

    assert bronze.distinct_bank_descriptions("someone-else") == []


def test_labeled_bank_descriptions_is_empty_on_a_fresh_lake() -> None:
    assert bronze.labeled_bank_descriptions("piero") == set()


def test_labeled_bank_descriptions_returns_the_users_confirmed_pairs(
    lakehouse: Path,
) -> None:
    bronze.replace_category_labels(
        "piero",
        [
            ("BCP", "PLAZA VEA SAN MIGUEL", "Alimentacion", True),
            ("BCP", "UBER TRIP", "Transporte", True),
        ],
    )

    assert bronze.labeled_bank_descriptions("piero") == {
        ("BCP", "PLAZA VEA SAN MIGUEL"),
        ("BCP", "UBER TRIP"),
    }


def test_labeled_bank_descriptions_is_scoped_to_the_user(lakehouse: Path) -> None:
    bronze.replace_category_labels("ana", [("BCP", "X", "Otros", True)])

    assert bronze.labeled_bank_descriptions("bea") == set()


def test_distinct_bank_descriptions_normalizes_padding_and_case(
    lakehouse: Path,
) -> None:
    """Real bug found live verifying scripts.categorize_new_movements end to end:
    bronze's own description is raw, but category_labels/category_predictions (and
    gold.rpt_movements's own join against them) always key by the normalized form
    (dbt/macros/normalize_description.sql), the same rules
    ingestion.schema.normalize_description implements here."""
    statement = _statement(
        transactions=[
            Transaction(
                user_id="piero",
                bank="BCP",
                account_id=VALID_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description="uber..trip   help.uber.com",
                amount=Decimal("-25.50"),
                currency="PEN",
                source_file_sha256=VALID_SHA256,
            )
        ]
    )
    bronze.write_statement(statement, VALID_SHA256)

    assert bronze.distinct_bank_descriptions("piero") == [
        ("BCP", "UBER TRIP HELP.UBER.COM")
    ]


def _plan_item(
    description: str = "PLANTED RENT", **overrides: Any
) -> bronze.PlanItemRow:
    fields: dict[str, Any] = {
        "bank": "BCP",
        "description": description,
        "currency": "PEN",
        "category": "Servicios",
        "months_seen": 6,
        "typical_amount": 1200.0,
        "proposed_kind": "fixed",
        "kind": "fixed",
        "expected_amount": 1250.5,
        "note": "",
    }
    fields.update(overrides)
    return bronze.PlanItemRow(**fields)


def _plan_goal(**overrides: Any) -> bronze.PlanGoalRow:
    fields: dict[str, Any] = {
        "goal_amount": 10000.0,
        "usd_to_pen": 3.7525,
        "emergency_months": 6,
        "emergency_basis": "all",
        "emergency_account": "Ripley",
        "target_date": date(2027, 12, 31),
        "income_pen_override": None,
        "income_usd_override": None,
    }
    fields.update(overrides)
    return bronze.PlanGoalRow(**fields)


def _plan_table(lakehouse: Path, name: str) -> Any:
    from deltalake import DeltaTable

    return DeltaTable(str(lakehouse / "bronze" / name)).to_pyarrow_table().to_pylist()


def test_replace_plan_writes_one_row_per_item_and_one_goal_row(
    lakehouse: Path,
) -> None:
    bronze.replace_plan(
        "piero",
        [_plan_item("PLANTED RENT"), _plan_item("PLANTED GYM", kind="variable")],
        _plan_goal(),
    )

    items = _plan_table(lakehouse, "plan_fixed_items")
    goal = _plan_table(lakehouse, "plan_goal")
    assert sorted((r["description"], r["kind"]) for r in items) == [
        ("PLANTED GYM", "variable"),
        ("PLANTED RENT", "fixed"),
    ]
    assert {r["user_id"] for r in items} == {"piero"}
    assert items[0]["expected_amount"] == Decimal("1250.50")
    assert len(goal) == 1
    assert goal[0]["goal_amount"] == Decimal("10000.00")
    assert goal[0]["usd_to_pen"] == 3.7525
    assert goal[0]["goal_currency"] == "USD"
    assert goal[0]["target_date"] == date(2027, 12, 31)
    assert goal[0]["income_pen_override"] is None


def test_replace_plan_stamps_both_tables_with_the_same_load_time(
    lakehouse: Path,
) -> None:
    bronze.replace_plan("piero", [_plan_item()], _plan_goal())

    items = _plan_table(lakehouse, "plan_fixed_items")
    goal = _plan_table(lakehouse, "plan_goal")
    assert items[0]["loaded_at"] == goal[0]["loaded_at"]


def test_replace_plan_replaces_the_whole_plan_not_appends(lakehouse: Path) -> None:
    bronze.replace_plan(
        "piero", [_plan_item("PLANTED RENT"), _plan_item("PLANTED GYM")], _plan_goal()
    )
    bronze.replace_plan("piero", [_plan_item("PLANTED RENT")], _plan_goal(usd_to_pen=4))

    items = _plan_table(lakehouse, "plan_fixed_items")
    goal = _plan_table(lakehouse, "plan_goal")
    assert [r["description"] for r in items] == ["PLANTED RENT"]
    assert [r["usd_to_pen"] for r in goal] == [4.0]


def test_replace_plan_is_scoped_to_the_user(lakehouse: Path) -> None:
    bronze.replace_plan("ana", [_plan_item("ANA RENT")], _plan_goal())
    bronze.replace_plan("bea", [_plan_item("BEA RENT")], _plan_goal())
    bronze.replace_plan("ana", [_plan_item("ANA NEW")], _plan_goal())

    rows = sorted(
        (r["user_id"], r["description"])
        for r in _plan_table(lakehouse, "plan_fixed_items")
    )
    assert rows == [("ana", "ANA NEW"), ("bea", "BEA RENT")]
    assert sorted(r["user_id"] for r in _plan_table(lakehouse, "plan_goal")) == [
        "ana",
        "bea",
    ]


def test_replace_plan_with_no_items_still_writes_the_goal(lakehouse: Path) -> None:
    bronze.replace_plan("piero", [_plan_item()], _plan_goal())

    bronze.replace_plan("piero", [], _plan_goal())

    assert _plan_table(lakehouse, "plan_fixed_items") == []
    assert len(_plan_table(lakehouse, "plan_goal")) == 1


def _empty_statement(
    bank: str, *, user_id: str = "piero", kind: str = "asset"
) -> tuple[Statement, str]:
    tag = f"{user_id}:{bank}".encode()
    statement = _statement(
        user_id=user_id,
        bank=bank,
        account_id=hashlib.sha256(tag).hexdigest(),
        account_kind=kind,
        closing_balance=Decimal("100.00"),
        transactions=[],
    )
    return statement, hashlib.sha256(tag + b"file").hexdigest()


def test_asset_account_names_are_the_users_asset_banks_only() -> None:
    for bank, user_id, kind in [
        ("BCP", "piero", "asset"),
        ("Ripley", "piero", "asset"),
        ("Scotiabank", "piero", "liability"),
        ("Other", "ana", "asset"),
    ]:
        bronze.write_statement(*_empty_statement(bank, user_id=user_id, kind=kind))

    assert bronze.asset_account_names("piero") == {"BCP", "Ripley"}


def test_asset_account_names_on_a_fresh_lake_is_empty() -> None:
    assert bronze.asset_account_names("piero") == set()


def _forecast_row(**overrides: Any) -> bronze.ForecastRow:
    fields: dict[str, Any] = {
        "kind": "forecast",
        "category": "Alimentacion",
        "currency": "PEN",
        "target_month": date(2026, 10, 1),
        "horizon": 1,
        "model_name": "median_6",
        "p10": 800.0,
        "p50": 1000.255,
        "p90": 1300.0,
        "actual": None,
    }
    fields.update(overrides)
    return bronze.ForecastRow(**fields)


def _series_row(**overrides: Any) -> bronze.ForecastSeriesRow:
    fields: dict[str, Any] = {
        "category": "Alimentacion",
        "currency": "PEN",
        "model_name": "median_6",
        "baseline_used": True,
        "low_history": False,
        "n_months": 24,
        "n_origins": 15,
        "mae_rel": 1.0,
        "coverage": 0.8,
    }
    fields.update(overrides)
    return bronze.ForecastSeriesRow(**fields)


def test_replace_forecast_run_writes_forecasts_and_series(lakehouse: Path) -> None:
    bronze.replace_forecast_run(
        "piero",
        date(2026, 9, 1),
        [_forecast_row(), _forecast_row(p10=None, p90=None, horizon=2)],
        [_series_row()],
    )

    forecasts = _plan_table(lakehouse, "spend_forecasts")
    series = _plan_table(lakehouse, "spend_forecast_series")
    assert len(forecasts) == 2
    assert {r["user_id"] for r in forecasts} == {"piero"}
    assert {r["run_month"] for r in forecasts} == {date(2026, 9, 1)}
    first = min(forecasts, key=lambda r: r["horizon"])
    assert first["p50"] == Decimal("1000.26")
    assert first["actual"] is None
    assert [r["p10"] for r in sorted(forecasts, key=lambda r: r["horizon"])] == [
        Decimal("800.00"),
        None,
    ]
    assert len(series) == 1
    assert series[0]["baseline_used"] is True
    assert series[0]["coverage"] == 0.8
    assert forecasts[0]["created_at"] == series[0]["created_at"]


def test_replace_forecast_run_twice_does_not_duplicate(lakehouse: Path) -> None:
    for _ in range(2):
        bronze.replace_forecast_run(
            "piero", date(2026, 9, 1), [_forecast_row()], [_series_row()]
        )

    assert len(_plan_table(lakehouse, "spend_forecasts")) == 1
    assert len(_plan_table(lakehouse, "spend_forecast_series")) == 1


def test_replace_forecast_run_keeps_other_months_and_other_users(
    lakehouse: Path,
) -> None:
    bronze.replace_forecast_run(
        "piero", date(2026, 8, 1), [_forecast_row(model_name="ses")], [_series_row()]
    )
    bronze.replace_forecast_run("ana", date(2026, 9, 1), [_forecast_row()], [])
    bronze.replace_forecast_run("piero", date(2026, 9, 1), [_forecast_row()], [])

    rows = sorted(
        (r["user_id"], r["run_month"], r["model_name"])
        for r in _plan_table(lakehouse, "spend_forecasts")
    )
    assert rows == [
        ("ana", date(2026, 9, 1), "median_6"),
        ("piero", date(2026, 8, 1), "ses"),
        ("piero", date(2026, 9, 1), "median_6"),
    ]
    assert len(_plan_table(lakehouse, "spend_forecast_series")) == 1


def _path_row(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "scenario": "base",
        "line": "liquid",
        "month_index": 0,
        "month": date(2026, 9, 1),
        "emergency": 1000.255,
        "goal_progress": 2000.0,
    }
    fields.update(overrides)
    return fields


def test_replace_goal_projection_writes_every_table(lakehouse: Path) -> None:
    bronze.replace_goal_projection(
        "piero",
        date(2026, 9, 1),
        {
            "goal_projection": [_path_row(), _path_row(month_index=1)],
            "goal_summary": [
                {
                    "scenario": "base",
                    "line": "liquid",
                    "months_to_goal": None,
                    "reached_month": None,
                    "required_monthly_saving": 12.346,
                    "projected_monthly_saving": 500.0,
                    "gap": None,
                    "headroom_share_of_gap": 0.5,
                }
            ],
            "emergency_fund": [
                {
                    "scenario": "base",
                    "target": 9000.0,
                    "bucket": 1000.0,
                    "gap": 8000.0,
                    "months_to_fill": 6,
                    "months_covered": 0.5,
                    "months_of_income": 3.0,
                    "savings_rate": 0.2,
                    "essential_over_income": False,
                    "target_over_two_years_income": False,
                    "balance_mismatch": None,
                    "mismatch_months": 0,
                    "months_checked": 0,
                    "avg_net_flow": None,
                    "avg_balance_change": None,
                }
            ],
            "goal_headroom": [
                {
                    "category": "Alimentacion",
                    "currency": "PEN",
                    "forecast": 300.0,
                    "reference": 250.0,
                    "headroom": 50.0,
                    "share": 1.0,
                }
            ],
            "goal_cashflow": [
                {
                    "scenario": "base",
                    "month_index": 1,
                    "month": date(2026, 10, 1),
                    "currency": "PEN",
                    "income": 4000.0,
                    "fixed": 400.255,
                    "variable": 1000.0,
                }
            ],
            "goal_balances": [
                {"bucket": "emergency", "currency": "PEN", "amount": 2000.0}
            ],
        },
    )

    path = _plan_table(lakehouse, "goal_projection")
    assert len(path) == 2
    assert {r["user_id"] for r in path} == {"piero"}
    assert {r["run_month"] for r in path} == {date(2026, 9, 1)}
    assert path[0]["emergency"] == Decimal("1000.26")
    summary = _plan_table(lakehouse, "goal_summary")[0]
    assert summary["months_to_goal"] is None
    assert summary["required_monthly_saving"] == Decimal("12.35")
    assert summary["headroom_share_of_gap"] == 0.5
    fund = _plan_table(lakehouse, "emergency_fund")[0]
    assert fund["balance_mismatch"] is None
    assert fund["months_to_fill"] == 6
    assert _plan_table(lakehouse, "goal_headroom")[0]["headroom"] == Decimal("50.00")
    [flow] = _plan_table(lakehouse, "goal_cashflow")
    assert (flow["currency"], flow["month_index"]) == ("PEN", 1)
    assert flow["fixed"] == Decimal("400.26")
    [held] = _plan_table(lakehouse, "goal_balances")
    assert (held["bucket"], held["amount"]) == ("emergency", Decimal("2000.00"))


def test_replace_goal_projection_replaces_the_users_whole_set(
    lakehouse: Path,
) -> None:
    for _ in range(2):
        bronze.replace_goal_projection(
            "piero", date(2026, 9, 1), {"goal_projection": [_path_row()]}
        )
    bronze.replace_goal_projection(
        "ana", date(2026, 9, 1), {"goal_projection": [_path_row()]}
    )
    bronze.replace_goal_projection(
        "piero", date(2026, 10, 1), {"goal_projection": [_path_row(month_index=3)]}
    )

    rows = sorted(
        (r["user_id"], r["run_month"], r["month_index"])
        for r in _plan_table(lakehouse, "goal_projection")
    )
    assert rows == [("ana", date(2026, 9, 1), 0), ("piero", date(2026, 10, 1), 3)]


def test_replace_goal_projection_with_nothing_clears_the_users_rows(
    lakehouse: Path,
) -> None:
    bronze.replace_goal_projection(
        "piero", date(2026, 9, 1), {"goal_projection": [_path_row()]}
    )

    bronze.replace_goal_projection("piero", date(2026, 10, 1), {})

    assert _plan_table(lakehouse, "goal_projection") == []
