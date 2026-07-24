from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from local_clip_ai.config import AnalysisProfile
from local_clip_ai.media.timecodes import TimeRange
from local_clip_ai.paths import AppPaths

CancelCheck = Callable[[], bool]
SegmentCallback = Callable[["TranscriptSegment"], None]
_DLL_DIRECTORY_HANDLES: list[Any] = []
_DLL_DIRECTORIES: set[Path] = set()


class TranscriptionCancelled(RuntimeError):
    pass


def configure_nvidia_dll_directories() -> tuple[Path, ...]:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return ()
    import importlib

    directories: list[Path] = []
    for module_name in ("nvidia.cublas", "nvidia.cuda_nvrtc", "nvidia.cudnn"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for package_root in getattr(module, "__path__", ()):
            binary_directory = Path(package_root) / "bin"
            if binary_directory.is_dir() and binary_directory not in _DLL_DIRECTORIES:
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(binary_directory))
                _DLL_DIRECTORIES.add(binary_directory)
            if binary_directory.is_dir():
                directories.append(binary_directory)
    current_path = os.environ.get("PATH", "").split(os.pathsep)
    missing = [str(directory) for directory in directories if str(directory) not in current_path]
    if missing:
        os.environ["PATH"] = os.pathsep.join([*missing, *current_path])
    return tuple(directories)


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    avg_log_probability: float
    no_speech_probability: float


@dataclass(frozen=True, slots=True)
class Transcript:
    media_path: str
    model: str
    device: str
    compute_type: str
    language: str
    language_probability: float
    duration_seconds: float
    elapsed_seconds: float
    source_offset_seconds: float
    segments: tuple[TranscriptSegment, ...]

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["segments"] = [asdict(segment) for segment in self.segments]
        return values

    def save(self, destination: Path | str) -> Path:
        output = Path(destination).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
        return output


def cuda_is_available() -> bool:
    try:
        configure_nvidia_dll_directories()
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except (ImportError, RuntimeError):
        return False


def transcribe_media(
    paths: AppPaths,
    media_path: Path | str,
    profile: AnalysisProfile,
    *,
    language: str | None = None,
    source_offset_seconds: float = 0,
    cancel_requested: CancelCheck | None = None,
    on_segment: SegmentCallback | None = None,
    device: str | None = None,
    clip_range: TimeRange | None = None,
) -> Transcript:
    configure_nvidia_dll_directories()
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "The transcription dependencies are missing; install the transcription extra"
        ) from error

    source = Path(media_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    selected_device = device or ("cuda" if cuda_is_available() else "cpu")
    compute_type = (
        profile.transcription_compute_type if selected_device == "cuda" else "int8"
    )
    model_root = paths.models / "faster-whisper"
    model_root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    model = WhisperModel(
        profile.transcription_model,
        device=selected_device,
        compute_type=compute_type,
        download_root=str(model_root),
    )
    segments_generator, info = model.transcribe(
        str(source),
        language=None if language in {None, "", "auto"} else language,
        beam_size=profile.beam_size,
        vad_filter=True,
        word_timestamps=False,
        condition_on_previous_text=True,
        clip_timestamps=(
            [clip_range.start, clip_range.end]
            if clip_range is not None
            else "0"
        ),
    )
    segments: list[TranscriptSegment] = []
    try:
        for raw_segment in segments_generator:
            if cancel_requested and cancel_requested():
                raise TranscriptionCancelled("Transcription cancelled at a segment boundary")
            segment = TranscriptSegment(
                start_seconds=float(raw_segment.start) + source_offset_seconds,
                end_seconds=float(raw_segment.end) + source_offset_seconds,
                text=raw_segment.text.strip(),
                avg_log_probability=float(raw_segment.avg_logprob),
                no_speech_probability=float(raw_segment.no_speech_prob),
            )
            segments.append(segment)
            if on_segment:
                on_segment(segment)
    except RuntimeError as error:
        runtime_error = str(error).lower()
        missing_cuda_library = "cublas" in runtime_error or "cudnn" in runtime_error
        if device is None and selected_device == "cuda" and not segments and missing_cuda_library:
            return transcribe_media(
                paths,
                source,
                profile,
                language=language,
                source_offset_seconds=source_offset_seconds,
                cancel_requested=cancel_requested,
                on_segment=on_segment,
                device="cpu",
                clip_range=clip_range,
            )
        raise
    return Transcript(
        media_path=str(source),
        model=profile.transcription_model,
        device=selected_device,
        compute_type=compute_type,
        language=str(info.language),
        language_probability=float(info.language_probability),
        duration_seconds=float(info.duration),
        elapsed_seconds=time.monotonic() - started,
        source_offset_seconds=source_offset_seconds,
        segments=tuple(segments),
    )
