$ErrorActionPreference = "Stop"
$Base = "http://localhost:8086"

function New-UserSession($email, $name) {
  $s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
  try {
    $r = Invoke-RestMethod -Method Post -Uri "$Base/api/auth/register" -WebSession $s -ContentType "application/json" -Body (@{email=$email;password="Test123456";displayName=$name}|ConvertTo-Json)
  } catch {
    $r = Invoke-RestMethod -Method Post -Uri "$Base/api/auth/login" -WebSession $s -ContentType "application/json" -Body (@{email=$email;password="Test123456"}|ConvertTo-Json)
  }
  return @{ Session=$s; Token=$r.data.accessToken }
}

$a = New-UserSession "tenant-a@example.com" "Tenant A"
$b = New-UserSession "tenant-b@example.com" "Tenant B"
$ha = @{Authorization="Bearer $($a.Token)"}
$hb = @{Authorization="Bearer $($b.Token)"}

$convA = Invoke-RestMethod -Method Post -Uri "$Base/api/conversations" -Headers $ha -WebSession $a.Session -ContentType "application/json" -Body (@{title="A private conversation"}|ConvertTo-Json)
$idA = $convA.data.id

Write-Host "A conversation id:" $idA
Write-Host "B tries to read A messages; expected 404..."
try {
  Invoke-RestMethod -Method Get -Uri "$Base/api/conversations/$idA/messages" -Headers $hb -WebSession $b.Session | Out-Null
  throw "TENANT ISOLATION FAILED: B could read A conversation"
} catch {
  if ($_.Exception.Response.StatusCode.value__ -ne 404) {
    throw
  }
}

Write-Host "TENANT ISOLATION TEST PASSED" -ForegroundColor Green
