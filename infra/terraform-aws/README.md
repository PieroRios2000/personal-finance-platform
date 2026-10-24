# Phase 4 Terraform (AWS, one-time trial, demo-only)

Provisions the same narrow slice as `infra/terraform/` (GCP, ADR 0050) on AWS instead:
App Runner (Superset) + RDS for PostgreSQL (a copy of the demo gold data) + Secrets
Manager + S3. Built per [ADR 0052](../../brain/decisions/0052-aws-trial-provider-mapping.md),
T73's owner-approved one-time trial, purely for hands-on evidence of both providers --
**not** a migration and **not** a standing second environment. It does not replace
`pfp-prod`'s tunnel (ADR 0042), does not touch the lakehouse, and does not stand up Dex.

## This has never been applied

- No real AWS account, credential or resource exists anywhere in this repo or was used
  to write this module.
- Only `terraform validate` has been run (syntax and internal consistency, no
  credentials, no network call):
  ```
  $ terraform init -backend=false && terraform validate
  Success! The configuration is valid.
  ```
- Every account-identifying variable (`superset_image`, `viewer_password`) has no
  default -- `plan`/`apply` fail immediately without them, by design (same rule as
  `infra/terraform/variables.tf`).

## Where this differs from the GCP module, and why

| Concern | GCP (`infra/terraform/`) | AWS (here) |
|---|---|---|
| Compute | Cloud Run, scales to zero | App Runner -- no scale-to-zero (ADR 0050's original reason AWS lost the first pick); immaterial for a trial applied for minutes |
| Database | Cloud SQL, one subnet + a managed private-services peering | RDS -- its subnet group needs 2 subnets across 2 AZs even for a single-AZ instance |
| Reader role | A dedicated `google_sql_user` reader, separate from the admin connection | No AWS Terraform resource creates a second Postgres role (no `aws_db_user`); the master user doubles as the reader App Runner gets. Fine for a trial destroyed within the hour, not a pattern to repeat for anything longer-lived |
| Loading the demo data | `gcloud sql import sql` -- a managed control-plane import straight from a Cloud Storage object, no network path needed | No RDS-for-PostgreSQL equivalent exists. The owner reaches RDS's private IP from a short-lived bastion launched into one of `network.tf`'s private subnets, over **SSM Session Manager port forwarding** (no SSH key, no public IP, no inbound rule) -- see "Loading data" below |
| Public ingress gate | Cloud Run defaults to private; `run.tf` explicitly grants `allUsers` invoker | App Runner services are public by default -- no equivalent grant needed. The viewer password (Secrets Manager) is still what actually gates the dashboard either way |
| Image pull identity | Cloud Run's default compute service account already has project-level pull rights | App Runner needs its own `access_role_arn` (`AWSAppRunnerServicePolicyForECRAccess`) on top of the instance role that reads secrets -- two roles here where GCP needed one |

## Before a real apply

1. An AWS account under the owner's own billing, with a Budgets alert already configured
   at a low threshold (ADR 0050's open question 3, same ceiling philosophy as the $1/month
   GCP alert) -- this module does not and should not manage the account's own billing.
2. AWS credentials for the Terraform AWS provider (e.g. `aws configure` with a personal
   access key, or SSO) -- never committed, never held by an agent.
3. The cloud-only Superset image (T70's image, reused as-is -- `bi/superset_config_cloud.py`,
   `bi/start_cloud.sh`, `bi/Dockerfile.cloud`, `bi/grant_gamma_access.py`; no AWS-specific
   variant needed, see "Why no new bi/ files" below), built and pushed to a private ECR
   repository in this account, then referenced by `superset_image`:
   ```
   aws ecr create-repository --repository-name pfp-demo/superset --region <aws_region>
   aws ecr get-login-password --region <aws_region> | docker login --username AWS \
       --password-stdin <account_id>.dkr.ecr.<aws_region>.amazonaws.com
   docker build -f bi/Dockerfile.cloud -t <account_id>.dkr.ecr.<aws_region>.amazonaws.com/pfp-demo/superset:latest bi/
   docker push <account_id>.dkr.ecr.<aws_region>.amazonaws.com/pfp-demo/superset:latest
   ```
4. `terraform init && terraform plan` first, read the plan, then `terraform apply`.
5. **Loading the demo data** (after `apply`, before capturing evidence -- the AWS analog
   of the GCP module's T71): since RDS is never reachable from the open internet, launch a
   throwaway `t3.micro` EC2 instance (no key pair; an instance profile with the
   `AmazonSSMManagedInstanceCore` managed policy) into one of `aws_subnet.private`'s
   subnets, reachable only through the SSM VPC endpoints `network.tf` already provisions.
   Then, from the owner's own machine:
   ```
   aws ssm start-session --target <instance-id> --document-name AWS-StartPortForwardingSessionToRemoteHost \
       --parameters '{"host":["<rds-endpoint-from-outputs>"],"portNumber":["5432"],"localPortNumber":["15432"]}'
   psql "postgresql://pfp_bi:<password>@localhost:15432/pfp_demo_gold" -f gold_dump.sql
   ```
   Terminate the bastion instance immediately after -- it is not part of this Terraform
   module (nothing here provisions it) specifically so that it never outlives the one-time
   load it exists for.
6. `terraform destroy` once the evidence (screenshot/recording) is captured -- same
   "evidence only, then destroy immediately" answer ADR 0050 recorded for GCP.

## Why no new `bi/` files

T70's cloud image already reads its database connection and viewer password from plain
environment variables (`PFP_DEMO_DB_CONNECTION_STRING`, `PFP_DEMO_VIEWER_PASSWORD`) set
by whatever platform runs the container -- `bi/start_cloud.sh` never calls a GCP-specific
API to fetch them, Cloud Run's `secret_key_ref` injection just happens to be how those
variables got set before the entrypoint ran. App Runner's `runtime_environment_secrets`
(`run.tf`, this module) does the equivalent injection for AWS, so the same image, the same
`start_cloud.sh`, the same `superset_config_cloud.py` and the same
`tests/test_bi_cloud_config.py` assertions all apply unchanged to this provider.

## Validating without any of the above

```
terraform init -backend=false
terraform validate
```

This only checks the HCL is well-formed and internally consistent; it does not need an
account, credentials or network access.
