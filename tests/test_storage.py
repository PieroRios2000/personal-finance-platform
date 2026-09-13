"""Tests for lakehouse.storage: LAKEHOUSE_URI and S3 storage_options (T14)."""

import pytest

from lakehouse.storage import (
    MissingLakehouseURIError,
    lakehouse_uri,
    storage_options,
    table_uri,
)


def test_lakehouse_uri_raises_a_clear_error_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LAKEHOUSE_URI", raising=False)

    with pytest.raises(MissingLakehouseURIError, match="LAKEHOUSE_URI"):
        lakehouse_uri()


def test_lakehouse_uri_returns_the_env_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAKEHOUSE_URI", "/tmp/lake")

    assert lakehouse_uri() == "/tmp/lake"


def test_storage_options_is_none_for_a_disk_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAKEHOUSE_URI", "/tmp/lake")

    assert storage_options() is None


def test_storage_options_builds_s3_options_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAKEHOUSE_URI", "s3://lakehouse")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:8333")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.delenv("AWS_REGION", raising=False)

    options = storage_options()

    assert options == {
        "AWS_ENDPOINT_URL": "http://localhost:8333",
        "AWS_ACCESS_KEY_ID": "test-key-id",
        "AWS_SECRET_ACCESS_KEY": "test-secret",
        "AWS_REGION": "us-east-1",
        "allow_http": "true",
        "aws_virtual_hosted_style_request": "false",
        "aws_conditional_put": "etag",
    }


def test_storage_options_honors_an_explicit_aws_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAKEHOUSE_URI", "s3://lakehouse")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:8333")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    options = storage_options()

    assert options is not None
    assert options["AWS_REGION"] == "us-west-2"


def test_table_uri_joins_the_lakehouse_uri_with_bronze_and_the_table_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAKEHOUSE_URI", "s3://lakehouse")

    assert table_uri("transactions") == "s3://lakehouse/bronze/transactions"


def test_table_uri_strips_a_trailing_slash_on_lakehouse_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAKEHOUSE_URI", "s3://lakehouse/")

    assert table_uri("transactions") == "s3://lakehouse/bronze/transactions"
