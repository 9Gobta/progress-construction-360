param(
    [ValidateRange(0, 300)]
    [int]$DelaySeconds = 30,
    [switch]$SkipLocalServices
)

$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDirectory = Join-Path $workspace ".runtime-logs"
$startupLog = Join-Path $logDirectory "auto-start.log"
$latestUrlFile = Join-Path $logDirectory "latest-public-url.txt"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Write-StartupLog([string]$Message) {
    Add-Content -LiteralPath $startupLog -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message" -Encoding UTF8
}

try {
    # Let start_local_dev.ps1 handle stale Docker runtime directories. A stale
    # AF_UNIX reparse point cannot always be removed while Docker/WSL still owns
    # it, and retrying the individual socket here only delays public startup.
    $staleDockerSocket = Join-Path $env:LOCALAPPDATA "Docker\run\sailor-ingest.sock"
    if (-not $SkipLocalServices -and (Test-Path -LiteralPath $staleDockerSocket)) {
        Write-StartupLog "Detected stale Docker socket; delegating safe runtime repair to local startup."
    }
    if ($DelaySeconds -gt 0) {
        Start-Sleep -Seconds $DelaySeconds
    }
    if (-not $SkipLocalServices) {
        Write-StartupLog "Starting local services."
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $localStdoutLog = Join-Path $logDirectory "local-start-$stamp.stdout.log"
        $localStderrLog = Join-Path $logDirectory "local-start-$stamp.stderr.log"
        $localLauncher = Join-Path $PSScriptRoot "start_local_dev.ps1"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $localLauncher -NoBrowser 1> $localStdoutLog 2> $localStderrLog
        $localExitCode = $LASTEXITCODE
        if ($localExitCode -ne 0) {
            $failure = Get-Content -LiteralPath $localStderrLog -Raw -ErrorAction SilentlyContinue
            throw "Local services failed to start (exit $localExitCode). $($failure.Trim())"
        }
        $localStatus = Get-Content -LiteralPath $localStdoutLog -Raw -ErrorAction SilentlyContinue
        Write-StartupLog ($localStatus.Trim())
    } else {
        Write-StartupLog "Local services check skipped; ensuring public Tunnel only."
    }

    $tunnelProcess = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "tunnel\s+--url\s+http://127\.0\.0\.1:3000" } |
        Select-Object -First 1

    if ($tunnelProcess) {
        $knownUrl = $null
        $knownUrlLog = Get-ChildItem -LiteralPath $logDirectory -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^cloudflared.*\.(err|stderr)\.log$' -or $_.Name -eq 'cloudflared.err.log' } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($knownUrlLog) {
            $knownUrlMatch = Select-String -LiteralPath $knownUrlLog.FullName -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches -ErrorAction SilentlyContinue |
                Select-Object -Last 1
            if ($knownUrlMatch) {
                $knownUrl = $knownUrlMatch.Matches[-1].Value
            }
        }
        $tunnelHealthy = $false
        if ($knownUrl) {
            try {
                $healthResponse = Invoke-WebRequest -UseBasicParsing -Uri "$knownUrl/login" -TimeoutSec 10
                $tunnelHealthy = $healthResponse.StatusCode -eq 200
            } catch {
                $tunnelHealthy = $false
            }
        }
        if (-not $tunnelHealthy) {
            Write-StartupLog "Existing Quick Tunnel is unhealthy; replacing PID $($tunnelProcess.ProcessId)."
            Stop-Process -Id $tunnelProcess.ProcessId -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            $tunnelProcess = $null
        }
    }

    $startedNewTunnel = $false
    if (-not $tunnelProcess) {
        $cloudflared = (Get-Command cloudflared.exe -ErrorAction Stop).Source
        $tunnelStamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $stdoutLog = Join-Path $logDirectory "cloudflared-$tunnelStamp.stdout.log"
        $stderrLog = Join-Path $logDirectory "cloudflared-$tunnelStamp.stderr.log"
        $sourceLog = $stderrLog
        Start-Process -FilePath $cloudflared `
            -ArgumentList "tunnel", "--url", "http://127.0.0.1:3000", "--no-autoupdate" `
            -WorkingDirectory $workspace `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog
        $startedNewTunnel = $true
        Write-StartupLog "Started a new Quick Tunnel."
    } else {
        Write-StartupLog "Quick Tunnel is already running (PID $($tunnelProcess.ProcessId))."
    }

    $publicUrl = $null
    for ($attempt = 0; $attempt -lt 60 -and -not $publicUrl; $attempt++) {
        $tunnelLogs = if ($startedNewTunnel) {
            Get-Item -LiteralPath $sourceLog -ErrorAction SilentlyContinue
        } else {
            Get-ChildItem -LiteralPath $logDirectory -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '^cloudflared.*\.(err|stderr)\.log$' -or $_.Name -eq 'cloudflared.err.log' } |
                Sort-Object LastWriteTime -Descending
        }
        foreach ($log in $tunnelLogs) {
            $match = Select-String -LiteralPath $log.FullName -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches -ErrorAction SilentlyContinue |
                Select-Object -Last 1
            if ($match) {
                $publicUrl = $match.Matches[-1].Value
                break
            }
        }
        if (-not $publicUrl) {
            Start-Sleep -Seconds 1
        }
    }

    if ($publicUrl) {
        Set-Content -LiteralPath $latestUrlFile -Value $publicUrl -Encoding UTF8
        Write-StartupLog "Public URL: $publicUrl"
    } else {
        Write-StartupLog "Services started, but the public URL was not found in the Tunnel log."
    }
} catch {
    Write-StartupLog "FAILED: $($_.Exception.Message)"
    exit 1
}
