#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${1:-"$ROOT/.env.production"}
BACKUP_ROOT=${2:-"$ROOT/backups"}
COMPOSE_FILE="$ROOT/docker-compose.production.yml"
set -a; . "$ENV_FILE"; set +a
VOLUME_PREFIX=${DATA_VOLUME_PREFIX:-agentmesh-prod}
STAMP=$(date -u +%Y%m%d-%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/agentmesh-$STAMP"
mkdir -p "$BACKUP_DIR"
cd "$ROOT"

MYSQL_ID=$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps -q mysql)
[ -n "$MYSQL_ID" ] || { echo "mysql container is not running" >&2; exit 1; }
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T mysql sh -c 'mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --single-transaction --quick --skip-lock-tables --no-tablespaces "$MYSQL_DATABASE" > /tmp/agentmesh-backup.sql'
docker cp "$MYSQL_ID:/tmp/agentmesh-backup.sql" "$BACKUP_DIR/mysql.sql"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T mysql rm -f /tmp/agentmesh-backup.sql

trap 'docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d >/dev/null 2>&1 || true' EXIT
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" stop gateway web-react runtime-python mcp-demo backend-go
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T redis redis-cli SAVE >/dev/null
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" stop redis milvus etcd minio

backup_volume() {
  docker run --rm -v "$1:/data:ro" -v "$BACKUP_DIR:/backup" alpine:3.21 tar -czf "/backup/$2" -C /data .
}
backup_volume $VOLUME_PREFIX-knowledge-data knowledge_data.tar.gz
backup_volume $VOLUME_PREFIX-redis-data redis_data.tar.gz
backup_volume $VOLUME_PREFIX-milvus-etcd-data milvus_etcd_data.tar.gz
backup_volume $VOLUME_PREFIX-milvus-minio-data milvus_minio_data.tar.gz
backup_volume $VOLUME_PREFIX-milvus-data milvus_data.tar.gz

( cd "$BACKUP_DIR" && sha256sum mysql.sql *.tar.gz > SHA256SUMS )
cat > "$BACKUP_DIR/manifest.json" <<JSON
{"format":"agentmesh-p10-backup-v1","createdAt":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","secretsAndTlsExcluded":true}
JSON
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d >/dev/null
trap - EXIT
echo "AgentMesh backup created: $BACKUP_DIR"
