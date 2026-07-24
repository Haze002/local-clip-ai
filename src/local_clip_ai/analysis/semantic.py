from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from local_clip_ai.analysis.condensation import EvidenceWindow
from local_clip_ai.analysis.transcription import TranscriptSegment
from local_clip_ai.paths import AppPaths

DEFAULT_TEXT_MODEL = "BAAI/bge-small-en-v1.5"


@dataclass(frozen=True, slots=True)
class SemanticPassage:
    start_seconds: float
    end_seconds: float
    text: str


def build_semantic_passages(
    segments: Sequence[TranscriptSegment],
    *,
    max_duration_seconds: float = 35,
    max_gap_seconds: float = 8,
) -> list[SemanticPassage]:
    passages: list[SemanticPassage] = []
    current: list[TranscriptSegment] = []
    for segment in segments:
        would_exceed_duration = (
            bool(current)
            and segment.end_seconds - current[0].start_seconds > max_duration_seconds
        )
        gap_too_large = (
            bool(current)
            and segment.start_seconds - current[-1].end_seconds > max_gap_seconds
        )
        if current and (would_exceed_duration or gap_too_large):
            passages.append(_passage_from_segments(current))
            current = []
        current.append(segment)
    if current:
        passages.append(_passage_from_segments(current))
    return passages


def _passage_from_segments(segments: list[TranscriptSegment]) -> SemanticPassage:
    return SemanticPassage(
        segments[0].start_seconds,
        segments[-1].end_seconds,
        " ".join(segment.text.strip() for segment in segments if segment.text.strip()),
    )


def cosine_similarity(first: Sequence[float], second: Sequence[float]) -> float:
    if len(first) != len(second):
        raise ValueError("Embedding vectors must have equal dimensions")
    dot = sum(float(left) * float(right) for left, right in zip(first, second, strict=True))
    first_norm = math.sqrt(sum(float(value) ** 2 for value in first))
    second_norm = math.sqrt(sum(float(value) ** 2 for value in second))
    if first_norm == 0 or second_norm == 0:
        return 0
    return dot / (first_norm * second_norm)


def semantic_evidence_from_vectors(
    passages: Sequence[SemanticPassage],
    query_vector: Sequence[float],
    passage_vectors: Sequence[Sequence[float]],
) -> list[EvidenceWindow]:
    if len(passages) != len(passage_vectors):
        raise ValueError("Every semantic passage needs one embedding")
    evidence = []
    for passage, vector in zip(passages, passage_vectors, strict=True):
        similarity = cosine_similarity(query_vector, vector)
        score = max(0.0, min(1.0, (similarity - 0.20) / 0.55))
        evidence.append(
            EvidenceWindow(
                passage.start_seconds,
                passage.end_seconds,
                score,
                f"content preference semantic match ({similarity:.0%})",
            )
        )
    return evidence


def extract_semantic_evidence(
    paths: AppPaths,
    segments: Sequence[TranscriptSegment],
    preference: str,
    *,
    model_name: str = DEFAULT_TEXT_MODEL,
) -> list[EvidenceWindow]:
    passages = build_semantic_passages(segments)
    if not passages or not preference.strip():
        return []
    try:
        from fastembed import TextEmbedding
    except ImportError as error:
        raise RuntimeError(
            "Semantic analysis dependencies are missing; install the semantic extra"
        ) from error
    cache = paths.models / "fastembed"
    cache.mkdir(parents=True, exist_ok=True)
    model = TextEmbedding(model_name=model_name, cache_dir=str(cache))
    texts = [
        f"query: {preference.strip()}",
        *(f"passage: {passage.text}" for passage in passages),
    ]
    vectors = list(model.embed(texts))
    return semantic_evidence_from_vectors(passages, vectors[0], vectors[1:])
