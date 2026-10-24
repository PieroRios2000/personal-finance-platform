# Same rule as infra/terraform's GCP module (ADR 0050/0052): no account-identifying
# variable has a default, so `plan`/`apply` fail loudly without real values deliberately
# supplied by the owner. This module is never applied by anyone but the owner, against
# their own billing -- an agent only ever runs `terraform validate` against it.

variable "aws_region" {
  description = "AWS region for every resource below. Free-tier eligible in every commercial region; us-east-1 is the default only because it is also the oldest/most-documented one, not because it is required."
  type        = string
  default     = "us-east-1"
}

variable "demo_name" {
  description = "Short name prefixing every resource (e.g. 'pfp-demo-aws'), so a second apply under a different account/env never collides, and so this trial's resources never share a name with the GCP module's (infra/terraform/)."
  type        = string
  default     = "pfp-demo-aws"
}

variable "superset_image" {
  description = "Fully qualified ECR image URI for the demo Superset container (the same image infra/terraform/README.md documents building, pushed to ECR instead of Artifact Registry). No default: built and pushed by the owner outside this module."
  type        = string
}

variable "postgres_instance_class" {
  description = "RDS instance class. Smallest free-tier-eligible class by default (db.t3.micro: 750 always-free hours/month, which this short-lived trial stays well under)."
  type        = string
  default     = "db.t3.micro"
}

variable "viewer_password" {
  description = "The dashboard's single viewer credential (same scope as the GCP module: Dex is skipped, spec section 3). Never given a default or committed anywhere; the owner supplies it at apply time (e.g. via TF_VAR_viewer_password or a -var-file kept out of git)."
  type        = string
  sensitive   = true
}
