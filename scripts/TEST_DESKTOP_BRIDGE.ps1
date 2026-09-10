param(
    [Parameter(Mandatory = $true)]
    [string]$Token,

    [Parameter(Mandatory = $true)]
    [string]$Root,

    [int]$Port = 9583
)

$ErrorActionPreference = "Stop"
$Base = "http://127.0.0.1:$Port"
$Headers = @{ "x-desktop-token" = $Token }
$RootPath = [System.IO.Path]::GetFullPath($Root)

Write-Host "===== Desktop Bridge Health ====="
Invoke-RestMethod -Uri "$Base/health"

Write-Host "`n===== Authorized Root List ====="
Invoke-RestMethod `
    -Method Post `
    -Uri "$Base/v1/files/list" `
    -Headers $Headers `
    -ContentType "application/json" `
    -Body (@{ path = $RootPath; limit = 20 } | ConvertTo-Json)

Write-Host "`nPASS: Desktop Bridge is reachable and the configured root is readable." -ForegroundColor Green
