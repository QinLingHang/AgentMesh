#!/usr/bin/env sh
set -eu
[ "${1:-}" = "--force" ] || { echo "Restore is destructive. Usage: $0 --force <backup-dir> [env-file]" >&2; exit 1; }
BACKUP_DIR=${2:?backup directory required}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ENV_FILE=${3:-"$ROOT/.env.production"}
COMPOSE_FILE="$ROOT/docker-compose.production.yml"
set -a; . "$ENV_FILE"; set +a
VOLUME_PREFIX=${DATA_VOLUME_PREFIX:-agentmesh-prod}
BACKUP_DIR=$(CDPATH= cd -- "$BACKUP_DIR" && pwd)

for f in mysql.sql knowledge_data.tar.gz redis_data.tar.gz milvus_etcd_data.tar.gz milvus_minio_data.tar.gz milvus_data.tar.gz SHA256SUMS manifest.json; do
  [ -f "$BACKUP_DIR/$f" ] || { echo "backup file missing: $f" >&2; exit 1; }
done
( cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS )
cd "$ROOT"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down
for v in $VOLUME_PREFIX-mysql-data $VOLUME_PREFIX-knowledge-data $VOLUME_PREFIX-redis-data $VOLUME_PREFIX-milvus-etcd-data $VOLUME_PREFIX-milvus-minio-data $VOLUME_PREFIX-milvus-data; do
  docker volume rm -f "$v" >/dev/null 2>&1 || true
  docker volume create "$v" >/dev/null
done
restore_volume() {
  docker run --rm -v "$1:/data" -v "$BACKUP_DIR:/backup:ro" alpine:3.21 sh -c "cd /data && tar -xzf /backup/$2"
}
restore_volume $VOLUME_PREFIX-knowledge-data knowledge_data.tar.gz
restore_volume $VOLUME_PREFIX-redis-data redis_data.tar.gz
restore_volume $VOLUME_PREFIX-milvus-etcd-data milvus_etcd_data.tar.gz
restore_volume $VOLUME_PREFIX-milvus-minio-data milvus_minio_data.tar.gz
restore_volume $VOLUME_PREFIX-milvus-data milvus_data.tar.gz

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d mysql
MYSQL_READY=false
for i in $(seq 1 60); do
  if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T mysql sh -c 'mysqladmin ping -h 127.0.0.1 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --silent' >/dev/null 2>&1; then MYSQL_READY=true; break; fi
  sleep 2
done
[ "$MYSQL_READY" = "true" ] || { echo "mysql did not become ready" >&2; exit 1; }
MYSQL_ID=$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps -q mysql)
docker cp "$BACKUP_DIR/mysql.sql" "$MYSQL_ID:/tmp/agentmesh-restore.sql"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" < /tmp/agentmesh-restore.sql'
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T mysql rm -f /tmp/agentmesh-restore.sql
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d
echo "AgentMesh restore completed from: $BACKUP_DIR"
