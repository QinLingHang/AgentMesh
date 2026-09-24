param(
    [ValidateRange(1, 10000)]
    [int]$GoStressCount = 100,
    [switch]$SkipGoStress
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend-go"
$Web = Join-Path $Root "web-react"
$Runtime = Join-Path $Root "runtime-python"
$Desktop = Join-Path $Root "desktop-bridge"

function Require-Path([string]$Path, [string]$Label) {
    if (-not (Test-Path $Path)) {
        throw "$Label not found: $Path"
    }
}

Require-Path $Backend "backend-go"
Require-Path $Web "web-react"
Require-Path $Runtime "runtime-python"
Require-Path $Desktop "desktop-bridge"
Require-Path (Join-Path $Web "e2e\v4-1-browser-e2e.mjs") "V4.1 browser harness"

if (-not $env:QA_TEST_MYSQL_DSN) {
    throw "QA_TEST_MYSQL_DSN is required. Use the same isolated MySQL acceptance DSN as the existing QA Database/Release Browser/V3 integration tests."
}

Write-Host "[V4.1 Dispatcher Lease Reliability] Preflight" -ForegroundColor Cyan
& go version
& node --version
& npm --version

if (-not $SkipGoStress) {
    Push-Location $Backend
    try {
        Write-Host "[V4.1 Dispatcher Lease Reliability] Deterministic dispatcher lease semantic case" -ForegroundColor Cyan
        & go test ./internal/service -run '^TestV3DispatcherLeaseFailoverUsesMonotonicEpoch$' "-count=1"
        if ($LASTEXITCODE -ne 0) {
            throw "Go dispatcher lease semantic case failed with exit code $LASTEXITCODE"
        }

        # Do not use `go test -count=N` for the integration stress. `-count=N`
        # recreates and migrates the isolated MySQL database N times and can hit
        # Go's global test timeout before the requested repetitions complete.
        # Instead run one test process/fixture and perform N real lease ownership
        # transfers against the same isolated database.
        Write-Host "[V4.1 Dispatcher Lease Reliability] Dispatcher lease ownership-transfer stress x$GoStressCount in one isolated DB" -ForegroundColor Cyan
        $PreviousStressIterations = $env:V4_1_LEASE_STRESS_ITERATIONS
        try {
            $env:V4_1_LEASE_STRESS_ITERATIONS = [string]$GoStressCount
            & go test ./internal/service -run '^TestV3DispatcherLeaseFailoverStress$' "-count=1"
            if ($LASTEXITCODE -ne 0) {
                throw "Go dispatcher lease stress failed with exit code $LASTEXITCODE"
            }
        }
        finally {
            if ($null -eq $PreviousStressIterations) {
                Remove-Item Env:V4_1_LEASE_STRESS_ITERATIONS -ErrorAction SilentlyContinue
            }
            else {
                $env:V4_1_LEASE_STRESS_ITERATIONS = $PreviousStressIterations
            }
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "[V4.1 Runtime Redis Isolation] Browser contracts" -ForegroundColor Cyan
Push-Location $Web
try {
    & node --test tests/browser-regression-contract.test.mjs
    if ($LASTEXITCODE -ne 0) {
        throw "V4.1 browser contract failed with exit code $LASTEXITCODE"
    }

    & node --test tests/runtime-memory-redis-isolation-contract.test.mjs
    if ($LASTEXITCODE -ne 0) {
        throw "V4.1 Runtime Redis Isolation Redis isolation contract failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host "[V4.1 Runtime Redis Isolation] Real-stack browser dynamic acceptance" -ForegroundColor Cyan
Push-Location $Web
try {
    & npm run test:e2e:v4-1
    if ($LASTEXITCODE -ne 0) {
        throw "V4.1 browser E2E failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host "[V4.1 Runtime Redis Isolation] PASS" -ForegroundColor Green
