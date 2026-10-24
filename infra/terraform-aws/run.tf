# Compute (ADR 0052, amended): AWS App Runner -- the module's original choice as the
# closest analog to Cloud Run -- turned out to be closed to new AWS customers as of
# 2026-04-30 (moved to maintenance mode 2026-03-31), discovered only on a real `apply`
# against the owner's brand-new account (ADR 0050's "Consequences" note that
# `terraform validate` alone can't catch everything a real apply does, confirmed
# again). AWS's own migration guidance for App Runner points at Amazon ECS Express
# Mode, used here instead: `aws_ecs_express_gateway_service`, Fargate-backed, with
# AWS provisioning its own Application Load Balancer, target group and auto-scaling
# -- the closest thing ECS has to App Runner's "just run a container" simplicity.
#
# Reads its database connection and viewer password from Secrets Manager via this
# resource's own `secret` block (resolved by the execution role, not the task role --
# standard ECS/Fargate behavior), injected as the same environment variable names
# bi/start_cloud.sh and bi/superset_config_cloud.py already expect
# (PFP_DEMO_DB_CONNECTION_STRING, PFP_DEMO_VIEWER_PASSWORD), so neither file needed any
# AWS-specific change: the interface was already provider-agnostic plain env vars.

resource "aws_ecs_express_gateway_service" "superset_demo" {
  service_name = "${var.demo_name}-superset"

  execution_role_arn      = aws_iam_role.ecs_execution.arn
  infrastructure_role_arn = aws_iam_role.ecs_infrastructure.arn

  cpu    = "1024" # 1 vCPU, matches the GCP module's run.tf limit
  memory = "2048"

  health_check_path = "/health" # Superset's own health endpoint; "/" redirects to login

  primary_container {
    image          = var.superset_image
    container_port = 8080

    secret {
      name       = "PFP_DEMO_DB_CONNECTION_STRING"
      value_from = aws_secretsmanager_secret.db_connection_string.arn
    }

    secret {
      name       = "PFP_DEMO_VIEWER_PASSWORD"
      value_from = aws_secretsmanager_secret.superset_viewer_password.arn
    }
  }

  network_configuration {
    subnets         = aws_subnet.public[*].id # public: the only way Express Mode provisions an internet-facing ALB (network.tf)
    security_groups = [aws_security_group.ecs_task.id]
  }

  scaling_target {
    min_task_count = 1
    max_task_count = 1 # a demo applied for minutes, never needs to scale out
  }

  # The Terraform resource's own documented deletion-race note: without this, the
  # execution role's secrets-access policy (secrets.tf) can be detached before ECS is
  # done using it, leaving the service stuck in DRAINING on destroy.
  depends_on = [
    aws_iam_role_policy.ecs_execution_secrets_access,
    aws_iam_role_policy_attachment.ecs_execution,
    aws_iam_role_policy_attachment.ecs_infrastructure,
  ]
}
