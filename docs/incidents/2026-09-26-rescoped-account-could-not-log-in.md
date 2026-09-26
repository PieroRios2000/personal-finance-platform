# 2026-09-26: the owner's re-scoped account could not log in to Superset

**Status:** resolved · **Severity:** outage of one login (no data lost or exposed)

## Summary

After T41 (row-level security) was rolled out, the owner's own Dex account was re-scoped
from username `priosdc` to his real ingestion `user_id`. His next Superset login failed
(`UniqueViolation ... ab_user_email_key`, back to the login page). The same day Docker
Desktop restarted and left the real Superset container stopped (`Exited (127)`, a stale
bind mount, the ADR 0034 class of problem).

## Impact

The owner could not sign in to Superset until both were fixed. No data was lost, and none
was shown to anyone it should not have been.

## Timeline

| When | What happened |
|---|---|
| 2026-09-25 evening | Rolled T41 into `pfp-poc`; re-scoped the owner's Dex username (`DEX_STATIC_PASSWORDS`, `dex` recreated). His login attempt failed: `Failed to add user to db session` in Superset's log |
| 2026-09-26 morning | Asked to test his own login; checked `ab_user` first: user id 2, `username=<email>`, same email, `ab_user_email_key` unique -- the failure mode |
| 2026-09-26 | Reproduced in a throwaway project: first login as `username=email`, re-scope in Dex, login again -> `Error creating a new OAuth user`, `UniqueViolation` |
| 2026-09-26 | Same check found the real Superset `Exited (127)` after a Docker Desktop restart |

## Root cause

1. Flask-AppBuilder's `auth_user_oauth` looks a user up by **username** only, and creates
   one when it finds none -- but `ab_user.email` is unique. A username change on an
   existing account therefore means "create a second user with the same email".
2. ADR 0036 stated that re-scoping "takes effect next login, no migration". That was
   argued from the role-sync mechanism and never run against an *already-registered*
   account: every earlier check used accounts created after the scope was set.
3. Separately, a container whose bind-mounted file was replaced does not survive a Docker
   Desktop restart (exit 127).

## Recovery

`DexSecurityManager.auth_user_oauth` renames the existing user (found by email) before
FAB looks it up, and refuses a username that belongs to another email (fix PR, with
tests). Verified in a throwaway project: the same user id is renamed, no duplicate;
a second Dex account with the same username is refused while the first keeps working.
Superset on the real stack recreated (`--force-recreate`).

## What went well / what went wrong

**Well:** caught before the owner's planned test: `ab_user` was checked first, and the
failure was reproduced, not assumed.

**Wrong:** the ADR claimed an unverified property ("no migration"), and the rollout
re-scoped a real account without first trying the re-scope on an already-registered
throwaway one.

## Prevention

| Action | Where | Status |
|---|---|---|
| Rename instead of duplicate; refuse a username owned by another email | `bi/superset_config.py` | Done |
| ADR 0036 corrected: the claim and the one-username-per-person rule | `brain/decisions/0036-...` | Done |
| Before re-scoping a real account, rehearse "log in, re-scope, log in again" on a throwaway | this file | Lesson |

## Lessons

A claim about "next login" needs a test that starts from an account that already logged
in. Anything that changes a value another system keys users on (a username) needs the
existing rows checked, not just the new ones.
