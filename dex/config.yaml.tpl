# Dex (T39, ADR 0034): one OpenID Connect login per person, by email, instead of a shared
# admin password per tool. Local users only for now (staticPasswords); who is behind each
# login is Dex's job, not the BI tool's -- Superset (and, later, OpenMetadata and Dagster)
# only need to trust this issuer.
#
# The official image's entrypoint renders this file through gomplate before starting Dex
# (`CMD ["dex", "serve", "/etc/dex/config.yaml"]`; see cmd/docker-entrypoint in dexidp/dex),
# so every gomplate action below is resolved from the container's environment at startup, not
# committed with real values. `idEnv`/`secretEnv` are Dex's own env-var indirection for a
# client's two scalar secret fields; the user list has no such indirection, so it is templated
# by hand from one env var, one user per comma.

issuer: {{ getenv "DEX_ISSUER" }}

storage:
  type: sqlite3
  config:
    file: /var/dex/dex.db

web:
  http: 0.0.0.0:5556

telemetry:
  http: 0.0.0.0:5558

oauth2:
  skipApprovalScreen: true
  passwordConnector: local

staticClients:
  - idEnv: PFP_BI_OAUTH_CLIENT_ID
    secretEnv: PFP_BI_OAUTH_CLIENT_SECRET
    name: 'Superset'
    redirectURIs:
      - {{ getenv "PFP_BI_BASE_URL" }}/oauth-authorized/dex

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
