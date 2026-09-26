# Dex (T39, ADR 0034): one OpenID Connect login per person, by email, instead of a shared
# admin password per tool. Local users only for now (staticPasswords); who is behind each
# login is Dex's job, not the BI tool's -- Superset (and, later, OpenMetadata and Dagster)
# only need to trust this issuer.
#
# The official image's entrypoint renders this file through gomplate before starting Dex
# (`CMD ["dex", "serve", "/etc/dex/config.yaml"]`; see cmd/docker-entrypoint in dexidp/dex),
# so every gomplate action below is resolved from the container's environment at startup, not
# committed with real values. `secretEnv` is Dex's own env-var indirection for a client's
# secret (its `id` is not one -- an OAuth client id is public, the same way a username is);
# the user list has no such indirection, so it is templated by hand from one env var, one
# user per comma.
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
# password created this way logs in right away, the same as one seeded from
# DEX_STATIC_PASSWORDS. No TLS: this is never published as a host port, only reachable
# from dex-register over the compose network, and that API grants full control over
# every account, so it must stay that way.
grpc:
  addr: 0.0.0.0:5557

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

# Local password database: `make dex-add-user EMAIL=...` (scripts/dex_add_user.py) hashes a
# chosen password with bcrypt and prints one "email:hash:username:userID" entry to add to
# DEX_STATIC_PASSWORDS in .env, comma-separated for more than one person. Never committed --
# .env is gitignored, like every other secret in this project.
enablePasswordDB: true

staticPasswords:
{{- $raw := getenv "DEX_STATIC_PASSWORDS" }}
{{- if $raw }}
{{- range (strings.Split "," $raw) }}
{{- $fields := strings.Split ":" . }}
  - email: {{ index $fields 0 }}
    hash: {{ index $fields 1 }}
    username: {{ index $fields 2 }}
    userID: {{ index $fields 3 }}
{{ end -}}
{{- else }}
  []
{{- end }}
