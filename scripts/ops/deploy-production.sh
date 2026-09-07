#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${1:-"$ROOT/.env.production"}
COMPOSE_FILE="$ROOT/docker-compose.production.yml"
"$ROOT/scripts/ops/validate-production.sh" "$ENV_FILE"
set -a; . "$ENV_FILE"; set +a
ORIGIN=${PUBLIC_ORIGIN%/}
cd "$ROOT"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build

i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS "$ORIGIN/readyz" | grep -q '"status":"ready"'; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
    echo "AgentMesh production deployment: READY at $ORIGIN"
    exit 0
  fi
  i=$((i+1))
  sleep 3
done

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
exit 1
