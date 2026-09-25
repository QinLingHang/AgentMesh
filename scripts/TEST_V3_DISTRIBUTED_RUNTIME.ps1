param(
    [string]$Python = "python",
    [string]$MySQLDSN = $env:QA_TEST_MYSQL_DSN
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "=== AgentMesh V3 Distributed Runtime Targeted Validation ==="
Write-Host "Root: $Root"

if ($MySQLDSN) {
    $env:QA_TEST_MYSQL_DSN = $MySQLDSN
    $env:MEMORY_TEST_MYSQL_DSN = $MySQLDSN
}

Push-Location "$Root\runtime-python"
try {
    & $Python -m pytest -q tests/test_v3_distributed_runtime.py
    if ($LASTEXITCODE -ne 0) { throw "V3 Python targeted tests failed" }
}
finally { Pop-Location }

Push-Location "$Root\backend-go"
try {
    if (-not $env:QA_TEST_MYSQL_DSN) {
        Write-Warning "QA_TEST_MYSQL_DSN is not set; mandatory V3 MySQL integration tests will skip."
    }
    go test ./internal/service -run '^TestV3' -count=1 -v
    if ($LASTEXITCODE -ne 0) { throw "V3 Go targeted tests failed" }
}
finally { Pop-Location }

Push-Location "$Root\web-react"
try {
    node --test tests/v3-distributed-runtime-contract.test.mjs
    if ($LASTEXITCODE -ne 0) { throw "V3 React contract tests failed" }

    if (Test-Path "node_modules") {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "React build failed" }
        npm run test:e2e:v3
        if ($LASTEXITCODE -ne 0) { throw "V3 browser E2E failed" }
    }
    else {
        Write-Warning "web-react/node_modules is absent; build/browser E2E not executed."
    }
}
finally { Pop-Location }

Write-Host "V3 TARGETED VALIDATION: PASS"
