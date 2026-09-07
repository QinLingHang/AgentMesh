param(
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Version = (Get-Content (Join-Path $Root "VERSION") -Raw).Trim()

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Split-Path $Root -Parent
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# Development trees legitimately contain local dependencies, build output and local .env.
# Validate release identity/docs here, then sanitize into a clean staging tree and run
# strict hygiene validation against the exact tree that will be archived.
python (Join-Path $Root "scripts\release\validate-release.py") --root $Root
if ($LASTEXITCODE -ne 0) { throw "P12 development-tree release validator failed" }

$Name = "AgentMesh_v${Version}_SOURCE.zip"
$Archive = Join-Path $OutputDir $Name
if (Test-Path $Archive) { Remove-Item -Force $Archive }

$StageParent = Join-Path ([System.IO.Path]::GetTempPath()) ("agentmesh-release-" + [guid]::NewGuid().ToString("N"))
$Leaf = Split-Path $Root -Leaf
$StageRoot = Join-Path $StageParent $Leaf
New-Item -ItemType Directory -Force -Path $StageParent | Out-Null

try {
    python (Join-Path $Root "scripts\release\stage-release.py") --source $Root --dest $StageRoot
    if ($LASTEXITCODE -ne 0) { throw "P12 release staging failed" }

    python (Join-Path $StageRoot "scripts\release\validate-release.py") --root $StageRoot --strict-tree
    if ($LASTEXITCODE -ne 0) { throw "P12 strict staging validator failed" }

    Push-Location $StageParent
    try {
        tar.exe -a -c -f $Archive $Leaf
        if ($LASTEXITCODE -ne 0) { throw "tar.exe failed" }
    } finally {
        Pop-Location
    }
} finally {
    if (Test-Path $StageParent) {
        Remove-Item -Recurse -Force $StageParent -ErrorAction SilentlyContinue
    }
}

Write-Host "P12 Release Package: $Archive"
