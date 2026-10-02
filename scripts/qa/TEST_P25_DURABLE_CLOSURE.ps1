param(
    [string]$MySQLDSN = $env:QA_TEST_MYSQL_DSN,
    [string]$RedisAddress = $(if ($env:P25_QA_REDIS_ADDR) { $env:P25_QA_REDIS_ADDR } else { "127.0.0.1:6382" }),
    [int]$RedisDB = $(if ($env:P25_QA_REDIS_DB) { [int]$env:P25_QA_REDIS_DB } else { 0 })
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Backend = Join-Path $Root "backend-go"
if (-not $MySQLDSN) {
    throw "QA_TEST_MYSQL_DSN is required; the runner only uses the existing random-schema MySQL fixture."
}

$previousMySQL = $env:QA_TEST_MYSQL_DSN
$previousRedisAddress = $env:P25_QA_REDIS_ADDR
$previousRedisDB = $env:P25_QA_REDIS_DB
try {
    $env:QA_TEST_MYSQL_DSN = $MySQLDSN
    $env:P25_QA_REDIS_ADDR = $RedisAddress
    $env:P25_QA_REDIS_DB = [string]$RedisDB
    Push-Location $Backend
    try {
        & go test -v -count=1 -run '^TestP25(DisconnectReplayUsesSameTaskAndCompositeDeltaCursor|HigherFenceRejectsLateAttemptAndPersistsOnlyAuthoritativeResult|RedisLiveBufferLossPreservesDurableTerminalResult)$' ./internal/service
        if ($LASTEXITCODE -ne 0) {
            throw "P25 durable closure integration failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($null -eq $previousMySQL) { Remove-Item Env:QA_TEST_MYSQL_DSN -ErrorAction SilentlyContinue } else { $env:QA_TEST_MYSQL_DSN = $previousMySQL }
    if ($null -eq $previousRedisAddress) { Remove-Item Env:P25_QA_REDIS_ADDR -ErrorAction SilentlyContinue } else { $env:P25_QA_REDIS_ADDR = $previousRedisAddress }
    if ($null -eq $previousRedisDB) { Remove-Item Env:P25_QA_REDIS_DB -ErrorAction SilentlyContinue } else { $env:P25_QA_REDIS_DB = $previousRedisDB }
}

Write-Host "P25 durable closure integration PASS" -ForegroundColor Green
