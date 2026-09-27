"""`scripts/export_category_labels.py`: the query and the CLI wiring, with a fake
psycopg connection -- the real connection is what `dbt build`/CI's ephemeral postgres
exercises. No description here is ever real (T51, ADR 0043)."""

from pathlib import Path
from typing import Any

import psycopg
import pytest
from openpyxl import load_workbook

from scripts import export_category_labels as ecl


class _FakeCursor:
    def __init__(self, rows: list[tuple[str, str, int]]) -> None:
        self._rows = rows
        self.seen_params: dict[str, Any] = {}

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: str, params: dict[str, Any]) -> None:
        self.seen_params = params

    def fetchall(self) -> list[tuple[str, str, int]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[tuple[str, str, int]]) -> None:
        self._cursor = _FakeCursor(rows)

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "PFP_PG_DATABASE": "pfp",
        "PFP_PG_USER": "pfp",
        "PFP_PG_PASSWORD": "secret",
    }.items():
        monkeypatch.setenv(name, value)


def test_fetch_groups_queries_gold_scoped_to_the_user_excluding_transfers(
    environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeConnection([("BCP", "PLAZA VEA SAN MIGUEL", 3)])
    monkeypatch.setattr(psycopg, "connect", lambda conninfo: fake)

    groups = ecl.fetch_groups("piero")

    assert groups == [("BCP", "PLAZA VEA SAN MIGUEL", 3)]
    assert fake._cursor.seen_params == {"user": "piero"}


def test_main_writes_the_template_with_a_guess_already_filled_in(
    environment: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        ecl,
        "fetch_groups",
        lambda user_id: [("BCP", "PLAZA VEA SAN MIGUEL", 3), ("BCP", "XYZ CORP", 1)],
    )
    out = tmp_path / "labels.xlsx"

    assert ecl.main(["--user", "piero", "--out", str(out)]) == 0

    rows = list(load_workbook(out)["Categorias"].iter_rows(min_row=2, values_only=True))
    assert rows[0] == ("BCP", "PLAZA VEA SAN MIGUEL", 3, "Alimentacion", "Alimentacion")
    assert rows[1] == ("BCP", "XYZ CORP", 1, "Sin categorizar", "Otros")


def test_main_requires_a_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    assert ecl.main(["--out", "/tmp/x.xlsx"]) == 2


def test_main_refuses_to_write_an_empty_template(
    environment: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ecl, "fetch_groups", lambda user_id: [])

    assert ecl.main(["--user", "piero", "--out", str(tmp_path / "labels.xlsx")]) == 1
    assert not (tmp_path / "labels.xlsx").exists()
