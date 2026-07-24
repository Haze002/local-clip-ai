# Architecture

## Design goals

- Keep the native interface responsive while video and AI work runs.
- Release GPU memory completely when requested.
- Resume from committed checkpoints after cancellation or a process/Windows crash.
- Keep original VODs, model weights, transcripts, and results local by default.
- Make transcription, language-model, and vision-model backends replaceable.

## Process boundaries

The desktop shell owns the user interface, queue scheduler, and durable job
database. Expensive work is delegated to disposable child processes:

1. **Media worker** — probes recordings, extracts audio, samples frames, and exports clips.
2. **Transcription worker** — produces timestamped speech segments in resumable chunks.
3. **Signal worker** — detects audio peaks, scene changes, motion, and other cheap signals.
4. **Semantic worker** — scores transcript windows with a local language model.
5. **Vision worker** — reranks promising candidates in Balanced and Deep modes.

Workers never become the authoritative source of job state. They report completed
checkpoints to the scheduler, which commits those checkpoints to SQLite. Terminating
a worker therefore releases its CUDA context without discarding completed stages.

## Data flow

```text
VOD
 ├─ media probe and fingerprint
 ├─ timestamped transcript
 ├─ audio/scene/activity signals
 ├─ candidate time windows
 ├─ semantic and optional visual scores
 ├─ refined clip boundaries
 └─ previews and exported clips
```

## Persistence

SQLite runs in WAL mode with foreign keys and explicit transactions. Jobs contain
snapshots of their content and analysis profiles. Each stage owns an independent
checkpoint document so a schema migration or failed stage does not invalidate
unrelated completed work.

Runtime artifacts live outside the source repository. A production installation
uses `%LOCALAPPDATA%\LocalClipAI` by default; development can use `.local-data`.

## Resource safety

The eventual scheduler will apply separate CPU and GPU temperature policies.
Thresholds use a sustained grace period, a lower resume temperature, and a stable
cooldown interval. Emergency conditions stop a worker at the nearest safe boundary.
The Windows shell prevents automatic system sleep only while work is active.

