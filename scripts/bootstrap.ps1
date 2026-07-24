$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$virtualEnvironment = Join-Path $repositoryRoot ".venv"
$pythonExecutable = Join-Path $virtualEnvironment "Scripts\python.exe"

Set-Location -LiteralPath $repositoryRoot

if (Test-Path -LiteralPath $pythonExecutable) {
    & $pythonExecutable -m pip --version *> $null
    $environmentIsReady = $LASTEXITCODE -eq 0
} else {
    $environmentIsReady = $false
}

if (-not $environmentIsReady) {
    $venvArguments = @("-3.12", "-m", "venv")
    if (Test-Path -LiteralPath $virtualEnvironment) {
        $venvArguments += "--clear"
    }
    $venvArguments += $virtualEnvironment
    & py @venvArguments
}

& $pythonExecutable -m pip install --upgrade pip
& $pythonExecutable -m pip install -e ".[dev]"
& $pythonExecutable -m local_clip_ai --data-dir ".local-data" diagnose

Write-Host ""
Write-Host "Bootstrap complete."
Write-Host "Launch the app with: .\scripts\run.ps1"
