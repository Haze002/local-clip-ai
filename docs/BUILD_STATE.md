# Build State

This file is the durable handoff ledger for the autonomous Windows beta build.
Update it whenever a milestone is completed or a material blocker changes.

## Current checkpoint

- Branch: `agent/end-to-end-build`
- Phase: Milestones 1-9 complete; tested Windows beta available
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
- Candidate discovery now preserves broad story candidates while reserving review
  capacity for coherent sub-events inside long windows. The default review capacity is
  50 and automatic preselection remains 10.
- Long repetitive one/two-word music hallucinations are removed from merged transcripts
  and candidate titles. Deep visual evidence can boost a candidate but cannot unfairly
  demote only the subset that received frame analysis.
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
- Added queue Up/Down controls while the runner is idle.
- Added a native Qt Multimedia review player. Preparing a preview applies the exact
  proposed chronological multi-span cut plan and stores the preview only under ignored
  local artifacts. Balanced/Deep previews reuse downloaded analysis video when possible;
  Quick previews cache a source section that the final export can reuse.
- Source acquisition and FFmpeg encoding now report real operation progress and can be
  cancelled safely. Partial export files are removed; completed analysis stages remain.
- Full-VOD audio and scene scans now report throttled stage progress from streamed FFmpeg
  timestamps, avoiding a seemingly frozen progress value during long Deep runs.
- Candidate titles now include a useful transcript excerpt when available, and
  explanations combine up to four strongest local speech/audio/visual/semantic reasons.
- Added Material dark styling, system tray behavior, and completion/export notifications.

### Milestone 5 - resource and interruption safety

- Added a show/hide compact monitor plus a full monitor page for total/app CPU, CPU clock
  and cores, RAM, process I/O, GPU utilization/temperature/clocks/power, total VRAM, and
  app-plus-worker VRAM.
- Added persisted GPU/CPU temperature limits, sustained grace period, lower resume
  temperature, cooldown stability, and VRAM soft limit.
- Defaults implement the requested behavior: 90 °C pause limit, 120-second grace,
  82 °C resume point, and 30-second stable cooldown.
- GPU/CPU limits, high-temperature grace time, stable cooldown duration, and VRAM soft
  limit are editable and persisted from the Monitor page.
- Added Windows sleep inhibition only while the queue runner is active.
- CPU package temperature is shown when the operating system exposes it; it is marked
  unavailable on the current Ryzen/Windows configuration rather than displaying a false
  ACPI value. GPU thermal protection is fully active.
- Added an end-to-end thermal policy regression test that proves sustained heat requests
  a safe pause and that a stable cooldown resumes the preserved job.
- Python subprocesses now force UTF-8 output. A real full-VOD run exposed a Windows
  legacy-code-page failure on accented transcript text; the failed chunk resumed
  successfully after the fix without repeating the first five durable chunks.

### Milestone 6 - Windows beta packaging

- Added a first-launch Settings action that downloads and verifies portable FFmpeg,
  ffprobe, and yt-dlp without a system-wide installation.
- Added a PyInstaller 6.21 one-folder build with Qt/QML/Multimedia, faster-whisper,
  CTranslate2, FastEmbed/ONNX, Windows Credential Manager support, and local NVIDIA
  CUDA/cuDNN runtime DLLs.
- Frozen queue processes use a dedicated `--worker-cli` entry path, preserving isolated
  transcription workers instead of accidentally launching another GUI.
- Built and tested the packaged executable:
  - strict packaged diagnostics exited successfully;
  - real packaged transcription ran on RTX 5070 CUDA `int8_float16`;
  - packaged parent → packaged child queue execution completed every Quick stage;
  - the packaged calibrated `rebuild-candidates` command preserved 6/6 recall;
  - packaged GUI process launched and remained healthy.
- The initial validated unpacked beta was 2.56 GiB. Its ZIP was 1.52 GiB with SHA-256:
  `c5e3f6e35df355b1faf8bd095b5f5094db31cdac3301b96daa3607945b43877f`.
- That initial archive contained 3,558 entries; its packaged executable and QML UI were
  verified in-place, and the generated checksum file matches the 1.515 GiB ZIP.
- Added `docs/WINDOWS_BETA.md` with install, first-run, Twitch, privacy, recovery, and
  build instructions. Build output remains ignored and is not committed to Git.

### Milestone 7 - Self-contained media-tool hotfix

- A real clean first launch exposed that the initial ZIP expected the user to select
  **Settings > Install / repair** before FFmpeg diagnostics could pass. Earlier packaged
  diagnostics had reused populated development runtime data and did not exercise this
  state.
- Version 0.1.1 bundles the verified FFmpeg/ffprobe shared build and yt-dlp executable
  inside the one-folder package. Runtime discovery checks user-local repaired tools
  first, then bundled tools, then `PATH`; no system-wide installation is required.
- The build now fails immediately when lint, tests, dependency setup, tool preparation,
  PyInstaller, or package diagnostics fail. It also asserts that all three bundled
  executables exist.
- Packaged diagnostics are launched as a hidden process with an explicit wait and real
  exit-code check. The test uses an empty runtime directory and asserts that FFmpeg was
  not installed into it, proving the package used its bundled copy.
- Diagnostics now checks yt-dlp as a required Twitch downloader and gives GUI-specific
  repair instructions when a media executable is missing.
- The corrected unpacked beta is 2.856 GiB and contains 3,552 files. The ZIP contains
  3,585 entries and is 1.651 GiB (1,772,325,408 bytes), with SHA-256:
  `c887ed93eb148835564737a384fe79c845b83abe75bca225f3d2a2d886ada5ed`.
- The generated checksum matches the archive, and FFmpeg, ffprobe, and yt-dlp were
  inspected inside the ZIP. Strict packaged diagnostics against a clean runtime exited
  successfully.

### Milestone 8 - Packaged worker Unicode hotfix

- A real Balanced job on VOD `2823263031` exposed a remaining Windows locale boundary:
  the packaged transcription worker received a redirected stream encoded as cp1253 and
  crashed while printing Whisper text containing `U+4E0B`. Transcription itself and the
  first durable 15-minute chunk were valid.
- Version 0.1.2 reconfigures existing packaged worker stdout/stderr streams to UTF-8 with
  `backslashreplace`, in addition to retaining the UTF-8 process environment. Source CLI
  entry points apply the same configuration.
- Added a regression test that starts with real cp1253 `TextIOWrapper` streams and prints
  multilingual text including the exact failing character. The process-level test also
  round-trips that text through a child worker.
- The Windows build now runs a hidden packaged worker with redirected stdout, requires
  the UTF-8 byte sequence for `日本語 下`, verifies an empty stderr stream and a zero exit
  code, and refuses to archive if any of those checks fail.
- The real packaged smoke output was inspected byte-for-byte and decoded to
  `Local Clip AI Unicode smoke: naïve café — 日本語 下`.
- The failed user job remains preserved at transcription chunk 2/8 with chunk 1 complete;
  Resume under v0.1.2 reuses that completed chunk.
- The v0.1.2 ZIP is 1.651 GiB (1,772,327,018 bytes), and its generated checksum matches
  SHA-256:
  `c414542bc6238de12b6b878027124eb47a9af7c9b5f73e0b0f12f21b91b63d5e`.

### Milestone 9 - Packaged GUI stream-safety hotfix

- Resuming the real Balanced job for VOD `2823263031` completed all eight durable
  transcription chunks plus audio and visual evidence, then exposed a second
  no-console boundary during the semantic `signals` stage:
  `'NoneType' object has no attribute 'write'`.
- The windowed PyInstaller process has no native stdout/stderr streams. FastEmbed/ONNX
  progress logging attempted to write through one of those `None` streams while loading
  local semantic analysis.
- Version 0.1.3 now initializes UTF-8-safe standard streams before either the GUI or
  worker entry path. Missing windowed streams are backed by the Windows null device;
  existing redirected streams retain UTF-8 with `backslashreplace`.
- The build runs a real hidden, no-console packaged GUI stream smoke test and requires
  a zero exit code before creating the ZIP. A regression test also starts from
  `sys.stdout = None` and `sys.stderr = None` and verifies both streams are writable.
- Unexpected pipeline failures now append a full traceback to the job's ignored local
  log while the database and UI continue to store a concise error.
- The user's failed job remains safely checkpointed at 90 percent with the VOD,
  analysis media, eight transcript chunks, merged transcript, audio evidence, and
  visual evidence preserved. Resume under v0.1.3 reuses all completed stages and
  continues at local semantic ranking/candidate generation.
- The v0.1.3 ZIP is 1.651 GiB (1,772,328,056 bytes). Its packaged version probe returned
  `0.1.3` with empty stderr, and its generated checksum matches SHA-256:
  `ee1589e7e7e63968bb7c68d44fd67d232ff0a426812b1f5f7689d4f158cc72d6`.

### Calibration tooling

- Added a machine-readable evaluator for the six user-labeled Twitch moments. It reports
  recall, score rank, source-window overlap, actual exported-span overlap, required
  overlap, output duration, and source-span count from the local database without
  committing media or analysis output.
- The 150-second calibration moment is required to fit within 60 seconds and contain
  multiple chronological source spans.
- Both complete public Twitch VODs were downloaded and processed through Deep mode:
  VOD `2816862211` used 19 durable transcription chunks and VOD `2823263031` used 8.
- The final candidate logic detects all six labeled moments using actual output-span
  overlap: 6/6 recall.
- The 150-second `01:27:00` case produced four chronological spans (9 + 11 + 16 + 24
  seconds). The exact plan encoded with NVENC to a decoded, playable 60.000-second H.264
  and AAC MP4.
- A real Windows encoding interruption resumed from chunk 6 without repeating the first
  five chunks. Across the long run, the RTX 5070 remained far below the 90 °C limit and
  used roughly 4 GiB of its 12 GiB VRAM; deterministic policy tests cover sustained-hot
  pause and stable-cooldown resume behavior.
- Candidate-only rebuilding is available through `rebuild-candidates`, so preference and
  ranking changes reuse completed media, transcript, audio, visual, and semantic stages.
- The full suite currently passes: 65 tests plus 2 parameterized subtests, with Ruff
  clean. All calibration reports, media, transcripts, models, frames, databases, and
  exports remain ignored local data.

## Optional follow-ups

1. Live Twitch device connection test after a public Client ID is entered.
2. Optional reliable CPU sensor provider where Windows exposes no package sensor.
3. Code signing and an installer can be added after beta feedback; the current portable
   one-folder ZIP is complete and tested.

## Calibration contract

The source of truth is `tests/calibration/twitch_known_moments.json`. The 150-second
range from `01:27:00` to `01:29:30` in VOD `2823263031` is explicitly marked as a
condensation case. Its expected result is at most 60 seconds and must be assembled
from multiple chronological source spans when the scoring evidence supports cuts.
The algorithm must remove low-value interior regions rather than simply trimming
one end. The 80-second `01:43:50` to `01:45:10` range must also fit the 60-second
output budget; it may remain one coherent span if that scores best.

## Resume instructions

1. Check `git status` and remain on `agent/end-to-end-build`.
2. Recreate the environment with `scripts/bootstrap.ps1` if `.venv` is missing.
3. Run `local-clip-ai --data-dir .local-data install-tools`; existing verified tools
   are reused.
4. Install development/AI dependencies with
   `pip install -e ".[dev,transcription,gpu]"`.
5. Run Ruff and pytest before each push.
6. Never add `.local-data`, VODs, models, transcripts, databases, or exports to Git.
