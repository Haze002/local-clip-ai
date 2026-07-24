from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from local_clip_ai.analysis.candidates import CandidateMoment
from local_clip_ai.analysis.semantic import cosine_similarity
from local_clip_ai.paths import AppPaths
from local_clip_ai.sources.acquisition import run_cancellable_process
from local_clip_ai.tools import find_ffmpeg

TEXT_MODEL = "Qdrant/clip-ViT-B-32-text"
IMAGE_MODEL = "Qdrant/clip-ViT-B-32-vision"
CancelCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class VisionAssessment:
    candidate_index: int
    score: float
    similarity: float
    frame_count: int


def candidate_frame_timestamps(
    candidate: CandidateMoment,
    *,
    max_frames: int = 3,
) -> list[float]:
    ranked_spans = sorted(
        candidate.condensation.spans,
        key=lambda span: span.score,
        reverse=True,
    )
    values = [
        (span.start_seconds + span.end_seconds) / 2
        for span in ranked_spans[:max_frames]
    ]
    values.append((candidate.source_range.start + candidate.source_range.end) / 2)
    unique: list[float] = []
    for value in values:
        timestamp = max(
            candidate.source_range.start,
            min(candidate.source_range.end - 0.05, value),
        )
        if not any(abs(existing - timestamp) < 0.5 for existing in unique):
            unique.append(timestamp)
        if len(unique) >= max_frames:
            break
    return sorted(unique)


def apply_vision_assessments(
    candidates: Sequence[CandidateMoment],
    assessments: Sequence[VisionAssessment],
    *,
    auto_preselect_count: int,
) -> list[CandidateMoment]:
    by_index = {assessment.candidate_index: assessment for assessment in assessments}
    reranked = []
    for index, candidate in enumerate(candidates):
        assessment = by_index.get(index)
        if assessment is None:
            reranked.append(candidate)
            continue
        score = min(1.0, candidate.score * 0.72 + assessment.score * 0.28)
        rationale = (
            f"{candidate.rationale}; local vision preference match "
            f"({assessment.similarity:.0%})"
        )
        reranked.append(
            replace(
                candidate,
                score=score,
                rationale=rationale,
                auto_preselected=False,
            )
        )
    reranked.sort(key=lambda item: item.score, reverse=True)
    return [
        replace(candidate, auto_preselected=index < auto_preselect_count)
        for index, candidate in enumerate(reranked)
    ]


def _extract_frame(
    paths: AppPaths,
    source: Path,
    timestamp: float,
    destination: Path,
    cancel_requested: CancelCheck | None,
) -> None:
    if destination.is_file() and destination.stat().st_size > 0:
        return
    ffmpeg, _ = find_ffmpeg(paths)
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not installed; run install-tools first")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem + ".tmp" + destination.suffix)
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        "scale=384:-2",
        str(temporary),
    ]
    return_code, lines = run_cancellable_process(
        command,
        cancel_requested=cancel_requested,
    )
    if return_code or not temporary.is_file():
        recent_output = "\n".join(lines[-20:])
        raise RuntimeError(
            f"Candidate frame extraction exited with code {return_code}:\n{recent_output}"
        )
    temporary.replace(destination)


def rerank_candidates_with_vision(
    paths: AppPaths,
    media_path: Path | str,
    candidates: Sequence[CandidateMoment],
    preference: str,
    *,
    output_directory: Path,
    auto_preselect_count: int,
    max_candidates: int = 12,
    cancel_requested: CancelCheck | None = None,
) -> tuple[list[CandidateMoment], list[VisionAssessment]]:
    if not candidates or not preference.strip():
        return list(candidates), []
    try:
        from fastembed import ImageEmbedding, TextEmbedding
    except ImportError as error:
        raise RuntimeError(
            "Vision reranking dependencies are missing; install fastembed"
        ) from error
    source = Path(media_path).expanduser().resolve()
    selected = list(candidates[:max_candidates])
    frame_paths: list[Path] = []
    frame_candidate_indices: list[int] = []
    for candidate_index, candidate in enumerate(selected):
        for frame_index, timestamp in enumerate(candidate_frame_timestamps(candidate)):
            frame = output_directory / (
                f"candidate_{candidate_index:03d}_frame_{frame_index:02d}.jpg"
            )
            _extract_frame(paths, source, timestamp, frame, cancel_requested)
            frame_paths.append(frame)
            frame_candidate_indices.append(candidate_index)

    cache = paths.models / "fastembed"
    cache.mkdir(parents=True, exist_ok=True)
    text_model = TextEmbedding(model_name=TEXT_MODEL, cache_dir=str(cache))
    image_model = ImageEmbedding(model_name=IMAGE_MODEL, cache_dir=str(cache))
    query_vector = list(text_model.embed([preference.strip()]))[0]
    image_vectors = list(image_model.embed(frame_paths))
    similarities: dict[int, list[float]] = {}
    for candidate_index, vector in zip(
        frame_candidate_indices,
        image_vectors,
        strict=True,
    ):
        similarities.setdefault(candidate_index, []).append(
            cosine_similarity(query_vector, vector)
        )
    assessments = []
    for candidate_index, values in similarities.items():
        peak = max(values)
        mean = sum(values) / len(values)
        similarity = peak * 0.7 + mean * 0.3
        score = max(0.0, min(1.0, (similarity - 0.14) / 0.20))
        assessments.append(
            VisionAssessment(
                candidate_index,
                score,
                similarity,
                len(values),
            )
        )
    return (
        apply_vision_assessments(
            candidates,
            assessments,
            auto_preselect_count=auto_preselect_count,
        ),
        assessments,
    )
