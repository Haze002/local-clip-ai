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
$packageSmokeRuntime = Join-Path $repositoryRoot "build\package-smoke-runtime"
$unicodeSmokeOutput = Join-Path $repositoryRoot "build\package-unicode-smoke.stdout.txt"
$unicodeSmokeError = Join-Path $repositoryRoot "build\package-unicode-smoke.stderr.txt"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "The development environment is missing. Run .\scripts\bootstrap.ps1 first."
}

Set-Location -LiteralPath $repositoryRoot
& $pythonExecutable -m pip install -e ".[dev,transcription,gpu,packaging]"
if ($LASTEXITCODE -ne 0) {
    throw "Dependency preparation failed."
}

if (-not $SkipTests) {
    & $pythonExecutable -m ruff check .
    if ($LASTEXITCODE -ne 0) {
        throw "Ruff validation failed."
    }
    & $pythonExecutable -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Test validation failed."
    }
}

& $pythonExecutable -m local_clip_ai --data-dir ".local-data" install-tools
if ($LASTEXITCODE -ne 0) {
    throw "Portable media-tool preparation failed."
}

& $pythonExecutable -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath (Join-Path $repositoryRoot "dist") `
    --workpath (Join-Path $repositoryRoot "build\pyinstaller") `
    $specFile
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed."
}

if (-not (Test-Path -LiteralPath (Join-Path $applicationDirectory "LocalClipAI.exe"))) {
    throw "PyInstaller completed without producing LocalClipAI.exe."
}

$requiredBundledExecutables = @(
    (Join-Path $applicationDirectory "_internal\bundled_tools\ffmpeg\bin\ffmpeg.exe"),
    (Join-Path $applicationDirectory "_internal\bundled_tools\ffmpeg\bin\ffprobe.exe"),
    (Join-Path $applicationDirectory "_internal\bundled_tools\yt-dlp\yt-dlp.exe")
)
foreach ($requiredExecutable in $requiredBundledExecutables) {
    if (-not (Test-Path -LiteralPath $requiredExecutable)) {
        throw "The package is missing a bundled media tool: $requiredExecutable"
    }
}

if (Test-Path -LiteralPath $packageSmokeRuntime) {
    Remove-Item -LiteralPath $packageSmokeRuntime -Recurse -Force
}
$diagnosticProcess = Start-Process `
    -FilePath (Join-Path $applicationDirectory "LocalClipAI.exe") `
    -ArgumentList @(
        "--worker-cli",
        "--data-dir",
        "`"$packageSmokeRuntime`"",
        "diagnose",
        "--strict"
    ) `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
if ($diagnosticProcess.ExitCode -ne 0) {
    throw "Packaged diagnostics failed against a clean runtime directory."
}
if (-not (Test-Path -LiteralPath $packageSmokeRuntime)) {
    throw "Packaged diagnostics did not initialize the clean runtime directory."
}
if (Get-ChildItem -LiteralPath $packageSmokeRuntime -Recurse -Filter "ffmpeg.exe") {
    throw "Clean-runtime validation unexpectedly installed FFmpeg outside the package."
}

foreach ($smokeFile in @($unicodeSmokeOutput, $unicodeSmokeError)) {
    if (Test-Path -LiteralPath $smokeFile) {
        Remove-Item -LiteralPath $smokeFile -Force
    }
}
$unicodeProcess = Start-Process `
    -FilePath (Join-Path $applicationDirectory "LocalClipAI.exe") `
    -ArgumentList @("--worker-cli", "_unicode-smoke") `
    -RedirectStandardOutput $unicodeSmokeOutput `
    -RedirectStandardError $unicodeSmokeError `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
if ($unicodeProcess.ExitCode -ne 0) {
    throw "Packaged Unicode worker smoke test exited with code $($unicodeProcess.ExitCode)."
}
$unicodeBytes = [System.IO.File]::ReadAllBytes($unicodeSmokeOutput)
$unicodeHex = ($unicodeBytes | ForEach-Object { $_.ToString("x2") }) -join ""
$expectedUnicodeHex = "e697a5e69cace8aa9e20e4b88b"
if (-not $unicodeHex.Contains($expectedUnicodeHex)) {
    throw "Packaged Unicode worker smoke test did not preserve non-locale text."
}

$guiStdioProcess = Start-Process `
    -FilePath (Join-Path $applicationDirectory "LocalClipAI.exe") `
    -ArgumentList @("--frozen-gui-stdio-smoke") `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
if ($guiStdioProcess.ExitCode -ne 0) {
    throw "Packaged no-console GUI stream smoke test failed."
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
