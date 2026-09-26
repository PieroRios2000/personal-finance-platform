---
type: decision
phase: 2
status: accepted
date: 2026-09-25
---

# ADR 0036: row-level security, filtered by the user who ingested the data

## Context

ADR 0034 and 0035 gave each person a Dex account, operator-added or self-registered, but
every account got Superset's Admin role -- everyone who could sign in saw every account's
financial data. Both earlier ADRs flagged this as the deliberate next PR. Asked how to
scope it, the owner was direct: filter by which PDFs a person actually ingested, i.e. by
`user_id`, the column already on every `gold.rpt_*` table (ADR 0005: the schema was
multi-user from Phase 1).

## Decision

**Superset Row Level Security, filtering every gold query to `user_id =
'{{ current_username() }}'`, except for the owner.**

- **Roles flip from ADR 0034's design:** `AUTH_USER_REGISTRATION_ROLE` is now `Gamma`
  (read-only, no data access of its own), not `Admin`. Whoever signs in with the email in
  `PFP_BI_OWNER_EMAIL` also gets `role_keys: ["owner"]` (`bi/superset_config.py`), mapped
  to `Admin` via `AUTH_ROLES_MAPPING`. `AUTH_ROLES_SYNC_AT_LOGIN` (already on) recomputes
  this every login, so changing the owner's email or a person's scope takes effect next
  sign-in, no migration.
- **Superset's *username* is Dex's own `username` field** (its ID token's `name` claim),
  not the email -- it is what the row-level rule matches against. `make dex-add-user
  --username` and `dex-register`'s self-service default both leave it equal to the full
  email unless the operator deliberately sets it to a real `user_id`
  (`--username piero`). This default is deliberate, not incidental: no `user_id` this
  project ever writes can contain `@`, so a login nobody explicitly scoped can never
  accidentally land on someone else's data -- including a self-registered stranger who
  picks an email whose local part happens to match a real `user_id` (the previous
  default, the part before `@`, did not have this property).
- **`bi/setup_access.py`** grants `Gamma` `datasource_access` on the five gold datasets
  and creates the one `Base` row-level-security rule (`roles: [Admin]`, exempting it --
  confirmed against Superset's own RLS schema docstring, not guessed) after every
  dashboard import (`bi/start.sh`), since it needs each dataset's live id, which the
  export in `bi/assets` does not carry. No REST endpoint exists for role/permission
  grants (only Superset's own domain objects are in `/api/v1/`), so this talks to the
  Superset ORM directly inside its own app context, the way `superset fab`/`superset
  shell` do.
- **`FEATURE_FLAGS = {"ENABLE_TEMPLATE_PROCESSING": True}`** -- found only by actually
  logging in as a second, filtered account: this flag is `False` by default in Superset
  itself, and without it a row-level clause's `{{ current_username() }}` reaches Postgres
  as that literal string, unrendered, matching no row rather than the signed-in user's.
  With Admin exempt from the rule entirely (no clause at all), this bug is invisible to
  the owner's own account -- it only shows up for someone the rule actually filters,
  which nothing before this PR ever was.

## Alternatives considered

- **A custom Superset role instead of `Gamma`:** more precise, but `Gamma` already ships
  with exactly the base permissions (read dashboards/charts) a viewer needs, and this
  Superset instance has no other Gamma users to collide with -- reusing it is simpler.
- **Scoping by email instead of a separate Dex username:** would need the row-level
  clause itself to look up email -> `user_id`, hardcoded and rebuilt every time someone
  is added; reusing the username field the operator already sets keeps one place to
  change.
- **A REST-only implementation:** ruled out once role/permission management turned out to
  have no REST endpoint in this Superset version (only Superset's own dashboards/charts/
  datasets/RLS do) -- the ORM script is the documented alternative Superset's own CLI
  commands use.

## Consequences

- Someone added with no `--username` override, or who self-registers, sees nothing --
  the safe default. Scoping them to real data is one explicit operator action.
- Rotating `PFP_BI_OWNER_EMAIL` takes effect on the next login. **Re-scoping an
  already-registered account (a new Dex `--username`) needed a code fix this ADR first
  missed** -- it claimed "no migration": Flask-AppBuilder finds a user by username alone,
  but `ab_user.email` is unique, so the next login tried to create a second user with the
  same email and failed (`UniqueViolation ... ab_user_email_key`, reproduced live).
  `DexSecurityManager.auth_user_oauth` now renames the existing user (found by email) to
  the new username first. It also **refuses a login whose username already belongs to a
  different email**: two Dex accounts sharing one username would share one Superset user,
  and the roles recomputed at each login would flap between them (a non-owner's open
  session could inherit the owner's Admin). One Dex username per person; to give two
  people the same data, give each their own login and scope them to the same `user_id`
  only if that ever needs a different mechanism.
- Changing `PFP_BI_OWNER_EMAIL` or the env needs Superset recreated
  (`--force-recreate`, ADR 0034's incident), not just restarted.
- `bi/setup_access.py` re-runs on every `bi-up`; granting an already-granted permission
  or updating the same-named RLS rule is a no-op, not a duplicate.

## Related

[ADR 0034](0034-dex-local-login-by-email.md) (Dex login, the account this filters),
[ADR 0035](0035-dex-self-service-registration-and-public-url.md) (self-service
accounts, the same default-username reasoning), [ADR 0005](0005-transaction-schema-with-user-and-account.md)
(`user_id` on every row since Phase 1).
