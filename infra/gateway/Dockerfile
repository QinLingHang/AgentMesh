FROM nginx:1.27-alpine

COPY http.conf /etc/agentmesh/http.conf
COPY https.conf /etc/agentmesh/https.conf
COPY http-ha.conf /etc/agentmesh/http-ha.conf
COPY https-ha.conf /etc/agentmesh/https-ha.conf
COPY 10-select-agentmesh-config.sh /docker-entrypoint.d/10-select-agentmesh-config.sh
RUN chmod +x /docker-entrypoint.d/10-select-agentmesh-config.sh

HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -q -O - http://127.0.0.1/livez || exit 1
