"""Superset settings (T32, ADR 0030). Everything secret comes from the environment."""

import os
from urllib.parse import quote

from flask_appbuilder.security.manager import AUTH_OAUTH
from superset.security import SupersetSecurityManager

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# Superset's own metadata (users, charts, dashboards) lives in its own database of
# PFP's Postgres, owned by its own role -- never in `pfp`, where dbt writes. The
# password is URL-encoded, so any character is safe in `.env`.
SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://superset:"
    f"{quote(os.environ['PFP_BI_DB_PASSWORD'], safe='')}@postgres:5432/superset"
)

# Handlebars charts (the KPI cards) compile their template with `new Function`, which
# Superset's default Content-Security-Policy forbids: allow 'unsafe-eval' for scripts.
# Everything else is Superset's default policy minus the analytics and map-tile hosts.
TALISMAN_CONFIG = {
    "content_security_policy": {
        "base-uri": ["'self'"],
        "default-src": ["'self'"],
        "img-src": ["'self'", "blob:", "data:"],
        "worker-src": ["'self'", "blob:"],
        "connect-src": ["'self'"],
        "object-src": "'none'",
        "style-src": ["'self'", "'unsafe-inline'"],
        "script-src": ["'self'", "'strict-dynamic'", "'unsafe-eval'"],
    },
    "content_security_policy_nonce_in": ["script-src"],
    "force_https": False,
    "session_cookie_secure": False,
}

# The KPI cards also use classes and a <style> block. Superset sanitizes chart HTML by
# default and strips both; allow exactly these two (no scripts, no event handlers).
# Only people who can edit charts (admins here) can write such HTML.
HTML_SANITIZATION_SCHEMA_EXTENSIONS = {
    "tagNames": ["style"],
    "attributes": {"*": ["className", "style"]},
}


class DexSecurityManager(SupersetSecurityManager):
    """Flask-AppBuilder only knows how to read the userinfo response for a handful
    of named providers (google, okta, auth0, keycloak...); Dex is a plain OIDC
    provider, not one of them, so it needs this one method. Modelled on FAB's own
    Auth0 branch: fetch `userinfo` from the metadata Superset's backend already
    discovered, and use the email as the username -- it is the one thing every
    login has, and the identity alerts and a future per-user data view (T39
    follow-up) will key on."""

    def oauth_user_info(
        self, provider: str, response: dict[str, str] | None = None
    ) -> dict[str, str | list[str]]:
        if provider != "dex":
            passthrough: dict[str, str | list[str]] = super().oauth_user_info(
                provider, response
            )
            return passthrough
        data = self.appbuilder.sm.oauth_remotes[provider].userinfo()
        email: str = data["email"]
        return {
            "username": email,
            "first_name": data.get("name", email),
            "last_name": "",
            "email": email,
            "role_keys": [],
        }


CUSTOM_SECURITY_MANAGER = DexSecurityManager

# Sign in with Dex (T39, ADR 0034): people who are not in DEX_STATIC_PASSWORDS
# cannot reach Dex's login screen at all, so anyone who comes back from it is
# trusted with the one role this project has today -- a finer, per-user view is
# the follow-up PR the owner asked for. `bi/build_dashboards.py` and
# `bi/cleanup_stale.py` still use the separate `admin` account
# (PFP_BI_ADMIN_PASSWORD) over the REST API: FAB's DB auth backend answers that
# endpoint regardless of AUTH_TYPE, so OAuth for human login does not touch it.
AUTH_TYPE = AUTH_OAUTH
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = "Admin"
AUTH_ROLES_SYNC_AT_LOGIN = True
OAUTH_PROVIDERS = [
    {
        "name": "dex",
        "icon": "fa-address-card",
        "token_key": "access_token",
        "remote_app": {
            "client_id": os.environ["PFP_BI_OAUTH_CLIENT_ID"],
            "client_secret": os.environ["PFP_BI_OAUTH_CLIENT_SECRET"],
            "client_kwargs": {"scope": "openid email profile"},
            # Dex's own issuer (dex/config.yaml.tpl) is the compose-network address:
            # every URL its discovery document hands back -- token exchange, userinfo,
            # jwks -- is that same internal host, correct for the backend-to-backend
            # calls those are. The one call a browser makes, the redirect to sign in,
            # is not one of them: it is set explicitly, to the published port, since
            # nothing derived from the (internal) discovery document would resolve
            # there.
            "server_metadata_url": (
                "http://dex:5556/dex/.well-known/openid-configuration"
            ),
            "authorize_url": f"{os.environ['DEX_ISSUER']}/auth",
        },
    }
]
