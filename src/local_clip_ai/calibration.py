from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from local_clip_ai.storage import JobDatabase


@dataclass(frozen=True, slots=True)
class MomentEvaluation:
    video_id: str
    start_seconds: float
    end_seconds: float
    expectation: str
    detected: bool
    candidate_rank: int | None
    candidate_start_seconds: float | None
    candidate_end_seconds: float | None
    candidate_score: float | None
    source_overlap_seconds: float
    output_overlap_seconds: float
    required_overlap_seconds: float
    output_duration_seconds: float | None
    span_count: int | None
    matching_span_count: int | None
    condensation_passed: bool

    @property
    def passed(self) -> bool:
        return self.detected and self.condensation_passed

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["passed"] = self.passed
        return values


def _overlap_seconds(
    first_start: float,
    first_end: float,
    second_start: float,
    second_end: float,
) -> float:
    return max(0.0, min(first_end, second_end) - max(first_start, second_start))


def evaluate_moment(
    video_id: str,
    moment: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> MomentEvaluation:
    start = float(moment["start_seconds"])
    end = float(moment["end_seconds"])
    ranked = sorted(candidates, key=lambda candidate: float(candidate["score"]), reverse=True)
    matches = []
    for rank, candidate in enumerate(ranked, start=1):
        source_overlap = _overlap_seconds(
            start,
            end,
            float(candidate["start_seconds"]),
            float(candidate["end_seconds"]),
        )
        span_overlaps = [
            _overlap_seconds(
                start,
                end,
                float(span["start_seconds"]),
                float(span["end_seconds"]),
            )
            for span in candidate.get("spans", [])
            if "start_seconds" in span and "end_seconds" in span
        ]
        output_overlap = sum(span_overlaps)
        matches.append(
            (
                rank,
                candidate,
                source_overlap,
                output_overlap,
                sum(overlap > 0 for overlap in span_overlaps),
            )
        )
    rank, candidate, source_overlap, output_overlap, matching_span_count = max(
        matches,
        key=lambda value: (value[3], value[2], float(value[1]["score"])),
        default=(0, None, 0, 0, 0),
    )
    required_overlap = min(20.0, max(5.0, (end - start) * 0.25))
    detected = candidate is not None and output_overlap >= required_overlap
    output_duration = (
        float(candidate["metadata"].get("output_duration_seconds", 0))
        if detected
        else None
    )
    span_count = len(candidate["spans"]) if detected else None
    condensation_passed = True
    target_max = moment.get("target_max_seconds")
    if target_max is not None:
        condensation_passed = bool(
            detected
            and output_duration is not None
            and output_duration <= float(target_max) + 0.1
        )
    if moment.get("require_multiple_source_spans"):
        condensation_passed = condensation_passed and bool(
            detected and matching_span_count >= 2
        )
    return MomentEvaluation(
        video_id=video_id,
        start_seconds=start,
        end_seconds=end,
        expectation=str(moment["expectation"]),
        detected=detected,
        candidate_rank=rank if detected else None,
        candidate_start_seconds=(
            float(candidate["start_seconds"]) if detected else None
        ),
        candidate_end_seconds=float(candidate["end_seconds"]) if detected else None,
        candidate_score=float(candidate["score"]) if detected else None,
        source_overlap_seconds=source_overlap,
        output_overlap_seconds=output_overlap,
        required_overlap_seconds=required_overlap,
        output_duration_seconds=output_duration,
        span_count=span_count,
        matching_span_count=matching_span_count if detected else None,
        condensation_passed=condensation_passed,
    )


def evaluate_manifest(
    database: JobDatabase,
    manifest: dict[str, Any],
    job_ids: dict[str, str],
) -> dict[str, Any]:
    evaluations = []
    for vod in manifest["vods"]:
        video_id = str(vod["video_id"])
        job_id = job_ids.get(video_id)
        candidates = database.list_candidates(job_id) if job_id else []
        evaluations.extend(
            evaluate_moment(video_id, moment, candidates)
            for moment in vod["moments"]
        )
    passed = sum(evaluation.passed for evaluation in evaluations)
    return {
        "schema_version": 2,
        "passed": passed,
        "total": len(evaluations),
        "recall": passed / len(evaluations) if evaluations else 0,
        "moments": [evaluation.to_dict() for evaluation in evaluations],
    }


def load_manifest(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
