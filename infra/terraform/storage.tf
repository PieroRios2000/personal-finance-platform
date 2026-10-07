# Object storage for Superset's own file storage (spec section 3). The lakehouse itself
# (SeaweedFS/Delta) is NOT replicated here — bronze/silver/gold stay local-only, by scope
# decision (spec section 3, ADR 0050).

resource "google_storage_bucket" "superset_storage" {
  name                        = "${var.demo_name}-superset-storage"
  location                    = var.gcp_region
  force_destroy               = true # this bucket only ever holds re-creatable demo exports
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}
