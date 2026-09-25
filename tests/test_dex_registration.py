"""`dex-register/registration.py`: the self-service sign-up page's pure logic
(T40, ADR 0035) -- validation and the per-IP throttle. `app.py` (grpc, the HTTP
server) is exercised live, the same way `bi/superset_config.py`'s OAuth wiring is:
see the PR for the throwaway-project verification."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parent.parent


def _registration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "registration", _ROOT / "dex-register" / "registration.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["registration"] = module
    spec.loader.exec_module(module)
    return module


registration = _registration()
CODE = "the-real-invite-code"


def test_a_good_submission_validates() -> None:
    error = registration.validate(
        "piero@example.com", "hunter2hunter2", "hunter2hunter2", CODE, CODE
    )

    assert error is None


def test_the_wrong_invite_code_is_refused_before_anything_else() -> None:
    error = registration.validate(
        "not-an-email", "short", "different", "wrong-code", CODE
    )

    assert error == "That invite code is wrong."


def test_a_malformed_email_is_refused() -> None:
    error = registration.validate(
        "not-an-email", "hunter2hunter2", "hunter2hunter2", CODE, CODE
    )

    assert error is not None and "email" in error


def test_a_short_password_is_refused() -> None:
    error = registration.validate("piero@example.com", "short1", "short1", CODE, CODE)

    assert error is not None and "8 characters" in error


def test_mismatched_passwords_are_refused() -> None:
    error = registration.validate(
        "piero@example.com", "hunter2hunter2", "typo2typo2typo2", CODE, CODE
    )

    assert error is not None and "match" in error


def test_the_throttle_blocks_after_five_failures_from_the_same_ip() -> None:
    throttle = registration.Throttle()
    now = 1_000_000.0

    for _ in range(registration.MAX_ATTEMPTS):
        assert not throttle.blocked("1.2.3.4", now)
        throttle.record_failure("1.2.3.4", now)

    assert throttle.blocked("1.2.3.4", now)
    assert not throttle.blocked("5.6.7.8", now)  # a different IP is unaffected


def test_the_throttle_forgets_failures_older_than_the_window() -> None:
    throttle = registration.Throttle()
    throttle.record_failure("1.2.3.4", now=1_000_000.0)

    later = 1_000_000.0 + registration.WINDOW_SECONDS + 1
    for _ in range(registration.MAX_ATTEMPTS - 1):
        throttle.record_failure("1.2.3.4", later)

    assert not throttle.blocked("1.2.3.4", later)  # the old failure aged out
