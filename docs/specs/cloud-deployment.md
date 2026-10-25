# Spec: Phase 4 cloud deployment (demo only)

Status: **proposed** (2026-10-07). Nothing here is built or provisioned. Decision record:
[ADR 0050](../../brain/decisions/0050-cloud-deployment-scope-and-provider.md). Phase note:
[Phase 4](../../brain/phases/phase-4.md). This spec stops at a reviewable plan plus
`terraform validate`-clean code; it does not run `terraform apply` and does not touch a real
cloud account. Tasks are listed in [`tasks/backlog.md`](../../tasks/backlog.md) once the owner
picks a direction.

## 1. Why this exists

PROJECT.md's Phase 4 goal is "the cloud 'nice to have' that shows up in job postings": Terraform
provisioning infra on a free tier, with secrets in a real secrets manager. Design principle 5 is
explicit that this is optional and demonstration-only — the platform's actual daily use (the
owner's real data, `pfp-poc`) stays local and never goes to the cloud.

Everything else in this project got a spec and an ADR before code (Phase 6, the forecast). Phase 4
is higher-stakes than those: a real cloud account, real billing, and real credentials the owner
alone must hold. This spec follows the same discipline T24 (OpenMetadata) used — measure/plan
before building, stop and ask if something doesn't fit — scaled up because here the cost of being
wrong is money, not just RAM.

## 2. Open question the owner must answer first

**Does Phase 4 replace the current public-URL approach, or sit beside it?**

Today (ADR 0042) `pfp-prod` is already public: a `cloudflared` tunnel exposes the whole local
Compose stack (Superset, Dex, the upload portal) under `personal-finance-analysis.com`, at zero
cloud cost, running on the owner's own machine. This already satisfies "show a working dashboard
with demo data" — the thing Phase 4 would also provide.

So Phase 4's actual value is narrower than "host the demo": it's specifically **showing Terraform
and a real secrets manager**, because those are the resume-relevant gaps, not better uptime or
reach (the tunnel already gives both). Two honest options:

- **A — IaC alongside the tunnel.** Terraform provisions a real cloud environment, but
  `pfp-prod`'s tunnel stays the actual demo URL people click. The cloud deployment is itself the
  artifact to show (a repo folder, a screenshot of the console, a short recording), not something
  kept running 24/7. Lowest cost and lowest risk: nothing needs to stay up, so there's nothing to
  forget to tear down.
- **B — IaC replaces the tunnel.** The public URL moves to a real cloud instance Terraform
  provisions, kept running (or started on demand) instead of the owner's own machine tunneling out.
  Higher resume value (real uptime, a real public IP/DNS, a real secrets manager actually gating
  real Superset credentials) but real ongoing cost and operational surface: patching, a second
  place `pfp-prod`'s data can drift from, a bill that must be watched.

**Recommendation: A.** The owner already decided (ADR 0042) that `pfp-prod` holds only synthetic
demo data and that no real audience depends on the upload portal or identity work staying live
(Phase 3's note: "frozen... no more effort goes there unless something breaks"). Spending real
money to re-host something that already works for free doesn't fit that same call. Terraform code
that provisions a believable slice of this stack, validated and documented but applied only long
enough to take a screenshot, demonstrates the skill without taking on B's ongoing cost and risk.

This spec is written for A. If the owner wants B instead, the Terraform module below is still the
right starting point, scaled up (the ADR has the fork in it).

## 3. What gets provisioned (option A)

Not the whole stack — Dagster, OpenMetadata and the ingestion pipeline are local-only tools whose
audience is "someone cloning the repo," not "someone clicking a public link." The slice worth
putting in the cloud is the one a recruiter actually opens:

- **Superset** (the dashboard), containerized, on a small managed container service.
- **PostgreSQL**, managed, holding a copy of `pfp-prod`'s gold tables (the same synthetic data
  already seeded by `make demo PFP_ENV=prod` locally — exported once, loaded in, not a live sync).
- **A secrets manager** holding Superset's admin password, the Postgres connection string and the
  Dex OAuth client secret — the actual demonstrable Phase 4 artifact — instead of `.env`.
- **Object storage** for Superset's own file storage if needed; the lakehouse (SeaweedFS/Delta)
  itself is NOT replicated to the cloud under option A — bronze/silver history isn't part of what
  a dashboard visitor needs, and shipping real financial-shaped data further than the owner's own
  machine re-opens the Ley 29733 exposure ADR 0042 already closed by keeping `pfp-poc` local-only.
- Dex (login) is the open question: standing it up cloud-side duplicates `pfp-prod`'s own Dex for
  no real benefit under option A, since nobody besides the owner needs to log in to a
  screenshot-only deployment. Default: skip it, put Superset behind a simple fixed viewer
  credential pulled from the secrets manager instead of a full OIDC round trip; revisit if the
  owner wants a clickable public demo rather than a documented-and-screenshotted one.

## 4. AWS vs GCP, for this project's shape

| | AWS | GCP |
|---|---|---|
| Container hosting (Superset) | App Runner or ECS Fargate (free tier: App Runner has none; Fargate has none either — only EC2's `t2.micro`/`t3.micro` 750 hrs/month free tier year one) | Cloud Run (free tier: 2 million requests/month, always-free, no time limit — better fit for "spin up, screenshot, tear down" or even "leave running cheaply") |
| Managed Postgres | RDS `db.t3.micro`, 750 hrs/month free **year one only** | Cloud SQL has no always-free tier; smallest shared-core instance is cheap (~$8-10/month) but not free |
| Object storage | S3, 5 GB free year one | Cloud Storage, 5 GB free **always-free**, not time-limited |
| Secrets manager | AWS Secrets Manager: $0.40/secret/month + API calls, **no free tier** | GCP Secret Manager: 6 active secret versions free **always-free**, then $0.06/version/month |
| SeaweedFS's S3 API | Already S3-compatible by design — an AWS S3 bucket is a drop-in replacement, zero adapter code, if bronze/silver/gold storage ever did move to the cloud | would need the S3-compatibility shim or a rewrite to GCS's API if ever used |

**Recommendation: GCP**, specifically for this slice (Cloud Run + Cloud SQL + Secret Manager +
Cloud Storage), for two reasons that matter more than the S3-compatibility row above (which only
matters if the lakehouse itself ever moves to the cloud, which §3 just ruled out for option A):

1. **GCP Secret Manager's free tier is real** (6 versions, always-free) — AWS Secrets Manager has
   none, so even the pure "show a secrets manager" demo costs a small fixed fee on AWS every month
   it exists, versus $0 on GCP for this scale.
2. **Cloud Run's free tier is always-free and scales to zero** — it matches option A's "exists for
   a screenshot, not 24/7" shape exactly: a container that costs nothing while nobody's hitting it,
   with no EC2 instance idling and billing in the background the owner has to remember to stop.

AWS is the more commonly job-posted of the two, which is the one argument for it; the ADR records
this as the owner's call to make, not assumed.

## 5. What "only deployed for demonstration" means operationally

- **No standing resource runs by default.** `terraform apply` is a manual, owner-initiated action
  (never run by CI, never run by an agent), and `terraform destroy` is the expected next step
  after the screenshot/recording is taken — unless the owner picks option B.
- **A hard cost ceiling is non-negotiable before any real `apply`.** GCP's billing budget alerts
  (or AWS Budgets) must be configured on the real account with a near-zero threshold (e.g. $1)
  before Terraform ever touches it — this is an account-level setting Terraform here does not and
  should not manage, since the account itself must pre-exist with billing already capped.
  Recorded as an open owner action in the ADR, not something this PR can satisfy.
- **The owner holds the real account and credentials.** No credential, project ID or account
  identifier is ever typed into this repo or into a conversation with an agent — Terraform
  variables here have no defaults for anything account-specific (`variables.tf`), so `terraform
  apply` fails loudly without them rather than silently reaching for a default.

## 6. Secrets manager

GCP Secret Manager (see §4). What it would hold once option A is applied for real: Superset's
admin/viewer credential, the Postgres connection string, nothing else — there is no OAuth client
secret under option A since Dex is skipped (§3). The Terraform module creates the secret
*resources* (empty containers) but never writes real secret values into Terraform state or this
repo; populating them is a manual `gcloud` step the owner runs once, outside of `terraform apply`,
exactly like every other credential in this project (ADR 0007's "no secrets in CI" pattern,
applied here to "no secrets in Terraform state or source").

## 7. Non-scope

- Dagster, OpenMetadata, the ingestion pipeline, the upload portal and Dex: stay local/tunnel-only
  (§3's reasoning).
- Any live sync from `pfp-prod`'s local Postgres to the cloud one — the cloud copy is a one-time
  export of demo data, refreshed manually if the demo dashboard changes meaningfully.
- CI running Terraform against a real account (no GitHub Actions secrets for a cloud account exist
  or are proposed here).
- Option B (replacing the tunnel) — left as a documented fork in the ADR, not designed in detail,
  unless the owner picks it.

## 8. What this PR actually delivers

Per §2's recommendation (option A), everything needed to make an informed decision and start
implementing once decided, with nothing applied:

- This spec and [ADR 0050](../../brain/decisions/0050-cloud-deployment-scope-and-provider.md).
- `infra/terraform/`: a GCP module (Cloud Run + Cloud SQL + Secret Manager + Cloud Storage),
  `terraform validate`-clean, no account-specific defaults, never applied.
- [`brain/phases/phase-4.md`](../../brain/phases/phase-4.md) and backlog tasks (blocked on the
  owner's decision in §2 and the AWS/GCP call in §4).
