output "superset_url" {
  description = "The demo dashboard's public URL, once applied for real."
  value       = google_cloud_run_v2_service.superset_demo.uri
}

output "db_connection_secret_name" {
  description = "Secret Manager resource name holding the Postgres connection string (never the value itself)."
  value       = google_secret_manager_secret.db_connection_string.id
}
