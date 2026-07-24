$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\pythonw.exe"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "The development environment is missing. Run .\scripts\bootstrap.ps1 first."
}

Set-Location -LiteralPath $repositoryRoot
& $pythonExecutable -m local_clip_ai.app.main --data-dir ".local-data"

