"""`scripts/experiment_recurrence_features.py`: the queries' scoping and the printed
report, with a fake psycopg connection. Every description here is invented (T63)."""

from datetime import date
from typing import Any

import psycopg
import pytest

from scripts import experiment_recurrence_features as experiment

_CATEGORIES = ["Servicios", "Alimentacion", "Transporte"]


def _movements() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for merchant in range(30):
        category = _CATEGORIES[merchant % 3]
        name = f"COMERCIO {category.upper()} {chr(65 + merchant)}{chr(97 + merchant)}"
        for month in range(1, 5):
            label = None if merchant == 29 else category
            rows.append(
                (
                    "BCP",
                    name,
                    date(2026, month, 5),
                    -40.0 - merchant,
                    label,
                )
            )
    return rows


class _Cursor:
    def __init__(self) -> None:
        self.seen: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: str, params: dict[str, Any]) -> None:
        self.seen.append((query, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        if "plan_fixed_items" in self.seen[-1][0]:
            return [("BCP", "COMERCIO SERVICIOS Aa", "fixed")]
        return _movements()


class _Connection:
    def __init__(self) -> None:
        self.cursor_ = _Cursor()

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self.cursor_


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> _Connection:
    for name, value in {
        "PFP_PG_DATABASE": "pfp",
        "PFP_PG_USER": "pfp",
        "PFP_PG_PASSWORD": "secret",
    }.items():
        monkeypatch.setenv(name, value)
    fake = _Connection()
    monkeypatch.setattr(psycopg, "connect", lambda conninfo: fake)
    return fake


def test_fetch_scopes_both_queries_to_the_user(connection: _Connection) -> None:
    rows, marks = experiment.fetch("piero")

    assert len(rows) == 120
    assert marks == {("BCP", "COMERCIO SERVICIOS Aa"): "fixed"}
    assert [params for _q, params in connection.cursor_.seen] == [
        {"user": "piero"},
        {"user": "piero"},
    ]


def test_main_prints_scores_and_counts_but_no_description(
    connection: _Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    code = experiment.main(["--user", "piero", "--seeds", "1"])

    out = capsys.readouterr().out
    assert code == 0
    assert "rows: 116 trusted movements of 120; 29 merchants; 3 categories" in out
    assert "weak categories found: Alimentacion, Servicios, Transporte" in out
    for variant in ("text", "recurrence", "plan_kind", "all"):
        assert f"{variant}: macro-F1" in out
    assert "accuracy on rows seen >=2 months" in out
    assert "COMERCIO" not in out


def test_main_requires_a_user(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    assert experiment.main([]) == 2
    assert "--user is required" in capsys.readouterr().err
