# Local Clip AI

Local Clip AI is a native Windows application for finding promising clips in long
VODs without uploading the recordings to a third-party analysis service.

The first tested Windows beta is available on the beta branch. The native
application checks the local environment, CPU, memory, NVIDIA GPU, portable FFmpeg
installation, storage, and durable SQLite job database. Twitch VOD inspection,
resumable queue processing, CUDA transcription, candidate condensation,
review/export, and resource safeguards are included.

This project is not affiliated with StreamLadder or ClipGPT.

## Intended workflow

1. Drag local Streamlabs recordings or supported VOD links into the application.
2. Queue one or more VODs with reusable content and analysis profiles.
3. Run Quick, Balanced, or Deep analysis locally.
4. Review time-coded candidate moments, or automatically export the preselected clips.
5. Resume safely after cancellation, overheating, or a Windows restart.

## Development setup

The project deliberately targets Python 3.12 because native AI dependencies tend
to adopt new Python releases more slowly than ordinary application libraries.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,transcription,gpu]"
```

Run the command-line diagnostics:

```powershell
.\.venv\Scripts\local-clip-ai.exe --data-dir .local-data diagnose
```

Launch the native application:

```powershell
.\.venv\Scripts\local-clip-ai-gui.exe --data-dir .local-data
```

The convenience scripts perform the same steps:

```powershell
.\scripts\bootstrap.ps1
.\scripts\run.ps1
```

## Windows beta package

Build the self-contained one-folder Windows beta and ZIP archive:

```powershell
.\scripts\build_windows_beta.ps1
```

The packaged app does not require a separate Python installation. On first
launch, use **Settings → Install / repair** to provision verified portable media
tools inside the app's local runtime directory. See
[docs/WINDOWS_BETA.md](docs/WINDOWS_BETA.md) for installation, privacy, recovery,
and Twitch connection details.

## Required external software

- Windows 11
- Python 3.12
- A current NVIDIA display driver
- FFmpeg, ffprobe, and yt-dlp (verified portable builds are bundled in the
  Windows beta and installed repository-locally for source development)
- About 2 GiB for repository-local NVIDIA runtime packages and the Quick model

AI model files, VODs, transcripts, databases, exports, logs, and credentials are
excluded from Git. Runtime data defaults to `%LOCALAPPDATA%\LocalClipAI`. The
native Settings page can independently redirect finished clips and downloaded
Twitch/cache media; the full root can also be selected with `--data-dir` or
`LOCAL_CLIP_AI_DATA_DIR`.

Install or repair the verified portable media tools without changing Windows:

```powershell
.\.venv\Scripts\local-clip-ai.exe --data-dir .local-data install-tools
```

The installer obtains the latest compatible release metadata over HTTPS from the
official BtbN/FFmpeg-Builds and yt-dlp GitHub repositories, validates each asset
against the SHA-256 digest reported by GitHub, and records a local receipt.

The development bootstrap installs NVIDIA's official CUDA 12 cuBLAS and cuDNN 9
Python packages inside `.venv`; it does not install a system CUDA toolkit. Models are
downloaded on first use below the selected runtime data directory.

Run queued jobs from the CLI:

```powershell
.\.venv\Scripts\local-clip-ai.exe --data-dir .local-data add-job `
  "https://www.twitch.tv/videos/2823263031" --mode quick
.\.venv\Scripts\local-clip-ai.exe --data-dir .local-data run-queue
```

Change a completed job's content preference or candidate count without repeating
its download, transcription, or signal scans:

```powershell
.\.venv\Scripts\local-clip-ai.exe --data-dir .local-data `
  rebuild-candidates JOB_ID --max-candidates 50
```

## Repository map

```text
src/local_clip_ai/
  app/          Native PySide6/QML application
  diagnostics/ Hardware and dependency probes
  storage/      Durable SQLite job and stage state
tests/          Fast, hardware-independent tests
scripts/        Windows development helpers
docs/           Architecture and decisions
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the process boundaries and
planned pipeline.
