"""Tests for scripts.categorize_new_movements: the batch step that predicts a
category for every new, unconfirmed (bank, description) at ingest time (T54, ADR
0045). A real disk-backed lake and a real trained Bundle throughout -- no mocking of
`lakehouse.bronze` or `categorization.model` themselves, same boundary
`tests/test_bronze.py` and `tests/test_category_model.py` already use. Every
description here is invented, never the owner's real one."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import joblib
import pytest

from categorization import model
from ingestion.schema import Statement, Transaction
from lakehouse import bronze
from scripts import categorize_new_movements as cnm

_ACCOUNT_ID = "a" * 64

# Enough distinct merchants, two categories, to satisfy model.train()'s own guards
# (MIN_EXAMPLES=10, MIN_PER_CLASS=2, at least 2 distinct merchant groups).
_DESCRIPTIONS = [
    "UBER TRIP HELP.UBER.COM",
    "TAXI SATELITAL LIMA",
    "GRIFO PRIMAX AV BRASIL",
    "PEAJE PUENTE PIEDRA",
    "PEAJE VILLA",
    "TAXI VERDE LIMA",
    "NETFLIX.COM 099999999",
    "SPOTIFY AB STOCKHOLM",
    "HBO MAX SUBSCRIPTION",
    "DISNEY PLUS SUBSCRIPTION",
]
_CATEGORIES = ["Transporte"] * 6 + ["Servicios"] * 4


@pytest.fixture(autouse=True)
def lakehouse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    lake = tmp_path / "lake"
    monkeypatch.setenv("LAKEHOUSE_URI", str(lake))
    return lake


def _write_transaction(
    *, bank: str, description: str, sha256: str, user_id: str = "piero"
) -> None:
    sha256 = hashlib.sha256(sha256.encode()).hexdigest()
    statement = Statement(
        user_id=user_id,
        bank=bank,
        account_id=_ACCOUNT_ID,
        account_last4="1234",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("74.50"),
        account_kind="asset",
        currency="PEN",
        transactions=[
            Transaction(
                user_id=user_id,
                bank=bank,
                account_id=_ACCOUNT_ID,
                account_last4="1234",
                date=date(2026, 1, 15),
                description=description,
                amount=Decimal("-25.50"),
                currency="PEN",
                source_file_sha256=sha256,
            )
        ],
    )
    bronze.write_statement(statement, sha256)


def _saved_bundle(path: Path) -> None:
    pipeline, _metrics = model.train(_DESCRIPTIONS, _CATEGORIES)
    bundle = model.Bundle(pipeline=pipeline, confidence_threshold=0.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def test_run_with_no_trained_model_predicts_nothing(tmp_path: Path) -> None:
    _write_transaction(bank="BCP", description="UBER TRIP HELP.UBER.COM", sha256="a")

    report = cnm.run("piero", model_path=tmp_path / "no-model-here")

    assert report.has_model is False
    assert report.predicted == 0
    assert report.total_descriptions == 1
    assert bronze.distinct_bank_descriptions("piero") == [
        ("BCP", "UBER TRIP HELP.UBER.COM")
    ]


def test_run_predicts_only_for_unlabeled_descriptions(
    tmp_path: Path, lakehouse: Path
) -> None:
    _write_transaction(bank="BCP", description="UBER TRIP HELP.UBER.COM", sha256="a")
    _write_transaction(bank="BCP", description="NETFLIX.COM 099999999", sha256="b")
    bronze.replace_category_labels(
        "piero", [("BCP", "NETFLIX.COM 099999999", "Servicios", True)]
    )
    model_path = tmp_path / "model"
    _saved_bundle(model_path.with_suffix(".joblib"))

    report = cnm.run("piero", model_path=model_path)

    assert report.has_model is True
    assert report.total_descriptions == 2
    assert report.already_labeled == 1
    assert report.predicted == 1

    from deltalake import DeltaTable

    table = DeltaTable(
        str(lakehouse / "bronze" / "category_predictions")
    ).to_pyarrow_table()
    rows = list(
        zip(
            table.column("bank").to_pylist(),
            table.column("description").to_pylist(),
            strict=True,
        )
    )
    assert rows == [("BCP", "UBER TRIP HELP.UBER.COM")]


def test_run_is_scoped_to_the_user(tmp_path: Path) -> None:
    _write_transaction(
        bank="BCP", description="UBER TRIP HELP.UBER.COM", sha256="a", user_id="ana"
    )
    model_path = tmp_path / "model"
    _saved_bundle(model_path.with_suffix(".joblib"))

    report = cnm.run("bea", model_path=model_path)

    assert report.total_descriptions == 0
    assert report.predicted == 0


def test_run_finds_a_model_saved_without_the_joblib_suffix(tmp_path: Path) -> None:
    """Same convention as export_category_labels.py/train_category_model.py: a
    --model-path with or without ".joblib" must resolve to the same file."""
    _write_transaction(bank="BCP", description="UBER TRIP HELP.UBER.COM", sha256="a")
    model_path = tmp_path / "model"
    _saved_bundle(model_path.with_suffix(".joblib"))

    report = cnm.run("piero", model_path=model_path)

    assert report.has_model is True
    assert report.predicted == 1


def test_main_requires_a_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    assert cnm.main([]) == 2
