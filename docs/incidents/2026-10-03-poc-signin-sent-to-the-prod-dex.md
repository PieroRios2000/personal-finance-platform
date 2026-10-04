# 2026-10-03: signing in to the real Superset was sent to the prod Dex

**Status:** resolved · **Severity:** outage of one login (no data lost or exposed)

## Summary

After updating `pfp-poc`, the owner's Superset sign-in on `localhost:8088` failed with
`Bad Request: Unregistered redirect_uri`. The real stack's `.env` still pointed `DEX_ISSUER`
at the public Dex address, so the browser was redirected to a Dex that is not the stack's own.

## Impact

The owner could not open the dashboard until his `.env` was corrected. No data was lost or shown to
anyone it should not have been: the request was refused by the Dex it reached. Side effect: the
`make dex-scope` run on the real Dex (so his account sees the `piero` data) was applied to a Dex his
login did not go through, so it only took effect after the fix.

## Timeline

| When | What happened |
|---|---|
| 2026-09-26 | `pfp-poc`'s `.env` got the public values (`DEX_ISSUER`, `PFP_BI_PUBLIC_URL`, `PFP_UPLOAD_PUBLIC_URL`, `PFP_REGISTER_PUBLIC_URL`) when the public URL went live there |
| 2026-09-27 | ADR 0042 removed `pfp-poc`'s tunnel; only `pfp-prod` runs `cloudflared`. The `.env` values were not reverted |
| 2026-10-03 | Superset on `pfp-poc` was recreated and the owner signed in: redirected to the public `/dex/auth`, which the tunnel serves from `pfp-prod`'s Dex, whose Superset client only knows `localhost:8288` and the public host |
| 2026-10-03 | Compared the rendered config of `pfp-poc`'s Dex (it did list `localhost:8088`) with the redirect target; the owner set the 4 lines and ran `make bi-up`; sign-in verified up to Dex's login page |

## Root cause

1. `DEX_ISSUER` doubles as the browser-facing authorize URL (`bi/superset_config.py`), so a public value
   sends the browser through the tunnel, whichever stack it is.
2. ADR 0042 changed where the tunnel lives but nothing checked the real stack's `.env` against it.
3. The owner had last signed in on 2026-09-26, before the change, so the mismatch stayed hidden.

## Recovery

`DEX_ISSUER=http://localhost:5556/dex`, the three public URLs emptied, `make bi-up`. Verified: Superset's
`/login/dex` redirects to `localhost:5556`, and Dex answers the authorize request with its login page
(HTTP 302 to `/dex/auth/local`) instead of the error. The previous `.env` was kept as `.env.bak`.

## What went well / what went wrong

- Well: the error text named the exact redirect URI, which pointed at the issuer in a few steps.
- Wrong: a grep of `.env` for names to compare also printed the sign-up invite code once (a local
  terminal only; not a password). Compare names and set/empty, not values.

## Prevention

| Action | Where | Status |
|---|---|---|
| `make up` / `bi-check` warns when `DEX_ISSUER` is a public `https` address but `PFP_TUNNEL_TOKEN` is empty (a local stack cannot serve it) | `Makefile` `bi-check` | proposed, not implemented |
| Revert environment settings together with the ADR that removes the feature behind them | operations log / ADR checklist | proposed |

## Lessons

An environment file is part of the deployment: when a decision changes what a stack does, check its
`.env` as well as its code.
