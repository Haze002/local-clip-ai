from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from local_clip_ai.media.probe import MediaProbe, probe_media
from local_clip_ai.media.timecodes import TimeRange
from local_clip_ai.paths import AppPaths
from local_clip_ai.sources.twitch import parse_twitch_vod_url, yt_dlp_section_command
from local_clip_ai.tools import find_ffmpeg, find_yt_dlp

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[str], None]


class AcquisitionCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AcquiredSection:
    video_id: str
    source_range: TimeRange
    path: Path
    probe: MediaProbe
    audio_only: bool


@dataclass(frozen=True, slots=True)
class AcquiredVod:
    video_id: str
    path: Path
    probe: MediaProbe
    format_selector: str


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def run_cancellable_process(
    command: list[str],
    *,
    cancel_requested: CancelCheck | None = None,
    on_output: ProgressCallback | None = None,
    poll_interval: float = 0.2,
) -> tuple[int, list[str]]:
    environment = os.environ.copy()
    # Windows otherwise gives Python workers the active legacy console code page.
    # Transcript text is arbitrary Unicode, so one unrepresentable character could
    # abort an otherwise healthy multi-hour transcription before its checkpoint.
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        creationflags=_creation_flags(),
    )
    output_queue: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output_queue.put(line.rstrip())
        output_queue.put(None)

    reader = threading.Thread(target=read_output, name="process-output", daemon=True)
    reader.start()
    lines: list[str] = []
    stream_closed = False
    cancelled = False
    while process.poll() is None or not stream_closed:
        if cancel_requested and cancel_requested() and process.poll() is None:
            cancelled = True
            process.terminate()
        try:
            line = output_queue.get(timeout=poll_interval)
        except queue.Empty:
            if cancelled and process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            continue
        if line is None:
            stream_closed = True
            continue
        lines.append(line)
        if on_output:
            on_output(line)
    return_code = process.wait()
    reader.join(timeout=1)
    if cancelled:
        raise AcquisitionCancelled("Acquisition cancelled; resumable files were preserved")
    return return_code, lines


def acquire_twitch_section(
    paths: AppPaths,
    url: str,
    source_range: TimeRange,
    *,
    destination: Path | None = None,
    audio_only: bool = False,
    cancel_requested: CancelCheck | None = None,
    on_output: ProgressCallback | None = None,
) -> AcquiredSection:
    video_id, canonical_url = parse_twitch_vod_url(url)
    paths.ensure_directories()
    target_directory = destination or paths.downloads / video_id
    target_directory.mkdir(parents=True, exist_ok=True)
    media_kind = "audio" if audio_only else "source"
    stem = (
        f"{video_id}_{int(source_range.start):06d}_{int(source_range.end):06d}_{media_kind}"
    )
    template = target_directory / f"{stem}.%(ext)s"
    command = yt_dlp_section_command(
        paths,
        url=canonical_url,
        start_seconds=source_range.start,
        end_seconds=source_range.end,
        output=template,
        audio_only=audio_only,
    )
    return_code, lines = run_cancellable_process(
        command,
        cancel_requested=cancel_requested,
        on_output=on_output,
    )
    if return_code:
        recent_output = "\n".join(lines[-30:])
        raise RuntimeError(f"yt-dlp exited with code {return_code}:\n{recent_output}")

    candidates = [
        path
        for path in target_directory.glob(f"{stem}.*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        printed_paths = [Path(line) for line in reversed(lines) if Path(line).is_file()]
        candidates = printed_paths[:1]
    if not candidates:
        raise RuntimeError("yt-dlp completed but no media section was found")
    result_path = max(candidates, key=lambda path: path.stat().st_mtime)
    probe = probe_media(paths, result_path)
    expected_duration = source_range.duration
    duration_tolerance = max(3.0, expected_duration * 0.08)
    if abs(probe.duration_seconds - expected_duration) > duration_tolerance:
        raise RuntimeError(
            f"Downloaded section duration was {probe.duration_seconds:.2f}s; "
            f"expected approximately {expected_duration:.2f}s"
        )
    return AcquiredSection(
        video_id=video_id,
        source_range=source_range,
        path=result_path.resolve(),
        probe=probe,
        audio_only=audio_only,
    )


def acquire_twitch_analysis_media(
    paths: AppPaths,
    url: str,
    *,
    analysis_mode: str,
    cancel_requested: CancelCheck | None = None,
    on_output: ProgressCallback | None = None,
) -> AcquiredVod:
    video_id, canonical_url = parse_twitch_vod_url(url)
    if analysis_mode not in {"quick", "balanced", "deep"}:
        raise ValueError(f"Unsupported analysis mode: {analysis_mode}")
    executable = find_yt_dlp(paths)
    if executable is None:
        raise RuntimeError("yt-dlp is not installed; run install-tools first")
    ffmpeg, _ = find_ffmpeg(paths)
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not installed; run install-tools first")
    target_directory = paths.downloads / video_id
    target_directory.mkdir(parents=True, exist_ok=True)
    format_selector = (
        "Audio_Only/bestaudio"
        if analysis_mode == "quick"
        else "360p/160p/worst"
    )
    stem = f"{video_id}_analysis_{analysis_mode}"
    existing = [
        path
        for path in target_directory.glob(f"{stem}.*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if existing:
        result_path = max(existing, key=lambda path: path.stat().st_mtime)
        return AcquiredVod(
            video_id,
            result_path.resolve(),
            probe_media(paths, result_path),
            format_selector,
        )
    command = [
        str(executable),
        "--no-playlist",
        "--continue",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--concurrent-fragments",
        "8",
        "--newline",
        "--ffmpeg-location",
        str(ffmpeg.parent),
        "--format",
        format_selector,
        "--output",
        str(target_directory / f"{stem}.%(ext)s"),
        "--print",
        "after_move:filepath",
        canonical_url,
    ]
    return_code, lines = run_cancellable_process(
        command,
        cancel_requested=cancel_requested,
        on_output=on_output,
    )
    if return_code:
        recent_output = "\n".join(lines[-30:])
        raise RuntimeError(f"yt-dlp exited with code {return_code}:\n{recent_output}")
    candidates = [
        path
        for path in target_directory.glob(f"{stem}.*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        raise RuntimeError("yt-dlp completed but no analysis media was found")
    result_path = max(candidates, key=lambda path: path.stat().st_mtime)
    return AcquiredVod(
        video_id,
        result_path.resolve(),
        probe_media(paths, result_path),
        format_selector,
    )


def wait_until_file_stable(
    path: Path,
    *,
    interval: float = 0.25,
    stable_checks: int = 3,
    timeout: float = 10,
) -> bool:
    deadline = time.monotonic() + timeout
    previous_size = -1
    unchanged = 0
    while time.monotonic() < deadline:
        current_size = path.stat().st_size if path.exists() else -1
        if current_size >= 0 and current_size == previous_size:
            unchanged += 1
            if unchanged >= stable_checks:
                return True
        else:
            unchanged = 0
        previous_size = current_size
        time.sleep(interval)
    return False
