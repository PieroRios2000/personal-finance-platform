output "superset_url" {
  description = "The demo dashboard's public URL, once applied for real. Express Mode exposes the ALB endpoint through ingress_paths; this takes the first one -- verify against the real apply output (not yet applied for real against this resource) in case a service with no custom networking ever exposes more than one path."
  value       = "https://${aws_ecs_express_gateway_service.superset_demo.ingress_paths[0].endpoint}"
}

output "db_connection_secret_arn" {
  description = "Secrets Manager ARN holding the Postgres connection string (never the value itself)."
  value       = aws_secretsmanager_secret.db_connection_string.arn
}
