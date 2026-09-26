"""Row-level data access (T41, ADR 0036): everyone but the owner sees only their own
`user_id` in the gold tables, or nothing at all by default.

Static checks on `bi/setup_access.py`, the role/mapping wiring in
`bi/superset_config.py`, and how it is run; the live behaviour (two accounts, two
different views of the data) is the PR's verification."""

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_SETUP_ACCESS = (_ROOT / "bi" / "setup_access.py").read_text()
_SUPERSET_CONFIG = (_ROOT / "bi" / "superset_config.py").read_text()
_START_SH = (_ROOT / "bi" / "start.sh").read_text()


def _compose() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (_ROOT / "bi" / "docker-compose.yml").read_text()
    )
    return loaded


def test_the_rls_clause_matches_user_id_to_the_signed_in_username() -> None:
    assert "RLS_CLAUSE = \"user_id = '{{ current_username() }}'\"" in _SETUP_ACCESS


def test_the_rule_is_a_base_filter_that_exempts_only_admin() -> None:
    """A Base filter applies to every role except the ones listed -- Admin here, the
    owner -- confirmed against Superset's own RLS schema docstring
    (RowLevelSecurityFilterType.BASE, `roles = [admin]`), not guessed."""
    assert "RowLevelSecurityFilterType.BASE" in _SETUP_ACCESS
    assert "rls.roles = [admin]" in _SETUP_ACCESS


def test_it_grants_gamma_not_admin_on_the_five_gold_tables() -> None:
    assert "TABLES = (" in _SETUP_ACCESS
    for table in (
        "rpt_movements",
        "rpt_capital",
        "rpt_balances",
        "rpt_investments",
        "rpt_reconciliation",
    ):
        assert f'"{table}"' in _SETUP_ACCESS
    assert 'find_role("Gamma")' in _SETUP_ACCESS
    assert "gamma.permissions.append" in _SETUP_ACCESS


def test_it_is_idempotent_never_duplicating_a_grant_or_a_rule() -> None:
    assert "not in gamma.permissions" in _SETUP_ACCESS
    assert "one_or_none()" in _SETUP_ACCESS  # reuses the existing RLS row, never a 2nd


def test_new_dex_logins_default_to_gamma_not_admin() -> None:
    """Everyone gets Gamma by default (AUTH_USER_REGISTRATION_ROLE); only the email in
    PFP_BI_OWNER_EMAIL also gets the "owner" role_key, mapped to Admin -- the opposite
    of T39's original design, where every Dex login was Admin and RLS could not have
    applied to anyone."""
    assert 'AUTH_USER_REGISTRATION_ROLE = "Gamma"' in _SUPERSET_CONFIG
    assert 'AUTH_ROLES_MAPPING = {"owner": ["Admin"]}' in _SUPERSET_CONFIG
    assert '"role_keys": ["owner"] if is_owner else []' in _SUPERSET_CONFIG
    assert "PFP_BI_OWNER_EMAIL" in _SUPERSET_CONFIG


def test_the_superset_username_is_dexs_own_username_not_the_raw_email() -> None:
    """Row-level security matches on Superset's username; it has to be the value
    `make dex-add-user --username`/`dex-register` control (Dex's ID token "name"
    claim), not the email itself, or scoping a login to a real user_id would be
    impossible."""
    assert 'username: str = data.get("name", email)' in _SUPERSET_CONFIG
    assert '"username": username' in _SUPERSET_CONFIG


def test_setup_access_runs_after_the_dashboard_import_not_before() -> None:
    """Needs each dataset's live id, which only exists once the import has run."""
    assert _START_SH.index("import-directory") < _START_SH.index("setup_access.py")


def test_the_owner_email_is_env_only_never_hardcoded() -> None:
    superset = _compose()["services"]["superset"]
    assert superset["environment"]["PFP_BI_OWNER_EMAIL"] == "${PFP_BI_OWNER_EMAIL:-}"


def test_setup_access_is_mounted_into_the_container() -> None:
    volumes = _compose()["services"]["superset"]["volumes"]
    assert any("setup_access.py" in v for v in volumes)


def test_template_processing_is_on_or_rls_never_actually_filters() -> None:
    """Off by default in Superset itself (confirmed against a real login, see
    ADR 0036): without it, `{{ current_username() }}` reaches Postgres as that
    literal string -- matching no row rather than the signed-in user's, so `member`
    saw 0 rows instead of the data they were scoped to until this was set."""
    assert 'FEATURE_FLAGS = {"ENABLE_TEMPLATE_PROCESSING": True}' in _SUPERSET_CONFIG


def test_a_rescoped_account_renames_its_superset_user_not_duplicates_it() -> None:
    """Superset finds a user by username only, and `ab_user.email` is unique: after the
    operator re-scopes a Dex account (a new `--username`), the next login would try to
    create a second user with the same email and fail with a UniqueViolation. Found by
    re-scoping the owner's own already-registered account -- see ADR 0036."""
    assert "def auth_user_oauth" in _SUPERSET_CONFIG
    assert "self.find_user(email=email)" in _SUPERSET_CONFIG
    assert "self.update_user(existing)" in _SUPERSET_CONFIG


def test_a_username_that_belongs_to_another_email_refuses_the_login() -> None:
    """Two Dex accounts sharing one username would share one Superset user, and the
    roles recomputed at each login would flap between them: a non-owner's still-open
    session could inherit the owner's Admin. Refuse instead."""
    assert "by_name.email.lower() != email.lower()" in _SUPERSET_CONFIG
