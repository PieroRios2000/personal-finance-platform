# Quality bar

What a change has to satisfy to be merged: each rule with its number, the command that
checks it, where it runs, and why. Read this before writing code. **This file doesn't get
weakened to let a change pass**: if a rule is in the way, fix the code or request an exception.

Last reviewed: 2026-09-12, by Piero. Commands are grouped in the [`Makefile`](Makefile);
if the Makefile and this file disagree, this file wins.

## Floor (blocks from day 1)

| Rule | Command | Where it runs |
|---|---|---|
| Lint and format with no errors | `uv run ruff check .` and `uv run ruff format --check .` | pre-commit, `make check-fast`, CI |
| Types: strict mypy with no errors | `uv run mypy .` | `make check-fast`, CI |
| No secrets in the code | gitleaks (pre-commit hook) | pre-commit, CI |
| Tests green, never disabled or weakened | `uv run pytest` and `uv run python scripts/floor_guard.py --base origin/develop` | `make check-task`, CI |

[floor-guard](scripts/floor_guard.py) checks the diff against the base branch (commits,
uncommitted changes and new files) and exits with code 1 if it finds any of these:

- `suppression`: a new comment that turns off a check, upper- or lowercase: `# noqa`,
  `# type: ignore`, `# mypy: ignore-errors`, `# mypy: disable-error-code`, `# fmt: off`,
  `# fmt: skip`, `# nosec`, `# pragma: no cover`, or `gitleaks:allow`.
- `disabled-test`: `pytest.mark.skip`, `skipif` or `xfail`, `pytest.skip()`, `pytest.xfail()`,
  `pytest.importorskip()`, `unittest.skip`, or `self.skipTest()`.
- `removed-tests`: a `test_*.py` with fewer tests or asserts than before (deleting it counts).
- `relaxed-config`: in `pyproject.toml`, the `Makefile`, or `.pre-commit-config.yaml`, any of:
  - `strict = true` removed, or `strict = false`.
  - A new `ignore`, `extend-ignore`, `ignore_errors`, `ignore_missing_imports`, or
    `disable_error_code` key, or a `disallow_*`/`warn_*` set to `false`.
  - `per-file-ignores`, as a key or as a table.
  - A floor check (ruff, mypy, pytest, floor-guard, gitleaks) that disappears from the file,
    or starts running with `-` or `|| true`.
  - A config file outside `pyproject.toml` (`mypy.ini`, `.mypy.ini`, `setup.cfg`,
    `tox.ini`, `pytest.ini`, `ruff.toml`, `.ruff.toml`, `.coveragerc`) that could override
    the configuration.
- `lowered-threshold`: in those same files, a line identical to another one except for a
  lower number (for example `--fail-under=80` → `--fail-under=70`). Dependency version bumps
  (`bandit>=1.9.4` → `bandit>=1.10.0`) don't count as a threshold.

Exits with code 2 if it can't run (for example, no `origin/develop`, or a shallow clone) and
reports only the rule and location, never the line's text.

**Known limits.** It's a text check on the diff: it doesn't understand the code. It won't
catch these, and Piero reviews them at PR time:

- Narrowing ruff's `select`, removing `fail_under` or `--fail-under`, or changing the option's
  format along with the number (`--fail-under=80` → `--fail-under 50`).
- `addopts` with `--deselect` or `-k`, a shorter `testpaths`, an `omit` in coverage, or
  `from pytest import skip`.
- A weakened assert (`assert True`), or a test deleted and a trivial one added in the same
  file. Conversely, moving tests from one file to another does get flagged (a false positive).
- A `-` or `|| true` on the numeric rules (already in warn mode until 2026-09-26), bumping
  the 20% performance margin, moving the blocking date, or adding an `ignore_imports` entry
  to the contracts.
- It flags markers that show up inside strings or docstrings in a `.py` file (a false
  positive). It doesn't check Markdown, since docs may need to name them, nor its own files,
  since its patterns and tests contain them.

## Numeric rules

Warn until **2026-09-26** and block from that day on: two weeks to calibrate the numbers
without slowing down the work. In warn mode the line carries a `-` in the `Makefile` (shows
the failure without stopping the recipe) and `continue-on-error` in CI (T5). Both come off on 2026-09-26.

| Rule | Threshold | Command | Where it runs | Mode | Why |
|---|---|---|---|---|---|
| Coverage of changed lines | ≥ 80% | `uv run pytest --cov --cov-report=xml` then `uv run diff-cover coverage.xml --compare-branch=origin/develop --fail-under=80` | `make check-full`, CI | Warns until 2026-09-26, then blocks | Forces testing what's new without requiring it for every config line |
| Security: dependencies | 0 known vulnerabilities | `uv run pip-audit` | `make check-full`, CI | Warns until 2026-09-26, then blocks | pip-audit doesn't filter by severity, so it's stricter than "no high severity": any published vulnerability fails it. If no fixed version exists, an exception is requested (`--ignore-vuln <ID>`) |
| Security: code | 0 high-severity findings | `uv run bandit -q -r . -x ./.venv --severity-level high` | `make check-full`, CI | Warns until 2026-09-26, then blocks | Below high tends to be noise (e.g. `assert` in tests) |
| Performance | The mean doesn't get worse by more than 20% | `uv run pytest -m benchmark --benchmark-min-rounds=10 --benchmark-compare --benchmark-compare-fail=mean:20%`, base vs PR on the same runner | CI's `benchmarks` job (T15) | Warns until 2026-09-26, then blocks | Leaves room for runner noise: two runs of the *same* code came out 17% apart at pytest-benchmark's default 5 rounds and ~3% apart at the 10 rounds the job uses. An artificial `time.sleep(0.1)` in `bcp.parse` is caught as `mean` +42.6% (T15's verification). The benchmarks only run when the change affects them (ADR 0008) |
| Architecture | 0 broken contracts | `uv run lint-imports` | `make check-task`, CI | Warns until 2026-09-26, then blocks | See "Architecture contracts" |

### Architecture contracts

Live in `pyproject.toml` (`[tool.importlinter]`):

1. **Parsing doesn't import `lakehouse`.** No module in `ingestion` may import
   `lakehouse`, except `ingestion.cli`, which orchestrates "parse → write to bronze". That way
   parsers are tested on their own, with no S3 or Delta, and a new bank never touches storage.
2. **`lakehouse` only depends on the schema.** It can't import anything from `ingestion`
   except `ingestion.schema`. The lakehouse writes already-validated transactions; if it
   imported a parser, a bank's layout change could break the write path.
3. **`ingestion.schema` never imports the rest of `ingestion`** (T14). Closes the gap
   contract 2 would otherwise leave open: without this, `ingestion.schema` importing a parser
   would make `lakehouse` transitively depend on it through `lakehouse → ingestion.schema`,
   without breaking contract 2.

Why they're shaped this way (tested with import-linter 2.15):

- Forbidding submodules that don't exist yet, like `ingestion.parsers`, passes silently: a
  typo or a new module nobody added to the list would go unwatched. That's why each contract
  forbids the whole package (which does exist today), so new modules underneath are covered automatically.
- The one allowed dependency goes in `ignore_imports`. If that import doesn't exist,
  import-linter fails by default ("No matches for ignored import"), and today `ingestion.cli`
  and `ingestion.schema` don't exist yet. With `unmatched_ignore_imports_alerting = "warn"` it
  only warns.
- Checked against a copy with the future layout: `ingestion.parsers.bcp → lakehouse.bronze`
  and `lakehouse.bronze → ingestion.parsers.bcp` break the contracts;
  `ingestion.cli → lakehouse.bronze` and `lakehouse.bronze → ingestion.schema` satisfy them.
- Each exception lists the package and its submodules (`ingestion.cli -> lakehouse` and
  `ingestion.cli -> lakehouse.**`), because `**` doesn't include the package itself. That also
  allows `import lakehouse` or `import ingestion.schema` from `lakehouse/__init__.py`.
- **Confirmed in T14, once the real imports existed:** the bare-package half of each
  `ignore_imports` pair (`ingestion.cli -> lakehouse`, `lakehouse -> ingestion.schema`) still
  warns "No matches" even now, and keeps warning — `from lakehouse import bronze` and
  `from ingestion.schema import Statement` are submodule/name imports, which only satisfy the
  `.**` half of each pair. That's expected, not a regression: those bare-package forms stay
  available for a future `import lakehouse` or `import ingestion.schema`, and the two warnings
  are permanent, harmless noise rather than a signal something is missing.

## Checks

| Recipe | What it runs | Budget | Why |
|---|---|---|---|
| `make check-fast` | ruff check, ruff format --check, mypy | < 5 s | Runs after every change; if it gets slower than that, it stops being run |
| `make check-task` | check-fast + pytest with coverage + floor-guard + import-linter | < 90 s | When finishing a task (Definition of Done) |
| `make check-full` | check-task + pip-audit + bandit + diff-cover against `origin/develop` | No limit | What CI runs, except gitleaks, which runs in pre-commit (and in CI from T5 on); pip-audit needs the network |

`BASE` changes the comparison branch: `make check-full BASE=origin/main`.

## Measured (2026-09-13, on the current code)

| Metric | Today | Note |
|---|---|---|
| Project coverage (`ingestion`, `lakehouse`, `scripts`) | 96% (820 statements, 33 uncovered) | Uncovered: `ingestion/parsers/base.py`'s Protocol body (9, never executed), the CLI's argparse wiring (8), the BCP parser's defensive branches (9), and the scripts' `sys.exit(main())` lines |
| Coverage of changed lines (diff-cover) | 90% | On T15's diff: 11 lines, 1 uncovered (`scripts/ci_impact.py`'s `sys.exit(main())`) |
| `make check-fast` duration | 0.7 s with mypy's cache; 16.8 s the first time | The first run (no cache, mypy also checks pdfplumber and pikepdf) goes over 5 s |
| `make check-task` duration | 28.2 s | 200 tests, 5 deselected (`real_pdf`, `integration`, `benchmark`) |
| `make check-full` duration | 37.4 s | Includes pip-audit's network lookup, which varies |
| pip-audit / bandit | 0 vulnerabilities / 0 high findings | |
| Parsing: a 3-page, 120-row synthetic statement (`bcp.parse`) | **274 ms mean** (median 259 ms, 10 rounds) | `uv run pytest -m benchmark` on Piero's WSL2 machine (T15). A GitHub runner's own numbers will differ; what the gate compares is base vs PR on one runner, never a number from here |
| Write: a 100-transaction statement to bronze (`bronze.write_statement`) | **99 ms mean** (median 96 ms, 16 rounds) | Three Delta appends (transactions, statements, ingested_files) to a `tmp_path` lake, not S3 (ADR 0006) |

## Exceptions

If a rule can't be met for a real reason (say, a library with no type stubs):

1. Add a row to the table in the same PR: rule, file (accepts globs like `tests/*`),
   reason, who approved it, and a review date, at most 90 days out.
2. Piero approves it while reviewing the PR. If he doesn't, the row is removed.
3. floor-guard reads this table: while the row exists, it won't block that rule on that file,
   and shows it as an "approved exception" so it's visible. floor-guard doesn't check the
   review date, because once the excepted change is merged it's already in the base branch and
   never shows up in a diff again. The date is a reminder for Piero: that day he decides
   whether to fix the code or renew the row with a new reason.
4. For numeric rules, the exception is configured in the tool itself (e.g. `--ignore-vuln <ID>`
   in pip-audit) and also noted here.

The rule is one of floor-guard's (`suppression`, `disabled-test`, `removed-tests`,
`relaxed-config`, `lowered-threshold`) or a numeric rule's name.

| Rule | File | Reason | Approved by | Review by |
|---|---|---|---|---|
| disabled-test | `tests/parsers/test_bcp.py` | The `real_pdf`-marked test conditionally skips at runtime when no real PDF or `BCP_PDF_PASSWORD` is available on this machine (T11's own acceptance criteria require this test to exist and be skippable, per ADR 0004). No skip mechanism exists that both matches floor-guard's other rules and evades this heuristic without hiding that fact from review, so this is an explicit exception rather than a workaround. | Piero | 2026-12-12 |
| relaxed-config | `pyproject.toml` | T11b's `pytesseract` and T14's `pyarrow` ship no type stubs or `py.typed` marker, and no `types-pytesseract` or `types-pyarrow` package exists on PyPI (checked on PyPI directly) — this is this file's own example case for an exception ("say, a library with no type stubs"). The `[[tool.mypy.overrides]]` scopes `ignore_missing_imports` to those two modules only; every other module still runs under `strict = true`. | Piero | 2026-12-12 |
| disabled-test | `tests/test_bronze_integration.py` | T14's `integration`-marked test needs real local S3 (SeaweedFS, T13) running via `make poc-up`, which isn't always available (not in CI until T17, and Docker wasn't reachable in this WSL session while T14 was built). It conditionally skips with a clear reason when the required env vars aren't set or `LAKEHOUSE_URI` isn't `s3://...`, mirroring the same already-approved `real_pdf` pattern above: the test exists and passes for real once run against a live SeaweedFS (`pytest -m integration`), which is T14's own acceptance criteria. | Piero | 2026-12-12 |
