param(
    [string]$OpenUrl = "http://localhost:3000",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Test-ListeningPort([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-ListeningPort([int]$Port, [int]$TimeoutSeconds = 60) {
    for ($attempt = 0; $attempt -lt $TimeoutSeconds * 2; $attempt++) {
        if (Test-ListeningPort $Port) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Port $Port did not become ready within $TimeoutSeconds seconds."
}

if (-not (Test-ListeningPort 9000)) {
    docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $dockerCandidates = @(
            "D:\DockerDesktop\Docker Desktop.exe",
            "C:\Program Files\Docker\Docker\Docker Desktop.exe",
            (Join-Path $env:LOCALAPPDATA "Docker\Docker Desktop.exe")
        )
        $dockerDesktop = $dockerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $dockerDesktop) {
            throw "Docker Desktop was not found. MinIO is required for plan and 360 images."
        }
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                break
            }
            Start-Sleep -Seconds 1
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Desktop did not become ready."
        }
    }
    & docker compose --env-file (Join-Path $workspace ".env") -f (Join-Path $workspace "infra\compose.yaml") up -d minio
    Wait-ListeningPort 9000
}

if (-not (Test-ListeningPort 8000)) {
    $apiCommand = "Set-Location -LiteralPath '$workspace'; uv run --project apps/api uvicorn progress_api.main:app --app-dir apps/api/src --reload --reload-dir apps/api/src"
    Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile", "-Command", $apiCommand -WorkingDirectory $workspace -WindowStyle Hidden
    Wait-ListeningPort 8000
}

if (-not (Test-ListeningPort 3000)) {
    $webCommand = "Set-Location -LiteralPath '$workspace'; npm run dev:web"
    Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile", "-Command", $webCommand -WorkingDirectory $workspace -WindowStyle Hidden
    Wait-ListeningPort 3000
}

$minioHealth = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:9000/minio/health/live" -TimeoutSec 10
$webHealth = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:3000" -TimeoutSec 10

if (-not $NoBrowser) {
    $chromeCandidates = @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
    )
    $chrome = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($chrome) {
        & $chrome --new-tab $OpenUrl
    } else {
        Start-Process $OpenUrl
    }
}

[pscustomobject]@{
    Web = $webHealth.StatusCode
    API = 8000
    MinIO = $minioHealth.StatusCode
    Url = $OpenUrl
}
