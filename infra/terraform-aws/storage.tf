# Object storage for Superset's own file storage (spec section 3), mirroring the GCP
# module's storage.tf. The lakehouse itself is NOT replicated here -- bronze/silver/gold
# stay local-only, by scope decision (spec section 3, ADR 0050).

resource "aws_s3_bucket" "superset_storage" {
  bucket_prefix = "${var.demo_name}-superset-storage-"
  force_destroy = true # this bucket only ever holds re-creatable demo exports
}

resource "aws_s3_bucket_lifecycle_configuration" "superset_storage" {
  bucket = aws_s3_bucket.superset_storage.id

  rule {
    id     = "expire-after-30-days"
    status = "Enabled"

    filter {} # apply to every object in the bucket, not just a prefix

    expiration {
      days = 30
    }
  }
}

resource "aws_s3_bucket_public_access_block" "superset_storage" {
  bucket                  = aws_s3_bucket.superset_storage.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
