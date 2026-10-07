# No account-specific variable has a default: `terraform plan`/`apply` must fail loudly
# without real values deliberately supplied by the owner, never silently reach for one
# (ADR 0050). This file is never applied against a real account by an agent.

variable "gcp_project_id" {
  description = "The owner's own GCP project id. No default on purpose: this module is never applied by anyone but the owner, against their own billing."
  type        = string
}

variable "gcp_region" {
  description = "GCP region for every resource below."
  type        = string
  default     = "us-central1" # Cloud Run and Cloud SQL both have an always-free tier here.
}

variable "demo_name" {
  description = "Short name prefixing every resource (e.g. 'pfp-demo'), so a second apply under a different project/env never collides."
  type        = string
  default     = "pfp-demo"
}

variable "superset_image" {
  description = "Fully qualified image reference for the demo Superset container (e.g. an Artifact Registry path). No default: built and pushed by the owner outside this module, not something Terraform builds."
  type        = string
}

variable "postgres_tier" {
  description = "Cloud SQL machine tier. Smallest shared-core tier by default (spec section 4: Cloud SQL has no always-free tier, unlike Cloud Run)."
  type        = string
  default     = "db-f1-micro"
}

variable "viewer_password" {
  description = "The dashboard's single viewer credential (Dex is skipped under this scope, spec section 3). Never given a default or committed anywhere; the owner supplies it at apply time (e.g. via TF_VAR_viewer_password or a -var-file kept out of git)."
  type        = string
  sensitive   = true
}
