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

Run via `make poc`, after `make poc-up`: `uv run python -m scripts.poc`.
"""

import os
import subprocess
import sys


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


def _safe_dbt_lines(output: str) -> list[str]:
    return [
        line
        for line in output.splitlines()
        if line.startswith("Done.") or " [FAIL" in line or " [ERROR" in line
    ]


def main() -> int:
    user = os.environ.get("PFP_USER")
    if not user:
        print("poc: PFP_USER is not set (see .env.example)", file=sys.stderr)
        return 2

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

    print("poc: building silver with dbt...")
    dbt = subprocess.run(
        ["uv", "run", "dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in _safe_dbt_lines(dbt.stdout):
        print(f"  {line}")

    ok = ingest.returncode == 0 and dbt.returncode == 0
    print(f"poc: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
