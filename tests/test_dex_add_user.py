"""`scripts/dex_add_user.py`: one Dex local user, bcrypt-hashed (T39, ADR 0034)."""

import getpass

import bcrypt
import pytest

from scripts import dex_add_user


def test_the_entry_has_four_fields_and_the_hash_verifies() -> None:
    line = dex_add_user.entry("piero@example.com", "hunter2")

    email, digest, username, user_id = line.split(":", 3)
    assert email == "piero@example.com"
    assert username == "piero"  # defaults to the part before @
    assert bcrypt.checkpw(b"hunter2", digest.encode())
    assert len(user_id) == 36  # a uuid4, so two users never collide


def test_a_username_can_be_chosen() -> None:
    line = dex_add_user.entry("piero@example.com", "hunter2", username="admin")

    assert line.split(":")[2] == "admin"


def test_two_calls_never_share_a_user_id() -> None:
    first = dex_add_user.entry("piero@example.com", "hunter2")
    second = dex_add_user.entry("piero@example.com", "hunter2")

    assert first.split(":")[3] != second.split(":")[3]


@pytest.mark.parametrize(
    ("email", "username"),
    [("pi:ero@example.com", None), ("piero@example.com", "a,b"), ("a@b.com", "x:y")],
)
def test_a_value_that_would_break_the_env_line_is_refused(
    email: str, username: str | None
) -> None:
    with pytest.raises(ValueError):
        dex_add_user.entry(email, "hunter2", username)


def test_main_prints_the_line_to_add_and_never_the_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passwords = iter(["hunter2", "hunter2"])
    monkeypatch.setattr(getpass, "getpass", lambda *_: next(passwords))

    assert dex_add_user.main(["piero@example.com"]) == 0

    out = capsys.readouterr().out
    assert "piero@example.com:" in out
    assert "hunter2" not in out


def test_main_refuses_a_value_that_would_break_the_env_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passwords = iter(["hunter2", "hunter2"])
    monkeypatch.setattr(getpass, "getpass", lambda *_: next(passwords))

    assert dex_add_user.main(["a@b.com", "--username", "x,y"]) == 2
    assert "x,y" in capsys.readouterr().err


def test_main_refuses_mismatched_passwords(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passwords = iter(["hunter2", "typo"])
    monkeypatch.setattr(getpass, "getpass", lambda *_: next(passwords))

    assert dex_add_user.main(["piero@example.com"]) == 1
    assert "piero@example.com" not in capsys.readouterr().out
