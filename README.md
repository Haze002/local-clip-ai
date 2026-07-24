# Local Clip AI

Local Clip AI is a native Windows application for finding promising clips in long
VODs without uploading the recordings to a third-party analysis service.

The project is currently building toward its first Windows beta. The native
application already checks the local Python environment, CPU, memory, NVIDIA GPU,
portable FFmpeg installation, storage, and durable SQLite job database. Twitch
VOD inspection and timestamp-range download primitives are under active development.

This project is not affiliated with StreamLadder or ClipGPT.

## Intended workflow

1. Drag local Streamlabs recordings or supported VOD links into the application.
2. Queue one or more VODs with reusable content and analysis profiles.
3. Run Quick, Balanced, or Deep analysis locally.
4. Review time-coded candidate moments and export selected clips.
5. Resume safely after cancellation, overheating, or a Windows restart.

## Development setup

The project deliberately targets Python 3.12 because native AI dependencies tend
to adopt new Python releases more slowly than ordinary application libraries.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
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

## Required external software

- Windows 11
- Python 3.12
- A current NVIDIA display driver
- FFmpeg and ffprobe (a verified portable build is installed locally by the bootstrap)
- CUDA 12 and cuDNN 9 when the transcription worker is enabled

AI model files, VODs, transcripts, databases, exports, logs, and credentials are
excluded from Git. Runtime data defaults to `%LOCALAPPDATA%\LocalClipAI`, and a
different directory can be selected with `--data-dir` or
`LOCAL_CLIP_AI_DATA_DIR`.

Install or repair the verified portable media tools without changing Windows:

```powershell
.\.venv\Scripts\local-clip-ai.exe --data-dir .local-data install-tools
```

The installer obtains the latest compatible release metadata over HTTPS from the
official BtbN/FFmpeg-Builds and yt-dlp GitHub repositories, validates each asset
against the SHA-256 digest reported by GitHub, and records a local receipt.

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
