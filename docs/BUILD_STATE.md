# Build State

This file is the durable handoff ledger for the autonomous Windows beta build.
Update it whenever a milestone is completed or a material blocker changes.

## Current checkpoint

- Branch: `agent/end-to-end-build`
- Phase: Milestone 1 complete; Milestone 2 in progress
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

## In progress

### Milestone 2 - durable queue and acquisition

- Database migrations for sources, profiles, artifacts, candidates, and exports.
- Resumable range acquisition and FFprobe-based validation.
- Native queue/source workflow, multi-VOD queuing, link paste, and file drag/drop.
- Latest-VOD/channel discovery with an optional Twitch device-code connection.

## Remaining milestones

1. Resumable audio extraction, local GPU transcription, and signal analysis.
2. Quick, Balanced, and Deep candidate generation/ranking profiles.
3. Long-moment condensation into chronological multi-span edit decisions.
4. Review UI, previews, selection, and source-quality export.
5. Live resource/temperature panel, configurable thermal policy, and VRAM fallback.
6. Cancel/pause/resume, Windows crash recovery, sleep prevention, notifications, and tray.
7. Calibration against the supplied moments, end-to-end GPU soak tests, Windows packaging,
   beta documentation, green checkpoint pushes, and a draft pull request.

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
4. Run Ruff and pytest before each push.
5. Never add `.local-data`, VODs, models, transcripts, databases, or exports to Git.
