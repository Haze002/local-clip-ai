from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from local_clip_ai.paths import AppPaths
from local_clip_ai.tools import find_yt_dlp


@dataclass(frozen=True, slots=True)
class TwitchVod:
    video_id: str
    canonical_url: str
    title: str
    channel: str
    duration_seconds: float
    recorded_at: str | None = None
    thumbnail_url: str | None = None
    availability: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_twitch_vod_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host not in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}:
        raise ValueError("Only twitch.tv VOD URLs are supported")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0].lower() != "videos" or not parts[1].isdigit():
        raise ValueError("Expected a Twitch URL in the form https://www.twitch.tv/videos/123")
    video_id = parts[1]
    return video_id, f"https://www.twitch.tv/videos/{video_id}"


def _vod_from_yt_dlp(values: dict[str, Any], canonical_url: str) -> TwitchVod:
    duration = values.get("duration")
    if duration is None:
        raise RuntimeError("Twitch did not return a duration for this VOD")
    video_id, _ = parse_twitch_vod_url(canonical_url)
    return TwitchVod(
        video_id=video_id,
        canonical_url=canonical_url,
        title=str(values.get("title") or "Untitled VOD"),
        channel=str(values.get("uploader") or values.get("channel") or "Unknown channel"),
        duration_seconds=float(duration),
        recorded_at=values.get("upload_date"),
        thumbnail_url=values.get("thumbnail"),
        availability=values.get("availability"),
    )


def inspect_twitch_vod(paths: AppPaths, url: str, *, timeout: float = 120) -> TwitchVod:
    _, canonical_url = parse_twitch_vod_url(url)
    executable = find_yt_dlp(paths)
    if executable is None:
        raise RuntimeError("yt-dlp is not installed; run install-tools first")
    completed = subprocess.run(
        [
            str(executable),
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
            canonical_url,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or "Unknown yt-dlp error"
        raise RuntimeError(f"Could not inspect Twitch VOD: {error[-2000:]}")
    return _vod_from_yt_dlp(json.loads(completed.stdout), canonical_url)


def yt_dlp_section_command(
    paths: AppPaths,
    *,
    url: str,
    start_seconds: float,
    end_seconds: float,
    output: Path,
    audio_only: bool = False,
    max_height: int | None = None,
) -> list[str]:
    if end_seconds <= start_seconds:
        raise ValueError("Section end must be after its start")
    if max_height is not None and max_height <= 0:
        raise ValueError("Maximum height must be positive")
    _, canonical_url = parse_twitch_vod_url(url)
    executable = find_yt_dlp(paths)
    if executable is None:
        raise RuntimeError("yt-dlp is not installed; run install-tools first")
    from local_clip_ai.tools import find_ffmpeg

    ffmpeg, _ = find_ffmpeg(paths)
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not installed; run install-tools first")
    command = [
        str(executable),
        "--no-playlist",
        "--continue",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--concurrent-fragments",
        "4",
        "--newline",
        "--download-sections",
        f"*{start_seconds:.3f}-{end_seconds:.3f}",
        "--force-keyframes-at-cuts",
        "--ffmpeg-location",
        str(ffmpeg.parent),
        "--output",
        str(output),
        "--print",
        "after_move:filepath",
    ]
    if audio_only:
        command.extend(["--format", "bestaudio/best", "--extract-audio", "--audio-format", "wav"])
    else:
        format_selector = "bestvideo*+bestaudio/best"
        if max_height is not None:
            format_selector = (
                f"bestvideo*[height<={max_height}]+bestaudio/best[height<={max_height}]/best"
            )
        command.extend(["--format", format_selector])
    command.append(canonical_url)
    return command
