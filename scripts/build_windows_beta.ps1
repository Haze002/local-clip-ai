param(
    [switch]$SkipTests,
    [switch]$SkipArchive
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$specFile = Join-Path $repositoryRoot "packaging\local_clip_ai.spec"
$applicationDirectory = Join-Path $repositoryRoot "dist\LocalClipAI"
$archivePath = Join-Path $repositoryRoot "dist\LocalClipAI-Windows-Beta.zip"
$checksumPath = "$archivePath.sha256"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "The development environment is missing. Run .\scripts\bootstrap.ps1 first."
}

Set-Location -LiteralPath $repositoryRoot
& $pythonExecutable -m pip install -e ".[dev,transcription,gpu,packaging]"

if (-not $SkipTests) {
    & $pythonExecutable -m ruff check .
    & $pythonExecutable -m pytest -q
}

& $pythonExecutable -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath (Join-Path $repositoryRoot "dist") `
    --workpath (Join-Path $repositoryRoot "build\pyinstaller") `
    $specFile

if (-not (Test-Path -LiteralPath (Join-Path $applicationDirectory "LocalClipAI.exe"))) {
    throw "PyInstaller completed without producing LocalClipAI.exe."
}

if (-not $SkipArchive) {
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    Compress-Archive -Path (Join-Path $applicationDirectory "*") `
        -DestinationPath $archivePath `
        -CompressionLevel Optimal
    $checksum = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLower()
    Set-Content -LiteralPath $checksumPath -Value "$checksum  LocalClipAI-Windows-Beta.zip"
}

Write-Host ""
Write-Host "Windows beta build complete:"
Write-Host "  $applicationDirectory"
if (-not $SkipArchive) {
    Write-Host "  $archivePath"
    Write-Host "  $checksumPath"
}
