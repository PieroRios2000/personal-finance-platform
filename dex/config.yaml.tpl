# Dex (T39, ADR 0034): one OpenID Connect login per person, by email, instead of a shared
# admin password per tool. Local users only (stored in Dex, ADR 0039); who is behind each
# login is Dex's job, not the BI tool's -- Superset (and, later, OpenMetadata and Dagster)
# only need to trust this issuer.
#
# The official image's entrypoint renders this file through gomplate before starting Dex
# (`CMD ["dex", "serve", "/etc/dex/config.yaml"]`; see cmd/docker-entrypoint in dexidp/dex),
# so every gomplate action below is resolved from the container's environment at startup, not
# committed with real values. `secretEnv` is Dex's own env-var indirection for a client's
# secret (its `id` is not one -- an OAuth client id is public, the same way a username is).
# The accounts themselves are never in this file: they live in Dex's storage.
#
# The issuer is the Compose network address, never the published one: it drives every URL
# Dex's discovery document hands back (token, userinfo, jwks), and those are all backend-to-
# backend calls Superset's container makes -- confirmed by first pointing this at the
# published host port, which left the token exchange doing `connect to localhost:5906
# refused` from inside the Superset container, itself, not Dex. The one call a browser
# actually needs (the redirect to /auth) never goes through this issuer or the discovery
# document at all: bi/superset_config.py sets `authorize_url` explicitly, straight to the
# published port.

issuer: http://dex:5556/dex

storage:
  type: sqlite3
  config:
    file: /var/dex/dex.db

web:
  http: 0.0.0.0:5556

telemetry:
  http: 0.0.0.0:5558

# T40, ADR 0035: dex-register (the self-service sign-up page) calls CreatePassword here
# to add a person immediately, no restart -- confirmed against a throwaway Dex that a
# password created this way logs in right away. No TLS: this is never published as a host port, only reachable
# from dex-register over the compose network, and that API grants full control over
# every account, so it must stay that way.
grpc:
  addr: 0.0.0.0:5557

# T43, ADR 0038: the login form's two links ("Forgot your password?", "Create an
# account") point at dex-register, a different host once the URL is public;
# dex/templates/password.html reads the address back with `extra "register_url"`. `dir`
# makes Dex read its templates from disk (they are embedded in the binary otherwise),
# which is where that modified copy is mounted.
frontend:
  dir: /srv/dex/web
  extra:
    register_url: {{ getenv "PFP_REGISTER_PUBLIC_URL" }}

oauth2:
  skipApprovalScreen: true
  passwordConnector: local

staticClients:
  - id: superset
    secretEnv: PFP_BI_OAUTH_CLIENT_SECRET
    name: 'Superset'
    redirectURIs:
      - {{ getenv "PFP_BI_BASE_URL" }}/oauth-authorized/dex
{{- if getenv "PFP_BI_PUBLIC_URL" }}
      - {{ getenv "PFP_BI_PUBLIC_URL" }}/oauth-authorized/dex
{{- end }}

# Local password database. Accounts are created and changed over the gRPC API above, by
# dex-register (sign-up, password reset) and `make dex-add-user` / `make dex-scope`, never
# listed here: a config-seeded (static) account is read-only for that API, so it could
# not be reset or re-scoped (ADR 0039).
enablePasswordDB: true
