$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$pepper = [Convert]::ToBase64String($bytes)

Write-Host ""
Write-Host "Generated VERIFICATION_PEPPER:"
Write-Host $pepper
Write-Host ""
Write-Host "Copy it into backend-go\.env and do NOT send it to anyone."
