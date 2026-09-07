#!/bin/sh
set -eu

CERT=/etc/agentmesh/tls/fullchain.pem
KEY=/etc/agentmesh/tls/privkey.pem
REQUIRE_TLS="${REQUIRE_TLS:-false}"

if [ -s "$CERT" ] && [ -s "$KEY" ]; then
  cp /etc/agentmesh/https.conf /etc/nginx/conf.d/default.conf
  echo "AgentMesh gateway: HTTPS enabled"
elif [ "$REQUIRE_TLS" = "true" ]; then
  echo "AgentMesh gateway: REQUIRE_TLS=true but fullchain.pem/privkey.pem are missing" >&2
  exit 1
else
  cp /etc/agentmesh/http.conf /etc/nginx/conf.d/default.conf
  echo "AgentMesh gateway: HTTP mode (TLS termination may be external)"
fi
