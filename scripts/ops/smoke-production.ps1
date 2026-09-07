param(
    [string]$EnvFile = ".env.production"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not [System.IO.Path]::IsPathRooted($EnvFile)) { $EnvFile = Join-Path $Root $EnvFile }
$publicOrigin = ((Get-Content $EnvFile | Where-Object { $_ -match '^PUBLIC_ORIGIN=' } | Select-Object -First 1) -split '=',2)[1].TrimEnd('/')

$live = Invoke-RestMethod -Uri "$publicOrigin/livez" -TimeoutSec 5
if ($live -ne "alive" -and $live.status -ne "alive") { throw "gateway liveness failed" }
$ready = Invoke-RestMethod -Uri "$publicOrigin/readyz" -TimeoutSec 5
if ($ready.status -ne "ready") { throw "control-plane readiness failed" }

Write-Host "P10 live deployment smoke: PASS" -ForegroundColor Green
Write-Host "Gateway: $publicOrigin"
