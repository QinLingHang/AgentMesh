param(
    [Parameter(Mandatory=$true)][string]$BackupDir,
    [string]$EnvFile = ".env.production",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
if (-not $Force) { throw "Restore is destructive. Re-run with -Force after confirming the backup path." }
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile = Join-Path $Root "docker-compose.production.yml"
if (-not [System.IO.Path]::IsPathRooted($EnvFile)) { $EnvFile = Join-Path $Root $EnvFile }
$BackupDir = (Resolve-Path $BackupDir).Path
$volumePrefixLine = Get-Content $EnvFile | Where-Object { $_ -match '^DATA_VOLUME_PREFIX=' } | Select-Object -First 1
$volumePrefix = if ($volumePrefixLine) { ($volumePrefixLine -split '=',2)[1].Trim() } else { "agentmesh-prod" }

$archives = [ordered]@{
    "$volumePrefix-knowledge-data" = "knowledge_data.tar.gz"
    "$volumePrefix-redis-data" = "redis_data.tar.gz"
    "$volumePrefix-milvus-etcd-data" = "milvus_etcd_data.tar.gz"
    "$volumePrefix-milvus-minio-data" = "milvus_minio_data.tar.gz"
    "$volumePrefix-milvus-data" = "milvus_data.tar.gz"
}
foreach ($file in @("mysql.sql", "manifest.json") + @($archives.Values)) {
    if (-not (Test-Path (Join-Path $BackupDir $file))) { throw "backup file missing: $file" }
}
$manifest = Get-Content (Join-Path $BackupDir "manifest.json") -Raw | ConvertFrom-Json
if ($manifest.format -ne "agentmesh-production-backup-v1") { throw "unsupported backup format: $($manifest.format)" }
foreach ($entry in $manifest.files) {
    $path = Join-Path $BackupDir $entry.name
    if (-not (Test-Path $path)) { throw "manifest file missing: $($entry.name)" }
    $actual = (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.sha256) { throw "backup checksum mismatch: $($entry.name)" }
}

$allVolumes = @("$volumePrefix-mysql-data") + @($archives.Keys)
Push-Location $Root
try {
    & docker compose --env-file $EnvFile -f $ComposeFile down
    foreach ($volume in $allVolumes) {
        & docker volume rm -f $volume 2>$null | Out-Null
        & docker volume create $volume | Out-Null
    }

    foreach ($entry in $archives.GetEnumerator()) {
        & docker run --rm -v (("{0}:/data" -f $entry.Key)) -v "${BackupDir}:/backup:ro" alpine:3.21 sh -c "cd /data && tar -xzf /backup/$($entry.Value)"
        if ($LASTEXITCODE -ne 0) { throw "restore failed for volume $($entry.Key)" }
    }

    & docker compose --env-file $EnvFile -f $ComposeFile up -d mysql
    if ($LASTEXITCODE -ne 0) { throw "mysql start failed" }
    $mysqlId = ""
    $mysqlReady = $false
    for ($i = 0; $i -lt 60; $i++) {
        $mysqlId = (& docker compose --env-file $EnvFile -f $ComposeFile ps -q mysql).Trim()
        if ($mysqlId) {
            & docker compose --env-file $EnvFile -f $ComposeFile exec -T mysql sh -c 'mysqladmin ping -h 127.0.0.1 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --silent' 2>$null
            if ($LASTEXITCODE -eq 0) { $mysqlReady = $true; break }
        }
        Start-Sleep -Seconds 2
    }
    if (-not $mysqlReady) { throw "mysql did not become ready" }

    & docker cp (Join-Path $BackupDir "mysql.sql") "${mysqlId}:/tmp/agentmesh-restore.sql"
    & docker compose --env-file $EnvFile -f $ComposeFile exec -T mysql sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" < /tmp/agentmesh-restore.sql'
    if ($LASTEXITCODE -ne 0) { throw "mysql restore failed" }
    & docker compose --env-file $EnvFile -f $ComposeFile exec -T mysql rm -f /tmp/agentmesh-restore.sql

    & docker compose --env-file $EnvFile -f $ComposeFile up -d
    if ($LASTEXITCODE -ne 0) { throw "stack restart failed" }
} finally {
    Pop-Location
}

Write-Host "AgentMesh restore completed from: $BackupDir" -ForegroundColor Green
