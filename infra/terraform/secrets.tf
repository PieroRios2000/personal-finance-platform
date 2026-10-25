# Secret *resources* only — empty containers Terraform creates. No real secret value is ever
# written into Terraform state or this repo: the db password's generated value and the
# viewer password variable flow into the version resources below only because Secret Manager
# itself is the intended holder of them going forward (the point of this module, spec section
# 6) — nothing here is a stand-in for a value that should instead live in plain source.

resource "google_secret_manager_secret" "db_connection_string" {
  secret_id = "${var.demo_name}-db-connection-string"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_connection_string" {
  secret = google_secret_manager_secret.db_connection_string.id
  secret_data = join("", [
    "postgresql://", google_sql_user.superset_reader.name, ":",
    random_password.db_password.result, "@",
    google_sql_database_instance.demo_postgres.private_ip_address, "/",
    google_sql_database.demo_gold.name,
  ])
}

resource "google_secret_manager_secret" "superset_viewer_password" {
  secret_id = "${var.demo_name}-superset-viewer-password"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "superset_viewer_password" {
  secret      = google_secret_manager_secret.superset_viewer_password.id
  secret_data = var.viewer_password
}

# Cloud Run's own runtime identity (the project's default compute service account, since
# `run.tf` never assigns `google_cloud_run_v2_service` a dedicated one) needs read access to
# both secrets above, or the revision fails at creation with a permission-denied error — found
# applying this module for real, not caught by `terraform validate` (it never calls the API).
data "google_project" "this" {}

locals {
  cloud_run_runtime_sa = "serviceAccount:${data.google_project.this.number}-compute@developer.gserviceaccount.com"
}

resource "google_secret_manager_secret_iam_member" "db_connection_string_accessor" {
  secret_id = google_secret_manager_secret.db_connection_string.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.cloud_run_runtime_sa
}

resource "google_secret_manager_secret_iam_member" "superset_viewer_password_accessor" {
  secret_id = google_secret_manager_secret.superset_viewer_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.cloud_run_runtime_sa
}
