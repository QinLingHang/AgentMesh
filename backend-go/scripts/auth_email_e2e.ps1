param(
    [ValidateSet("register", "login", "reset")]
    [string]$Mode = "register",

    [string]$BaseUrl = "http://127.0.0.1:8086",

    [Parameter(Mandatory = $true)]
    [string]$Email,

    [string]$DisplayName = "AgentMesh User",

    [string]$Password = "AgentMeshTest123!",

    [string]$NewPassword = "AgentMeshNew123!"
)

$ErrorActionPreference = "Stop"

function Invoke-AgentMeshJson {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("GET", "POST", "PUT", "DELETE")]
        [string]$Method,

        [Parameter(Mandatory = $true)]
        [string]$Path,

        [object]$Body = $null,

        [Microsoft.PowerShell.Commands.WebRequestSession]$WebSession = $null
    )

    $uri = $BaseUrl.TrimEnd("/") + $Path

    $params = @{
        Method      = $Method
        Uri         = $uri
        ContentType = "application/json; charset=utf-8"
    }

    if ($null -ne $Body) {
        $params.Body = (
            $Body |
                ConvertTo-Json -Depth 10
        )
    }

    if ($null -ne $WebSession) {
        $params.WebSession = $WebSession
    }

    try {
        return Invoke-RestMethod @params
    }
    catch {
        Write-Host ""
        Write-Host "Request failed:" -ForegroundColor Red
        Write-Host "$Method $uri" -ForegroundColor Red

        if ($_.ErrorDetails.Message) {
            Write-Host $_.ErrorDetails.Message
        }
        else {
            Write-Host $_.Exception.Message
        }

        throw
    }
}

function Send-Code {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Scene
    )

    Write-Host ""
    Write-Host "1. Sending verification code..." -ForegroundColor Cyan

    $response = Invoke-AgentMeshJson `
        -Method POST `
        -Path "/api/auth/email/code" `
        -Body @{
            email = $Email
            scene = $Scene
        }

    Write-Host "Code request accepted." -ForegroundColor Green

    if ($response.data) {
        Write-Host (
            "Expires in: {0}s; resend cooldown: {1}s" -f `
                $response.data.expiresInSeconds, `
                $response.data.cooldownSeconds
        )
    }

    Write-Host ""
    Write-Host "Check your mailbox. Do not paste the code into ChatGPT."
    return Read-Host "Enter the 6-digit code locally"
}

Write-Host ""
Write-Host "AgentMesh real SMTP Auth E2E" -ForegroundColor Cyan
Write-Host "Mode: $Mode"
Write-Host "Base URL: $BaseUrl"
Write-Host "Target email: $Email"

switch ($Mode) {
    "register" {
        $code = Send-Code -Scene "register"

        Write-Host ""
        Write-Host "2. Registering verified account..." -ForegroundColor Cyan

        $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession

        $response = Invoke-AgentMeshJson `
            -Method POST `
            -Path "/api/auth/register/verify" `
            -WebSession $session `
            -Body @{
                email       = $Email
                code        = $code
                password    = $Password
                displayName = $DisplayName
            }

        Write-Host "Verified registration succeeded." -ForegroundColor Green

        if ($response.data.user) {
            Write-Host (
                "User: id={0}, email={1}, name={2}" -f `
                    $response.data.user.id, `
                    $response.data.user.email, `
                    $response.data.user.displayName
            )
        }

        Write-Host (
            "Access token TTL: {0}s" -f `
                $response.data.expiresIn
        )

        Write-Host "Refresh cookie captured in local PowerShell WebSession."
    }

    "login" {
        $code = Send-Code -Scene "login"

        Write-Host ""
        Write-Host "2. Logging in with verification code..." -ForegroundColor Cyan

        $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession

        $response = Invoke-AgentMeshJson `
            -Method POST `
            -Path "/api/auth/login/code" `
            -WebSession $session `
            -Body @{
                email = $Email
                code  = $code
            }

        Write-Host "Verification-code login succeeded." -ForegroundColor Green

        if ($response.data.user) {
            Write-Host (
                "User: id={0}, email={1}, name={2}" -f `
                    $response.data.user.id, `
                    $response.data.user.email, `
                    $response.data.user.displayName
            )
        }

        Write-Host (
            "Access token TTL: {0}s" -f `
                $response.data.expiresIn
        )
    }

    "reset" {
        $code = Send-Code -Scene "reset_password"

        Write-Host ""
        Write-Host "2. Resetting password..." -ForegroundColor Cyan

        $response = Invoke-AgentMeshJson `
            -Method POST `
            -Path "/api/auth/password/reset" `
            -Body @{
                email       = $Email
                code        = $code
                newPassword = $NewPassword
            }

        Write-Host "Password reset succeeded." -ForegroundColor Green
        Write-Host "All old refresh-token sessions for this account should now be revoked."
    }
}

Write-Host ""
Write-Host "E2E finished." -ForegroundColor Green
