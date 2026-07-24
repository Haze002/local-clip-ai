from __future__ import annotations

from dataclasses import dataclass

from local_clip_ai.media.timecodes import TimeRange


@dataclass(frozen=True, slots=True)
class EvidenceWindow:
    start_seconds: float
    end_seconds: float
    score: float
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Evidence window end must be after its start")
        if not 0 <= self.score <= 1:
            raise ValueError("Evidence score must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class CondensedSpan:
    start_seconds: float
    end_seconds: float
    score: float
    rationale: str

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


@dataclass(frozen=True, slots=True)
class CondensationPlan:
    source_range: TimeRange
    target_max_seconds: float
    spans: tuple[CondensedSpan, ...]
    removed_seconds: float

    @property
    def output_duration_seconds(self) -> float:
        return sum(span.duration_seconds for span in self.spans)


def _merge_ranges(
    ranges: list[tuple[float, float, float, str]],
    merge_gap_seconds: float,
) -> list[tuple[float, float, float, str]]:
    merged: list[tuple[float, float, float, str]] = []
    for start, end, score, rationale in sorted(ranges):
        if not merged or start - merged[-1][1] > merge_gap_seconds:
            merged.append((start, end, score, rationale))
            continue
        old_start, old_end, old_score, old_rationale = merged[-1]
        combined_rationale = " / ".join(
            value for value in (old_rationale, rationale) if value
        )
        merged[-1] = (
            old_start,
            max(old_end, end),
            max(old_score, score),
            combined_rationale,
        )
    return merged


def _total_duration(ranges: list[tuple[float, float, float, str]]) -> float:
    return sum(end - start for start, end, _, _ in ranges)


def condense_moment(
    source_range: TimeRange,
    evidence: list[EvidenceWindow],
    *,
    target_max_seconds: float,
    context_seconds: float = 4,
    merge_gap_seconds: float = 2,
    max_spans: int = 5,
) -> CondensationPlan:
    if target_max_seconds <= 0:
        raise ValueError("Target duration must be positive")
    if source_range.duration <= target_max_seconds:
        span = CondensedSpan(
            source_range.start,
            source_range.end,
            max((item.score for item in evidence), default=1),
            "Within target duration; no cuts needed.",
        )
        return CondensationPlan(source_range, target_max_seconds, (span,), 0)

    relevant = [
        item
        for item in evidence
        if item.end_seconds > source_range.start and item.start_seconds < source_range.end
    ]
    if not relevant:
        midpoint = (source_range.start + source_range.end) / 2
        half = target_max_seconds / 2
        start = max(source_range.start, midpoint - half)
        end = min(source_range.end, start + target_max_seconds)
        span = CondensedSpan(start, end, 0, "Fallback centered span; no evidence available.")
        return CondensationPlan(
            source_range,
            target_max_seconds,
            (span,),
            source_range.duration - span.duration_seconds,
        )

    selected: list[tuple[float, float, float, str]] = []
    for item in sorted(relevant, key=lambda value: value.score, reverse=True):
        start = max(source_range.start, item.start_seconds - context_seconds)
        end = min(source_range.end, item.end_seconds + context_seconds)
        proposal = _merge_ranges(
            [*selected, (start, end, item.score, item.rationale)],
            merge_gap_seconds,
        )
        if len(proposal) <= max_spans and _total_duration(proposal) <= target_max_seconds:
            selected = proposal

    if not selected:
        strongest = max(relevant, key=lambda value: value.score)
        midpoint = (strongest.start_seconds + strongest.end_seconds) / 2
        start = max(source_range.start, midpoint - target_max_seconds / 2)
        end = min(source_range.end, start + target_max_seconds)
        selected = [(start, end, strongest.score, strongest.rationale)]

    remaining = target_max_seconds - _total_duration(selected)
    if remaining > 0:
        expanded: list[tuple[float, float, float, str]] = []
        per_side = remaining / (2 * len(selected))
        for index, (start, end, score, rationale) in enumerate(selected):
            left_limit = source_range.start if index == 0 else selected[index - 1][1]
            right_limit = (
                source_range.end if index == len(selected) - 1 else selected[index + 1][0]
            )
            expanded.append(
                (
                    max(left_limit, start - per_side),
                    min(right_limit, end + per_side),
                    score,
                    rationale,
                )
            )
        selected = _merge_ranges(expanded, merge_gap_seconds)

    spans = tuple(
        CondensedSpan(start, end, score, rationale or "High-scoring evidence")
        for start, end, score, rationale in selected
    )
    output_duration = sum(span.duration_seconds for span in spans)
    return CondensationPlan(
        source_range=source_range,
        target_max_seconds=target_max_seconds,
        spans=spans,
        removed_seconds=max(0, source_range.duration - output_duration),
    )
