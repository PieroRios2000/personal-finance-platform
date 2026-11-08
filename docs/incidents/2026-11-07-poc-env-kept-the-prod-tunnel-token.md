# 2026-11-07: the real stack's `.env` still held the public tunnel's token

**Status:** mitigated · **Severity:** near miss (no data exposed)

## Summary

ADR 0042 moved the public tunnel from `pfp-poc` (real data) to `pfp-prod` (demo data) by removing
`pfp-poc`'s `cloudflared` container, but `pfp-poc`'s `.env` kept `PFP_TUNNEL_TOKEN`, the same token
`pfp-prod` uses (compared by hash, no value printed). `make up` starts `cloudflared` whenever that
variable is set, so a single `make up` on the real stack would have put it back on the internet.
Nothing ran; `make up` now refuses that combination.

## Impact

None that happened. What would have: a second connector of the same tunnel on `pfp-poc`, so
Cloudflare would have sent part of the traffic for the public hostnames (Superset, Dex, sign-up,
upload portal) to the real stack instead of the demo one, exactly the exposure ADR 0042 removed.

Checked on 2026-11-07: `docker ps -a` shows no `cloudflared` container in `pfp-poc`, only
`pfp-prod-cloudflared-1` (created 2026-09-27). The operations log records no `make up` on `pfp-poc`
since 2026-09-27, only `make build` and `make bi-up`, and neither starts `cloudflared`.

## Timeline

| When | What happened |
|---|---|
| 2026-09-26 | T42: `PFP_TUNNEL_TOKEN` added to `pfp-poc`'s `.env`; `make up` started `cloudflared` there |
| 2026-09-27 | ADR 0042: `docker rm -f pfp-poc-cloudflared-1`; `pfp-prod` set up with the same tunnel. The token stayed in `pfp-poc`'s `.env` |
| 2026-10-03 | The owner corrected 4 public values in `pfp-poc`'s `.env` ([incident](2026-10-03-poc-signin-sent-to-the-prod-dex.md)); the token was not among them |
| 2026-11-07 | Found by comparing the two env files' token by hash; `make up` gets a `tunnel-guard` |

## Root cause

1. `make up` decides whether to start `cloudflared` from the env file alone
   (`${PFP_TUNNEL_TOKEN:+--profile tunnel}`), with no notion of which environment may run it.
2. ADR 0042 was carried out on the containers (one `docker rm`), not on the configuration that
   recreates them, so the next `make up` would have undone it.
3. `SETUP.md` section 12 still told readers to put the token in `.env`, the real stack's file.

## Recovery

Nothing to recover. The guard was verified against the real `.env` without starting anything:
`make tunnel-guard` on `pfp-poc` exits 2 with the ADR 0042 message, so `make up` stops there too.
On a throwaway copy (`PFP_PROJECT=pfp-test`, a fake token) `make up` stopped at `tunnel-guard` with
0 `pfp-test` containers before and after.

## What went well / what went wrong

- Well: the env files were compared by hash, so the token never appeared in a terminal.
- Wrong: the same leftover class as 2026-10-03, whose prevention ("revert environment settings
  together with the ADR") was proposed but never turned into a check.

## Prevention

| Action | Where | Status |
|---|---|---|
| `make up` refuses `PFP_ENV=poc` with `PFP_TUNNEL_TOKEN` set (env file or shell), before anything changes; no override | `Makefile` `tunnel-guard`, `tests/test_public_url.py` | done |
| `SETUP.md` section 12 puts the token in `.env.prod`, never `.env` | `SETUP.md` | done |
| Delete `PFP_TUNNEL_TOKEN` from `pfp-poc`'s `.env` (until then `make up` there refuses) | owner's `.env` | pending, owner |

## Lessons

A decision that removes a capability is done when the command that recreates it can no longer do
so, not when the running container is gone.
