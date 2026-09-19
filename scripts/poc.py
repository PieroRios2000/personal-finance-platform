"""`make poc`'s flow (T17, ADR 0007): the ephemeral environment against Piero's
own real PDFs, locally, once — `pfp ingest`, then `dbt build`, and a report with
only pass/fail and reconciliation *differences* (never a real value).

This is the one place in the repo that runs the real platform against real
statements, so it is also the one place that could accidentally print one:
`ingestion.reconciliation.ReconciliationError`'s own message carries the real
expected/actual balances that did not match (`"closing balance: expected
1000.00, got 974.50 (difference -25.50)"`), and `organize()` (T12b) folds that
straight into a "needs review" entry when a real statement fails to reconcile.
So this script never prints `pfp ingest`'s or `dbt build`'s raw output — only
the handful of lines that are amount-free *by construction*:

- `OrganizeReport.render()`'s own summary line ("Archived: N  Duplicates: N
  Needs review: N", `ingestion/organizer.py`) — counts only, and "Needs review"
  is exactly the reconciliation-difference count ADR 0004 allows.
- `pfp ingest`'s own "Bronze: N written, M skipped" line (`ingestion/cli.py`).
- dbt's final "Done. PASS=.. WARN=.. ERROR=.. SKIP=.. TOTAL=.." line and its
  per-test PASS/FAIL/ERROR lines, which name a test (e.g.
  `assert_statement_continuity`), never a row's data.
- T18b's own internal-transfer match summary: row *counts* only, from
  `silver.internal_transfers`/`silver.unmatched_transfers` -- never an amount,
  account or date, and only ever queried once `dbt build` has actually
  succeeded (skipping it on a failed build avoids querying tables that may not
  exist yet, or that hold a stale run's data).

Run via `make poc`, after `make poc-up`: `uv run python -m scripts.poc`.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import duckdb


def _safe_ingest_lines(output: str) -> list[str]:
    """Only the two summary lines that are amount-free by construction: the
    report's own "Archived: N  Duplicates: N  Needs review: N" line (never the
    bare "Archived:" section header that precedes its per-item list, which this
    deliberately does not match) and `pfp ingest`'s own "Bronze: ..." line."""
    return [
        line
        for line in output.splitlines()
        if (line.startswith("Archived:") and "Duplicates:" in line)
        or line.startswith("Bronze:")
    ]


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_TIMESTAMP = re.compile(r"^\d{2}:\d{2}:\d{2}\s+")


def _safe_dbt_lines(output: str) -> list[str]:
    """dbt's summary and its failing/erroring node lines. Real dbt output has an
    ANSI colour and a `HH:MM:SS` timestamp on every line, so both are stripped
    before matching (and from what is printed)."""
    cleaned = (_TIMESTAMP.sub("", _ANSI.sub("", line)) for line in output.splitlines())
    return [
        line
        for line in cleaned
        if line.startswith("Done.") or " [FAIL" in line or " [ERROR" in line
    ]


_ALERT_VARIABLES = ("ALERT_TEAMS_WEBHOOK_URL", "ALERT_SMTP_HOST", "ALERT_EMAIL_TO")


def _needs_review_count(ingest_output: str) -> int:
    """N from the report's own "Needs review: N" summary line (a count)."""
    for line in _safe_ingest_lines(ingest_output):
        match = re.search(r"Needs review: (\d+)", line)
        if match:
            return int(match[1])
    return 0


def _send_alerts(needs_review: int, dbt_returncode: int) -> None:
    """Phase 7: errors go out now, warnings are queued for the weekly digest.
    Only when a channel is configured, and never allowed to change `make poc`'s
    own result. `alerting` prints names and counts only."""
    if not any(os.environ.get(name) for name in _ALERT_VARIABLES):
        return
    try:
        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                "alerting",
                "dbt",
                "--needs-review",
                str(needs_review),
                "--dbt-returncode",
                str(dbt_returncode),
            ],
            check=False,
        )
    except OSError as error:
        print(f"poc: could not run alerting ({type(error).__name__})", file=sys.stderr)


def _transfer_match_summary(duckdb_path: str) -> str:
    """T18b: how many internal transfers matched, and how many candidates
    didn't -- row counts only, never an amount, account or date."""
    with duckdb.connect(duckdb_path, read_only=True) as connection:
        matched = connection.execute(
            "select count(*) from silver.internal_transfers"
        ).fetchone()
        unmatched = connection.execute(
            "select count(*) from silver.unmatched_transfers"
        ).fetchone()
    assert matched is not None and unmatched is not None
    return (
        f"Internal transfers: {matched[0]} matched pair(s), "
        f"{unmatched[0]} unmatched candidate(s)"
    )


def main() -> int:
    user = os.environ.get("PFP_USER")
    if not user:
        print("poc: PFP_USER is not set (see .env.example)", file=sys.stderr)
        return 2

    # T22: Elementary is a dbt package, and dbt/dbt_packages is gitignored, so a
    # checkout that never ran `dbt deps` fails `dbt build` below. Before ingest:
    # a setup failure shouldn't have already moved the PDFs out of the inbox.
    print("poc: installing dbt packages...")
    deps = subprocess.run(
        ["uv", "run", "dbt", "deps", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        capture_output=True,
        text=True,
        check=False,
    )
    if deps.returncode != 0:
        # Package names and network errors only -- no statement data exists yet.
        print(deps.stderr.strip() or deps.stdout.strip(), file=sys.stderr)
        print("poc: FAIL")
        return 1

    print(f"poc: ingesting the real inbox for user {user!r}...")
    ingest = subprocess.run(
        ["uv", "run", "pfp", "ingest", "--user", user],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in _safe_ingest_lines(ingest.stdout):
        print(f"  {line}")
    if ingest.returncode != 0:
        # Every top-level ingest error (missing --user, PFP_ACCOUNT_KEY,
        # LAKEHOUSE_URI) is static guidance text, never a statement's data
        # (ingestion/cli.py's _run_ingest); safe to print in full.
        print(ingest.stderr.strip(), file=sys.stderr)

    # A `run_results.json` left by an earlier build must never be mistaken for
    # this one's: if dbt fails before writing a new one, there is none.
    Path("dbt/target/run_results.json").unlink(missing_ok=True)

    print("poc: building silver with dbt...")
    dbt = subprocess.run(
        ["uv", "run", "dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in _safe_dbt_lines(dbt.stdout):
        print(f"  {line}")

    if dbt.returncode == 0:
        duckdb_path = os.environ.get("PFP_DUCKDB_PATH", "dbt/pfp.duckdb")
        print(f"  {_transfer_match_summary(duckdb_path)}")

    _send_alerts(_needs_review_count(ingest.stdout), dbt.returncode)

    ok = ingest.returncode == 0 and dbt.returncode == 0
    print(f"poc: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
