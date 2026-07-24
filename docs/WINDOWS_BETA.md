# Local Clip AI Windows Beta

## Install and first launch

1. Extract the entire `LocalClipAI-Windows-Beta.zip` folder. Do not run the
   executable from inside the ZIP.
2. Launch `LocalClipAI.exe`. The beta is not code-signed yet, so Windows may
   show a SmartScreen warning.
3. Open **Diagnostics** and confirm that the required checks pass. Verified
   portable FFmpeg, ffprobe, and yt-dlp builds are included in the Windows ZIP,
   so a clean extraction does not require a separate media-tool installation.
4. If those bundled files are damaged or removed, open **Settings** and select
   **Install / repair**. Local Clip AI downloads fresh copies from the official
   GitHub releases, verifies GitHub's SHA-256 digests, and installs them only
   inside Local Clip AI's runtime directory.

Python, a system CUDA toolkit, and system-wide FFmpeg are not required by the
packaged beta. A current NVIDIA display driver is required for GPU acceleration.

## Analyze a VOD

1. Paste a public Twitch VOD URL, or drag one or more Streamlabs recording files
   into the Queue page.
2. Choose Quick, Balanced, or Deep and optionally reuse the previous content
   preference, analysis mode, or both.
3. Start the queue. The app prevents Windows sleep while the queue is active.
   Download, transcription, audio, and scene stages report incremental progress.
4. The newest VOD opens automatically on the Results page. Review its candidates.
   **Preview** downloads a source section at up to 720p, builds the exact proposed
   multi-span cut, and starts playback automatically.
5. Select **Export auto** on a VOD to export every unexported preselected candidate,
   or export candidates individually. By default the app performs this batch export
   after the full queue finishes; Settings can disable it. Finished clips are stored
   below a `VOD title [Twitch ID]` folder.

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

Settings exposes two independent locations:

- **Export folder** stores finished MP4 clips. Changing it affects new exports and
  never moves old clips. **Previous** opens folders containing completed older clips.
- **Download/cache folder** stores future Twitch analysis downloads and the temporary
  source-quality sections used for preview/export. Existing durable checkpoints stay
  in their original locations.

## Safety and recovery

- Transcription checkpoints every 15 minutes with five-second overlap.
- Pause/cancel preserves completed analysis stages.
- Interrupted running jobs recover after a Windows/app crash.
- Configurable GPU/CPU temperature grace and cooldown limits.
- CUDA allocation failures retry the affected transcription chunk on CPU.
- Packaged transcription workers force UTF-8 output, so arbitrary multilingual
  Whisper text cannot crash on a Windows legacy code page.
- The windowed GUI initializes safe standard streams for local AI libraries that
  emit progress output even when no console is attached.
- The package includes Qt's FFmpeg and Windows multimedia backends. Its build gate
  decodes a real H.264/AAC video, receives a frame, and verifies playback advances.
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

The script installs or verifies the repository-local portable tools, runs
lint/tests, builds a PyInstaller one-folder app, runs strict diagnostics against
a completely clean runtime directory, creates
`dist\LocalClipAI-Windows-Beta.zip`, and writes its SHA-256 checksum. Build
outputs and all runtime data are ignored by Git.
