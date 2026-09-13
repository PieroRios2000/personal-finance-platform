"""Delta Lake storage configuration (T14, ADR 0006).

`LAKEHOUSE_URI` decides where bronze lives: `s3://...` against local (or, later,
real) S3, or a plain disk path for unit tests. `storage_options()` builds what
`deltalake`'s S3 backend needs for a non-AWS, plain-HTTP endpoint like SeaweedFS
(T13) — every key here is documented at
https://delta-io.github.io/delta-rs/integrations/object-storage/s3-like/.
"""

import os


class MissingLakehouseURIError(RuntimeError):
    """Raised when `LAKEHOUSE_URI` isn't set. See `.env.example` and SETUP.md."""


def lakehouse_uri() -> str:
    uri = os.environ.get("LAKEHOUSE_URI")
    if not uri:
        raise MissingLakehouseURIError(
            "LAKEHOUSE_URI is not set. Copy .env.example to .env and fill it in "
            "(s3://lakehouse for local S3, or a disk path for tests)."
        )
    return uri


def storage_options() -> dict[str, str] | None:
    """`None` for a plain disk path; the S3-compatible options `deltalake` needs
    when `LAKEHOUSE_URI` starts with `s3://` (read from `.env`, T13)."""
    if not lakehouse_uri().startswith("s3://"):
        return None
    return {
        "AWS_ENDPOINT_URL": os.environ["AWS_ENDPOINT_URL"],
        "AWS_ACCESS_KEY_ID": os.environ["AWS_ACCESS_KEY_ID"],
        "AWS_SECRET_ACCESS_KEY": os.environ["AWS_SECRET_ACCESS_KEY"],
        "AWS_REGION": os.environ.get("AWS_REGION", "us-east-1"),
        # SeaweedFS is plain HTTP, not a real AWS region, and needs path-style
        # bucket addressing (http://host:port/bucket/key, not
        # bucket.host:port/key). aws_conditional_put=etag is delta-rs's
        # recommended way to get safe concurrent writes on S3-compatible
        # storage without DynamoDB-style external locking.
        "allow_http": "true",
        "aws_virtual_hosted_style_request": "false",
        "aws_conditional_put": "etag",
    }


def table_uri(name: str) -> str:
    """Full URI for one bronze table, e.g. `table_uri("transactions")` ->
    `<LAKEHOUSE_URI>/bronze/transactions`."""
    return f"{lakehouse_uri().rstrip('/')}/bronze/{name}"
