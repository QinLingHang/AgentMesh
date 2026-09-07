param(
    [string]$Output = ".env.production",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Template = Join-Path $Root ".env.production.example"
if (-not [System.IO.Path]::IsPathRooted($Output)) { $Output = Join-Path $Root $Output }
if ((Test-Path $Output) -and -not $Force) { throw "$Output already exists. Use -Force to replace it." }

function New-Secret([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return ([Convert]::ToBase64String($buffer)).TrimEnd('=').Replace('+','-').Replace('/','_')
}

$content = Get-Content $Template -Raw
$replacements = @{
    'CHANGE_ME_mysql_password' = (New-Secret 24)
    'CHANGE_ME_mysql_root_password' = (New-Secret 24)
    'CHANGE_ME_minio_secret' = (New-Secret 32)
    'CHANGE_ME_jwt_secret_at_least_32_characters' = (New-Secret 48)
    'CHANGE_ME_verification_pepper_at_least_16_characters' = (New-Secret 32)
    'CHANGE_ME_runtime_internal_token_at_least_16_characters' = (New-Secret 32)
    'CHANGE_ME_governance_master_key_at_least_32_characters' = (New-Secret 48)
}
foreach ($entry in $replacements.GetEnumerator()) {
    $content = $content.Replace($entry.Key, $entry.Value)
}
[System.IO.File]::WriteAllText($Output, $content, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Created $Output with generated local secrets." -ForegroundColor Green
Write-Host "Review PUBLIC_ORIGIN, TLS, email, and model settings before real deployment."
