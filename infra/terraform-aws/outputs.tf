output "superset_url" {
  description = "The demo dashboard's public URL, once applied for real."
  value       = "https://${aws_apprunner_service.superset_demo.service_url}"
}

output "db_connection_secret_arn" {
  description = "Secrets Manager ARN holding the Postgres connection string (never the value itself)."
  value       = aws_secretsmanager_secret.db_connection_string.arn
}
