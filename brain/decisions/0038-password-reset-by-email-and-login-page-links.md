---
type: decision
phase: 2
status: accepted
date: 2026-09-26
---

# ADR 0038: password reset by email, and links on Dex's login page

## Context

With the URL public (ADR 0037), someone who forgets their password had no way back in
except the operator, and Dex's login page offered no way to create an account either.

## Decision

- **Two links on Dex's login form**: "Forgot your password?" and "Create an account".
  Dex embeds its templates in the binary, so `frontend.dir` points it at
  `/srv/dex/web` and `dex/templates/password.html` (Dex v2.43.1's own file plus the two
  links) is mounted over it. The links' address comes from `frontend.extra` /
  `extra "register_url"` in the template, filled from `PFP_REGISTER_PUBLIC_URL` (a
  different host from Dex once public; `http://localhost:<port>` by default).
- **Reset lives in `dex-register`** (`/forgot`, `/reset?token=`), which already speaks to
  Dex's gRPC API: `ListPasswords` to know whether the email has an account,
  `UpdatePassword` to set the new hash (username and `user_id` untouched, so a
  re-scoped account keeps its scope, ADR 0036).
- **The token** is 32 random bytes, kept as a SHA-256 in memory for 30 minutes, single
  use, and a new request cancels the earlier link. A restart forgets pending links (ask
  again); no database for a link that lives half an hour.
- **It cannot be used to find out who has an account**: the reply is one fixed message,
  and the lookup and the email run in a thread, so timing does not tell either. Mail goes
  only to an address that has an account. Limits: 5 submissions per IP and 3 per email
  every 5 minutes. The reset page sends `Referrer-Policy: no-referrer`.
- **Email** reuses the alerting's `ALERT_SMTP_*` variables (STARTTLS, Phase 7); without
  them, or without `PFP_REGISTER_PUBLIC_URL`, the page says reset is not set up.

## Alternatives considered

- **A signed stateless token** (email + expiry + HMAC of the current hash): Dex's
  `ListPasswords` does not return hashes, so it could not be single-use.
- **A SQLite volume for tokens**: durability across restarts is not worth a volume the
  container's `nobody` user could not write without more setup.
- **The Dex-host relative path (`/forgot` on the login host)**: needs a path route on the
  tunnel; a template variable is simpler.

## Consequences

- Accounts created by `make dex-add-user` are *static* (config, read-only over gRPC):
  their reset fails with a message that says so. Recreate them through the sign-up page
  (remove the entry from `DEX_STATIC_PASSWORDS` first), or keep the operator route.
- Dex upgrades must re-copy `password.html` from the new image and re-add the links; a
  test checks the file is still Dex's own login form.
- Sending mail from a public page is an abuse surface: hence the per-IP and per-email
  limits, existing accounts only, and (later, optional) Cloudflare rate limiting.

## Related

[ADR 0035](0035-dex-self-service-registration-and-public-url.md) (dex-register),
[ADR 0037](0037-public-url-through-a-bundled-cloudflare-tunnel-connector.md) (public URL),
[ADR 0026](0026-alerts-errors-now-warnings-weekly-names-and-counts-only.md) (SMTP).
