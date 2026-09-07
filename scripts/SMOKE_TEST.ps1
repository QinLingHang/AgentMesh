$ErrorActionPreference = "Stop"
$Base = "http://localhost:8086"
$email = "test@example.com"
$password = "Test123456"
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession

Write-Host "[1/7] register or login"
try {
  $auth = Invoke-RestMethod -Method Post -Uri "$Base/api/auth/register" -WebSession $session -ContentType "application/json" -Body (@{ email=$email; password=$password; displayName="MVP Tester" } | ConvertTo-Json)
} catch {
  $auth = Invoke-RestMethod -Method Post -Uri "$Base/api/auth/login" -WebSession $session -ContentType "application/json" -Body (@{ email=$email; password=$password } | ConvertTo-Json)
}
$token = $auth.data.accessToken
$headers = @{ Authorization = "Bearer $token" }

Write-Host "[2/7] create conversation"
$conv = Invoke-RestMethod -Method Post -Uri "$Base/api/conversations" -Headers $headers -WebSession $session -ContentType "application/json" -Body (@{ title="MVP Smoke" } | ConvertTo-Json)
$convId = $conv.data.id

Write-Host "[3/7] seed demo agents"
$agents = Invoke-RestMethod -Method Post -Uri "$Base/api/agents/seed-demo" -Headers $headers -WebSession $session
$agents.data | Select-Object id,name,protocol,endpoint | Format-Table

Write-Host "[4/7] runtime plugins"
$plugins = Invoke-RestMethod -Method Get -Uri "$Base/api/runtime/plugins" -Headers $headers -WebSession $session
$plugins.data | Select-Object id,kind,status | Format-Table

Write-Host "[5/7] run multi-capability task with fallback"
$body = @{
  conversationId = $convId
  task = "Analyze this PDF and CSV data"
  scheduler = "greedy"
  constraints = @{ maxLatencyMs = 8000; maxCost = 0.15; minQuality = 0.8 }
} | ConvertTo-Json -Depth 6
$result = Invoke-RestMethod -Method Post -Uri "$Base/api/tasks/run" -Headers $headers -WebSession $session -ContentType "application/json" -Body $body

Write-Host "Selected Agents:" ($result.data.selectedAgents -join " -> ")
Write-Host "Elapsed:" $result.data.elapsedMs "ms"
Write-Host "Estimated Cost:" $result.data.estimatedCost
Write-Host "Trace:"
$result.data.trace | Select-Object elapsedMs,kind,title,status,detail | Format-Table -AutoSize

$fallback = $result.data.trace | Where-Object { $_.kind -eq "reschedule" -and $_.status -eq "completed" }
if (-not $fallback) { throw "Fallback/reschedule event not found" }

Write-Host "[6/7] messages"
$messages = Invoke-RestMethod -Method Get -Uri "$Base/api/conversations/$convId/messages" -Headers $headers -WebSession $session
if ($messages.data.Count -lt 2) { throw "Expected user + assistant messages" }

Write-Host "[7/7] task history"
$tasks = Invoke-RestMethod -Method Get -Uri "$Base/api/tasks" -Headers $headers -WebSession $session
if ($tasks.data.Count -lt 1) { throw "No task history" }

Write-Host "`nMVP SMOKE TEST PASSED" -ForegroundColor Green
