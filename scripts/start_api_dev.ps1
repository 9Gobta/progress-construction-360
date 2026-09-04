$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$apiSource = Join-Path $projectRoot "apps\api\src"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python environment not found: $python"
}
if (-not (Test-Path -LiteralPath $apiSource -PathType Container)) {
    throw "API source directory not found: $apiSource"
}

& $python -m uvicorn progress_api.main:app `
    --app-dir $apiSource `
    --reload `
    --reload-dir $apiSource `
    --host 127.0.0.1 `
    --port 8000
