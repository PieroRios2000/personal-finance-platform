"""`scripts/init_env.py`: a `.env` a clean clone can start from, secrets generated.

(T33: a clean clone follows the README to a running dashboard.)"""

import re
import stat
from pathlib import Path

import pytest

from scripts import init_env

_TEMPLATE = (Path(__file__).resolve().parent.parent / ".env.example").read_text()
_GENERATED = (
    "PFP_ACCOUNT_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "PFP_PG_PASSWORD",
    "PFP_PG_BI_PASSWORD",
    "PFP_BI_DB_PASSWORD",
    "PFP_BI_ADMIN_PASSWORD",
    "PFP_BI_SECRET_KEY",
    "PFP_BI_OAUTH_CLIENT_SECRET",
)


def _values(text: str) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )


def test_every_secret_the_platform_needs_is_generated() -> None:
    values = _values(init_env.render(_TEMPLATE))

    for name in _GENERATED:
        assert len(values[name]) >= 32, name
    assert values["PFP_USER"] == "demo"


def test_secrets_are_hex_so_the_shell_and_compose_read_them_back_unchanged() -> None:
    values = _values(init_env.render(_TEMPLATE))

    for name in _GENERATED:
        assert re.fullmatch(r"[0-9a-f]+", values[name]), name


def test_everything_else_is_left_as_the_template_has_it() -> None:
    rendered = init_env.render(_TEMPLATE)
    values = _values(rendered)

    assert (
        values["BCP_PDF_PASSWORD"] == ""
    )  # a real PDF's password: the owner's to fill
    assert values["ALERT_SMTP_HOST"] == ""
    assert values["PFP_PG_PORT"] == "5432"

    def comments(text: str) -> list[str]:
        return [line for line in text.splitlines() if line.startswith("#")]

    assert comments(rendered) == comments(_TEMPLATE)


def test_two_environments_never_share_a_secret() -> None:
    first, second = (_values(init_env.render(_TEMPLATE)) for _ in range(2))

    assert all(first[name] != second[name] for name in _GENERATED)


def test_it_writes_a_private_file_and_never_overwrites_an_existing_one(
    tmp_path: Path,
) -> None:
    target = tmp_path / ".env"

    assert init_env.main(["--out", str(target)]) == 0
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    written = target.read_text()

    assert init_env.main(["--out", str(target)]) == 1  # would destroy the real secrets
    assert target.read_text() == written


def test_a_different_demo_user_can_be_chosen(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / ".env"

    init_env.main(["--out", str(target), "--user", "ana"])

    assert _values(target.read_text())["PFP_USER"] == "ana"
    assert "dex-add-user" in capsys.readouterr().out  # says how to sign in


def test_a_user_name_that_would_break_sourcing_the_file_is_refused(
    tmp_path: Path,
) -> None:
    """`.env` is sourced by the shell and the name is a folder: no spaces or `$`."""
    target = tmp_path / ".env"

    assert init_env.main(["--out", str(target), "--user", "a b$c"]) == 2
    assert not target.exists()
