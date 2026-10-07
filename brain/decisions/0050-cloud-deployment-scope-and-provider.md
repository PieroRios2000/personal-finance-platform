---
type: decision
phase: 4
status: accepted
date: 2026-10-07
---

# ADR 0050: Phase 4 cloud deployment — scope, provider, and what still needs the owner's decision

## Context

Phase 4's plan (PROJECT.md) is "Terraform to provision infra on AWS or GCP (free tier); stack
deployment; secrets in a secrets manager (never hardcoded)." No Terraform exists in this repo yet.
Unlike every other phase, this one needs a real cloud account, real billing and real credentials
that only the owner can hold — an agent cannot and should not provision real infrastructure,
choose an account, or set a billing ceiling on the owner's behalf. See
[spec](../../docs/specs/cloud-deployment.md) for the full reasoning; this ADR records the decision
and the open questions that block real implementation.

## Decision

**Scope: option A, "IaC alongside the tunnel," not a replacement for it** (spec §2). `pfp-prod`'s
existing `cloudflared` tunnel (ADR 0042) stays the actual public demo URL. Phase 4's Terraform
provisions a separate, narrow slice — Superset + a copy of the demo Postgres data + a secrets
manager + object storage (spec §3) — applied only long enough to produce evidence (a screenshot,
a short recording, the Terraform plan output itself), then torn down. This is a deliberate
divergence from "stack deployment" read as "the whole platform, always up": nothing in this
project's current design needs the cloud running continuously, and ADR 0042 already settled that
no real audience depends on uptime here.

**Provider: GCP** (spec §4) — Cloud Run (always-free tier, scales to zero) + Cloud SQL + Secret
Manager (always-free for 6 secret versions) + Cloud Storage. Chosen over AWS specifically because
AWS Secrets Manager has no free tier at all ($0.40/secret/month forever) and AWS's free compute
options don't scale to zero the way Cloud Run does, which matters more here than AWS's higher
name-recognition in job postings.

**Dex (login) is skipped** under this scope — a viewer credential from the secrets manager
replaces a full OIDC round trip, since nobody but the owner needs to authenticate against a
screenshot-only deployment.

**Nothing is provisioned by this decision.** This ADR and its spec are reviewable artifacts; no
`terraform apply` ran, no cloud account was created or touched, no real credential exists anywhere
in this repo or this conversation.

## Open questions that block real implementation (owner must answer)

1. **Confirm option A over option B.** If the owner instead wants the public URL itself to move to
   a real cloud host (option B, spec §2) — e.g. because "real cloud hosting" reads better in an
   interview than "a tunnel from my own machine" — that is a materially different, higher-cost,
   higher-maintenance scope and needs its own pass, not an extension of this one.
2. **Confirm GCP over AWS**, if the owner weighs "AWS is asked about more often in Peru job
   postings" higher than this spec's cost argument. Either is buildable; the Terraform module
   structure (provider block, variables, a compute resource, a managed database, a secrets
   resource, object storage) carries over either way — the provider-specific resource names
   inside it do not.
3. **A hard billing ceiling**, set on the real account before any `apply` (GCP Budget alert or AWS
   Budgets), and who configures it — this is an account-level action outside Terraform's reach
   here, and outside what an agent should do on the owner's behalf regardless.
4. **Who holds the account.** A personal GCP/AWS account under the owner's own billing, presumably
   — stated here so it's an explicit choice, not an assumption.
5. **How long it stays up.** Applied-then-destroyed for evidence only (this ADR's default), or
   kept running for some bounded demo window (e.g. "up during an interview process, destroyed
   after")? Changes nothing in the Terraform code, only the owner's own runbook.

Until these are answered, backlog tasks past "write the Terraform module" (already done, this PR)
stay blocked — see `tasks/backlog.md`'s Phase 4 section.

## Owner's answers (2026-10-08)

1. **Option A**, confirmed as written above.
2. **GCP first.** Once the GCP slice is proven working end to end, a *separate, one-time* trial
   deployment of the same slice on AWS is planned afterward, purely to have hands-on evidence of
   both providers for the portfolio — not a migration, not a standing second environment. Tracked
   as a new task after T72, not detailed further until GCP is done.
3. **Billing ceiling: $1/month.** The scope (Superset plus a small Postgres copy, applied briefly
   then destroyed) is expected to stay inside the always-free tiers; $1 is the alert threshold,
   not an expected cost.
4. **Account: the owner's own.** Piero creates and holds the GCP account and its billing; an agent
   never receives real credentials. Setup is a guided, interactive walkthrough (console clicks and
   CLI commands the owner runs, confirmed step by step), not something delegated to a background
   agent.
5. **Uptime: evidence only, then destroy immediately.** Never left running unattended; matches
   this ADR's default in the Decision section above, now confirmed rather than assumed.

## Consequences

- The Terraform module in `infra/terraform/` is real, `terraform validate`-clean code with no
  account-specific defaults (every account-identifying variable has no default, so `terraform
  plan`/`apply` fails loudly without real values deliberately supplied) — but it has never been
  planned or applied against a real account, so an actual `apply` may still surface issues
  `validate` can't catch (a quota limit, an API not yet enabled on a fresh project, a naming
  collision).
- `pfp-prod`'s tunnel (ADR 0042) is unaffected either way: this ADR does not touch it.
- If the owner later picks option B, this ADR gets superseded, not amended in place (the scope
  change is large enough to deserve its own record), per this project's own ADR convention.

## Related

[ADR 0042](0042-public-url-shows-only-demo-data.md) (the tunnel this sits beside),
[ADR 0033](0033-dev-and-prod-environments-on-one-machine.md) (`pfp-prod`'s own design),
[ADR 0007](0007-ephemeral-per-pr-environments.md) (the "no secrets in CI" pattern this
extends to "no secrets in Terraform state"),
[spec](../../docs/specs/cloud-deployment.md).
