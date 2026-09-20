"""Tests for scripts.poc (T17, ADR 0007's `make poc`).

The property that matters here is privacy, not orchestration: `pfp ingest`'s own
report is amount-free by construction *except* for a "needs review" entry whose
reason carries `ReconciliationError`'s real expected/actual balances
(`ingestion/reconciliation.py`). These tests prove the two filters this script
uses to build its report never let one of those lines through, and that the
overall pass/fail wiring is sane -- never the real `pfp`/`dbt` subprocesses,
which is what `make poc` itself (against Piero's real inbox) is for.
"""

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from scripts import poc
from scripts.poc import (
    _safe_dbt_lines,
    _safe_ingest_lines,
    _transfer_match_summary,
    main,
)


@pytest.fixture(autouse=True)
def postgres_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """`make poc` needs Postgres (ADR 0029): dummy connection variables, and the
    count query stubbed so no test needs a live database."""
    for name, value in {
        "PFP_PG_HOST": "127.0.0.1",
        "PFP_PG_PORT": "5432",
        "PFP_PG_DATABASE": "pfp",
        "PFP_PG_USER": "pfp",
        "PFP_PG_PASSWORD": "not-a-real-password",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(poc, "_transfer_counts", lambda: (0, 0))


_LEAKY_INGEST_REPORT = """Inbox: /home/piero/finance-data/inbox/piero
Archived: 1  Duplicates: 0  Needs review: 1

Archived:
  BCP ...1234: 2026-01-01 to 2026-01-31 -> \
/home/piero/finance-data/raw/piero/BCP/1234-abcdef/2026-01-01_2026-01-31.pdf

Needs review (moved to _needs_review/, nothing deleted):
  #1 (sha256 deadbeef00...): the statement did not reconcile: closing balance: \
expected 1000.00, got 974.50 (difference -25.50)

Bronze: 1 statement(s) written, 0 already ingested"""

_DBT_BUILD_OUTPUT = """1 of 13 START test assert_statement_continuity .......... [RUN]
1 of 13 FAIL 1 assert_statement_continuity .................. [FAIL 1 in 0.40s]
Done. PASS=12 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=13"""


def test_ingest_filter_keeps_only_the_two_amount_free_summary_lines() -> None:
    safe = _safe_ingest_lines(_LEAKY_INGEST_REPORT)

    assert safe == [
        "Archived: 1  Duplicates: 0  Needs review: 1",
        "Bronze: 1 statement(s) written, 0 already ingested",
    ]


@pytest.mark.parametrize("leaked", ["974.50", "1000.00", "-25.50", "deadbeef00"])
def test_ingest_filter_never_lets_a_reconciliation_difference_through(
    leaked: str,
) -> None:
    assert not any(leaked in line for line in _safe_ingest_lines(_LEAKY_INGEST_REPORT))


def test_dbt_filter_keeps_the_summary_and_failing_test_names_only() -> None:
    safe = _safe_dbt_lines(_DBT_BUILD_OUTPUT)

    assert safe == [
        "1 of 13 FAIL 1 assert_statement_continuity .................. "
        "[FAIL 1 in 0.40s]",
        "Done. PASS=12 WARN=0 ERROR=0 SKIP=0 NO-OP=0 REUSED=0 TOTAL=13",
    ]


def test_dbt_filter_drops_ordinary_start_and_pass_noise() -> None:
    assert _safe_dbt_lines("1 of 13 START test x .......... [RUN]") == []
    assert _safe_dbt_lines("1 of 13 PASS x .......... [PASS in 0.01s]") == []


def test_main_fails_clearly_without_pfp_user(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PFP_USER", raising=False)

    def _unexpected_call(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("subprocess.run must not be called without PFP_USER")

    monkeypatch.setattr(subprocess, "run", _unexpected_call)

    assert main() == 2
    assert "PFP_USER" in capsys.readouterr().err


def _fake_run(
    ingest_returncode: int, dbt_returncode: int, deps_returncode: int = 0
) -> Any:
    def run(cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[2:4] == ["dbt", "deps"]:
            return subprocess.CompletedProcess(
                cmd, deps_returncode, stdout="", stderr="deps: could not resolve"
            )
        if cmd[2] == "pfp":
            return subprocess.CompletedProcess(
                cmd, ingest_returncode, stdout=_LEAKY_INGEST_REPORT, stderr=""
            )
        return subprocess.CompletedProcess(
            cmd, dbt_returncode, stdout=_DBT_BUILD_OUTPUT, stderr=""
        )

    return run


def test_main_reports_pass_when_both_steps_succeed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PFP_USER", "piero")
    monkeypatch.setattr(subprocess, "run", _fake_run(0, 0))

    assert main() == 0
    out = capsys.readouterr().out
    assert "poc: PASS" in out
    assert "974.50" not in out


def test_main_reports_fail_when_dbt_build_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PFP_USER", "piero")
    monkeypatch.setattr(subprocess, "run", _fake_run(0, 1))

    assert main() == 1
    assert "poc: FAIL" in capsys.readouterr().out


def test_transfer_match_summary_reports_counts_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(poc, "_transfer_counts", lambda: (3, 2))

    assert (
        _transfer_match_summary()
        == "Internal transfers: 3 matched pair(s), 2 unmatched candidate(s)"
    )


class _FakePostgres:
    """Stands in for psycopg.connect(): answers each count query in order."""

    def __init__(self, counts: list[int]) -> None:
        self.counts = counts
        self.queries: list[str] = []

    def __enter__(self) -> "_FakePostgres":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: str) -> "_FakePostgres":
        self.queries.append(query)
        return self

    def fetchone(self) -> tuple[int]:
        return (self.counts.pop(0),)


def test_the_counts_are_read_from_postgres_with_no_amount_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgres([7, 4])
    monkeypatch.setattr(poc.psycopg, "connect", lambda *args, **kwargs: fake)

    assert poc._transfer_counts() == (7, 4)
    assert fake.queries == [
        "select count(*) from silver.internal_transfers",
        "select count(*) from silver.unmatched_transfers",
    ]


def test_main_fails_clearly_without_the_postgres_variables(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PFP_USER", "piero")
    monkeypatch.delenv("PFP_PG_PASSWORD")

    def _unexpected_call(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("subprocess.run must not be called without Postgres")

    monkeypatch.setattr(subprocess, "run", _unexpected_call)

    assert main() == 2
    assert "PFP_PG_PASSWORD" in capsys.readouterr().err


def test_main_prints_the_transfer_summary_when_dbt_build_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PFP_USER", "piero")
    monkeypatch.setattr(poc, "_transfer_counts", lambda: (1, 4))
    monkeypatch.setattr(subprocess, "run", _fake_run(0, 0))

    assert main() == 0
    out = capsys.readouterr().out
    assert "Internal transfers: 1 matched pair(s), 4 unmatched candidate(s)" in out


def test_main_does_not_query_transfer_tables_when_dbt_build_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No dbt build means silver's tables may not exist or may be stale --
    querying them here would be misleading at best, an unhandled error at
    worst."""
    monkeypatch.setenv("PFP_USER", "piero")

    def _must_not_query() -> tuple[int, int]:
        raise AssertionError("the tables must not be queried after a failed build")

    monkeypatch.setattr(poc, "_transfer_counts", _must_not_query)
    monkeypatch.setattr(subprocess, "run", _fake_run(0, 1))

    assert main() == 1
    assert "Internal transfers:" not in capsys.readouterr().out


def _recording(inner: Any, calls: list[list[str]]) -> Any:
    def run(cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        result: subprocess.CompletedProcess[str] = inner(cmd, **kwargs)
        return result

    return run


def test_main_installs_dbt_packages_before_ingesting_and_building(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Elementary (T22) is a dbt package: on a checkout that never ran `dbt deps`
    (dbt/dbt_packages is gitignored) a bare `dbt build` fails, so `make poc` has to
    install the packages itself, first."""
    monkeypatch.setenv("PFP_USER", "piero")
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _recording(_fake_run(0, 0), calls))

    assert main() == 0
    assert [cmd[2:4] for cmd in calls] == [
        ["dbt", "deps"],
        ["pfp", "ingest"],
        ["dbt", "build"],
    ]


def test_main_stops_before_touching_the_inbox_when_dbt_deps_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PFP_USER", "piero")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        subprocess, "run", _recording(_fake_run(0, 0, deps_returncode=1), calls)
    )

    assert main() == 1
    assert len(calls) == 1
    captured = capsys.readouterr()
    assert "poc: FAIL" in captured.out
    assert "deps: could not resolve" in captured.err


# What real dbt prints: an ANSI colour, a timestamp, then the line. The lines
# `_safe_dbt_lines` used to expect (starting with "Done." or containing " [FAIL")
# never appeared, so `make poc` showed no dbt result at all on a real run.
_REAL_DBT_OUTPUT = (
    "\x1b[0m15:20:12  Running with dbt=1.11.0\n"
    "\x1b[0m15:20:14  1 of 124 START test assert_statement_continuity ...... [RUN]\n"
    "\x1b[0m15:20:15  17 of 124 \x1b[31mFAIL 4\x1b[0m assert_statement_continuity "
    "................ [\x1b[31mFAIL 4\x1b[0m in 1.04s]\n"
    "\x1b[0m15:20:16  18 of 124 \x1b[31mERROR\x1b[0m thing .......... "
    "[\x1b[31mERROR\x1b[0m in 0.10s]\n"
    "\x1b[0m15:20:17  \n"
    "\x1b[0m15:20:17  Done. PASS=33 WARN=0 ERROR=1 SKIP=93 NO-OP=0 REUSED=0 TOTAL=127\n"
)


def test_dbt_filter_reads_real_coloured_and_timestamped_output() -> None:
    assert _safe_dbt_lines(_REAL_DBT_OUTPUT) == [
        "17 of 124 FAIL 4 assert_statement_continuity "
        "................ [FAIL 4 in 1.04s]",
        "18 of 124 ERROR thing .......... [ERROR in 0.10s]",
        "Done. PASS=33 WARN=0 ERROR=1 SKIP=93 NO-OP=0 REUSED=0 TOTAL=127",
    ]


def test_main_sends_alerts_after_the_build_when_a_channel_is_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Errors are sent the moment they appear (Phase 7): `make poc` hands the
    build's results and the count of files needing review to `alerting`."""
    monkeypatch.setenv("PFP_USER", "piero")
    monkeypatch.setenv("ALERT_TEAMS_WEBHOOK_URL", "https://teams.example.test/hook")
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _recording(_fake_run(0, 1), calls))

    main()

    alert = calls[-1]
    assert alert[2:6] == ["python", "-m", "alerting", "dbt"]
    assert alert[alert.index("--needs-review") + 1] == "1"


def test_main_does_not_call_alerting_without_a_configured_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PFP_USER", "piero")
    for name in ("ALERT_TEAMS_WEBHOOK_URL", "ALERT_SMTP_HOST", "ALERT_EMAIL_TO"):
        monkeypatch.delenv(name, raising=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _recording(_fake_run(0, 1), calls))

    main()

    assert not any("alerting" in cmd for cmd in calls)


def test_main_removes_stale_dbt_results_before_building_and_reports_the_return_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale `run_results.json` from an earlier build must never be alerted on
    as if it were this run's; and a build that produced no results at all still
    has to be reported, so poc passes dbt's return code along."""
    monkeypatch.setenv("PFP_USER", "piero")
    monkeypatch.setenv("ALERT_TEAMS_WEBHOOK_URL", "https://teams.example.test/hook")
    monkeypatch.chdir(tmp_path)
    stale = tmp_path / "dbt" / "target" / "run_results.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    calls: list[list[str]] = []
    seen_at_build: list[bool] = []

    def run(cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[2:4] == ["dbt", "build"]:
            seen_at_build.append(stale.exists())
        calls.append(list(cmd))
        result: subprocess.CompletedProcess[str] = _fake_run(0, 2)(cmd, **kwargs)
        return result

    monkeypatch.setattr(subprocess, "run", run)

    main()

    assert seen_at_build == [False]
    alert = calls[-1]
    assert alert[alert.index("--dbt-returncode") + 1] == "2"


def test_a_missing_alerting_program_never_breaks_poc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PFP_USER", "piero")
    monkeypatch.setenv("ALERT_TEAMS_WEBHOOK_URL", "https://teams.example.test/hook")

    def run(cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "alerting" in cmd:
            raise FileNotFoundError("uv")
        result: subprocess.CompletedProcess[str] = _fake_run(0, 0)(cmd, **kwargs)
        return result

    monkeypatch.setattr(subprocess, "run", run)

    assert main() == 0
