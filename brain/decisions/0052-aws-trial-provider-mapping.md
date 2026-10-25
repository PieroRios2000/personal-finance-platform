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
| Cloud Run | ~~App Runner~~ Amazon ECS Express Mode (`aws_ecs_express_gateway_service`) — see the amendment below | Originally App Runner, the closest managed, container-based analog with no ALB or ECS cluster to hand-wire; swapped after a real `apply` found App Runner closed to new AWS accounts |
| Cloud SQL (Postgres) | RDS for PostgreSQL | The direct managed-Postgres analog on both providers |
| Secret Manager | Secrets Manager | Same role, confirmed still with no free tier on AWS (ADR 0050's original cost argument against AWS) — irrelevant here since this is applied for minutes, not run continuously |
| Cloud Storage | S3 | Same role: Superset's own file storage, not the lakehouse |

**Where the mapping is not 1:1**, and the deliberate choice made for each (verified
against the `hashicorp/aws` provider's own resource docs, not recalled from training —
source-driven-development):

1. **No scale-to-zero.** Neither App Runner nor its replacement, ECS Express Mode, has an
   equivalent to Cloud Run's `scaling.min_instance_count = 0` — Fargate tasks have a
   `min_task_count` floor of 1 (`run.tf`'s `scaling_target`), ADR 0050's original reason
   AWS lost the first pick. Immaterial for a trial applied for minutes then destroyed;
   would matter if this were ever a standing second environment, which the owner's answer
   to ADR 0050's open question 2 already rules out.
2. **RDS's subnet-group requirement.** `aws_db_subnet_group` needs at least two subnets in
   two different availability zones even for a single-AZ instance (confirmed against the
   provider's own docs) — `infra/terraform-aws/network.tf` provisions two private subnets
   for this reason alone, where the GCP module needed only one.
3. **No second, less-privileged database role.** `google_sql_user` has no AWS Terraform
   equivalent (no `aws_db_user` resource); `aws_db_instance`'s own master user doubles as
   the reader the ECS task's secret hands over. Acceptable for a trial destroyed within the
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
   grant GCP's own real apply found missing (ADR 0050's `secrets.tf` comment). ECS Express
   Mode has no implicit default identity at all: an execution role (image pull, logs, and
   resolving the `secret` blocks in `run.tf`'s `primary_container` into real env values —
   standard ECS/Fargate behavior) and a separate infrastructure role (what Express Mode
   itself assumes to provision the load balancer, target group and auto-scaling it manages
   on this module's behalf, `AmazonECSInfrastructureRoleforExpressGatewayServices`) are
   both required from scratch.
6. **Public ingress needs explicit public subnets, not a grant.** Cloud Run defaults to
   private, so `run.tf`'s GCP module explicitly grants `allUsers` the invoker role. ECS
   Express Mode instead resolves internet-facing vs. internal purely from which subnets
   its `network_configuration` is given: public subnets (with a route to an Internet
   Gateway) get an internet-facing ALB, private subnets get an internal one, per AWS's own
   docs on how Express Mode provisions its load balancer. `network.tf` therefore adds a
   second, public subnet tier purely for the ECS task — RDS stays on the original private
   tier, reachable over the VPC's internal routing regardless of which tier the task sits
   in. The viewer password (Secrets Manager either way) is still what actually gates the
   dashboard, unchanged.

**No new Superset-side code.** T70's cloud image (`bi/superset_config_cloud.py`,
`bi/start_cloud.sh`, `bi/Dockerfile.cloud`, `bi/grant_gamma_access.py`) already reads its
database connection and viewer password from plain environment variables
(`PFP_DEMO_DB_CONNECTION_STRING`, `PFP_DEMO_VIEWER_PASSWORD`) — Cloud Run's `secret_key_ref`
injection was never baked into the entrypoint logic itself, just how those variables
happened to get set before it ran. ECS Express Mode's own `secret` block
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

**Superseded 2026-10-24** — see the "Amendment (2026-10-24): the real retry" section below;
the real-apply stage described here is done.

## Amendment (2026-10-24): App Runner closed to new AWS accounts, swapped for ECS Express Mode

The real-apply stage above started for real: the owner created a personal AWS account
(2026-10-24), a $1/month Budgets alert, an IAM user for Terraform, pushed the Superset
image to a private ECR repository, and ran a real `terraform apply`. RDS, the VPC, both
subnets' worth of networking, and the SSM VPC endpoints all created successfully — then
`aws_apprunner_vpc_connector.demo` failed:

```
Error: creating App Runner VPC Connector (pfp-demo-aws-connector): operation error
AppRunner: CreateVpcConnector, https response error StatusCode: 400, api error
SubscriptionRequiredException: The AWS Access Key Id needs a subscription for the service
```

Root cause, confirmed against AWS's own App Runner documentation (not a permissions or
quota issue, and not fixable by retrying): **App Runner stopped accepting new customers as
of 2026-04-30** (moved to maintenance mode 2026-03-31, existing customers unaffected, no
new features planned). The owner's account, created today, is a new customer by
definition — every future `apply` against it would hit the same wall regardless of IAM
permissions. AWS's own migration guidance for existing App Runner customers points at
**Amazon ECS Express Mode** as the direct replacement.

Everything that did create was destroyed immediately (`terraform destroy`, confirmed
empty via `terraform show`, `aws rds describe-db-instances`, `aws ec2 describe-vpcs`, and
`aws secretsmanager list-secrets` all returning nothing) — no resource was left running
while this amendment and the module fix were written. The ECR repository and its already-
pushed image, and the owner's own Budgets alert and IAM user, were untouched and remain
reusable for the retry.

**The fix**: `infra/terraform-aws/run.tf`, `network.tf`, `secrets.tf`, `outputs.tf` and
`versions.tf` now use `aws_ecs_express_gateway_service` (hashicorp/aws provider ≥ 6.26.0)
instead of `aws_apprunner_service`. Verified against the provider's own resource
documentation and AWS's ECS Express Mode developer guide (source-driven-development, not
recalled from training) rather than against the several mutually-contradicting blog posts
that turned up first in a web search — see the Decision section's updated mapping table
and points 1, 5 and 6 above for what changed. `terraform validate` is clean again; this
amendment's fix has **not yet been re-applied for real** — that retry is still the
remainder of T73.

This is the second time this project's own stated caveat about `terraform validate`
(ADR 0050's "Consequences" note, repeated in this ADR's own Consequences section below)
has proven true in exactly this way: a real `apply` surfaced something no amount of
`validate` or documentation-reading before the fact could have — this time an account-
level product availability restriction with no API-visible signal until the call itself
is made.

## Amendment (2026-10-24): the real retry — applied, evidenced, destroyed

The fixed module was applied for real against the same account. Two more things only a
real `apply` surfaced, neither a code bug this time but both specific to a brand-new AWS
account:

- `CreateExpressGatewayService` failed with `InvalidParameterException: Unable to assume
  the service linked role` — `AWSServiceRoleForECS` didn't exist yet on an account that
  had never used ECS. Created directly (`aws iam create-service-linked-role
  --aws-service-name ecs.amazonaws.com`); the retry succeeded once it had propagated.
- The ECS deployment then rolled back with `AccessDenied: The infrastructure role ...
  doesn't have enough permission`, even though the role already had the correct
  `AmazonECSInfrastructureRoleforExpressGatewayServices` managed policy attached — IAM
  policy-attachment propagation, not a missing permission. `aws ecs update-service
  --force-new-deployment` after about a minute succeeded.
- A genuine Terraform provider bug also surfaced: the apply that actually created the
  service errored anyway with "Provider produced inconsistent result after apply" on
  `scaling_target`'s server-side defaults, which the resource's schema doesn't declare as
  computed. Unlike the usual pattern, Terraform still wrote the resource into state despite
  the error — confirmed real and correctly tracked via `aws ecs describe-services` and
  `terraform state list` before relying on either. A later `terraform plan` shows this as
  a forced replacement (1 to add, 1 to destroy) that was deliberately **not** applied, to
  avoid recreating a running service over a provider quirk; it does not block `destroy`.

Beyond the module itself: RDS has no managed "import from object storage" the way Cloud
SQL does, so the one-time `gold`-schema load used a throwaway `t3.micro` EC2 bastion in a
private subnet (no key pair, no public IP, reached only via SSM Session Manager port
forwarding — its own ad-hoc IAM role and instance profile, deliberately outside the
Terraform module per this ADR's own design, deleted by hand right after the load) and a
direct `psql` restore over that tunnel — simpler than GCP's bucket-staged
`gcloud sql import sql`, since the SSM tunnel gives a direct network path the GCP module's
private-IP-only Cloud SQL never had.

The dashboard rendered real demo data (88 movements, matching the known demo-user count)
at the ECS Express Mode service's own public URL
(`https://<id>.ecs.us-east-1.on.aws`, an AWS-managed domain and certificate — no custom DNS
needed). The owner recorded a screencast as evidence, then `terraform destroy` removed all
32 resources; confirmed empty via `terraform show`, `describe-db-instances`,
`describe-vpcs`, `list-services` and `list-secrets`, the same verification pattern used
after the first (App Runner) attempt's partial destroy.

T73 is now fully closed, both providers proven end to end.

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
  0050 recorded for the GCP module) — confirmed a third and fourth time here: the App
  Runner account-availability block, two IAM-propagation delays, and a real Terraform
  provider bug, none of them visible to `validate`.

## Related

[ADR 0050](0050-cloud-deployment-scope-and-provider.md) (the scope and GCP decision this
mirrors), [ADR 0042](0042-public-url-shows-only-demo-data.md) (the tunnel neither module
touches), `infra/terraform-aws/README.md` (the real-apply runbook, including the bastion
data-load step), `infra/terraform/README.md` (the GCP module's own equivalent runbook).
