from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from local_clip_ai.analysis.condensation import EvidenceWindow
from local_clip_ai.paths import AppPaths
from local_clip_ai.sources.acquisition import run_cancellable_process
from local_clip_ai.tools import find_ffmpeg

PTS_TIME = re.compile(r"\bpts_time:(-?\d+(?:\.\d+)?)")
SCENE_SCORE = re.compile(r"lavfi\.scene_score=(\d+(?:\.\d+)?)", re.IGNORECASE)
CancelCheck = Callable[[], bool]


def parse_scene_lines(lines: Iterable[str]) -> list[tuple[float, float]]:
    readings: list[tuple[float, float]] = []
    timestamp: float | None = None
    for line in lines:
        time_match = PTS_TIME.search(line)
        if time_match:
            timestamp = float(time_match.group(1))
        score_match = SCENE_SCORE.search(line)
        if score_match and timestamp is not None:
            readings.append((max(0.0, timestamp), float(score_match.group(1))))
            timestamp = None
    return readings


def normalize_scene_evidence(
    readings: list[tuple[float, float]],
) -> list[EvidenceWindow]:
    per_second: dict[int, float] = {}
    for timestamp, raw_score in readings:
        second = math.floor(timestamp)
        per_second[second] = max(per_second.get(second, 0), raw_score)
    return [
        EvidenceWindow(
            float(second),
            float(second + 1),
            max(0.0, min(1.0, raw_score * 2)),
            "strong scene change" if raw_score >= 0.35 else "visual activity",
        )
        for second, raw_score in sorted(per_second.items())
    ]


def extract_visual_evidence(
    paths: AppPaths,
    media_path: Path | str,
    *,
    analysis_mode: str,
    cancel_requested: CancelCheck | None = None,
) -> list[EvidenceWindow]:
    if analysis_mode not in {"balanced", "deep"}:
        return []
    ffmpeg, _ = find_ffmpeg(paths)
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not installed; run install-tools first")
    source = Path(media_path).expanduser().resolve()
    sample_fps = 1 if analysis_mode == "balanced" else 2
    scene_threshold = 0.16 if analysis_mode == "balanced" else 0.07
    visual_filter = (
        f"fps={sample_fps},scale=320:-2,"
        f"select='gt(scene,{scene_threshold})',"
        "metadata=print:key=lavfi.scene_score"
    )
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-nostats",
        "-i",
        str(source),
        "-vf",
        visual_filter,
        "-an",
        "-f",
        "null",
        "NUL" if os.name == "nt" else "/dev/null",
    ]
    return_code, lines = run_cancellable_process(
        command,
        cancel_requested=cancel_requested,
    )
    if return_code:
        recent_output = "\n".join(lines[-30:])
        raise RuntimeError(
            f"Visual signal analysis exited with code {return_code}:\n{recent_output}"
        )
    return normalize_scene_evidence(parse_scene_lines(lines))
