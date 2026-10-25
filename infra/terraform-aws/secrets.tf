# Secret *resources* only -- same note as the GCP module's secrets.tf: no real secret
# value is ever written into this repo, only into Terraform state and Secrets Manager
# itself (the intended holder of them, spec section 6).
#
# Unlike Cloud SQL (one instance, one dedicated `google_sql_user` reader role), RDS has
# no Terraform resource for creating a second, less-privileged database role (no
# `aws_db_user` equivalent) -- database.tf's master user doubles as the reader this
# secret hands to the ECS task. Noted in ADR 0052 as a deliberate simplification for a
# trial that is destroyed within the hour, not a pattern to repeat for anything longer-
# lived.

resource "aws_secretsmanager_secret" "db_connection_string" {
  name                    = "${var.demo_name}-db-connection-string"
  recovery_window_in_days = 0 # destroyed for good immediately, not held for 30 days (a demo)
}

resource "aws_secretsmanager_secret_version" "db_connection_string" {
  secret_id = aws_secretsmanager_secret.db_connection_string.id
  secret_string = join("", [
    "postgresql://", aws_db_instance.demo_postgres.username, ":",
    random_password.db_password.result, "@",
    aws_db_instance.demo_postgres.address, ":",
    tostring(aws_db_instance.demo_postgres.port), "/",
    aws_db_instance.demo_postgres.db_name,
  ])
}

resource "aws_secretsmanager_secret" "superset_viewer_password" {
  name                    = "${var.demo_name}-superset-viewer-password"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "superset_viewer_password" {
  secret_id     = aws_secretsmanager_secret.superset_viewer_password.id
  secret_string = var.viewer_password
}

# ECS Express Mode (ADR 0052, amended) needs two separate IAM roles, both with no
# implicit default the way Cloud Run's compute service account provided one -- the
# AWS analog of the GCP module's `google_secret_manager_secret_iam_member` grants,
# except both roles here must be created and attached explicitly or the service fails
# at creation, same failure mode the GCP module hit for real (ADR 0050's secrets.tf
# comment) and the same shape of failure App Runner's own instance/ECR-access role
# split hit before this module dropped App Runner entirely.

# 1. Execution role: what ECS itself assumes to pull the image, write logs, and --
# critically -- resolve the `secret` blocks in run.tf's primary_container into actual
# environment values before the container starts. This is standard ECS/Fargate
# behavior: secrets referenced in a task definition are resolved by the execution
# role, never by the task role.
data "aws_iam_policy_document" "ecs_execution_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution" {
  name               = "${var.demo_name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_execution_trust.json
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ecs_execution_secrets_access" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.db_connection_string.arn,
      aws_secretsmanager_secret.superset_viewer_password.arn,
    ]
  }
}

resource "aws_iam_role_policy" "ecs_execution_secrets_access" {
  name   = "${var.demo_name}-ecs-execution-secrets-access"
  role   = aws_iam_role.ecs_execution.id
  policy = data.aws_iam_policy_document.ecs_execution_secrets_access.json
}

# 2. Infrastructure role: what Express Mode itself assumes to provision and manage
# the load balancer, target group, security groups and auto-scaling it creates on this
# module's behalf (run.tf's `infrastructure_role_arn`) -- a plain `ecs.amazonaws.com`
# trust, per AWS's own infrastructure-IAM-role guide (the same role type backs EBS
# volume attachment, Service Connect TLS and VPC Lattice too; only the attached
# managed policy differs by use case).
data "aws_iam_policy_document" "ecs_infrastructure_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_infrastructure" {
  name               = "${var.demo_name}-ecs-infrastructure"
  assume_role_policy = data.aws_iam_policy_document.ecs_infrastructure_trust.json
}

resource "aws_iam_role_policy_attachment" "ecs_infrastructure" {
  role       = aws_iam_role.ecs_infrastructure.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}
