---
type: component
phase: 2
status: built
task: T39
---

# Dex

Local OpenID Connect provider: one login per person, by email, instead of a shared admin
password per tool. Only Superset uses it today. Design in
[ADR 0034](../decisions/0034-dex-local-login-by-email.md).

## Pieces

| Piece | What it does |
|---|---|
| [`dex/config.yaml.tpl`](../../dex/config.yaml.tpl) | Committed template; the official image renders it through its bundled gomplate at container start -- issuer, the Superset client (`idEnv`/`secretEnv`), and the local user list, all from the environment |
| [`bi/docker-compose.yml`](../../bi/docker-compose.yml) | `dex` service, behind the `bi` profile (port 5556 on 127.0.0.1); `superset` waits for it to be healthy |
| [`scripts/dex_add_user.py`](../../scripts/dex_add_user.py) | `make dex-add-user EMAIL=...`: asks for a password, bcrypt-hashes it, prints the `email:hash:username:userID` line for `DEX_STATIC_PASSWORDS` in `.env` |
| [`bi/superset_config.py`](../../bi/superset_config.py) | `AUTH_TYPE = AUTH_OAUTH`, `OAUTH_PROVIDERS`, and `DexSecurityManager.oauth_user_info` (FAB has no built-in mapping for a plain OIDC provider) |
| `make dex-add-user` | Wraps the script above |

## Related

[Superset](superset.md) (the one tool behind it today), [ADR 0033](../decisions/0033-dev-and-prod-environments-on-one-machine.md)
(port offsets apply to Dex's published port and issuer the same way).
