# Phase 4 Terraform (GCP, demo-only)

Provisions the slice described in
[`docs/specs/cloud-deployment.md`](../../docs/specs/cloud-deployment.md) (option A, ADR 0050):
Cloud Run (Superset) + Cloud SQL (a copy of the demo gold data) + Secret Manager + Cloud Storage.
It does **not** replace `pfp-prod`'s tunnel (ADR 0042), does not touch the lakehouse, and does not
stand up Dex.

## This has never been applied

- No real GCP project, account or credential exists anywhere in this repo or was used to write
  this module.
- Only `terraform validate` has been run (syntax and internal consistency, no credentials, no
  network call). `terraform plan`/`apply` need a real project and are the owner's own action,
  never run by CI or by an agent.
- Every account-specific variable (`gcp_project_id`, `superset_image`, `viewer_password`) has no
  default — `plan`/`apply` fail immediately without them, by design.

## Before a real apply

1. A GCP project under the owner's own billing, with a billing budget alert already configured at
   a low threshold (ADR 0050's open question 3 — this module does not and should not manage the
   account's own billing settings).
2. `gcloud auth application-default login` (or a service-account key the owner generates and
   keeps outside this repo).
3. The APIs this module needs enabled on that project: Cloud Run, Cloud SQL Admin, Secret Manager,
   Cloud Storage, Service Networking (for Cloud SQL's private IP).
4. A Superset image built and pushed somewhere this project can pull it from (Artifact Registry),
   referenced by `superset_image`.
5. `terraform init && terraform plan` first, read the plan, then `terraform apply` — and
   `terraform destroy` once the evidence (screenshot/recording) is captured, unless the owner has
   decided to keep it running (ADR 0050's open question 5).

## Validating without any of the above

```
terraform validate
```

This only checks the HCL is well-formed and internally consistent; it does not need a project,
credentials or network access.
