---
type: decision
phase: 5
status: accepted
date: 2026-09-27
---

# ADR 0042: the public URL runs `prod` (demo data); real data stays local

## Context

By T49 the public URL (ADR 0037) tunneled the owner's own real environment (`pfp-poc`): his real
dashboard, and a self-service portal any invitee could reach with the invite code. A reviewer of
the project pointed out the real exposure this creates: once a stranger can sign up and upload a
real bank statement to an internet-facing instance the owner operates, he is processing that
person's personal financial data, which Peru's Ley 29733 (Protección de Datos Personales) covers
-- security obligations, breach notification, possibly registration -- none of which this project
has, nor should build for a portfolio piece.

The owner wants to keep the option of a real product later (so the invite code and self-service
registration stay), and, right now, wants to send people a working public URL that shows what the
dashboard looks like with real-shaped data, for his own showcase/publication.

## Decision

- **The public URL now tunnels `pfp-prod`** (ADR 0033's environment already designed for exactly
  this: artificial data, `main`'s code, "so anyone can see what the dashboard looks like"), not
  `pfp-poc`. `pfp-prod` is seeded with `make demo` -- Dex, Superset, dex-register, the upload
  portal and `cloudflared` all run there, on their own ports and ~~`main`~~ code, same domain and
  hostnames as before.
- **`pfp-poc` (the owner's real data) loses its tunnel connector.** Every service there was
  already bound to `127.0.0.1` only (T39-T44); removing `cloudflared` from it closes the one path
  that made real data reachable from the internet. It keeps running locally, unaffected.
- **The invite code and self-service registration stay live**, now against `prod`'s fictional
  data: someone who signs up sees the same empty-then-populate experience a real user would, with
  nothing real behind it either way.
- **The upload portal keeps working on `prod`**, with an optional banner
  (`PFP_UPLOAD_NOTICE`, a plain environment variable, empty by default) saying it is a demo and
  asking people not to upload a real statement. This does not, by itself, stop someone from doing
  it anyway -- the banner is a notice, not a technical control -- so it does not fully remove the
  Ley 29733 exposure by itself; it is the minimum honest step before ever inviting real strangers.
  Opening this for real, paying customers later needs its own legal and security work (consent,
  a privacy policy, breach handling, likely registration), out of scope here and left in the
  backlog.

## Consequences

- The owner's daily use of his real data moves to `http://localhost:8088` etc. on `pfp-poc`; it is
  no longer reachable by the public hostnames.
- `pfp-prod` needs its own `.env.prod` (tunnel token, public URLs, invite code, owner email,
  generated secrets) and `make demo PFP_ENV=prod` to have data; it is rebuilt from a `main`
  checkout, so `develop`'s newest work reaches it only after a release PR is merged.
- Two Postgres/lake instances now exist (`pfp-poc`, `pfp-prod`): the demo one can be reset any
  time with no loss (`make poc-down PFP_ENV=prod`), the real one never gets that treatment.

## Related

[ADR 0033](0033-dev-and-prod-environments-on-one-machine.md) (the `prod` environment this reuses),
[ADR 0037](0037-public-url-through-a-bundled-cloudflare-tunnel-connector.md) (the tunnel),
[ADR 0040](0040-upload-portal-unlocks-at-upload-and-owner-processes.md),
[ADR 0004](0004-real-pdfs-never-leave-your-machine.md).
