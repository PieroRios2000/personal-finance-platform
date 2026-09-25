---
type: decision
phase: 2
status: accepted
date: 2026-09-22
---

# ADR 0034: sign in with Dex, one local account per email

## Context

Superset had one shared `admin` login (`PFP_BI_ADMIN_PASSWORD`); OpenMetadata has its own
default admin login too, and Dagster OSS has none at all. The owner asked to replace the
per-tool passwords with a single sign-on so each person logs in with their own email. The
first question was which identity source: a real company or personal directory (Microsoft
Entra ID / Azure AD, via OIDC) was one option; the owner decided against it -- **local
accounts, one per email, chosen and hashed here**, not delegated to an outside provider. A
second question, whether each person's login should also narrow which rows they see, the
owner explicitly deferred to its own PR ("hacemos en un PR separado que solamente muestre
información de la persona que ingresa"): this PR is sign-in only, everyone who has an
account keeps today's one role.

## Decision

**[Dex](https://dexidp.io) as a local OpenID Connect provider**, with its own built-in local
connector (`enablePasswordDB: true`, `staticPasswords`) instead of a real upstream identity
provider. `dex/config.yaml.tpl` is the committed template; the official image renders it
through its bundled `gomplate` at container start (`CMD ["dex", "serve",
"/etc/dex/config.yaml"]`; see `cmd/docker-entrypoint` in `dexidp/dex`), so every real value
(the Superset client secret, the user list) comes from `.env`, never committed. The issuer
itself is the one line in the template that is *not* templated (below).

- **Adding a person:** `make dex-add-user EMAIL=...` (`scripts/dex_add_user.py`) asks for a
  password once, twice to confirm, bcrypt-hashes it, and prints one
  `email:hash:username:userID` line to paste into `DEX_STATIC_PASSWORDS` in `.env`
  (comma-separated for more than one person). The password itself is never printed, logged,
  or stored anywhere but the hash.
- **Only Superset today**, behind the `bi` profile (`bi/docker-compose.yml`); OpenMetadata's
  own OIDC config and an `oauth2-proxy` in front of Dagster (which has no auth of its own)
  are follow-up PRs, not part of this one.
- **Superset:** `AUTH_TYPE = AUTH_OAUTH`, one `OAUTH_PROVIDERS` entry, and a
  `DexSecurityManager.oauth_user_info` override (`bi/superset_config.py`) -- Flask-AppBuilder
  only ships a userinfo mapping for a handful of named providers, not a plain OIDC one.
  `AUTH_USER_REGISTRATION_ROLE = "Admin"`: since only people in `DEX_STATIC_PASSWORDS` can
  reach the login screen at all, and there is only one role in this project today, whoever
  gets through Dex is trusted the way the single shared `admin` login already was.
- **Dex's own issuer is the internal address, `http://dex:5556/dex`, never the published
  one -- found by actually running a login, not by reading the source.** Every URL Dex's
  discovery document hands back (token, userinfo, jwks) is built from whatever `issuer`
  says, and all of those are calls Superset's *backend* makes; pointing `issuer` at the
  published port instead left the token exchange trying to connect to `localhost:5906`
  from inside the Superset container, itself, not Dex (`Connection refused`). The one call a
  browser makes -- the redirect to sign in -- never goes through the discovery document at
  all: `bi/superset_config.py` sets `authorize_url` explicitly, to the *published* host
  (`DEX_ISSUER` in `.env`, offset in dev/prod like every other port, ADR 0033), confirmed
  against `authlib`'s client (`sync_app.py`): an explicit `authorize_url` overrides the
  discovery-derived `authorization_endpoint`, the only override that kind of client exposes.
  `flask-appbuilder`'s OAuth code needs `authlib` itself, which the official Superset image
  does not ship (`bi/Dockerfile`, alongside the already-needed `psycopg2-binary`).
- **The `admin` / `PFP_BI_ADMIN_PASSWORD` account is untouched.** `bi/build_dashboards.py` and
  `bi/cleanup_stale.py` still authenticate it over the REST API (`provider: db`): Superset's
  `SecurityApi.login` calls `auth_user_db` regardless of `AUTH_TYPE`, so switching *human*
  login to OAuth does not touch the automation account.

## Alternatives considered

- **A real upstream provider (Microsoft Entra ID / Azure AD) behind Dex's `oidc` connector:**
  the owner's first answer, then reversed -- fewer accounts to manage, but a tenant/app
  registration and a dependency this local, zero-cost project does not need.
- **Superset's own `AUTH_DB` per person (a Superset user per email, no Dex):** works for
  Superset alone, but does nothing for OpenMetadata's or Dagster's separate logins later, and
  keeps three places to add a person instead of one.
- **Row-level filtering in this same PR:** rejected by the owner; sign-in and "which data a
  signed-in person sees" are separate concerns and separate PRs.

## Consequences

- One place (`DEX_STATIC_PASSWORDS`) to add or remove who can sign in to any tool behind Dex;
  today that is only Superset.
- Everyone who has an account still sees every account's data -- the point of this PR is who
  can log in, not what they see once they do. A follow-up PR is needed before this fits more
  than one trusted person.
- `dex-data` (Dex's own sqlite3 file: sessions, not the identity source) is a named volume,
  kept by `make down`/`bi-down` like every other named volume; `DEX_STATIC_PASSWORDS` in
  `.env` is the actual source of truth and is never deleted by any `make` target.

## Related

[ADR 0030](0030-superset-for-dashboards-over-the-read-only-role.md) (Superset),
[ADR 0032](0032-one-compose-project-one-command.md) (one Compose project),
[ADR 0033](0033-dev-and-prod-environments-on-one-machine.md) (port offsets, `.env` per
environment).
