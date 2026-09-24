param(
    [string]$EnvFile = ".env.production"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile = Join-Path $Root "docker-compose.production.yml"
if (-not [System.IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile = Join-Path $Root $EnvFile
}
if (-not (Test-Path $EnvFile)) {
    throw "Production env file not found: $EnvFile"
}

function Read-DotEnv([string]$Path) {
    $map = @{}
    foreach ($line in Get-Content $Path) {
        $trim = $line.Trim()
        if (-not $trim -or $trim.StartsWith("#") -or -not $trim.Contains("=")) { continue }
        $parts = $trim.Split("=", 2)
        $map[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $map
}

$envMap = Read-DotEnv $EnvFile
$required = @(
    "MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD", "MINIO_SECRET_KEY",
    "JWT_SECRET", "VERIFICATION_PEPPER", "RUNTIME_INTERNAL_TOKEN",
    "GOVERNANCE_MASTER_KEY", "PUBLIC_ORIGIN"
)
foreach ($key in $required) {
    if (-not $envMap.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($envMap[$key])) {
        throw "$key is required in $EnvFile"
    }
    if ($envMap[$key] -match "CHANGE_ME") {
        throw "$key still contains CHANGE_ME"
    }
}
if ($envMap["JWT_SECRET"].Length -lt 32) { throw "JWT_SECRET must be at least 32 characters" }
if ($envMap["GOVERNANCE_MASTER_KEY"].Length -lt 32) { throw "GOVERNANCE_MASTER_KEY must be at least 32 characters" }
if ($envMap["VERIFICATION_PEPPER"].Length -lt 16) { throw "VERIFICATION_PEPPER must be at least 16 characters" }
if ($envMap["RUNTIME_INTERNAL_TOKEN"].Length -lt 16) { throw "RUNTIME_INTERNAL_TOKEN must be at least 16 characters" }

$requireTls = ($envMap["REQUIRE_TLS"] -eq "true")
if ($requireTls) {
    if ($envMap["AUTH_COOKIE_SECURE"] -ne "true") { throw "AUTH_COOKIE_SECURE must be true when REQUIRE_TLS=true" }
    if (-not $envMap["PUBLIC_ORIGIN"].StartsWith("https://")) { throw "PUBLIC_ORIGIN must use https:// when REQUIRE_TLS=true" }
    $certDir = $envMap["TLS_CERT_DIR"]
    if (-not [System.IO.Path]::IsPathRooted($certDir)) { $certDir = Join-Path $Root $certDir }
    if (-not (Test-Path (Join-Path $certDir "fullchain.pem"))) { throw "TLS fullchain.pem not found in $certDir" }
    if (-not (Test-Path (Join-Path $certDir "privkey.pem"))) { throw "TLS privkey.pem not found in $certDir" }
}

Push-Location $Root
try {
    & docker compose --env-file $EnvFile -f $ComposeFile config --quiet
    if ($LASTEXITCODE -ne 0) { throw "docker compose config failed" }
} finally {
    Pop-Location
}

Write-Host "Production preflight: PASS" -ForegroundColor Green
Write-Host "Public origin: $($envMap['PUBLIC_ORIGIN'])"
Write-Host "TLS required: $requireTls"
