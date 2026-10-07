# Cloud Run (spec section 4): the always-free-tier, scale-to-zero piece this scope was chosen
# for. Reads its database connection and viewer password from Secret Manager at startup,
# never from a baked-in environment value.

resource "google_cloud_run_v2_service" "superset_demo" {
  name     = "${var.demo_name}-superset"
  location = var.gcp_region

  template {
    containers {
      image = var.superset_image

      env {
        name = "PFP_DEMO_DB_CONNECTION_STRING"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_connection_string.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "PFP_DEMO_VIEWER_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.superset_viewer_password.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }
    }

    scaling {
      min_instance_count = 0 # scales to zero between demo sessions (spec section 5)
      max_instance_count = 1 # a single viewer at a time; this is a demo, not a product
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  name     = google_cloud_run_v2_service.superset_demo.name
  location = var.gcp_region
  role     = "roles/run.invoker"
  member   = "allUsers" # the dashboard itself is public; the viewer password (above) gates it
}
