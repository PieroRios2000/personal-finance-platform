---
type: decision
phase: 2
status: accepted
date: 2026-09-24
---

# ADR 0035: self-service sign-up, gated by an invite code, and a public URL

## Context

ADR 0034 gave each person a Dex account, but only the operator could create one
(`make dex-add-user`, run on the machine itself). The owner asked for two things after
using it for real: a public URL (not just `localhost`), and a friendly page where a new
person picks their own email and password instead of the operator doing it for them.

Put together, those two are a real risk today: this project has no per-user data
filtering yet (ADR 0034's own follow-up, still not built), so **anyone who can create an
account sees every account's data**. A public URL with open self-registration would let
a stranger on the internet do exactly that. Asked directly, the owner chose to gate
registration behind a shared invite code, and to reuse the Cloudflare Tunnel he already
runs on this machine (for other projects) rather than open a port on his router or run a
second tunnel.

## Decision

**A small self-service page (`dex-register/`), gated by one shared invite code,
reachable publicly only through the owner's own Cloudflare Tunnel.**

- **Dex's gRPC API** (`grpc: addr: 0.0.0.0:5557` in `dex/config.yaml.tpl`), never a
  published port -- only `dex-register` reaches it, over the compose network. That API
  grants full control over every account (create, update, delete, list), so publishing
  it would be far worse than publishing the sign-up page itself.
- **`CreatePassword`, not a file + restart.** Verified directly (a throwaway Dex, a
  password created over gRPC, then a login with it): the config's `staticPasswords` are
  a read-only, in-memory overlay (`storage.WithStaticPasswords` in dexidp/dex) that never
  touches the real storage; `CreatePassword` writes straight to it, so a self-registered
  account works immediately, no restart, and survives one exactly like a
  `DEX_STATIC_PASSWORDS` one does.
- **`dex-register/app.py`:** a plain stdlib `http.server` page (email, password twice,
  invite code) -- no new web framework for one form and one POST handler. `api.proto` is
  vendored from `dexidp/dex` (pinned to the same `v2.43.1` as the image) and compiled to
  a client at image build time (`grpcio-tools`), never committed: it is Dex's own wire
  format, not this project's code.
- **The invite code is checked first, in constant time** (`hmac.compare_digest`), before
  the email or password are even looked at -- it is the one thing keeping the page safe
  to be public. A per-IP throttle (5 wrong codes / 5 minutes) slows brute force on top of
  the code itself being long and random, generated like every other secret
  (`PFP_DEX_INVITE_CODE`).
- **(Superseded by [ADR 0037](0037-public-url-through-a-bundled-cloudflare-tunnel-connector.md): the connector now lives in the stack.) The public URL is the owner's own action, not this repo's.** A committed
  `docker-compose.override.yml.dist` (copied to a gitignored, personal
  `docker-compose.override.yml`) attaches `superset`, `dex` and `dex-register` to a
  second, externally-defined network (`PFP_TUNNEL_NETWORK` in `.env`) -- the one the
  owner's existing `cloudflared` container already runs on, so it can reach these
  services by their container name with no published port and no change to that other
  project. Adding the actual public hostnames is done on the owner's own Cloudflare Zero
  Trust dashboard; nothing here can do that for him.

## Alternatives considered

- **Open registration, no invite code:** what the owner first described; rejected once
  the "everyone becomes Admin, sees everything" consequence of ADR 0034 was pointed out,
  in favor of a code.
- **An allowlist of specific emails**, decided against in favor of a code: simpler to
  share (one string, any channel) and to rotate than maintaining a list.
- **File + `docker compose restart dex`:** the registration page would need Docker
  socket access to trigger it -- a much larger attack surface for a public-facing page
  than a gRPC call confined to the compose network.
- **A second, dedicated Cloudflare Tunnel:** offered as an option; the owner chose to
  reuse the one he already runs.
- **Router port-forwarding + a real domain:** offered as an option; not chosen -- keeps
  the machine's IP private and needs no certificate management of its own (the tunnel's
  edge terminates TLS).

## Consequences

- Three ways into an account now exist: `make dex-add-user` (operator, any email),
  self-service at `/` on `dex-register` (anyone with the invite code), both landing in
  the same Dex storage. Rotating `PFP_DEX_INVITE_CODE` in `.env` (and sharing the new one)
  is how the owner closes the self-service door without touching anyone's account.
- Still no per-user data filtering: every account, however it was created, keeps seeing
  every account's data. This ADR does not change that -- it only decides how an account
  gets made and how the invite code protects that one step.
- The public URL is opt-in per machine (`docker-compose.override.yml`, gitignored) and
  needs the owner's own Cloudflare dashboard action; a fresh clone or CI never has it and
  is unaffected.

## Related

[ADR 0034](0034-dex-local-login-by-email.md) (Dex, per-user role, the still-open
row-level-filtering follow-up), [ADR 0032](0032-one-compose-project-one-command.md) (one
Compose project, profiles).
