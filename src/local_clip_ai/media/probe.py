from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from local_clip_ai.paths import AppPaths
from local_clip_ai.tools import find_ffmpeg


@dataclass(frozen=True, slots=True)
class MediaProbe:
    path: Path
    duration_seconds: float
    size_bytes: int
    format_name: str
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None
    sample_rate: int | None


def _first_stream(values: dict[str, Any], codec_type: str) -> dict[str, Any] | None:
    return next(
        (stream for stream in values.get("streams", []) if stream.get("codec_type") == codec_type),
        None,
    )


def parse_ffprobe(values: dict[str, Any], path: Path) -> MediaProbe:
    format_values = values.get("format") or {}
    duration = format_values.get("duration")
    if duration is None:
        durations = [
            float(stream["duration"])
            for stream in values.get("streams", [])
            if stream.get("duration") is not None
        ]
        if not durations:
            raise RuntimeError(f"FFprobe did not report a duration for {path}")
        duration = max(durations)
    video = _first_stream(values, "video")
    audio = _first_stream(values, "audio")
    return MediaProbe(
        path=path.resolve(),
        duration_seconds=float(duration),
        size_bytes=path.stat().st_size,
        format_name=str(format_values.get("format_name") or "unknown"),
        video_codec=str(video["codec_name"]) if video and video.get("codec_name") else None,
        audio_codec=str(audio["codec_name"]) if audio and audio.get("codec_name") else None,
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
        sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
    )


def probe_media(paths: AppPaths, path: Path | str, *, timeout: float = 60) -> MediaProbe:
    media_path = Path(path).expanduser().resolve()
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    _, ffprobe = find_ffmpeg(paths)
    if ffprobe is None:
        raise RuntimeError("FFprobe is not installed; run install-tools first")
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(media_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if completed.returncode != 0:
        error = completed.stderr.strip() or "Unknown FFprobe error"
        raise RuntimeError(f"Could not probe {media_path.name}: {error[-2000:]}")
    return parse_ffprobe(json.loads(completed.stdout), media_path)
