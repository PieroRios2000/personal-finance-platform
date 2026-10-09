"""Static checks on the cloud-only Superset image (T70, ADR 0050). Mirrors
test_bi_config.py's style for the local image: source-level checks, no live Superset
or Docker needed. The real build is this PR's own verification (docker build + a
throwaway Postgres), not something CI repeats here."""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BI = _ROOT / "bi"


def _config() -> str:
    return (_BI / "superset_config_cloud.py").read_text()


def _start() -> str:
    return (_BI / "start_cloud.sh").read_text()


def _dockerfile() -> str:
    return (_BI / "Dockerfile.cloud").read_text()


def test_the_cloud_config_has_no_oauth_dependency() -> None:
    """Dex/OAuth is skipped for this scope (ADR 0050): nobody but the owner needs to
    authenticate against a screenshot-only deployment."""
    config = _config()

    assert "authlib" not in _dockerfile()
    assert "AUTH_OAUTH" not in config
    assert "OAUTH_PROVIDERS" not in config
    assert "CUSTOM_SECURITY_MANAGER" not in config


def test_the_cloud_config_reads_its_secret_key_from_the_environment() -> None:
    """One value shared by both gunicorn workers (bi/start_cloud.sh generates and
    exports it before starting them) -- not computed per-worker at import time, which
    would give each worker a different key and break sessions across them."""
    config = _config()

    assert 'os.environ["SUPERSET_SECRET_KEY"]' in config
    assert "secrets.token_hex" in _start()


def test_the_cloud_image_is_pinned_like_the_local_one() -> None:
    dockerfile = _dockerfile()

    assert re.search(r"^FROM apache/superset:\d+\.\d+\.\d+$", dockerfile, re.M)
    assert re.search(r"psycopg2-binary==\d", dockerfile)


def test_the_cloud_image_bakes_in_its_own_files_instead_of_mounting_them() -> None:
    """Cloud Run has no volume mounts (unlike bi/docker-compose.yml's local setup):
    the cloud image must COPY everything the entrypoint needs."""
    dockerfile = _dockerfile()

    assert "COPY superset_config_cloud.py /app/superset_config.py" in dockerfile
    assert "COPY start_cloud.sh /app/start.sh" in dockerfile
    assert "COPY cleanup_stale.py /app/bi-cleanup.py" in dockerfile
    assert "COPY assets /app/pfp-assets" in dockerfile
    assert "SUPERSET_CONFIG_PATH" in dockerfile
    assert "ENTRYPOINT" in dockerfile
    assert "setup_access.py" not in dockerfile  # no per-user RLS in this scope
    assert "COPY grant_gamma_access.py /app/grant_gamma_access.py" in dockerfile


def test_the_cloud_start_script_creates_exactly_one_idempotent_viewer() -> None:
    start = _start()

    assert "--role Gamma" in start
    assert "create-user --username viewer" in start
    assert "|| true" in start
    assert "reset-password --username viewer" in start
    assert "PFP_DEMO_VIEWER_PASSWORD" in start
    assert "setup_access.py" not in start  # single shared viewer, no per-user filter
    assert "grant_gamma_access.py" in start  # but Gamma still needs base read access


def test_the_cloud_start_script_rewrites_the_whole_connection_string() -> None:
    """Unlike the local start.sh (same host, only the password is masked), Cloud SQL's
    host and database name both differ from the committed export's placeholder, so the
    whole `sqlalchemy_uri` is replaced, not just a password substring."""
    start = _start()

    assert "PFP_DEMO_DB_CONNECTION_STRING" in start
    assert "postgresql+psycopg2://pfp_bi:XXXXXXXXXX@postgres:5432/pfp" in start
    assert "PFP_PG_BI_PASSWORD" not in start  # that's the local-only substitution


def test_the_cloud_start_script_listens_on_the_cloud_run_port() -> None:
    assert '--bind "0.0.0.0:${PORT:-8080}"' in _start()


def test_the_local_image_and_config_are_untouched() -> None:
    """The existing Dex-based image must keep working exactly as before -- this task
    only adds new files beside it."""
    assert "AUTH_OAUTH" in (_BI / "superset_config.py").read_text()
    assert "setup_access.py" in (_BI / "start.sh").read_text()
