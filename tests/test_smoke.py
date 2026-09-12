import importlib

import pytest


@pytest.mark.parametrize("package", ["ingestion", "lakehouse"])
def test_package_imports(package: str) -> None:
    importlib.import_module(package)
