from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from local_clip_ai.analysis.condensation import EvidenceWindow
from local_clip_ai.analysis.signal_progress import (
    PTS_TIME,
    ProgressCallback,
    metadata_progress_reporter,
)
from local_clip_ai.paths import AppPaths
from local_clip_ai.sources.acquisition import run_cancellable_process
from local_clip_ai.tools import find_ffmpeg

RMS_LEVEL = re.compile(
    r"lavfi\.astats\.Overall\.RMS_level=(-?\d+(?:\.\d+)?|-inf)",
    re.IGNORECASE,
)
CancelCheck = Callable[[], bool]


def parse_audio_rms_lines(lines: Iterable[str]) -> list[tuple[float, float]]:
    readings: list[tuple[float, float]] = []
    timestamp: float | None = None
    for line in lines:
        time_match = PTS_TIME.search(line)
        if time_match:
            timestamp = float(time_match.group(1))
        level_match = RMS_LEVEL.search(line)
        if level_match and timestamp is not None:
            raw_level = level_match.group(1).lower()
            level = -100.0 if raw_level == "-inf" else float(raw_level)
            readings.append((max(0.0, timestamp), level))
            timestamp = None
    return readings


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("A percentile requires at least one value")
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def normalize_audio_evidence(
    readings: list[tuple[float, float]],
    *,
    window_seconds: float = 1,
) -> list[EvidenceWindow]:
    if not readings:
        return []
    levels = [level for _, level in readings]
    floor = _percentile(levels, 0.20)
    peak = _percentile(levels, 0.95)
    dynamic_range = max(6.0, peak - floor)
    evidence = []
    previous_level = readings[0][1]
    for timestamp, level in readings:
        relative_energy = max(0.0, min(1.0, (level - floor) / dynamic_range))
        sudden_rise = max(0.0, min(1.0, (level - previous_level) / 12.0))
        score = max(0.0, min(1.0, relative_energy * 0.82 + sudden_rise * 0.18))
        evidence.append(
            EvidenceWindow(
                timestamp,
                timestamp + window_seconds,
                score,
                "audio energy peak" if score >= 0.65 else "audio energy",
            )
        )
        previous_level = level
    return evidence


def extract_audio_evidence(
    paths: AppPaths,
    media_path: Path | str,
    *,
    cancel_requested: CancelCheck | None = None,
    duration_seconds: float | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[EvidenceWindow]:
    ffmpeg, _ = find_ffmpeg(paths)
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not installed; run install-tools first")
    source = Path(media_path).expanduser().resolve()
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-nostats",
        "-i",
        str(source),
        "-vn",
        "-af",
        (
            "aresample=16000,asetnsamples=n=16000:p=1,"
            "astats=metadata=1:reset=1,"
            "ametadata=print:key=lavfi.astats.Overall.RMS_level"
        ),
        "-f",
        "null",
        "NUL" if os.name == "nt" else "/dev/null",
    ]
    return_code, lines = run_cancellable_process(
        command,
        cancel_requested=cancel_requested,
        on_output=metadata_progress_reporter(duration_seconds, on_progress),
    )
    readings = parse_audio_rms_lines(lines)
    if return_code or not readings:
        recent_output = "\n".join(lines[-30:])
        raise RuntimeError(
            f"Audio signal analysis exited with code {return_code}:\n{recent_output}"
        )
    return normalize_audio_evidence(readings)
