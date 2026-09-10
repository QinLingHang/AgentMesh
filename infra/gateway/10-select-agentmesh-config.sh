#!/bin/sh
set -eu

CERT=/etc/agentmesh/tls/fullchain.pem
KEY=/etc/agentmesh/tls/privkey.pem
REQUIRE_TLS="${REQUIRE_TLS:-false}"
ENABLE_CONTROL_PLANE_HA="${ENABLE_CONTROL_PLANE_HA:-false}"

if [ -s "$CERT" ] && [ -s "$KEY" ]; then
  if [ "$ENABLE_CONTROL_PLANE_HA" = "true" ]; then
    cp /etc/agentmesh/https-ha.conf /etc/nginx/conf.d/default.conf
    echo "AgentMesh gateway: HTTPS + control-plane HA enabled"
  else
    cp /etc/agentmesh/https.conf /etc/nginx/conf.d/default.conf
    echo "AgentMesh gateway: HTTPS enabled"
  fi
elif [ "$REQUIRE_TLS" = "true" ]; then
  echo "AgentMesh gateway: REQUIRE_TLS=true but fullchain.pem/privkey.pem are missing" >&2
  exit 1
else
  if [ "$ENABLE_CONTROL_PLANE_HA" = "true" ]; then
    cp /etc/agentmesh/http-ha.conf /etc/nginx/conf.d/default.conf
    echo "AgentMesh gateway: HTTP + control-plane HA enabled"
  else
    cp /etc/agentmesh/http.conf /etc/nginx/conf.d/default.conf
    echo "AgentMesh gateway: HTTP mode (TLS termination may be external)"
  fi
fi
