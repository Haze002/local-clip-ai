# Local Clip AI Windows Beta

## Install and first launch

1. Extract the entire `LocalClipAI-Windows-Beta.zip` folder. Do not run the
   executable from inside the ZIP.
2. Launch `LocalClipAI.exe`. The beta is not code-signed yet, so Windows may
   show a SmartScreen warning.
3. Open **Settings** and select **Install / repair** under Portable Media Tools.
   Local Clip AI downloads FFmpeg, ffprobe, and yt-dlp from their official
   GitHub releases, verifies GitHub's SHA-256 digests, and installs them only
   inside Local Clip AI's runtime directory.
4. Open **Diagnostics** and confirm that the required checks pass.

Python, a system CUDA toolkit, and system-wide FFmpeg are not required by the
packaged beta. A current NVIDIA display driver is required for GPU acceleration.

## Analyze a VOD

1. Paste a public Twitch VOD URL, or drag one or more Streamlabs recording files
   into the Queue page.
2. Choose Quick, Balanced, or Deep and optionally reuse the previous content
   preference, analysis mode, or both.
3. Start the queue. The app prevents Windows sleep while the queue is active.
   Download, transcription, audio, and scene stages report incremental progress.
4. Review candidates on the Results page. **Preview** builds and plays the exact
   proposed multi-span cut; **Export** retrieves source-quality Twitch media when
   necessary.

Quick uses local Whisper small, audio peaks, and semantic preference matching.
Balanced uses Whisper large-v3-turbo plus scene activity. Deep adds denser scene
signals and candidate-only CLIP visual reranking. Models download on first use
and remain local. The default profile keeps up to 50 review candidates and
preselects the highest-scoring 10; both values are editable.

## Twitch latest-VOD connection

Manual VOD links work without a Twitch developer application. For one-click
latest-VOD queueing:

1. Create a Twitch developer application with **Public** client type.
2. Paste its Client ID and optional channel login under Settings.
3. Select **Connect Twitch**, open the activation page, and enter the displayed
   device code.

Tokens are stored only in Windows Credential Manager. No client secret is used.

## Local data and privacy

Runtime data defaults to:

`%LOCALAPPDATA%\LocalClipAI`

This directory contains tools, models, VOD media, transcripts, the SQLite queue,
logs, previews, and exports. None of it is uploaded to the Local Clip AI GitHub
repository. AI inference runs on the local computer; network access is used for
Twitch media/API requests and first-time tool/model downloads.

## Safety and recovery

- Transcription checkpoints every 15 minutes with five-second overlap.
- Pause/cancel preserves completed analysis stages.
- Interrupted running jobs recover after a Windows/app crash.
- Configurable GPU/CPU temperature grace and cooldown limits.
- CUDA allocation failures retry the affected transcription chunk on CPU.
- Long repetitive one/two-word music hallucinations are filtered before ranking.
- Export and preview preparation are cancellable; incomplete export files are
  removed.

CPU package temperature may show unavailable on Windows systems that do not
expose a supported sensor interface. GPU monitoring and GPU thermal protection
remain active.

## Build from source

From a bootstrapped checkout:

```powershell
.\scripts\build_windows_beta.ps1
```

The script runs lint/tests, builds a PyInstaller one-folder app, creates
`dist\LocalClipAI-Windows-Beta.zip`, and writes its SHA-256 checksum. Build
outputs and all runtime data are ignored by Git.
