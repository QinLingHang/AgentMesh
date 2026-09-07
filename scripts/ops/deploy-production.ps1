param(
    [string]$EnvFile = ".env.production",
    [int]$ReadyTimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile = Join-Path $Root "docker-compose.production.yml"
if (-not [System.IO.Path]::IsPathRooted($EnvFile)) { $EnvFile = Join-Path $Root $EnvFile }

& (Join-Path $PSScriptRoot "validate-production.ps1") -EnvFile $EnvFile
if ($LASTEXITCODE -ne 0) { throw "production preflight failed" }

$publicOrigin = ((Get-Content $EnvFile | Where-Object { $_ -match '^PUBLIC_ORIGIN=' } | Select-Object -First 1) -split '=',2)[1].TrimEnd('/')

Push-Location $Root
try {
    & docker compose --env-file $EnvFile -f $ComposeFile up -d --build
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri "$publicOrigin/readyz" -TimeoutSec 5
            if ($response.status -eq "ready") { $ready = $true; break }
        } catch {
            Start-Sleep -Seconds 3
        }
    }
    if (-not $ready) {
        & docker compose --env-file $EnvFile -f $ComposeFile ps
        throw "AgentMesh gateway did not become ready within $ReadyTimeoutSeconds seconds"
    }

    & docker compose --env-file $EnvFile -f $ComposeFile ps
} finally {
    Pop-Location
}

Write-Host "AgentMesh production deployment: READY at $publicOrigin" -ForegroundColor Green
