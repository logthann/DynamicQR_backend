[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$BaseUrl = "http://127.0.0.1:8000",

    [Parameter(Mandatory = $false)]
    [string]$Endpoint = "/api/v1/ga4/properties",

    [Parameter(Mandatory = $false)]
    [string]$Email,

    [Parameter(Mandatory = $false)]
    [string]$Password,

    [Parameter(Mandatory = $false)]
    [string]$AccessToken,

    [Parameter(Mandatory = $false)]
    [string]$LoginPath = "/api/v1/auth/login",

    [Parameter(Mandatory = $false)]
    [string]$OutDir = ".\\logs",

    [switch]$SkipCertificateCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Join-Url {
    param(
        [string]$Root,
        [string]$Path
    )

    $rootTrimmed = $Root.TrimEnd("/")
    $pathTrimmed = $Path.TrimStart("/")
    return "$rootTrimmed/$pathTrimmed"
}

function Resolve-Token {
    param(
        [string]$Root,
        [string]$Path,
        [string]$ExistingToken,
        [string]$UserEmail,
        [string]$UserPassword
    )

    if (-not [string]::IsNullOrWhiteSpace($ExistingToken)) {
        return $ExistingToken
    }

    if ([string]::IsNullOrWhiteSpace($UserEmail) -or [string]::IsNullOrWhiteSpace($UserPassword)) {
        throw "Provide either -AccessToken, or both -Email and -Password."
    }

    $loginUrl = Join-Url -Root $Root -Path $Path
    $loginBody = @{
        email = $UserEmail
        password = $UserPassword
    } | ConvertTo-Json

    $loginResponse = Invoke-RestMethod -Method Post -Uri $loginUrl -ContentType "application/json" -Body $loginBody
    if ([string]::IsNullOrWhiteSpace($loginResponse.access_token)) {
        throw "Login succeeded but access_token is missing in response."
    }

    return [string]$loginResponse.access_token
}

if ($SkipCertificateCheck) {
    add-type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustEverythingPolicy : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint srvPoint, X509Certificate certificate, WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
    [System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustEverythingPolicy
}

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$token = Resolve-Token -Root $BaseUrl -Path $LoginPath -ExistingToken $AccessToken -UserEmail $Email -UserPassword $Password
$targetUrl = Join-Url -Root $BaseUrl -Path $Endpoint
$headers = @{ Authorization = "Bearer $token" }

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$jsonLogPath = Join-Path -Path $OutDir -ChildPath "api-response-$timestamp.json"
$metaLogPath = Join-Path -Path $OutDir -ChildPath "api-response-$timestamp.txt"

try {
    $response = Invoke-RestMethod -Method Get -Uri $targetUrl -Headers $headers

    $response | ConvertTo-Json -Depth 20 | Out-File -FilePath $jsonLogPath -Encoding utf8

    @(
        "timestamp=$((Get-Date).ToString('o'))"
        "url=$targetUrl"
        "status=success"
        "json_log=$jsonLogPath"
    ) | Out-File -FilePath $metaLogPath -Encoding utf8

    Write-Host "[OK] API response logged"
    Write-Host "  URL: $targetUrl"
    Write-Host "  JSON: $jsonLogPath"
    Write-Host "  META: $metaLogPath"
}
catch {
    $errorMessage = $_.Exception.Message
    $rawBody = $null

    if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $rawBody = $reader.ReadToEnd()
    }

    @(
        "timestamp=$((Get-Date).ToString('o'))"
        "url=$targetUrl"
        "status=failed"
        "error=$errorMessage"
        "response_body=$rawBody"
    ) | Out-File -FilePath $metaLogPath -Encoding utf8

    Write-Host "[ERROR] API request failed"
    Write-Host "  URL: $targetUrl"
    Write-Host "  META: $metaLogPath"
    if ($rawBody) {
        Write-Host "  Response body: $rawBody"
    }

    throw
}

