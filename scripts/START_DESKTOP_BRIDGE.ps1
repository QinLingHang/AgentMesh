param(
    [string[]]$Root = @(),
    [switch]$Restricted,
    [switch]$ReadOnly,
    [switch]$AllowDelete,
    [switch]$AllowSensitive,
    [string]$Token = "",
    [int]$Port = 9583
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path $PSScriptRoot -Parent
$Bridge = Join-Path $Repo "desktop-bridge"

if (-not (Test-Path $Bridge)) {
    throw "desktop-bridge directory not found: $Bridge"
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    $Bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($Bytes)
    $Token = [Convert]::ToHexString($Bytes).ToLowerInvariant()
}

$UseRestricted = $Restricted.IsPresent -or $Root.Count -gt 0
$Grants = @()

if ($UseRestricted) {
    if ($Root.Count -eq 0) {
        throw "Restricted mode requires at least one -Root."
    }
    $Grants = @(
        foreach ($Item in $Root) {
            $Resolved = [System.IO.Path]::GetFullPath($Item)
            [ordered]@{
                path           = $Resolved
                read           = $true
                write          = -not $ReadOnly.IsPresent
                delete         = $AllowDelete.IsPresent -and -not $ReadOnly.IsPresent
                allowSensitive = $AllowSensitive.IsPresent
            }
        }
    )
}

$env:DESKTOP_BRIDGE_HOST = "127.0.0.1"
$env:DESKTOP_BRIDGE_PORT = "$Port"
$env:DESKTOP_BRIDGE_TOKEN = $Token
$env:DESKTOP_ACCESS_MODE = if ($UseRestricted) { "restricted" } else { "local" }
$env:DESKTOP_ALLOWED_ROOTS_JSON = if ($UseRestricted) { ($Grants | ConvertTo-Json -Compress -Depth 6) } else { "[]" }

Write-Host ""
Write-Host "===== AgentMesh Desktop Bridge =====" -ForegroundColor Cyan
Write-Host "URL    : http://127.0.0.1:$Port"
Write-Host "Mode   : $($env:DESKTOP_ACCESS_MODE)"
if ($UseRestricted) {
    Write-Host "Roots  :"
    $Grants | ForEach-Object {
        Write-Host "  - $($_.path) read=$($_.read) write=$($_.write) delete=$($_.delete) sensitive=$($_.allowSensitive)"
    }
} else {
    Write-Host "Access : local fixed drives under the current Windows user permissions"
    Write-Host "Safety : sensitive/system paths protected; mutation approval remains enforced"
}
Write-Host ""
Write-Host "Runtime must use the same token:" -ForegroundColor Yellow
Write-Host '$env:DESKTOP_BRIDGE_ENABLED = "true"'
Write-Host '$env:DESKTOP_BRIDGE_BASE_URL = "http://127.0.0.1:'$Port'"'
Write-Host '$env:DESKTOP_BRIDGE_TOKEN = "'$Token'"'
Write-Host ""
Write-Host "The token is not written to the repository." -ForegroundColor DarkGray
Write-Host ""

Push-Location $Bridge
try {
    python -c "import fastapi, uvicorn" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Missing Desktop Bridge dependencies. Run: python -m pip install -r `"$Bridge\requirements.txt`""
    }
    python -m uvicorn desktop_bridge.app:app --host 127.0.0.1 --port $Port
}
finally {
    Pop-Location
}
