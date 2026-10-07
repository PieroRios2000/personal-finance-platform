---
type: phase
phase: 4
status: specified
---

# Phase 4 — Cloud + IaC (specified)

PROJECT.md's goal: "the cloud 'nice to have' that shows up in job postings" — Terraform
provisioning infra on a free tier, secrets in a real secrets manager. Full reasoning:
[spec](../../docs/specs/cloud-deployment.md), decision: [ADR 0050](../decisions/0050-cloud-deployment-scope-and-provider.md).

## What's decided

- **Scope: option A** — Terraform provisions a narrow slice (Superset + a copy of the demo gold
  data + Secret Manager + Cloud Storage) alongside `pfp-prod`'s existing public tunnel (ADR 0042),
  not instead of it. Nothing needs to run continuously; the Terraform code and its evidence
  (applied once, screenshotted, destroyed) are the demonstrable artifact.
- **Provider: GCP** (Cloud Run + Cloud SQL + Secret Manager + Cloud Storage), over AWS, because
  Secret Manager has a real always-free tier and Cloud Run scales to zero — both matter more for
  "exists for a screenshot, not 24/7" than AWS's higher name-recognition in job postings.
- **Dex is skipped** under this scope — a single viewer credential from Secret Manager gates the
  dashboard instead.
- `infra/terraform/` exists, is `terraform validate`-clean, and has never been applied against a
  real account. See its own `README.md` for what a real apply needs.

## What's still open (the owner's call, ADR 0050)

1. Confirm option A over option B (replacing the tunnel with a real always-on cloud host).
2. Confirm GCP over AWS.
3. A real billing ceiling, configured on the account before any `apply`.
4. Who holds the account (presumably the owner's own personal billing).
5. How long the demo stays up once applied for real.

## Why this phase moves slower than the others

Every other phase in this project got built the moment it was specified. This one doesn't, on
purpose: it is the first phase that needs a real cloud account, real billing and real credentials
that only the owner can hold — an agent provisioning real infrastructure or choosing an account on
the owner's behalf is exactly the kind of action this project's own standing rules (never run
destructive or hard-to-reverse actions without checking first) are meant to catch. T68 in
`tasks/backlog.md` blocks every implementation task until the owner answers the open questions
above.
