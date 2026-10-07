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
