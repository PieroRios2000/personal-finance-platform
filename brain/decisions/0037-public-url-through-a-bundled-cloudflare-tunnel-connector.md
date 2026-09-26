---
type: decision
phase: 2
status: accepted
date: 2026-09-26
---

# ADR 0037: a public URL through a Cloudflare Tunnel connector inside the stack

## Context

ADR 0035 planned a public URL by attaching Superset, Dex and `dex-register` to the
network of a `cloudflared` container the owner already ran for another project
(`docker-compose.override.yml.dist`). He had no tunnel yet, and asked for the connector
to live inside this stack, so everything starts together.

## Decision

- **`cloudflared` is a service of the stack**, behind its own `tunnel` profile, pinned to
  an exact version. `make up` turns the profile on only when `PFP_TUNNEL_TOKEN` is set in
  `.env`; without it nothing changes, and CI never runs it. The connector shares the
  project network, so the routes on Cloudflare's dashboard point at container names
  (`http://superset:8088`, `http://dex:5556`, `http://dex-register:5559`), no published
  port and no router change. The override file and `PFP_TUNNEL_NETWORK` are gone.
- **Three hostnames, one domain** (`www.` Superset, `login.` Dex, `register.`
  `dex-register`): Dex must be reachable by the browser, since it draws the login form.
  The OAuth token exchange stays internal (Dex's `issuer` remains the compose address,
  ADR 0034).
- **`PFP_BI_PUBLIC_URL`** (empty = local only) adds the public callback to Dex's
  `redirectURIs` next to the local one, so localhost keeps working. `DEX_ISSUER` (the
  address Superset sends the browser to) is set to Dex's public address.
- **Superset trusts the proxy** (`ENABLE_PROXY_FIX`, forwarded scheme and host), or the
  callback it builds would be `http://`, and marks its session cookie `Secure` when the
  public URL is https.
- **The spend cap** is the domain alone: Tunnel and Zero Trust Free (up to 50 users) cost
  nothing and nothing is metered; keep the plan and turn domain auto-renew off.

## Alternatives considered

- **`cloudflared` as a Windows service** (the installer Cloudflare offers): works through
  `localhost` ports, but lives outside the repo, cannot be tested or versioned here.
- **The existing-network override (ADR 0035)**: needs a tunnel that already exists.
- **One hostname with path routing**: Dex and `dex-register` both serve from `/`; three
  subdomains are simpler than rewriting paths.

## Consequences

- Sign-up is now reachable by anyone who has the link: the invite code and its per-IP
  throttle (ADR 0035) are the only gate; consider Cloudflare rate limiting later.
- Verified against a throwaway project with fake public hostnames: Superset builds the
  `https` callback and sends the browser to the public Dex, Dex accepts that callback and
  refuses an unregistered one, the session cookie is `Secure`. The tunnel itself needs the
  owner's real token.

## Related

[ADR 0035](0035-dex-self-service-registration-and-public-url.md) (the override it
replaces), [ADR 0034](0034-dex-local-login-by-email.md) (issuer),
[ADR 0032](0032-one-compose-project-one-command.md) (profiles).
