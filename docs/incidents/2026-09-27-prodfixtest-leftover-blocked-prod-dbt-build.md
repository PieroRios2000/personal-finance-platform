# 2026-09-27: a leftover synthetic test user blocked `dbt build` on `pfp-prod`

**Status:** resolved · **Severity:** near miss

## Summary

Updating `pfp-prod` after this session's release (PR #162) to `main`, `dbt build` failed on
`assert_statement_continuity`: one duplicate-period row for a synthetic test account
(`prodfixtest-0001`) that a fix earlier in this same session (PR #154) had already stopped from
happening again, but never cleaned up from `pfp-prod`'s own bronze lake. The demo account's own
data (`PFP_USER=demo`, 88 movements) was never at risk.

## Impact

`dbt build` failed on `pfp-prod` until cleaned up; the public demo dashboard's own data was
correct throughout (the failing build never got far enough to touch `gold.rpt_movements`, so
nothing wrong was ever shown). No real owner data involved anywhere in this incident --
`prodfixtest-0001` is a synthetic id from testing the upload portal's inbox isolation, not a real
person.

## Timeline

| When | What happened |
|---|---|
| Earlier this session | `process_submissions.py`'s missing `--inbox-root`/`--archive-root` (fixed in PR #154) let a synthetic test submission (`prodfixtest-0001`) get ingested into `pfp-prod`'s real bronze lake before the fix landed. The file itself was deleted from `~/finance-data/` at the time, but the already-ingested bronze rows (`statements`, `transactions`, `ingested_files`) were not. |
| 2026-09-27 (this update) | `dbt build` on `pfp-prod` after pulling PR #162 failed `assert_statement_continuity`: `prodfixtest-0001` had two statement periods ending in the same month on the same account/currency -- exactly the "duplicated period" case the test is designed to catch (its own docstring). |
| Same session | Diagnosed via `dbt show --inline` on the compiled test query; confirmed the one flagged row belonged to `prodfixtest-0001`, not `demo`. Deleted with `lakehouse.bronze._delete_user_rows` across every bronze table (`statements`, `transactions`, `ingested_files`, `category_labels`, `investment_entries`). `dbt build` then passed 176/176. |

## Root cause

PR #154 fixed the code path that let this happen, but a code fix doesn't retroactively clean up
data a bug already wrote. The leftover rows sat in `pfp-prod`'s bronze lake, invisible until the
next `dbt build` actually re-scanned bronze -- which hadn't happened since before the fix, because
`pfp-prod` wasn't rebuilt again until this session's release.

## Recovery

1. `dbt show --inline "<assert_statement_continuity's own compiled SQL>"` to see the exact failing
   row without touching the assertion itself -- confirmed `user_id = 'prodfixtest-0001'`.
2. `lakehouse.bronze._delete_user_rows(table, "prodfixtest-0001")` for every bronze table.
3. `dbt build` again: `176/176`, no errors.
4. Verified via `psql`: `gold.rpt_movements` has exactly one `user_id` (`demo`, 88 rows,
   unchanged) and `gold.dim_category` has the nine categories from PR #159/#160.

## What went well / what went wrong

Went well: `assert_statement_continuity` did exactly its job -- caught a real data-quality problem
before it reached a chart, on the very first rebuild after the leftover row existed. Went wrong:
the leftover row survived a code fix silently for as long as it did, because nothing re-ran
`dbt build` against `pfp-prod` in between to surface it sooner.

## Prevention

| Action | Where | Status |
|---|---|---|
| Fix the root-cause code path (missing `--inbox-root`/`--archive-root`) | PR #154 | Done, before this incident's leftover was even found |
| Clean up the leftover rows this incident found | `lakehouse.bronze._delete_user_rows`, this session | Done |
| No new guard added: `assert_statement_continuity` already is the guard, and it worked | -- | N/A |

## Lessons

A code fix and a data cleanup are two different actions; landing the first doesn't imply the
second happened. When a bug wrote bad rows before its own fix merged, check whether those rows
still exist anywhere the fix doesn't reach automatically -- here, a long-lived environment
(`pfp-prod`) that wasn't rebuilt again until well after the fix.
