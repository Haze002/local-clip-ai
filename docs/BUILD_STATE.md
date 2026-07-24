# Build State

This file is the durable handoff ledger for the autonomous Windows beta build.
Update it whenever a milestone is completed or a material blocker changes.

## Current checkpoint

- Branch: `agent/end-to-end-build`
- Phase: Milestones 1-2 complete; Milestones 3-5 substantially implemented
- Last updated: 2026-07-24
- GitHub media/model state: clean by design; all runtime artifacts remain ignored

## Completed

### Milestone 0 - foundation

- Native PySide6/QML application shell and diagnostics page.
- Python 3.12 project and Windows helper scripts.
- SQLite WAL queue database with durable per-stage JSON checkpoints.
- Hardware diagnostics for the Ryzen 9 5950X, 64 GiB RAM, and RTX 5070 12 GiB.
- Continuous integration for lint and hardware-independent tests.

### Milestone 1 - reproducible media and Twitch foundation

- Added a repository-local tool installer for FFmpeg 8.1 LGPL shared and yt-dlp.
- Tools are fetched from their official GitHub release repositories and verified
  using GitHub-provided SHA-256 digests before installation.
- Added portable-tool discovery to diagnostics; no system-wide installation is needed.
- Added strict Twitch VOD URL parsing and metadata inspection.
- Added partial timestamp-range command generation with FFmpeg keyframe cuts.
- Added timecode parsing/formatting and a versioned calibration manifest containing
  only the supplied public VOD URLs and timestamp labels.
- Confirmed both calibration VODs are currently reachable:
  - `2816862211`: ARAM VOD, 16,554 seconds
  - `2823263031`: Minecraft VOD, 7,113 seconds
- Local runtime receipts, downloaded executables, media, and all future derived data
  live below `.local-data/` and are excluded from Git.

### Milestone 2 - durable queue and acquisition

- Added transactional migrations through schema 3 for sources, independently reusable
  content/analysis profiles, artifacts, candidates, multi-span decisions, exports,
  application settings, pause/cancel flags, progress, and recovery state.
- Added resumable whole-VOD analysis acquisition and timestamp-range source acquisition.
  Quick uses Twitch `Audio_Only`; Balanced/Deep retain a 360p analysis stream and fetch
  source-quality video only for exports.
- Added the native queue UI with link paste, multi-file drag/drop, Quick/Balanced/Deep,
  none/content/analysis/both reuse, Start Queue, pause, resume, cancel, and progress.
- Added restart recovery and completed-stage reuse.
- Added an optional Twitch device-code connection using the official Helix API.
  The public application Client ID and preferred channel are stored in local SQLite;
  access/refresh tokens are stored only in Windows Credential Manager through keyring.
- Added one-click latest archived VOD lookup and queueing from the native application.
  A user-created public Twitch application Client ID is still required for the live
  connection test.

## In progress

### Milestone 3 - local analysis and intelligent clips

- Installed faster-whisper 1.2.1 and CTranslate2 4.8.1 with NVIDIA's official local
  CUDA 12 cuBLAS and cuDNN 9 packages.
- Confirmed the RTX 5070 supports CUDA float16 and mixed int8/float16 inference.
- Transcription runs in a disposable child process so its CUDA context is released when
  the stage completes or is cancelled.
- Long media is transcribed in independently durable 15-minute chunks with five-second
  boundary overlap. Valid chunks are reused after a crash or cancellation, overlap
  duplicates are removed, and the combined transcript is written atomically.
- Confirmed with the real Twitch calibration media that faster-whisper preserves
  absolute source timestamps for internal clip ranges.
- Added FFmpeg audio-energy and sudden-rise measurement in one-second windows. Audio
  evidence is persisted as its own reusable artifact and now contributes to candidate
  scoring, including reactions that speech-only analysis could miss.
- Quick now uses transcript, audio, and local semantic evidence without downloading
  video frames. Balanced adds one-frame-per-second low-resolution scene-change evidence.
  Deep samples visual activity twice as densely and performs candidate-only visual
  reranking.
- Added the 67 MB `BAAI/bge-small-en-v1.5` FastEmbed model for local semantic matching
  between editable content preferences and timestamped transcript passages.
- Added paired local CLIP text/image models for Deep candidate-only visual preference
  reranking. Only a few frames from the provisional top candidates are embedded; whole
  VODs are not passed through the heavier visual model.
- CUDA library/allocation/out-of-memory failures that occur before a chunk produces
  output automatically retry that chunk on CPU. The fallback is covered by a simulated
  CUDA OOM test and does not discard previous chunks.
- Added transcript reaction/content scoring, up-to-three-minute event grouping,
  automatic preselection, and chronological multi-span condensation.
- Added candidate review and source-quality FFmpeg/NVENC export.
- Real local validation completed on the supplied `00:14:50-00:15:20` moment:
  - exact 30.021-second Twitch audio acquisition;
  - Quick GPU transcription into three timestamped segments;
  - one automatically preselected candidate from the real queue pipeline;
  - two separated five-second source spans exported as a validated 10.00-second MP4.
- Re-ran the complete durable queue after chunking/audio integration: acquisition,
  chunk transcription, atomic merge, audio analysis, and candidate selection all
  completed with their expected local database checkpoints and artifacts.
- Completed a real Deep-mode end-to-end run on the calibration media using the RTX 5070:
  Whisper `large-v3-turbo` ran with CUDA float16, five dense visual windows were found,
  local semantic evidence was saved, CLIP candidate frames were reranked, and the job
  completed with every expected artifact.

### Milestone 4 - native workflow and preferences

- Added editable default content preference, language, duration, candidate count, and
  automatic-preselection settings.
- Results can be selected, rejected, or exported; all state remains in local SQLite.
- Added Material dark styling, system tray behavior, and completion/export notifications.

### Milestone 5 - resource and interruption safety

- Added a show/hide compact monitor plus a full monitor page for total/app CPU, CPU clock
  and cores, RAM, process I/O, GPU utilization/temperature/clocks/power, total VRAM, and
  app-plus-worker VRAM.
- Added persisted GPU/CPU temperature limits, sustained grace period, lower resume
  temperature, cooldown stability, and VRAM soft limit.
- Defaults implement the requested behavior: 90 °C pause limit, 120-second grace,
  82 °C resume point, and 30-second stable cooldown.
- Added Windows sleep inhibition only while the queue runner is active.
- CPU package temperature is shown when the operating system exposes it; it is marked
  unavailable on the current Ryzen/Windows configuration rather than displaying a false
  ACPI value. GPU thermal protection is fully active.

## Remaining milestones

1. Preview playback, richer explanations, export progress/cancellation, and queue reorder UI.
2. Live Twitch device connection test after a public Client ID is entered.
3. Full calibration against all six supplied moments and long-duration thermal/GPU tests.
4. Optional reliable CPU sensor provider where Windows exposes no package sensor.
5. Windows packaging, beta installation docs, final green checkpoints, and PR completion.

## Calibration contract

The source of truth is `tests/calibration/twitch_known_moments.json`. The 150-second
range from `01:27:00` to `01:29:30` in VOD `2823263031` is explicitly marked as a
condensation case. Its expected result is at most 60 seconds and must be assembled
from multiple chronological source spans when the scoring evidence supports cuts.
The algorithm must remove low-value interior regions rather than simply trimming
one end.

## Resume instructions

1. Check `git status` and remain on `agent/end-to-end-build`.
2. Recreate the environment with `scripts/bootstrap.ps1` if `.venv` is missing.
3. Run `local-clip-ai --data-dir .local-data install-tools`; existing verified tools
   are reused.
4. Install development/AI dependencies with
   `pip install -e ".[dev,transcription,gpu]"`.
5. Run Ruff and pytest before each push.
6. Never add `.local-data`, VODs, models, transcripts, databases, or exports to Git.
