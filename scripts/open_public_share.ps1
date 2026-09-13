param(
    [switch]$CopyOnly
)

$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcher = Join-Path $PSScriptRoot "start_public_share.ps1"
$latestUrlFile = Join-Path $workspace ".runtime-logs\latest-public-url.txt"

try {
    & $launcher -DelaySeconds 0

    if (-not (Test-Path -LiteralPath $latestUrlFile)) {
        throw "Public link was not created."
    }

    $baseUrl = (Get-Content -LiteralPath $latestUrlFile -Raw).Trim().TrimEnd("/")
    if ($baseUrl -notmatch '^https://[a-z0-9-]+\.trycloudflare\.com$') {
        throw "Public link has an unexpected format."
    }

    $loginUrl = "$baseUrl/login"
    $response = Invoke-WebRequest -UseBasicParsing -Uri $loginUrl -TimeoutSec 20
    if ($response.StatusCode -ne 200) {
        throw "Public website is not ready (HTTP $($response.StatusCode))."
    }

    Set-Clipboard -Value $loginUrl
    if (-not $CopyOnly) {
        Start-Process $loginUrl
    }
} catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "เปิดเว็บไซต์ไม่สำเร็จ: $($_.Exception.Message)",
        "Progress Construction 360"
    ) | Out-Null
    exit 1
}
