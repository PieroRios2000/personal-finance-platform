---
type: decision
phase: 4
status: accepted
date: 2026-10-19
---

# ADR 0052: AWS trial (T73) — provider mapping and what stays code-only

## Context

ADR 0050 picked GCP for Phase 4's cloud slice, with the owner's explicit answer to open
question 2: once GCP was proven working end to end (closed, T72, ADR 0050 amendment and
`PROJECT.md`'s Phase 4 section), build a *separate, one-time* trial of the same slice on
AWS, purely for hands-on evidence of both providers for the portfolio — not a migration,
not a standing second environment (`tasks/backlog.md` T73).

GCP's own path to a real `apply` went through two distinct stages, tracked separately in
the backlog: T67 (write a `terraform validate`-clean module, nothing provisioned, no real
account touched) and T68-T72 (the owner's own decisions, then a real guided walkthrough
with real credentials, a real `apply`, evidence capture, and `terraform destroy`). This
ADR and the module it documents are **only the first stage** for AWS — the mapping
decision and the code, not a real account or a real `apply`. The second stage needs the
owner's own AWS account, their own credentials, and their own real-time walkthrough,
exactly as GCP's did; an agent does not and should not do that unattended.

## Decision

**Provider mapping** (the "provider-specific resource names... do not" carry over half of
ADR 0050's open question 2):

| GCP (`infra/terraform/`) | AWS (`infra/terraform-aws/`) | Why |
|---|---|---|
| Cloud Run | App Runner | Closest managed, container-based analog; no ALB or ECS cluster to hand-wire for a slice this narrow |
| Cloud SQL (Postgres) | RDS for PostgreSQL | The direct managed-Postgres analog on both providers |
| Secret Manager | Secrets Manager | Same role, confirmed still with no free tier on AWS (ADR 0050's original cost argument against AWS) — irrelevant here since this is applied for minutes, not run continuously |
| Cloud Storage | S3 | Same role: Superset's own file storage, not the lakehouse |

**Where the mapping is not 1:1**, and the deliberate choice made for each (verified
against the `hashicorp/aws` provider's own resource docs, not recalled from training —
source-driven-development):

1. **No scale-to-zero.** App Runner has no equivalent to Cloud Run's `scaling.min_instance_count
   = 0` — ADR 0050's original reason AWS lost the first pick. Immaterial for a trial
   applied for minutes then destroyed; would matter if this were ever a standing second
   environment, which the owner's answer to ADR 0050's open question 2 already rules out.
2. **RDS's subnet-group requirement.** `aws_db_subnet_group` needs at least two subnets in
   two different availability zones even for a single-AZ instance (confirmed against the
   provider's own docs) — `infra/terraform-aws/network.tf` provisions two private subnets
   for this reason alone, where the GCP module needed only one.
3. **No second, less-privileged database role.** `google_sql_user` has no AWS Terraform
   equivalent (no `aws_db_user` resource); `aws_db_instance`'s own master user doubles as
   the reader App Runner's secret hands over. Acceptable for a trial destroyed within the
   hour; not a pattern to repeat for anything longer-lived.
4. **No managed "import SQL from object storage" API for RDS Postgres.** Cloud SQL's
   `gcloud sql import sql` reaches a private-IP instance from the control plane with no
   network path needed from the operator. RDS has nothing equivalent for a plain SQL dump.
   The AWS module stays private-only anyway (RDS's `publicly_accessible = false`,
   `network.tf`'s security groups) and reaches the data-load problem the same way a
   real-world private RDS instance normally is reached: a short-lived bastion in the
   private subnet, SSM Session Manager port forwarding (no SSH key, no public IP, no
   inbound rule), `psql` run from the owner's own machine through that tunnel. That
   bastion is **not** a Terraform resource in this module — same reasoning GCP's module
   used for its own `gcloud sql import sql` step, which also was not a Terraform resource:
   a one-time data load belongs in the real-apply runbook (`README.md`'s "Loading the
   demo data" step), not in code that would otherwise provision and tear down a bastion on
   every unrelated `apply`/`destroy` cycle. The three VPC interface endpoints
   (`ssm`, `ssmmessages`, `ec2messages`) the bastion will need to reach SSM without a NAT
   gateway *are* provisioned here, since they are needed regardless of exactly when the
   bastion is launched.
5. **Two IAM roles instead of one.** Cloud Run's default compute service account already
   has project-level image-pull rights; `secrets.tf` only needed to add the secret-read
   grant GCP's own real apply found missing (ADR 0050's `secrets.tf` comment). App Runner
   has no implicit default identity at all: an instance role (secret reads) and a separate
   access role (`AWSAppRunnerServicePolicyForECRAccess`, the private-ECR image pull) are
   both required from scratch.
6. **Public ingress needs no explicit grant.** Cloud Run defaults to private, so `run.tf`'s
   GCP module explicitly grants `allUsers` the invoker role. App Runner services are public
   by default — no equivalent resource exists here. The viewer password (Secrets Manager
   either way) is what actually gates the dashboard in both modules, unchanged.

**No new Superset-side code.** T70's cloud image (`bi/superset_config_cloud.py`,
`bi/start_cloud.sh`, `bi/Dockerfile.cloud`, `bi/grant_gamma_access.py`) already reads its
database connection and viewer password from plain environment variables
(`PFP_DEMO_DB_CONNECTION_STRING`, `PFP_DEMO_VIEWER_PASSWORD`) — Cloud Run's `secret_key_ref`
injection was never baked into the entrypoint logic itself, just how those variables
happened to get set before it ran. App Runner's `runtime_environment_secrets`
(`infra/terraform-aws/run.tf`) does the equivalent injection; the same image, the same
`start_cloud.sh`, and the same `tests/test_bi_cloud_config.py` assertions apply to this
provider unchanged.

**Scope stays identical to ADR 0050's**: option A (alongside `pfp-prod`'s tunnel, not
replacing it), applied only long enough to capture evidence, then destroyed — this is a
*trial*, read verbatim from the owner's own answer, not a second standing environment.

## Status: code-only

As of this ADR, `infra/terraform-aws/` is `terraform validate`-clean (`terraform init
-backend=false && terraform validate` → `Success! The configuration is valid.`), with no
account-identifying variable given a default. **No real AWS account, credential, `plan`,
or `apply` exists anywhere.** The real-apply stage — an AWS account under the owner's own
billing with a Budgets alert, a real `terraform plan`/`apply`, the one-time data load
through a manually-launched bastion, evidence capture, then `terraform destroy` — is a
separate, later, owner-guided walkthrough, tracked as the remainder of T73 in
`tasks/backlog.md`, the same way ADR 0050's own module went through T67 before T68-T72.

## Consequences

- `infra/terraform-aws/` and `infra/terraform/` are fully independent: neither module
  references the other, and either can be applied or destroyed without touching the other
  or `pfp-prod`.
- The AWS module needs more resources than the GCP one for the equivalent slice (two IAM
  roles instead of one, a two-AZ subnet group instead of one subnet, three VPC endpoints
  for the eventual bastion) — a genuine, now-documented cost of AWS's narrower set of
  fully-managed primitives for this specific shape of workload, not an implementation
  accident.
- `terraform validate` alone does not prove a real `apply` will succeed (same caveat ADR
  0050 recorded for the GCP module, and the same caveat that in practice surfaced three
  real bugs only a real apply caught there) — expect the real AWS walkthrough to surface
  its own equivalent issues (a quota, a region-specific API gap, a naming collision) that
  this stage's `validate` cannot.

## Related

[ADR 0050](0050-cloud-deployment-scope-and-provider.md) (the scope and GCP decision this
mirrors), [ADR 0042](0042-public-url-shows-only-demo-data.md) (the tunnel neither module
touches), `infra/terraform-aws/README.md` (the real-apply runbook, including the bastion
data-load step), `infra/terraform/README.md` (the GCP module's own equivalent runbook).
