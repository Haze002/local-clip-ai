from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class AnalysisMode(StrEnum):
    QUICK = "quick"
    BALANCED = "balanced"
    DEEP = "deep"


@dataclass(frozen=True, slots=True)
class ContentProfile:
    preference: str = "Funny, exciting, surprising, or skillful moments with a clear payoff."
    language: str = "auto"
    target_min_seconds: float = 20
    target_max_seconds: float = 60
    setup_context_seconds: float = 4
    payoff_context_seconds: float = 3
    max_candidates: int = 30
    auto_preselect_count: int = 10

    def __post_init__(self) -> None:
        if self.target_min_seconds <= 0:
            raise ValueError("Minimum clip length must be positive")
        if self.target_max_seconds < self.target_min_seconds:
            raise ValueError("Maximum clip length cannot be shorter than the minimum")
        if self.auto_preselect_count > self.max_candidates:
            raise ValueError("Preselection count cannot exceed maximum candidates")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnalysisProfile:
    mode: AnalysisMode
    transcription_model: str
    transcription_compute_type: str
    beam_size: int
    audio_signal_resolution_seconds: float
    frame_sample_interval_seconds: float | None
    semantic_rerank: bool
    vision_rerank: bool
    source_quality_candidate_downloads: bool
    gpu_vram_soft_limit_gib: float = 10.5

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["mode"] = self.mode.value
        return values


def default_content_profile() -> ContentProfile:
    return ContentProfile()


def default_analysis_profile(mode: AnalysisMode | str) -> AnalysisProfile:
    selected = AnalysisMode(mode)
    if selected is AnalysisMode.QUICK:
        return AnalysisProfile(
            mode=selected,
            transcription_model="small",
            transcription_compute_type="int8_float16",
            beam_size=2,
            audio_signal_resolution_seconds=1.0,
            frame_sample_interval_seconds=None,
            semantic_rerank=True,
            vision_rerank=False,
            source_quality_candidate_downloads=True,
        )
    if selected is AnalysisMode.BALANCED:
        return AnalysisProfile(
            mode=selected,
            transcription_model="large-v3-turbo",
            transcription_compute_type="float16",
            beam_size=4,
            audio_signal_resolution_seconds=0.5,
            frame_sample_interval_seconds=4.0,
            semantic_rerank=True,
            vision_rerank=False,
            source_quality_candidate_downloads=True,
        )
    return AnalysisProfile(
        mode=selected,
        transcription_model="large-v3-turbo",
        transcription_compute_type="float16",
        beam_size=5,
        audio_signal_resolution_seconds=0.25,
        frame_sample_interval_seconds=1.5,
        semantic_rerank=True,
        vision_rerank=True,
        source_quality_candidate_downloads=True,
    )
