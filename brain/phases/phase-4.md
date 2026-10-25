---
type: phase
phase: 4
status: built
---

# Phase 4 — Cloud + IaC (built, GCP closed, AWS trial code-only)

PROJECT.md's goal: "the cloud 'nice to have' that shows up in job postings" — Terraform
provisioning infra on a free tier, secrets in a real secrets manager. Full reasoning:
[spec](../../docs/specs/cloud-deployment.md), decision: [ADR 0050](../decisions/0050-cloud-deployment-scope-and-provider.md).

## What's decided and built (GCP, closed)

- **Scope: option A** — Terraform provisions a narrow slice (Superset + a copy of the demo gold
  data + Secret Manager + Cloud Storage) alongside `pfp-prod`'s existing public tunnel (ADR 0042),
  not instead of it. Nothing needs to run continuously; the Terraform code and its evidence
  (applied once, screenshotted, destroyed) are the demonstrable artifact.
- **Provider: GCP** (Cloud Run + Cloud SQL + Secret Manager + Cloud Storage), over AWS, because
  Secret Manager has a real always-free tier and Cloud Run scales to zero — both matter more for
  "exists for a screenshot, not 24/7" than AWS's higher name-recognition in job postings.
- **Dex is skipped** under this scope — a single viewer credential from Secret Manager gates the
  dashboard instead.
- `infra/terraform/` exists, is `terraform validate`-clean, was applied for real against the
  owner's own project (`pfp-demo-511101`), evidence captured (a Loom recording), then destroyed
  (T69-T72, 2026-10-17). See its own `README.md`.

## T73 — AWS trial, code-only stage done (ADR 0052)

The same slice mapped onto AWS (ECS Express Mode + RDS for PostgreSQL + Secrets Manager + S3,
`infra/terraform-aws/`), `terraform validate`-clean, no new Superset-side code needed (the cloud
image's env-var interface was already provider-agnostic). Originally App Runner; a real `apply`
against the owner's own account found App Runner closed to new AWS customers since 2026-04-30,
so the module now uses ECS Express Mode instead — ADR 0052's amendment has the real error and
the fix. This is only the code-only stage, the AWS analog of T67 — no real AWS account,
credential, `plan` or `apply` exists yet for this (ECS) version. See ADR 0052
for the full provider mapping and where AWS needed more resources than GCP for the equivalent
slice (RDS's two-AZ subnet-group requirement, two IAM roles instead of one, a manually-launched
SSM bastion for the one-time data load since RDS has no managed import-from-object-storage API).

**Still open, the owner's call, same as GCP's own T68-T72 stage:** a real AWS account under the
owner's own billing with a Budgets alert, real credentials, a real `terraform plan`/`apply`, the
data load, evidence capture, then `terraform destroy` — a guided, interactive walkthrough, not
something delegated to a background agent (ADR 0050's same reasoning, unchanged for AWS).

## Why this phase moves slower than the others

Every other phase in this project got built the moment it was specified. This one doesn't, on
purpose: it is the first phase that needs a real cloud account, real billing and real credentials
that only the owner can hold — an agent provisioning real infrastructure or choosing an account on
the owner's behalf is exactly the kind of action this project's own standing rules (never run
destructive or hard-to-reverse actions without checking first) are meant to catch. T68 in
`tasks/backlog.md` blocks every implementation task until the owner answers the open questions
above.
