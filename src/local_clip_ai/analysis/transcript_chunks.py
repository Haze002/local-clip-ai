from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TranscriptionChunk:
    index: int
    start_seconds: float
    end_seconds: float


def plan_transcription_chunks(
    duration_seconds: float,
    *,
    chunk_seconds: float = 900,
    overlap_seconds: float = 5,
) -> list[TranscriptionChunk]:
    if duration_seconds <= 0:
        raise ValueError("Media duration must be positive")
    if chunk_seconds <= 0:
        raise ValueError("Chunk duration must be positive")
    if not 0 <= overlap_seconds < chunk_seconds:
        raise ValueError("Chunk overlap must be non-negative and shorter than a chunk")
    chunks = []
    start = 0.0
    index = 0
    while start < duration_seconds:
        end = min(duration_seconds, start + chunk_seconds)
        chunks.append(TranscriptionChunk(index, start, end))
        if end >= duration_seconds:
            break
        start = end - overlap_seconds
        index += 1
    return chunks


def _segment_overlap(first: dict[str, Any], second: dict[str, Any]) -> float:
    overlap = max(
        0.0,
        min(float(first["end_seconds"]), float(second["end_seconds"]))
        - max(float(first["start_seconds"]), float(second["start_seconds"])),
    )
    shortest = min(
        float(first["end_seconds"]) - float(first["start_seconds"]),
        float(second["end_seconds"]) - float(second["start_seconds"]),
    )
    return overlap / shortest if shortest > 0 else 0


def merge_transcript_documents(documents: list[dict[str, Any]]) -> dict[str, Any]:
    if not documents:
        raise ValueError("At least one transcript chunk is required")
    all_segments = [
        dict(segment)
        for document in documents
        for segment in document.get("segments", [])
    ]
    all_segments.sort(
        key=lambda segment: (
            float(segment["start_seconds"]),
            float(segment["end_seconds"]),
        )
    )
    merged: list[dict[str, Any]] = []
    for segment in all_segments:
        if not merged:
            merged.append(segment)
            continue
        previous = merged[-1]
        same_text = _normalized_text(previous) == _normalized_text(segment)
        if _segment_overlap(previous, segment) >= 0.5 and same_text:
            if _confidence(segment) > _confidence(previous):
                merged[-1] = segment
            continue
        merged.append(segment)
    first = documents[0]
    return {
        "media_path": first.get("media_path"),
        "model": first.get("model"),
        "device": first.get("device"),
        "compute_type": first.get("compute_type"),
        "language": first.get("language"),
        "language_probability": max(
            float(document.get("language_probability", 0))
            for document in documents
        ),
        "duration_seconds": max(
            float(document.get("duration_seconds", 0))
            for document in documents
        ),
        "elapsed_seconds": sum(
            float(document.get("elapsed_seconds", 0))
            for document in documents
        ),
        "source_offset_seconds": 0,
        "segments": merged,
        "chunk_count": len(documents),
    }


def _normalized_text(segment: dict[str, Any]) -> str:
    return " ".join(str(segment.get("text", "")).casefold().split())


def _confidence(segment: dict[str, Any]) -> float:
    return float(segment.get("avg_log_probability", float("-inf")))
