#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${1:-"$ROOT/.env.production"}
set -a; . "$ENV_FILE"; set +a
ORIGIN=${PUBLIC_ORIGIN%/}
curl -fsS "$ORIGIN/livez" >/dev/null
curl -fsS "$ORIGIN/readyz" | grep -q '"status":"ready"'
echo "P10 live deployment smoke: PASS ($ORIGIN)"
