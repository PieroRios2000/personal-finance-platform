---
type: decision
phase: 3
status: accepted
date: 2026-10-03
---

# ADR 0046: monitor the classifier's inputs and assigned categories with Evidently, on derived features only

## Context

T52-T54 trained a classifier and put its predictions into `gold.rpt_movements`. A model trained
on one period's text keeps producing answers when the world changes (a new bank, a new currency,
a trip, a new kind of merchant) and nothing says its answers got worse. T55 adds the standard
MLOps check for that: compare the recent data against the older data and flag what moved.

## Decision

- **`scripts/monitor_category_drift.py` / `make monitor-category-drift`** reads
  `gold.rpt_movements` (read-only, internal transfers excluded, the same `PFP_PG_*` variables
  `train_category_model.py` uses) and runs Evidently's `DataDriftPreset` with a REFERENCE window
  (every movement older than the last `--current-days`, default 90) against a CURRENT window
  (the last 90 days, counted back from the most recent movement). The report is an HTML file
  in `~/finance-data/reports/` (directory 0700, file 0600), never the repo; the terminal gets
  only counts, a drifted-columns total and a yes/no per column.
- **Derived features only, never the description.** `build_features` drops the description
  before anything reaches Evidently. What is compared: bank, currency, flow type, description
  length, digit share of the description, `log(1 + |amount|)`, the assigned category, and
  `label_source` (the owner's confirmed label vs a model/rules proposal, from
  `category_confirmed`). So the report, the printout and any screenshot cannot contain a real
  merchant string (ADR 0004). A test asserts the feature frame has no description column.
- **No model confidence.** The batch step stores the already-thresholded category, not a
  probability (ADR 0045), so there is no confidence to monitor without a schema change nobody
  needs yet. The assigned-category distribution is the prediction-side signal.
- **Too little data is an error, not a report.** A window with fewer than `--min-rows` (30)
  movements exits 1 saying so, instead of producing a chart that looks like a finding.
- **Manual, not scheduled.** The owner ingests a statement a month; a command run after an
  ingest (like `make train-category-model`) is the whole job. Wiring it into Dagster is easy
  later if a schedule ever earns its place.

## What this can and cannot tell

- Windows here are a few hundred movements (1,066 vs 463 on the first real run). Evidently
  picks a per-column statistical test (Kolmogorov-Smirnov, chi-square or Z-test) at p < 0.05
  with no correction for testing eight columns at once, so at this size a flag is a prompt to
  open the report, not proof, and a quiet column is not proof of stability either.
- **Drift is not error.** It says the data moved, not that the model got worse. Real
  seasonality (a trip makes `Viajes` jump and the USD share rise) trips it correctly and
  harmlessly. Only new labels measure accuracy (`make train-category-model`).
- **`label_source` is uninformative while every movement is labeled.** Predictions are only
  written for descriptions the owner has not labeled, so right after a full labeling round both
  windows read 100% confirmed and the column cannot drift. It starts to mean something once new
  unlabeled statements arrive; then a growing `predicted` share is exactly the "model is
  answering more of the data" signal.
- The first real run flagged 7 of 8 columns: the 90-day window is mostly Scotiabank and more
  USD than the older history, with more `Viajes` and less `Gastos varios`. That is the
  owner's data changing shape, which is the case the monitor exists for, and also why the
  default says nothing about model quality.

## Alternatives considered

- **Put the description text in the report** (Evidently has text drift). Rejected: the report
  would hold the owner's real merchant strings, and a standing HTML artifact is much easier to
  leak than a model file. Length and digit share keep a coarse text signal at no privacy cost.
- **Whylogs, NannyML or a hand-rolled test.** Evidently is the tool named in the Phase 3 plan
  and the one a reader expects; a hand-rolled KS test would give no report to look at.
- **Compare against the training set rather than an older window.** Needs the training frame
  persisted next to the model; "older movements" needs nothing new and answers the same
  question for a model that is retrained on all labels each time.

## Consequences

- `evidently` and `pandas` are now direct dependencies (pandas was already pulled in
  transitively); `pandas-stubs` is a dev dependency, and `evidently` has a scoped mypy
  `ignore_missing_imports` override (CONSTRAINTS.md exception).
- **`evidently` pulls `nltk`, which carries PYSEC-2026-3740 (CVE-2026-81726) with no fixed
  version.** The advisory is a path-sandbox bypass in nltk's parser/tagger model save and load
  APIs, which nothing here calls. `pip-audit` runs with `--ignore-vuln PYSEC-2026-3740` in
  the Makefile and CI, recorded in CONSTRAINTS.md with a review date; the flag goes away when
  nltk ships a fix. It needs Piero's approval in this PR.
