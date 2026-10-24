# App Runner (ADR 0052): the closest AWS analog to Cloud Run used in infra/terraform --
# managed, container-based, no ALB or ECS cluster to hand-wire. Reads its database
# connection and viewer password from Secrets Manager at startup via
# `runtime_environment_secrets`, never a baked-in environment value -- same contract
# bi/start_cloud.sh and bi/superset_config_cloud.py already expect
# (PFP_DEMO_DB_CONNECTION_STRING, PFP_DEMO_VIEWER_PASSWORD), so neither file needed any
# AWS-specific change: the interface was already provider-agnostic plain env vars.

resource "aws_apprunner_service" "superset_demo" {
  service_name = "${var.demo_name}-superset"

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_ecr_access.arn
    }

    image_repository {
      image_identifier      = var.superset_image
      image_repository_type = "ECR"

      image_configuration {
        port = "8080"
        runtime_environment_secrets = {
          PFP_DEMO_DB_CONNECTION_STRING = aws_secretsmanager_secret.db_connection_string.arn
          PFP_DEMO_VIEWER_PASSWORD      = aws_secretsmanager_secret.superset_viewer_password.arn
        }
      }
    }
  }

  instance_configuration {
    cpu               = "1024" # 1 vCPU, matches the GCP module's run.tf limit
    memory            = "2048" # App Runner's own minimum paired with 1 vCPU
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  network_configuration {
    egress_configuration {
      egress_type       = "VPC" # the only way this container can reach RDS's private IP
      vpc_connector_arn = aws_apprunner_vpc_connector.demo.arn
    }
  }

  # No `max_size`/auto-pause knob: unlike Cloud Run's `scaling.min_instance_count = 0`,
  # App Runner has no scale-to-zero (ADR 0050's original reason AWS lost the first pick).
  # Immaterial here -- this trial is applied for minutes, not run continuously.
}
