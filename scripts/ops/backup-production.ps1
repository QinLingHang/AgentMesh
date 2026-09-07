param(
    [string]$EnvFile = ".env.production",
    [string]$BackupRoot = "backups"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile = Join-Path $Root "docker-compose.production.yml"
if (-not [System.IO.Path]::IsPathRooted($EnvFile)) { $EnvFile = Join-Path $Root $EnvFile }
if (-not [System.IO.Path]::IsPathRooted($BackupRoot)) { $BackupRoot = Join-Path $Root $BackupRoot }
$volumePrefixLine = Get-Content $EnvFile | Where-Object { $_ -match '^DATA_VOLUME_PREFIX=' } | Select-Object -First 1
$volumePrefix = if ($volumePrefixLine) { ($volumePrefixLine -split '=',2)[1].Trim() } else { "agentmesh-prod" }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir = Join-Path $BackupRoot "agentmesh-$stamp"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$volumeArchives = [ordered]@{
    "$volumePrefix-knowledge-data" = "knowledge_data.tar.gz"
    "$volumePrefix-redis-data" = "redis_data.tar.gz"
    "$volumePrefix-milvus-etcd-data" = "milvus_etcd_data.tar.gz"
    "$volumePrefix-milvus-minio-data" = "milvus_minio_data.tar.gz"
    "$volumePrefix-milvus-data" = "milvus_data.tar.gz"
}

Push-Location $Root
try {
    $mysqlId = (& docker compose --env-file $EnvFile -f $ComposeFile ps -q mysql).Trim()
    if (-not $mysqlId) { throw "mysql container is not running" }

    & docker compose --env-file $EnvFile -f $ComposeFile exec -T mysql sh -c 'mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --single-transaction --quick --skip-lock-tables --no-tablespaces "$MYSQL_DATABASE" > /tmp/agentmesh-backup.sql'
    if ($LASTEXITCODE -ne 0) { throw "mysqldump failed" }
    & docker cp "${mysqlId}:/tmp/agentmesh-backup.sql" (Join-Path $BackupDir "mysql.sql")
    & docker compose --env-file $EnvFile -f $ComposeFile exec -T mysql rm -f /tmp/agentmesh-backup.sql

    & docker compose --env-file $EnvFile -f $ComposeFile stop gateway web-react runtime-python mcp-demo backend-go
    & docker compose --env-file $EnvFile -f $ComposeFile exec -T redis redis-cli SAVE | Out-Null
    & docker compose --env-file $EnvFile -f $ComposeFile stop redis milvus etcd minio

    foreach ($entry in $volumeArchives.GetEnumerator()) {
        & docker run --rm -v (("{0}:/data:ro" -f $entry.Key)) -v "${BackupDir}:/backup" alpine:3.21 tar -czf "/backup/$($entry.Value)" -C /data .
        if ($LASTEXITCODE -ne 0) { throw "backup failed for volume $($entry.Key)" }
    }

    $files = Get-ChildItem $BackupDir -File | ForEach-Object {
        [ordered]@{ name = $_.Name; sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); bytes = $_.Length }
    }
    [ordered]@{
        format = "agentmesh-p10-backup-v1"
        createdAt = (Get-Date).ToUniversalTime().ToString("o")
        files = $files
        note = "Secrets (.env.production) and TLS private keys are intentionally excluded."
    } | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $BackupDir "manifest.json")
} finally {
    & docker compose --env-file $EnvFile -f $ComposeFile up -d | Out-Null
    Pop-Location
}

Write-Host "AgentMesh backup created: $BackupDir" -ForegroundColor Green
