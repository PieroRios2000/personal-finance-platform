"""`scripts/train_category_model.py`: the query, the model-vs-rules report and the CLI
wiring, with fakes for psycopg and MLflow -- the real connection, and the real MLflow
run, are what the manual end-to-end check (this PR's own verification) exercises. No
description here is ever real (T52, ADR 0044)."""

from pathlib import Path
from typing import Any

import psycopg
import pytest

from scripts import train_category_model as tcm

# General, synthetic training data (same shape as tests/test_category_model.py): only
# ever invented merchant-style text, never the owner's real one.
_ROWS = [
    ("BCP", "PLAZA VEA SAN MIGUEL", "Alimentacion"),
    ("BCP", "SUPERMERCADO WONG", "Alimentacion"),
    ("BCP", "SUELDO PLANILLA", "Ingreso"),
    ("BCP", "ABONO REMUNERACION", "Ingreso"),
    ("Scotiabank", "UBER TRIP", "Transporte"),
    ("Scotiabank", "GRIFO PRIMAX", "Transporte"),
    ("BCP", "NETFLIX.COM", "Entretenimiento"),
    ("BCP", "SPOTIFY AB", "Entretenimiento"),
    ("BCP", "COMISION MANTENIMIENTO", "Otros"),
    ("BCP", "ITF RETENCION", "Otros"),
]


class _FakeCursor:
    def __init__(self, rows: list[tuple[str, str, str]]) -> None:
        self._rows = rows
        self.seen_params: dict[str, Any] = {}

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: str, params: dict[str, Any]) -> None:
        self.seen_params = params

    def fetchall(self) -> list[tuple[str, str, str]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[tuple[str, str, str]]) -> None:
        self._cursor = _FakeCursor(rows)

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name, value in {
        "PFP_PG_DATABASE": "pfp",
        "PFP_PG_USER": "pfp",
        "PFP_PG_PASSWORD": "secret",
        "MLFLOW_TRACKING_URI": f"sqlite:///{tmp_path / 'mlflow.db'}",
    }.items():
        monkeypatch.setenv(name, value)


def test_fetch_labels_prefixes_the_bank_and_scopes_to_the_user(
    environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeConnection([("BCP", "PLAZA VEA", "Alimentacion")])
    monkeypatch.setattr(psycopg, "connect", lambda conninfo: fake)

    descriptions, categories = tcm.fetch_labels("piero")

    assert descriptions == ["BCP PLAZA VEA"]
    assert categories == ["Alimentacion"]
    assert fake._cursor.seen_params == {"user": "piero"}


def test_main_trains_scores_the_baseline_and_saves_the_model_locally(
    environment: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        tcm,
        "fetch_labels",
        lambda user_id: (
            [f"{bank} {description}" for bank, description, _c in _ROWS],
            [category for _b, _d, category in _ROWS],
        ),
    )
    model_path = tmp_path / "model"

    assert tcm.main(["--user", "piero", "--model-path", str(model_path)]) == 0

    assert model_path.with_suffix(".joblib").exists()


def test_main_requires_a_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    assert tcm.main(["--model-path", "/tmp/x"]) == 2


def test_main_reports_not_enough_data_instead_of_crashing(
    environment: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tcm, "fetch_labels", lambda user_id: (["A"], ["Otros"]))

    assert tcm.main(["--user", "piero", "--model-path", str(tmp_path / "model")]) == 1
    assert not (tmp_path / "model.joblib").exists()
