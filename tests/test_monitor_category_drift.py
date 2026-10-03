"""`scripts/monitor_category_drift.py` (T55, ADR 0046): the privacy boundary (no
description text can reach the report), the reference/current split, the refusal on
too little data, the report's path and permissions and the CLI wiring. Every row is
synthetic; the real database read is faked like the other script tests do."""

import datetime as dt
import stat
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
import pytest

from scripts import monitor_category_drift as mcd

_TODAY = dt.date(2026, 9, 30)


def _row(
    days_ago: int,
    *,
    bank: str = "BCP",
    description: str = "PLAZA VEA SAN MIGUEL 123",
    amount: float = -42.5,
    category: str = "Alimentacion",
    confirmed: bool = True,
) -> tuple[Any, ...]:
    return (
        _TODAY - dt.timedelta(days=days_ago),
        bank,
        description,
        "PEN",
        "expense",
        amount,
        category,
        confirmed,
    )


def _rows(count: int, days_ago: int, **kwargs: Any) -> list[tuple[Any, ...]]:
    return [_row(days_ago + (i % 5), **kwargs) for i in range(count)]


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.seen_params: dict[str, Any] = {}

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: str, params: dict[str, Any]) -> None:
        self.seen_params = params

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
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


def test_fetch_movements_scopes_to_the_user(
    environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeConnection([_row(1)])
    monkeypatch.setattr(psycopg, "connect", lambda conninfo: fake)

    frame = mcd.fetch_movements("piero")

    assert len(frame) == 1
    assert fake._cursor.seen_params == {"user": "piero"}


def test_features_never_carry_the_description_text() -> None:
    raw = mcd.movements_frame([_row(1, description="SECRET MERCHANT 99")])

    features = mcd.build_features(raw)

    assert "description" not in features.columns
    assert set(features.columns) == {"date", *mcd.FEATURE_COLUMNS}
    assert "SECRET MERCHANT" not in features.to_csv()


def test_features_are_the_derived_description_shape_and_amount() -> None:
    raw = mcd.movements_frame(
        [
            _row(1, description="AB12", amount=-99.0, confirmed=True),
            _row(2, description="ABCD", amount=10.0, confirmed=False),
        ]
    )

    features = mcd.build_features(raw)

    assert features["description_length"].tolist() == [4, 4]
    assert features["digit_share"].tolist() == [0.5, 0.0]
    assert features["log_abs_amount"].iloc[0] == pytest.approx(4.60517, abs=1e-4)
    assert features["label_source"].tolist() == ["confirmed", "predicted"]


def test_split_puts_the_most_recent_days_in_current() -> None:
    raw = mcd.movements_frame(_rows(40, days_ago=100) + _rows(40, days_ago=3))

    reference, current = mcd.split_windows(
        mcd.build_features(raw), current_days=30, min_rows=30
    )

    assert len(reference) == 40
    assert len(current) == 40
    assert "date" not in reference.columns
    assert "date" not in current.columns


def test_split_refuses_a_window_with_too_few_rows() -> None:
    raw = mcd.movements_frame(_rows(40, days_ago=100) + _rows(3, days_ago=3))

    with pytest.raises(mcd.NotEnoughDataError, match="current"):
        mcd.split_windows(mcd.build_features(raw), current_days=30, min_rows=30)


def test_split_refuses_an_empty_reference() -> None:
    raw = mcd.movements_frame(_rows(40, days_ago=3))

    with pytest.raises(mcd.NotEnoughDataError, match="reference"):
        mcd.split_windows(mcd.build_features(raw), current_days=30, min_rows=30)


def test_report_is_private_and_summarizes_only_aggregates(tmp_path: Path) -> None:
    raw = mcd.movements_frame(
        _rows(60, days_ago=100, bank="BCP", category="Alimentacion")
        + _rows(60, days_ago=3, bank="Scotiabank", category="Viajes", amount=-5000.0)
    )
    reference, current = mcd.split_windows(
        mcd.build_features(raw), current_days=30, min_rows=30
    )
    out = tmp_path / "reports" / "drift.html"

    summary = mcd.write_report(reference, current, out)

    assert out.exists()
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert stat.S_IMODE(out.parent.stat().st_mode) == 0o700
    assert "PLAZA VEA" not in out.read_text(encoding="utf-8")
    assert summary.total_columns == len(mcd.FEATURE_COLUMNS)
    assert summary.per_column["bank"] is True
    assert summary.per_column["category"] is True
    assert summary.drifted_columns == sum(summary.per_column.values())


def test_main_prints_aggregates_and_writes_the_report(
    environment: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = _rows(60, days_ago=100) + _rows(60, days_ago=3, bank="Scotiabank")
    monkeypatch.setattr(mcd, "fetch_movements", lambda user: mcd.movements_frame(rows))
    out = tmp_path / "drift.html"

    assert mcd.main(["--user", "piero", "--output", str(out)]) == 0

    printed = capsys.readouterr().out
    assert "drifted" in printed
    assert "bank" in printed
    assert "PLAZA VEA" not in printed
    assert out.exists()


def test_main_says_so_when_there_is_too_little_data(
    environment: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        mcd, "fetch_movements", lambda user: mcd.movements_frame(_rows(5, days_ago=3))
    )
    out = tmp_path / "drift.html"

    assert mcd.main(["--user", "piero", "--output", str(out)]) == 1

    assert "not enough" in capsys.readouterr().err.lower()
    assert not out.exists()


def test_main_requires_a_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    assert mcd.main([]) == 2


def test_main_default_output_lives_under_finance_data() -> None:
    assert mcd.DEFAULT_REPORT_DIR == Path.home() / "finance-data" / "reports"


def test_movements_frame_is_a_dataframe() -> None:
    assert isinstance(mcd.movements_frame([_row(1)]), pd.DataFrame)
