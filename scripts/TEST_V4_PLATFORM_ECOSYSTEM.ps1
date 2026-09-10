param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Run-Step([string]$Name, [scriptblock]$Action) {
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

if (-not $env:P2_TEST_MYSQL_DSN) {
    throw "P2_TEST_MYSQL_DSN is required; mandatory V4 MySQL tests must not be skipped."
}
if (-not $env:P3_TEST_MYSQL_DSN) { $env:P3_TEST_MYSQL_DSN = $env:P2_TEST_MYSQL_DSN }
if (-not $env:P3_TEST_PYTHON) { $env:P3_TEST_PYTHON = (Get-Command $Python).Source }

Run-Step "V4 Go/MySQL" {
    Push-Location "$Root\backend-go"
    try { go test ./internal/service -run '^TestV4' -count=1 -v }
    finally { Pop-Location }
}
Run-Step "V4 Python SDK" {
    Push-Location "$Root\sdk\python"
    try { & $Python -m unittest discover -s tests -p "test_*.py" -v }
    finally { Pop-Location }
}
Run-Step "V4 TypeScript SDK" {
    Push-Location "$Root\sdk\typescript"
    try {
        $SdkTsc = "$Root\sdk\typescript\node_modules\typescript\bin\tsc"
        $WebTsc = "$Root\web-react\node_modules\typescript\bin\tsc"
        if (Test-Path $SdkTsc) {
            node $SdkTsc -p tsconfig.json
        } elseif (Test-Path $WebTsc) {
            node $WebTsc -p tsconfig.json
        } else {
            throw "TypeScript compiler not found. Run npm ci in sdk/typescript or web-react first."
        }
        if ($LASTEXITCODE -ne 0) { throw "V4 TypeScript SDK build failed" }
        node --test tests/*.test.mjs
    }
    finally { Pop-Location }
}
Run-Step "V4 React contract" {
    Push-Location "$Root\web-react"
    try { node --test tests/v4-platform-ecosystem-contract.test.mjs }
    finally { Pop-Location }
}
Run-Step "V4 React build" {
    Push-Location "$Root\web-react"
    try { npm run build }
    finally { Pop-Location }
}
Run-Step "V4 Browser E2E" {
    Push-Location "$Root\web-react"
    try { npm run test:e2e:v4 }
    finally { Pop-Location }
}

Write-Host "`nV4 Platform Ecosystem targeted acceptance: PASS" -ForegroundColor Green
