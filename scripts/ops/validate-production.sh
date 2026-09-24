#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${1:-"$ROOT/.env.production"}
COMPOSE_FILE="$ROOT/docker-compose.production.yml"

[ -f "$ENV_FILE" ] || { echo "Production env file not found: $ENV_FILE" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

for key in MYSQL_PASSWORD MYSQL_ROOT_PASSWORD MINIO_SECRET_KEY JWT_SECRET VERIFICATION_PEPPER RUNTIME_INTERNAL_TOKEN GOVERNANCE_MASTER_KEY PUBLIC_ORIGIN; do
  eval "value=\${$key:-}"
  [ -n "$value" ] || { echo "$key is required" >&2; exit 1; }
  case "$value" in *CHANGE_ME*) echo "$key still contains CHANGE_ME" >&2; exit 1;; esac
done
[ "${#JWT_SECRET}" -ge 32 ] || { echo "JWT_SECRET must be at least 32 characters" >&2; exit 1; }
[ "${#GOVERNANCE_MASTER_KEY}" -ge 32 ] || { echo "GOVERNANCE_MASTER_KEY must be at least 32 characters" >&2; exit 1; }
[ "${#VERIFICATION_PEPPER}" -ge 16 ] || { echo "VERIFICATION_PEPPER must be at least 16 characters" >&2; exit 1; }
[ "${#RUNTIME_INTERNAL_TOKEN}" -ge 16 ] || { echo "RUNTIME_INTERNAL_TOKEN must be at least 16 characters" >&2; exit 1; }

if [ "${REQUIRE_TLS:-false}" = "true" ]; then
  [ "${AUTH_COOKIE_SECURE:-false}" = "true" ] || { echo "AUTH_COOKIE_SECURE must be true when REQUIRE_TLS=true" >&2; exit 1; }
  case "$PUBLIC_ORIGIN" in https://*) ;; *) echo "PUBLIC_ORIGIN must use https:// when REQUIRE_TLS=true" >&2; exit 1;; esac
  TLS_CERT_DIR=${TLS_CERT_DIR:-"$ROOT/infra/gateway/tls"}
  case "$TLS_CERT_DIR" in /*) ;; *) TLS_CERT_DIR="$ROOT/$TLS_CERT_DIR";; esac
  [ -s "$TLS_CERT_DIR/fullchain.pem" ] || { echo "missing $TLS_CERT_DIR/fullchain.pem" >&2; exit 1; }
  [ -s "$TLS_CERT_DIR/privkey.pem" ] || { echo "missing $TLS_CERT_DIR/privkey.pem" >&2; exit 1; }
fi

cd "$ROOT"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet
echo "Production preflight: PASS"
