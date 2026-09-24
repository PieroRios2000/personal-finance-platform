---
type: component
phase: 2
status: built
task: T39, T40
---

# Dex

Local OpenID Connect provider: one login per person, by email, instead of a shared admin
password per tool. Only Superset uses it today. Design in
[ADR 0034](../decisions/0034-dex-local-login-by-email.md) (login) and
[ADR 0035](../decisions/0035-dex-self-service-registration-and-public-url.md)
(self-service sign-up, invite code, public URL).

## Pieces

| Piece | What it does |
|---|---|
| [`dex/config.yaml.tpl`](../../dex/config.yaml.tpl) | Committed template; the official image renders it through its bundled gomplate at container start -- issuer, the Superset client (`secretEnv`), the local user list, and the gRPC API (internal only), all from the environment |
| [`bi/docker-compose.yml`](../../bi/docker-compose.yml) | `dex` service, behind the `bi` profile (port 5556 on 127.0.0.1, gRPC 5557 never published); `superset` and `dex-register` wait for it to be healthy |
| [`scripts/dex_add_user.py`](../../scripts/dex_add_user.py) | `make dex-add-user EMAIL=...`: asks for a password, bcrypt-hashes it, prints the `email:hash:username:userID` line for `DEX_STATIC_PASSWORDS` in `.env` -- the operator adding someone |
| [`dex-register/`](../../dex-register) | A friendly sign-up page (port 5559): email, password, invite code (`PFP_DEX_INVITE_CODE`); calls Dex's gRPC `CreatePassword` directly, no restart -- someone adding themselves |
| [`bi/superset_config.py`](../../bi/superset_config.py) | `AUTH_TYPE = AUTH_OAUTH`, `OAUTH_PROVIDERS`, and `DexSecurityManager.oauth_user_info` (FAB has no built-in mapping for a plain OIDC provider) |
| [`docker-compose.override.yml.dist`](../../docker-compose.override.yml.dist) | Personal, gitignored once copied: attaches Superset/Dex/dex-register to the owner's own Cloudflare Tunnel network for a public URL |
| `make dex-add-user` | Wraps `scripts/dex_add_user.py` |

## Related

[Superset](superset.md) (the one tool behind it today), [ADR 0033](../decisions/0033-dev-and-prod-environments-on-one-machine.md)
(port offsets apply to Dex's published port and issuer the same way).
