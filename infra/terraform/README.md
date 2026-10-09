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
   Cloud Storage, Service Networking (the VPC peering Cloud SQL's private IP needs), Compute
   Engine (the VPC/subnet/reserved-range resources that peering sits on top of, `network.tf`),
   Artifact Registry.
4. The cloud-only Superset image (T70; no Dex/OAuth — `bi/superset_config_cloud.py`,
   `bi/start_cloud.sh`, `bi/Dockerfile.cloud`), built and pushed to an Artifact Registry repo in
   this project, then referenced by `superset_image`:
   ```
   gcloud artifacts repositories create pfp-demo --repository-format=docker \
       --location=<gcp_region> --project=<gcp_project_id>
   gcloud auth configure-docker <gcp_region>-docker.pkg.dev
   docker build -f bi/Dockerfile.cloud -t <gcp_region>-docker.pkg.dev/<gcp_project_id>/pfp-demo/superset:latest bi/
   docker push <gcp_region>-docker.pkg.dev/<gcp_project_id>/pfp-demo/superset:latest
   ```
   Verified locally (not against this registry): built, run against a throwaway local Postgres
   with dummy `PFP_DEMO_DB_CONNECTION_STRING`/`PFP_DEMO_VIEWER_PASSWORD` values, logged in as the
   one `viewer` user over HTTP, read the dashboard list — then torn down.
5. `terraform init && terraform plan` first, read the plan, then `terraform apply` — and
   `terraform destroy` once the evidence (screenshot/recording) is captured, unless the owner has
   decided to keep it running (ADR 0050's open question 5).

## Networking (added after T70, during T71/T72 prep)

`database.tf`'s `private_ip_address` and `secrets.tf`'s connection string need a VPC actually
peered to Google's private-services range, or the host comes back empty and Cloud Run can never
reach Cloud SQL. `network.tf` builds a small, dedicated VPC (not the project's implicit `default`
network, so this module stays fully self-contained and `terraform destroy` removes everything it
made) with one subnet in `var.gcp_region`, a reserved peering range, and the
`google_service_networking_connection` itself. `run.tf`'s Cloud Run service reaches it over direct
VPC egress (`template.vpc_access`, GA in the `hashicorp/google` provider used here -- no separate
Serverless VPC Access connector resource needed).

## Validating without any of the above

```
terraform validate
```

This only checks the HCL is well-formed and internally consistent; it does not need a project,
credentials or network access.
