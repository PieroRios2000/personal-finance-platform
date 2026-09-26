---
type: decision
phase: 2
status: accepted
date: 2026-09-26
---

# ADR 0039: every Dex account lives in Dex, none in the config

## Context

ADR 0034 seeded accounts from `DEX_STATIC_PASSWORDS` (`make dex-add-user` printed a line
to paste into `.env`). Accounts created through `dex-register` (ADR 0035) live in Dex's
storage. Static entries are read-only over Dex's gRPC API, so they could not be reset by
email (ADR 0038) or re-scoped to a `user_id` without editing `.env` by hand and restarting
Dex (found out re-scoping the owner's own account, ADR 0036).

## Decision

- **No static accounts.** `DEX_STATIC_PASSWORDS` and the `staticPasswords` block of
  `dex/config.yaml.tpl` are removed, and so is `scripts/dex_add_user.py`.
- **`make dex-add-user EMAIL=... [USERNAME=user_id]`** and **`make dex-scope EMAIL=...
  USERNAME=user_id`** run `dex-register/manage.py` inside the `dex-register` container
  (the gRPC API is never published) and create / re-scope accounts in Dex's storage,
  immediately, no restart. `add` asks for the password (twice, never shown or logged);
  `scope` changes only the username and leaves the password hash alone (checked: the
  login still works after it).
- The username still defaults to the full email, so an account nobody scoped sees no data
  (ADR 0036).

## Consequences

- Every account can be reset by email and re-scoped with one command.
- Accounts now live only in Dex's volume (`dex-data`): losing it loses them (they used to
  be reconstructible from `.env`). Recreating them is one sign-up or `dex-add-user` each.
- An existing install with `DEX_STATIC_PASSWORDS` set: the variable is now ignored; create
  those accounts again with `make dex-add-user` (Dex may keep the old static ones in its
  storage until then, which is harmless).

## Related

[ADR 0034](0034-dex-local-login-by-email.md) (static accounts, superseded here),
[ADR 0035](0035-dex-self-service-registration-and-public-url.md),
[ADR 0036](0036-row-level-security-by-ingesting-user.md),
[ADR 0038](0038-password-reset-by-email-and-login-page-links.md).
