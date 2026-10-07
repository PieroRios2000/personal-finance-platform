# A copy of pfp-prod's demo gold tables, exported once and loaded in by the owner — not a
# live sync from the local lake (spec section 3, section 7).

resource "random_password" "db_password" {
  length  = 24
  special = false # kept simple for a connection string the secrets manager will hold anyway
}

resource "google_sql_database_instance" "demo_postgres" {
  name             = "${var.demo_name}-postgres"
  database_version = "POSTGRES_16"
  region           = var.gcp_region

  settings {
    tier              = var.postgres_tier
    availability_type = "ZONAL" # single zone: a demo, not a production database (spec section 5)
    disk_size         = 10
    disk_autoresize   = false

    backup_configuration {
      enabled = false # re-creatable from the export; no backup budget needed for a demo
    }
  }

  deletion_protection = false # option A (spec section 2): this is destroyed after the demo
}

resource "google_sql_database" "demo_gold" {
  name     = "pfp_demo_gold"
  instance = google_sql_database_instance.demo_postgres.name
}

resource "google_sql_user" "superset_reader" {
  name     = "pfp_bi"
  instance = google_sql_database_instance.demo_postgres.name
  password = random_password.db_password.result
}
