param(
    [string]$DockerPath = "",
    [int]$BuildThreads = 4
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeRoot = Join-Path $repositoryRoot ".runtime\stella"
$sourceRoot = Join-Path $runtimeRoot "source"
$vocabularyPath = Join-Path $runtimeRoot "orb_vocab.fbow"
$imageName = "progress-stella-vslam:0.7.0"

if (-not $DockerPath) {
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerCommand) {
        $DockerPath = $dockerCommand.Source
    } elseif (Test-Path -LiteralPath "D:\DockerDesktop\resources\bin\docker.exe") {
        $DockerPath = "D:\DockerDesktop\resources\bin\docker.exe"
    } elseif (Test-Path -LiteralPath "C:\Program Files\Docker\Docker\resources\bin\docker.exe") {
        $DockerPath = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    } else {
        throw "Docker CLI not found. Start Docker Desktop or pass -DockerPath."
    }
}

# Docker Desktop can be installed outside Program Files. BuildKit launches the
# credential helper by name, so the directory containing docker.exe must also
# be visible through PATH for image pulls.
$dockerBinDirectory = Split-Path -Parent $DockerPath
if (($env:PATH -split ";") -notcontains $dockerBinDirectory) {
    $env:PATH = "$dockerBinDirectory;$env:PATH"
}

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot ".git"))) {
    git clone --branch 0.7.0 --depth 1 --recursive `
        https://github.com/stella-cv/stella_vslam.git $sourceRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not clone stella_vslam 0.7.0." }
} else {
    git -C $sourceRoot submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) { throw "Could not update stella_vslam submodules." }
}

if (-not (Test-Path -LiteralPath $vocabularyPath)) {
    Invoke-WebRequest -UseBasicParsing `
        "https://github.com/stella-cv/FBoW_orb_vocab/raw/main/orb_vocab.fbow" `
        -OutFile $vocabularyPath
}

& $DockerPath build `
    --tag $imageName `
    --file (Join-Path $sourceRoot "Dockerfile.socket") `
    --build-arg "NUM_THREADS=$BuildThreads" `
    $sourceRoot
if ($LASTEXITCODE -ne 0) { throw "Stella Docker image build failed." }

& $DockerPath image inspect $imageName --format "{{.Id}}"
if ($LASTEXITCODE -ne 0) { throw "Stella Docker image is not available after build." }

Write-Host "Stella is ready: $imageName"
Write-Host "Vocabulary: $vocabularyPath"
