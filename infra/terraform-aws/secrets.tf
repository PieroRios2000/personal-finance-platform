# Secret *resources* only -- same note as the GCP module's secrets.tf: no real secret
# value is ever written into this repo, only into Terraform state and Secrets Manager
# itself (the intended holder of them, spec section 6).
#
# Unlike Cloud SQL (one instance, one dedicated `google_sql_user` reader role), RDS has
# no Terraform resource for creating a second, less-privileged database role (no
# `aws_db_user` equivalent) -- database.tf's master user doubles as the reader this
# secret hands to App Runner. Noted in ADR 0052 as a deliberate simplification for a
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

# App Runner's own runtime identity: an instance role it assumes to read both secrets
# above at container startup (runtime_environment_secrets, run.tf) -- the AWS analog of
# the GCP module's `google_secret_manager_secret_iam_member` grants to Cloud Run's
# default compute service account, except App Runner has no implicit default identity,
# so this role must be created and attached explicitly (instance_configuration.instance_role_arn,
# run.tf) or the service fails at creation with an access-denied error, same failure
# mode the GCP module hit for real (ADR 0050's secrets.tf comment).
data "aws_iam_policy_document" "apprunner_instance_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["tasks.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_instance" {
  name               = "${var.demo_name}-apprunner-instance"
  assume_role_policy = data.aws_iam_policy_document.apprunner_instance_trust.json
}

data "aws_iam_policy_document" "apprunner_secrets_access" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.db_connection_string.arn,
      aws_secretsmanager_secret.superset_viewer_password.arn,
    ]
  }
}

resource "aws_iam_role_policy" "apprunner_secrets_access" {
  name   = "${var.demo_name}-apprunner-secrets-access"
  role   = aws_iam_role.apprunner_instance.id
  policy = data.aws_iam_policy_document.apprunner_secrets_access.json
}

# A separate role App Runner's *build* side assumes to pull the private ECR image
# (source_configuration.authentication_configuration.access_role_arn, run.tf) -- distinct
# from the instance role above, which only runs the already-pulled container.
data "aws_iam_policy_document" "apprunner_ecr_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["build.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_ecr_access" {
  name               = "${var.demo_name}-apprunner-ecr-access"
  assume_role_policy = data.aws_iam_policy_document.apprunner_ecr_trust.json
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr_access" {
  role       = aws_iam_role.apprunner_ecr_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}
