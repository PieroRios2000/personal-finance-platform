# A copy of pfp-prod's demo gold tables, exported once and loaded in by the owner --
# same as the GCP module's database.tf, not a live sync from the local lake (spec
# section 3, section 7). RDS has no managed "import SQL from an object-storage file"
# control-plane API the way Cloud SQL's `gcloud sql import sql` does, so the actual
# load is a manual step through the bastion in network.tf's comment, not something this
# resource does.

resource "random_password" "db_password" {
  length  = 24
  special = false # kept simple for a connection string the secrets manager will hold anyway
}

resource "aws_db_instance" "demo_postgres" {
  identifier     = "${var.demo_name}-postgres"
  engine         = "postgres"
  engine_version = "16.4"
  instance_class = var.postgres_instance_class

  allocated_storage     = 20 # RDS's own gp3 minimum; free-tier covers up to 20GB-month
  max_allocated_storage = 0  # 0 disables storage autoscaling -- a demo, not production

  db_name  = "pfp_demo_gold"
  username = "pfp_bi"
  password = random_password.db_password.result

  db_subnet_group_name   = aws_db_subnet_group.demo.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false # never reachable outside this VPC (network.tf)

  multi_az                   = false # single AZ: a demo, not production (spec section 5)
  auto_minor_version_upgrade = true
  backup_retention_period    = 0 # re-creatable from the export; no backup budget needed
  skip_final_snapshot        = true
  deletion_protection        = false # option A (spec section 2): destroyed after the demo
  apply_immediately          = true
}
