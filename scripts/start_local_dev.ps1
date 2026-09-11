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

function Test-DockerReady {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
    $ready = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $previousPreference
    return $ready
}

function Move-StaleDockerRuntime([string]$Directory) {
    if (-not (Test-Path -LiteralPath $Directory)) {
        return
    }
    $localAppDataRoot = [IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\') + '\'
    $resolvedDirectory = [IO.Path]::GetFullPath($Directory)
    if (-not $resolvedDirectory.StartsWith($localAppDataRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to move Docker runtime outside LOCALAPPDATA: $resolvedDirectory"
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Move-Item -LiteralPath $resolvedDirectory -Destination "$resolvedDirectory-stale-$stamp"
}

function Repair-StaleDockerRuntime {
    if (Test-DockerReady) {
        return
    }
    $runtimeDirectories = @(
        (Join-Path $env:LOCALAPPDATA "Docker\run"),
        (Join-Path $env:LOCALAPPDATA "docker-secrets-engine")
    )
    $socketPaths = @(
        (Join-Path $runtimeDirectories[0] "sailor-ingest.sock"),
        (Join-Path $runtimeDirectories[1] "engine.sock")
    )
    if (-not ($socketPaths | Where-Object { Test-Path -LiteralPath $_ })) {
        return
    }

    # Docker Desktop can leave inaccessible AF_UNIX reparse points after a
    # crash. Stop only its failed helpers, release WSL, then quarantine the
    # small runtime directories. Images, volumes and project data are outside
    # these paths and are never touched.
    Get-Process -Name "Docker Desktop", "com.docker.backend" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    & wsl.exe --shutdown 2>$null
    foreach ($directory in $runtimeDirectories) {
        Move-StaleDockerRuntime $directory
    }
}

function Ensure-DockerReady {
    if (Test-DockerReady) {
        return
    }

    Repair-StaleDockerRuntime

    $dockerCandidates = @(
        "D:\DockerDesktop\Docker Desktop.exe",
        "C:\Program Files\Docker\Docker\Docker Desktop.exe",
        (Join-Path $env:LOCALAPPDATA "Docker\Docker Desktop.exe")
    )
    $dockerDesktop = $dockerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $dockerDesktop) {
        throw "Docker Desktop was not found. Redis is required for background processing."
    }

    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 180; $attempt++) {
        if (Test-DockerReady) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Docker Desktop did not become ready. Redis and the background worker were not started."
}

function Get-DotEnvValue([string]$Name) {
    $envFile = Join-Path $workspace ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        return $null
    }
    $prefix = "$Name="
    $line = Get-Content -LiteralPath $envFile |
        Where-Object { $_.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) } |
        Select-Object -First 1
    if (-not $line) {
        return $null
    }
    return $line.Substring($prefix.Length).Trim().Trim('"').Trim("'")
}

function Find-NativeMinio {
    $command = Get-Command minio.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") `
        -Directory -Filter "MinIO.Server_*" -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -File -Filter "minio.exe" -ErrorAction SilentlyContinue } |
        Select-Object -ExpandProperty FullName -First 1
}

function Start-NativeMinio {
    $minio = Find-NativeMinio
    if (-not $minio) {
        return $false
    }
    $dataPath = Get-DotEnvValue "MINIO_DATA_PATH"
    if (-not $dataPath) {
        $dataPath = "C:\ProgressConstructionData\minio"
    }
    New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
    $logDirectory = Join-Path $workspace ".runtime-logs"
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $minioCommand = "`$env:MINIO_ROOT_USER='progress'; `$env:MINIO_ROOT_PASSWORD='change-this-minio-password'; & '$minio' server '$dataPath' --address ':9000' --console-address ':9001'"
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-Command", $minioCommand `
        -WorkingDirectory $workspace `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory "minio-native.stdout.log") `
        -RedirectStandardError (Join-Path $logDirectory "minio-native.stderr.log")
    return $true
}

function Find-NativeRedis {
    $command = Get-Command redis-server.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return Get-ChildItem -LiteralPath (Join-Path $workspace ".runtime") `
        -Directory -Filter "redis-windows-*" -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Filter "redis-server.exe" -ErrorAction SilentlyContinue } |
        Sort-Object FullName -Descending |
        Select-Object -ExpandProperty FullName -First 1
}

function Start-NativeRedis {
    $redis = Find-NativeRedis
    if (-not $redis) {
        return $false
    }
    $logDirectory = Join-Path $workspace ".runtime-logs"
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    Start-Process -FilePath $redis `
        -ArgumentList "--bind", "127.0.0.1", "--port", "6379", "--save", '""', "--appendonly", "no" `
        -WorkingDirectory (Split-Path -Parent $redis) `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory "redis.stdout.log") `
        -RedirectStandardError (Join-Path $logDirectory "redis.stderr.log")
    return $true
}

function Test-VideoWorker {
    $workerProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
        $_.CommandLine -match "celery" -and $_.CommandLine -match "progress_api\.worker"
    })
    if ($workerProcesses.Count -eq 0) {
        return $false
    }

    $apiPython = @(
        (Join-Path $workspace ".venv\Scripts\python.exe"),
        (Join-Path $workspace "apps\api\.venv\Scripts\python.exe")
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $apiPython) {
        return $false
    }

    # A process can survive a Redis/Docker restart while its broker connection
    # is dead. Require a real Celery response before declaring it healthy.
    $previousPythonPath = $env:PYTHONPATH
    $previousPreference = $ErrorActionPreference
    $env:PYTHONPATH = Join-Path $workspace "apps\api\src"
    $ErrorActionPreference = "Continue"
    & $apiPython -m celery -A progress_api.worker:celery_app inspect ping --timeout 5 2>$null | Out-Null
    $ready = $LASTEXITCODE -eq 0
    $env:PYTHONPATH = $previousPythonPath
    $ErrorActionPreference = $previousPreference
    return $ready
}

function Stop-StaleVideoWorkers {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
        $_.CommandLine -match "celery" -and $_.CommandLine -match "progress_api\.worker"
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Start-DockerLocalizationEngine {
    if ((Get-DotEnvValue "LOCALIZATION_ENGINE") -ne "stella_vslam") {
        return
    }
    Ensure-DockerReady
}

if (-not (Test-ListeningPort 9000)) {
    if (-not (Start-NativeMinio)) {
        Ensure-DockerReady
        & docker compose --env-file (Join-Path $workspace ".env") -f (Join-Path $workspace "infra\compose.yaml") up -d minio
    }
    Wait-ListeningPort 9000
}

if (-not (Test-ListeningPort 6379)) {
    if (-not (Start-NativeRedis)) {
        Ensure-DockerReady
        & docker compose --env-file (Join-Path $workspace ".env") -f (Join-Path $workspace "infra\compose.yaml") up -d redis
    }
    Wait-ListeningPort 6379
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

if (-not (Test-VideoWorker)) {
    Stop-StaleVideoWorkers
    $apiPython = @(
        (Join-Path $workspace ".venv\Scripts\python.exe"),
        (Join-Path $workspace "apps\api\.venv\Scripts\python.exe")
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $apiPython) {
        throw "Python environment was not found. Run uv sync before starting the worker."
    }
    $apiSource = Join-Path $workspace "apps\api\src"
    $logDirectory = Join-Path $workspace ".runtime-logs"
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    # Keep the worker at the repository root so relative SQLite and runtime
    # paths resolve to the same files as the API.  Starting it from apps/api/src
    # silently created a second empty progress-dev.db and stranded every job.
    # The solo pool can reach the Redis "ready" state on Windows while never
    # consuming queued work. A single-thread pool keeps video jobs serialized,
    # supports Celery health checks, and has proven reliable on this host.
    $workerCommand = "Set-Location -LiteralPath '$workspace'; `$env:PYTHONPATH = '$apiSource'; & '$apiPython' -m celery -A progress_api.worker:celery_app worker -Q video_cpu --pool=threads --concurrency=1 --without-mingle --without-gossip --without-heartbeat --hostname progress360-worker@%h --loglevel=INFO"
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-Command", $workerCommand `
        -WorkingDirectory $workspace `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory "worker.stdout.log") `
        -RedirectStandardError (Join-Path $logDirectory "worker.stderr.log")

    $workerReady = $false
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        Start-Sleep -Seconds 2
        if (Test-VideoWorker) {
            $workerReady = $true
            break
        }
    }
    if (-not $workerReady) {
        throw "Background video worker started but did not answer its health check."
    }
}

Start-DockerLocalizationEngine

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
    Redis = 6379
    Worker = "video_cpu"
    Url = $OpenUrl
}
