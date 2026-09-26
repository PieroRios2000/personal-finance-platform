---
type: component
phase: 2
status: built
task: T39, T40, T41, T42
---

# Dex

Local OpenID Connect provider: one login per person, by email, instead of a shared admin
password per tool. Only Superset uses it today. Design in
[ADR 0034](../decisions/0034-dex-local-login-by-email.md) (login),
[ADR 0035](../decisions/0035-dex-self-service-registration-and-public-url.md)
(self-service sign-up, invite code, public URL), and
[ADR 0036](../decisions/0036-row-level-security-by-ingesting-user.md) (who sees which
rows once signed in), and [ADR 0037](../decisions/0037-public-url-through-a-bundled-cloudflare-tunnel-connector.md)
(the public URL).

## Pieces

| Piece | What it does |
|---|---|
| [`dex/config.yaml.tpl`](../../dex/config.yaml.tpl) | Committed template; the official image renders it through its bundled gomplate at container start -- issuer, the Superset client (`secretEnv`), the local user list, and the gRPC API (internal only), all from the environment |
| [`bi/docker-compose.yml`](../../bi/docker-compose.yml) | `dex` service, behind the `bi` profile (port 5556 on 127.0.0.1, gRPC 5557 never published); `superset` and `dex-register` wait for it to be healthy |
| [`scripts/dex_add_user.py`](../../scripts/dex_add_user.py) | `make dex-add-user EMAIL=... [--username user_id]`: asks for a password, bcrypt-hashes it, prints the `email:hash:username:userID` line for `DEX_STATIC_PASSWORDS` in `.env` -- the operator adding someone, and (T41) scoping them to a real `user_id` |
| [`dex-register/`](../../dex-register) | A friendly sign-up page (port 5559): email, password, invite code (`PFP_DEX_INVITE_CODE`); calls Dex's gRPC `CreatePassword` directly, no restart -- someone adding themselves, always scoped to their own email (sees no data) until the operator re-scopes them |
| [`bi/superset_config.py`](../../bi/superset_config.py) | `AUTH_TYPE = AUTH_OAUTH`, `OAUTH_PROVIDERS`, `DexSecurityManager.oauth_user_info` (username = Dex's own username field, `role_keys: ["owner"]` for `PFP_BI_OWNER_EMAIL`), `AUTH_USER_REGISTRATION_ROLE = "Gamma"`, `AUTH_ROLES_MAPPING`, `ENABLE_TEMPLATE_PROCESSING` |
| [`bi/setup_access.py`](../../bi/setup_access.py) | T41: grants `Gamma` access to the gold datasets and creates the row-level security rule (`user_id = current_username()`, `Admin` exempt); runs after every dashboard import (`bi/start.sh`) |
| `cloudflared` (in [`bi/docker-compose.yml`](../../bi/docker-compose.yml)) | T42: the Cloudflare Tunnel connector, behind the `tunnel` profile; `make up` starts it when `PFP_TUNNEL_TOKEN` is set. Routes to `superset:8088`, `dex:5556`, `dex-register:5559` are added on Cloudflare's dashboard |
| `make dex-add-user` | Wraps `scripts/dex_add_user.py` |

## Related

[Superset](superset.md) (the one tool behind it today), [ADR 0033](../decisions/0033-dev-and-prod-environments-on-one-machine.md)
(port offsets apply to Dex's published port and issuer the same way).
