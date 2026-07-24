from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from local_clip_ai.media.probe import MediaProbe, probe_media
from local_clip_ai.paths import AppPaths
from local_clip_ai.sources.acquisition import run_cancellable_process
from local_clip_ai.tools import find_ffmpeg

CancelCheck = Callable[[], bool]
ProgressCallback = Callable[[float], None]
OUT_TIME = re.compile(r"out_time_(?:us|ms)=(\d+)")


class SpanLike(Protocol):
    start_seconds: float
    end_seconds: float

    @property
    def duration_seconds(self) -> float: ...


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: Path
    probe: MediaProbe
    source_spans: tuple[SpanLike, ...]
    encoder: str


def build_concat_filter(
    spans: tuple[SpanLike, ...] | list[SpanLike],
    *,
    source_offset_seconds: float = 0,
) -> str:
    if not spans:
        raise ValueError("At least one source span is required")
    filters: list[str] = []
    inputs: list[str] = []
    previous_end = -1.0
    for index, span in enumerate(spans):
        start = span.start_seconds - source_offset_seconds
        end = span.end_seconds - source_offset_seconds
        if start < 0 or end <= start:
            raise ValueError("Export spans fall outside the acquired source")
        if span.start_seconds < previous_end:
            raise ValueError("Export spans must be chronological and non-overlapping")
        previous_end = span.end_seconds
        filters.extend(
            (
                f"[0:v]trim=start={start:.6f}:end={end:.6f},"
                f"setpts=PTS-STARTPTS[v{index}]",
                f"[0:a]atrim=start={start:.6f}:end={end:.6f},"
                f"asetpts=PTS-STARTPTS[a{index}]",
            )
        )
        inputs.append(f"[v{index}][a{index}]")
    filters.append(
        f"{''.join(inputs)}concat=n={len(spans)}:v=1:a=1[outv][outa]"
    )
    return ";".join(filters)


def _available_encoders(ffmpeg: Path) -> str:
    completed = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-encoders"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    return completed.stdout


def _encoder_arguments(encoder: str) -> list[str]:
    if encoder == "h264_nvenc":
        return ["-c:v", encoder, "-preset", "p5", "-tune", "hq", "-cq", "20", "-b:v", "0"]
    return ["-c:v", "mpeg4", "-q:v", "3"]


def _run_export(
    ffmpeg: Path,
    source: Path,
    partial: Path,
    filter_graph: str,
    encoder: str,
    expected_duration_seconds: float,
    cancel_requested: CancelCheck | None,
    on_progress: ProgressCallback | None,
) -> tuple[int, list[str]]:
    def output(line: str) -> None:
        if not on_progress:
            return
        match = OUT_TIME.fullmatch(line.strip())
        if match:
            elapsed_seconds = int(match.group(1)) / 1_000_000
            on_progress(min(0.99, elapsed_seconds / expected_duration_seconds))
        elif line.strip() == "progress=end":
            on_progress(1.0)

    return run_cancellable_process(
        [
            str(ffmpeg),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            str(source),
            "-filter_complex",
            filter_graph,
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            *_encoder_arguments(encoder),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(partial),
        ],
        cancel_requested=cancel_requested,
        on_output=output,
    )


def export_condensed_clip(
    paths: AppPaths,
    source: Path | str,
    spans: tuple[SpanLike, ...] | list[SpanLike],
    destination: Path | str,
    *,
    source_offset_seconds: float = 0,
    overwrite: bool = False,
    cancel_requested: CancelCheck | None = None,
    on_progress: ProgressCallback | None = None,
) -> ExportResult:
    source_path = Path(source).expanduser().resolve()
    output = Path(destination).expanduser().resolve()
    if output.exists() and not overwrite:
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg, _ = find_ffmpeg(paths)
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not installed; run install-tools first")
    input_probe = probe_media(paths, source_path)
    if not input_probe.video_codec or not input_probe.audio_codec:
        raise RuntimeError("Clip export requires a source with both video and audio")
    filter_graph = build_concat_filter(
        spans,
        source_offset_seconds=source_offset_seconds,
    )
    encoders = _available_encoders(ffmpeg)
    preferred_encoder = "h264_nvenc" if "h264_nvenc" in encoders else "mpeg4"
    partial = output.with_name(f".{output.stem}.partial{output.suffix}")
    expected_duration = sum(span.duration_seconds for span in spans)
    try:
        return_code, lines = _run_export(
            ffmpeg,
            source_path,
            partial,
            filter_graph,
            preferred_encoder,
            expected_duration,
            cancel_requested,
            on_progress,
        )
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    encoder = preferred_encoder
    if return_code and preferred_encoder == "h264_nvenc":
        partial.unlink(missing_ok=True)
        encoder = "mpeg4"
        try:
            return_code, lines = _run_export(
                ffmpeg,
                source_path,
                partial,
                filter_graph,
                encoder,
                expected_duration,
                cancel_requested,
                on_progress,
            )
        except Exception:
            partial.unlink(missing_ok=True)
            raise
    if return_code:
        partial.unlink(missing_ok=True)
        error = "\n".join(lines[-40:]).strip() or "Unknown FFmpeg export error"
        raise RuntimeError(f"FFmpeg export failed: {error[-4000:]}")
    os.replace(partial, output)
    output_probe = probe_media(paths, output)
    if abs(output_probe.duration_seconds - expected_duration) > max(1.0, expected_duration * 0.03):
        raise RuntimeError(
            f"Export duration was {output_probe.duration_seconds:.2f}s; "
            f"expected approximately {expected_duration:.2f}s"
        )
    return ExportResult(
        path=output,
        probe=output_probe,
        source_spans=tuple(spans),
        encoder=encoder,
    )
