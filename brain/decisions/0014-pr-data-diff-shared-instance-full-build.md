---
type: decision
phase: 1
status: accepted
date: 2026-09-14
---

# ADR 0014: pr-data-diff isolates by URI prefix, not by environment, and always builds in full

## Context

ADR 0007 already decided *that* every PR should get its base-vs-PR data diff published to
the job summary; T17b is what actually builds it. Two questions ADR 0007 left open once the
implementation started:

1. **How do the base run and the PR run avoid clobbering each other** — the same SeaweedFS
   bucket (`lakehouse`) and the same on-disk `dbt/pfp.duckdb` path are exactly what every
   other job (`ephemeral-integration`, `make poc`) already writes to.
2. **How much of `dbt build` should each run do** — `ephemeral-integration` (ADR 0008, ADR
   0013) narrows to `state:modified+` when it safely can, to save time; does `pr-data-diff`
   get the same narrowing for the same reason?

> **Amended by T29 ([ADR 0029](0029-dbt-stores-silver-and-gold-in-postgres.md)).** Silver and gold
> now live in PostgreSQL, so each run's own store is a **database** of the job's one Postgres
> (`pfp_diff_base`, `pfp_diff_pr`, created empty by `scripts/pg_databases.py`) instead of a
> `PFP_DUCKDB_PATH` file, and `scripts/data_diff.py` attaches both databases read-only and compares
> `silver` and `gold`. Everything below about prefixes, separate inboxes and never narrowing the
> build still holds; where it says "`.duckdb` file", read "database". Elementary keeps a DuckDB
> file per run.

## Decision

**One SeaweedFS instance, two URI prefixes; two full `dbt build` runs, never narrowed.**

- **Isolation is a prefix, not a second environment.** `pr-data-diff` brings up exactly one
  `docker compose -p pfp-pr-diff-<n>` SeaweedFS, the same as any other job's environment
  (ADR 0007). The base run points `LAKEHOUSE_URI` at `s3://lakehouse/pr-diff-base` and the PR
  run at `s3://lakehouse/pr-diff-pr` — two prefixes in the one `lakehouse` bucket
  `bucket-init` already creates, not two buckets or two SeaweedFS containers. Each run also
  gets its own `PFP_DUCKDB_PATH` (`/tmp/pfp-ci-diff-base.duckdb` /
  `-pr.duckdb`) and its own `PFP_INBOX_ROOT`/`PFP_ARCHIVE_ROOT`, so the second run's
  `organize()` dedup pass never sees the first run's already-archived synthetic file and
  silently skips it as a duplicate.
- **Always a full `dbt build`, on both sides — never `DBT_SELECT`'s `state:modified+`.** That
  narrowing (ADR 0008, ADR 0013) only makes sense against a *persisted* target from a real
  previous build; every run here starts from a brand-new, empty `.duckdb` file with nothing
  in it yet. Selecting "only what changed" against an empty target would leave most models
  simply absent from that fresh database — not a narrower diff, a broken one, since
  `data_diff.py` would report every un-selected model as "missing" on whichever side (or
  both) skipped it. `ephemeral-integration`'s narrowing and `pr-data-diff`'s full build are
  answering different questions — "did this change break anything," narrowed for speed, vs.
  "what does the data actually look like," which needs the whole picture — so the same
  `dbt_select` job output doesn't apply to both.
- **The diff itself reads two files through one DuckDB connection.** `scripts/data_diff.py`
  `ATTACH`es both `.duckdb` files read-only (`base`/`pr`) rather than opening two separate
  connections: every comparison — row counts, a column/type diff, a bounded `EXCEPT`-both-
  ways sample — is then one ordinary cross-catalog SQL query DuckDB already supports, with
  no data copied between connections and no second process.
- **The base branch's code gets onto disk two different ways, on purpose.** `ingestion/` and
  `lakehouse/` swap in place (`git checkout origin/$PFP_BASE_REF -- ingestion lakehouse`,
  `benchmarks`' own idiom, T15): safe there, since Python only executes what's reachable from
  an import, so a file the PR added and base doesn't have just sits on disk unused once
  `dispatcher.py` etc. are swapped back. `dbt/` instead comes from a detached worktree
  (`git worktree add --detach /tmp/pfp-diff-base-ref origin/$PFP_BASE_REF`), exactly ADR
  0013's own pattern: `git checkout <ref> -- dbt` only overwrites or *creates* paths `<ref>`
  has, it never *deletes* a path the PR added that base doesn't — harmless for Python's
  import graph, but a real bug for dbt, which discovers every model by scanning `models/` on
  disk. A model file the PR added would stay in place under a plain checkout swap and get
  built into the "base" run too, silently defeating the exact case this job most needs to
  catch (a new model reported as "unchanged" instead of "new"). A worktree always contains
  exactly what the base ref has, nothing more.

## Alternatives considered

- **Two separate `docker compose -p` SeaweedFS instances** (e.g. `pfp-pr-diff-base-<n>` and
  `pfp-pr-diff-pr-<n>`): true isolation, but two containers to wait on and tear down for
  isolation a URI prefix already gives for free — SeaweedFS's own bucket/key namespace
  already separates `pr-diff-base/...` from `pr-diff-pr/...` as cleanly as two servers would,
  at a fraction of the setup and teardown cost.
- **Narrowing `pr-data-diff`'s `dbt build` the same way `ephemeral-integration` does**:
  rejected per the Decision above — narrowed selection against an empty target isn't a
  smaller comparison, it's a wrong one.
- **`duckdb.connect()` twice (two connections) instead of `ATTACH`**: would need to shuttle
  query results between two separate Python-side connections by hand (fetch from one, filter
  in Python, compare against the other) for every comparison `EXCEPT` does natively in SQL —
  more code in `data_diff.py` to do what one `ATTACH` and a cross-catalog query already does,
  and harder to keep the row-diff query (which needs both tables in the same `FROM`/`EXCEPT`
  clause) correct.
- **A separate CI job per side** (`pr-data-diff-base`, `pr-data-diff-pr`) with the comparison
  in a third job consuming both as artifacts: the same round-trip cost ADR 0013 already
  rejected for the `dbt parse` manifest, for a build that takes longer, not less time, to
  serialize through artifacts than to just run twice in one job.
- **A plain `git checkout origin/$PFP_BASE_REF -- ingestion lakehouse dbt` for all three
  directories**, matching `benchmarks`' idiom exactly: the first version of this job did
  exactly this, and a code-review pass on the diff caught the bug described in the Decision
  above before this PR was reviewed by Piero — a model the PR added would stay on disk and
  get built into the "base" run too. Fixed by moving `dbt/` to a worktree; `ingestion/` and
  `lakehouse/` keep the checkout-swap, since the failure mode is specific to how dbt discovers
  models, not to the swap mechanism itself.

## Consequences

- `pr-data-diff` runs in parallel with `ephemeral-integration`, gated by the same
  `needs.changes.outputs.integration` output (`scripts/ci_impact.py`) — not sequenced after
  it, since the two jobs write to entirely separate places and there is nothing one needs
  from the other.
- Warn-only, per T17b: the job carries `continue-on-error: true` at the job level (not just a
  step), and — unlike `ephemeral-integration` — is never added to the branch ruleset's
  required checks. A real base-vs-PR difference is expected and informative; a broken
  base-branch build shouldn't block a PR that never touched it.
- The known gap this leaves: if the base branch's own build is broken, `pr-data-diff` posts no
  summary for that run (the base-run step is `continue-on-error` so the PR run and teardown
  still happen, but `data_diff.py` has nothing to read on the base side). Acceptable the same
  way ADR 0008 bounds every other CI gap — visible in the job's own log, never a blocked
  merge, and it says something true (the base branch itself doesn't build) rather than a
  misleading empty diff.

## Related

- [ADR 0007: Ephemeral per-PR environments](0007-ephemeral-per-pr-environments.md) — the
  "Compare" bullet this ADR implements, and the project-name-per-environment convention this
  reuses for the shared instance's isolation.
- [ADR 0008: Impact-based CI](0008-impact-based-ci.md) — the `integration` gate this job
  shares with `ephemeral-integration`, and the narrowing this ADR deliberately does not reuse.
- [ADR 0013: dbt state comparison via a base-ref worktree](0013-dbt-state-comparison-via-a-base-ref-worktree.md)
  — the narrowing mechanism this ADR explains why `pr-data-diff` doesn't call.
- [CI](../components/ci.md) — the workflow this describes.
