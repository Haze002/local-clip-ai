from __future__ import annotations

import math
import re
from dataclasses import dataclass

from local_clip_ai.analysis.condensation import (
    CondensationPlan,
    EvidenceWindow,
    condense_moment,
)
from local_clip_ai.analysis.transcription import TranscriptSegment
from local_clip_ai.config import ContentProfile
from local_clip_ai.media.timecodes import TimeRange, format_timecode

REACTION_TERMS = {
    "amazing",
    "bro",
    "damn",
    "fuck",
    "holy",
    "insane",
    "laugh",
    "lol",
    "no way",
    "oh my god",
    "shit",
    "what",
    "wow",
}
STOP_WORDS = {
    "about",
    "after",
    "again",
    "clear",
    "from",
    "into",
    "moment",
    "moments",
    "that",
    "their",
    "then",
    "this",
    "with",
}
WORD_PATTERN = re.compile(r"[\w']+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class CandidateMoment:
    source_range: TimeRange
    score: float
    title: str
    rationale: str
    condensation: CondensationPlan
    auto_preselected: bool = False


def _words(text: str) -> list[str]:
    return [word.lower() for word in WORD_PATTERN.findall(text)]


def _preference_keywords(preference: str) -> set[str]:
    return {
        word
        for word in _words(preference)
        if len(word) >= 4 and word not in STOP_WORDS
    }


def _filter_repetitive_transcript_runs(
    segments: tuple[TranscriptSegment, ...] | list[TranscriptSegment],
) -> list[TranscriptSegment]:
    """Drop long one/two-word music hallucinations while retaining real reactions."""
    filtered: list[TranscriptSegment] = []
    run: list[TranscriptSegment] = []
    run_text = ""

    def flush() -> None:
        if not run:
            return
        duration = run[-1].end_seconds - run[0].start_seconds
        repeated_short_phrase = len(_words(run_text)) <= 2 and len(run_text) <= 16
        if not (len(run) >= 8 and duration >= 20 and repeated_short_phrase):
            filtered.extend(run)

    for segment in segments:
        normalized = " ".join(_words(segment.text))
        continues = (
            bool(run)
            and normalized == run_text
            and segment.start_seconds - run[-1].end_seconds <= 6
        )
        if not continues:
            flush()
            run = [segment]
            run_text = normalized
        else:
            run.append(segment)
    flush()
    return filtered


def _reaction_score(text: str) -> tuple[float, list[str]]:
    lower = text.lower()
    matched = sorted(term for term in REACTION_TERMS if term in lower)
    punctuation = min(1.0, (text.count("!") + text.count("?")) / 3)
    repeated = 1.0 if re.search(r"\b(\w+)(?:\s+\1){1,}\b", lower) else 0.0
    term_score = min(1.0, len(matched) / 3)
    score = min(1.0, term_score * 0.65 + punctuation * 0.2 + repeated * 0.15)
    reasons = []
    if matched:
        reasons.append("reaction language")
    if punctuation:
        reasons.append("question/exclamation")
    if repeated:
        reasons.append("repeated speech")
    return score, reasons


def score_transcript_segments(
    segments: tuple[TranscriptSegment, ...] | list[TranscriptSegment],
    content_profile: ContentProfile,
    audio_evidence: list[EvidenceWindow] | None = None,
    visual_evidence: list[EvidenceWindow] | None = None,
    semantic_evidence: list[EvidenceWindow] | None = None,
) -> list[EvidenceWindow]:
    preference = _preference_keywords(content_profile.preference)
    audio = audio_evidence or []
    visual = visual_evidence or []
    semantic = semantic_evidence or []
    evidence: list[EvidenceWindow] = []
    for segment in segments:
        duration = max(0.5, segment.end_seconds - segment.start_seconds)
        reaction, reasons = _reaction_score(segment.text)
        words = _words(segment.text)
        speech_density = min(1.0, len(words) / duration / 3.5)
        matched_preferences = preference.intersection(words)
        preference_score = min(1.0, len(matched_preferences) / max(1, len(preference) // 4))
        overlapping_audio = [
            item.score
            for item in audio
            if item.end_seconds > segment.start_seconds
            and item.start_seconds < segment.end_seconds
        ]
        audio_score = max(overlapping_audio, default=0.35)
        overlapping_visual = [
            item.score
            for item in visual
            if item.end_seconds > segment.start_seconds
            and item.start_seconds < segment.end_seconds
        ]
        visual_score = max(overlapping_visual, default=0.2)
        overlapping_semantic = [
            item.score
            for item in semantic
            if item.end_seconds > segment.start_seconds
            and item.start_seconds < segment.end_seconds
        ]
        semantic_score = max(overlapping_semantic, default=0.2)
        confidence = max(0.0, min(1.0, math.exp(segment.avg_log_probability)))
        score = (
            reaction * 0.38
            + speech_density * 0.15
            + audio_score * 0.15
            + visual_score * 0.08
            + semantic_score * 0.15
            + preference_score * 0.04
            + confidence * 0.05
        )
        if speech_density > 0.65:
            reasons.append("dense speech")
        if overlapping_audio and audio_score > 0.65:
            reasons.append("audio peak")
        if matched_preferences:
            reasons.append("content preference match")
        if overlapping_visual and visual_score > 0.6:
            reasons.append("visual activity")
        if overlapping_semantic and semantic_score > 0.6:
            reasons.append("semantic preference match")
        evidence.append(
            EvidenceWindow(
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                score=max(0, min(1, score)),
                rationale=", ".join(reasons) or "speech activity",
            )
        )
    return evidence


def _group_evidence(
    evidence: list[EvidenceWindow],
    *,
    threshold: float,
    max_gap_seconds: float,
    max_source_seconds: float,
) -> list[list[EvidenceWindow]]:
    interesting = [item for item in evidence if item.score >= threshold]
    if not interesting and evidence:
        interesting = sorted(evidence, key=lambda item: item.score, reverse=True)[:3]
    groups: list[list[EvidenceWindow]] = []
    for item in sorted(interesting, key=lambda value: value.start_seconds):
        if (
            not groups
            or item.start_seconds - groups[-1][-1].end_seconds > max_gap_seconds
            or item.end_seconds - groups[-1][0].start_seconds > max_source_seconds
        ):
            groups.append([item])
        else:
            groups[-1].append(item)
    return groups


def _overlap_ratio(first: TimeRange, second: TimeRange) -> float:
    overlap = max(0.0, min(first.end, second.end) - max(first.start, second.start))
    union = max(first.end, second.end) - min(first.start, second.start)
    return overlap / union


def _candidate_title(
    strongest: EvidenceWindow,
    segments: tuple[TranscriptSegment, ...] | list[TranscriptSegment],
) -> str:
    overlapping = [
        segment
        for segment in segments
        if segment.end_seconds > strongest.start_seconds
        and segment.start_seconds < strongest.end_seconds
        and segment.text.strip()
    ]
    if not overlapping:
        return f"Visual/audio highlight at {format_timecode(strongest.start_seconds)}"
    excerpt = max(
        overlapping,
        key=lambda segment: min(segment.end_seconds, strongest.end_seconds)
        - max(segment.start_seconds, strongest.start_seconds),
    ).text.strip()
    if len(excerpt) > 64:
        excerpt = excerpt[:61].rstrip() + "..."
    return f"{format_timecode(strongest.start_seconds)} — {excerpt}"


def _group_rationale(group: list[EvidenceWindow]) -> str:
    reasons = []
    for item in sorted(group, key=lambda value: value.score, reverse=True):
        reason = item.rationale.strip()
        if reason and reason.casefold() not in {value.casefold() for value in reasons}:
            reasons.append(reason)
        if len(reasons) >= 4:
            break
    return "; ".join(reasons) or "combined local evidence"


def discover_candidates(
    segments: tuple[TranscriptSegment, ...] | list[TranscriptSegment],
    content_profile: ContentProfile,
    *,
    audio_evidence: list[EvidenceWindow] | None = None,
    visual_evidence: list[EvidenceWindow] | None = None,
    semantic_evidence: list[EvidenceWindow] | None = None,
    score_threshold: float = 0.36,
) -> list[CandidateMoment]:
    filtered_segments = _filter_repetitive_transcript_runs(segments)
    audio = audio_evidence or []
    visual = visual_evidence or []
    semantic = semantic_evidence or []
    evidence = score_transcript_segments(
        filtered_segments,
        content_profile,
        audio,
        visual,
        semantic,
    )
    evidence.extend(
        EvidenceWindow(
            item.start_seconds,
            item.end_seconds,
            min(1.0, 0.36 + item.score * 0.42),
            item.rationale,
        )
        for item in audio
        if item.score >= 0.72
    )
    evidence.extend(
        EvidenceWindow(
            item.start_seconds,
            item.end_seconds,
            min(1.0, 0.32 + item.score * 0.48),
            item.rationale,
        )
        for item in visual
        if item.score >= 0.58
    )
    evidence.extend(
        EvidenceWindow(
            item.start_seconds,
            item.end_seconds,
            min(1.0, 0.3 + item.score * 0.5),
            item.rationale,
        )
        for item in semantic
        if item.score >= 0.62
    )
    broad_groups = _group_evidence(
        evidence,
        threshold=score_threshold,
        max_gap_seconds=55,
        max_source_seconds=180,
    )
    focused_groups: list[list[EvidenceWindow]] = []
    long_groups = [
        group
        for group in broad_groups
        if group[-1].end_seconds - group[0].start_seconds >= 150
    ]
    if long_groups:
        focused_groups = [
            group
            for group in _group_evidence(
                evidence,
                threshold=score_threshold,
                max_gap_seconds=20,
                max_source_seconds=75,
            )
            if any(
                group[0].start_seconds >= broad[0].start_seconds
                and group[-1].end_seconds <= broad[-1].end_seconds
                for broad in long_groups
            )
        ]

    def build_moments(groups: list[list[EvidenceWindow]]) -> list[CandidateMoment]:
        moments = []
        for group in groups:
            start = max(
                0.0,
                group[0].start_seconds - content_profile.setup_context_seconds,
            )
            end = group[-1].end_seconds + content_profile.payoff_context_seconds
            source_range = TimeRange(start, end)
            condensation = condense_moment(
                source_range,
                group,
                target_max_seconds=content_profile.target_max_seconds,
                context_seconds=content_profile.setup_context_seconds,
            )
            peak = max(item.score for item in group)
            mean = sum(item.score for item in group) / len(group)
            score = min(1.0, peak * 0.7 + mean * 0.3)
            strongest = max(group, key=lambda item: item.score)
            moments.append(
                CandidateMoment(
                    source_range=source_range,
                    score=score,
                    title=_candidate_title(strongest, filtered_segments),
                    rationale=_group_rationale(group),
                    condensation=condensation,
                )
            )
        return moments

    broad_candidates = build_moments(broad_groups)
    focused_candidates = build_moments(focused_groups)
    ranked: list[CandidateMoment] = []
    focused_limit = (
        max(1, content_profile.max_candidates // 5) if focused_candidates else 0
    )
    broad_limit = content_profile.max_candidates - focused_limit

    def append_pool(pool: list[CandidateMoment], limit: int) -> None:
        added = 0
        for candidate in sorted(pool, key=lambda item: item.score, reverse=True):
            if added >= limit:
                break
            if any(
                _overlap_ratio(candidate.source_range, existing.source_range) >= 0.7
                for existing in ranked
            ):
                continue
            ranked.append(candidate)
            added += 1

    append_pool(broad_candidates, broad_limit)
    append_pool(focused_candidates, focused_limit)
    if len(ranked) < content_profile.max_candidates:
        append_pool(
            [
                candidate
                for candidate in [*broad_candidates, *focused_candidates]
                if candidate not in ranked
            ],
            content_profile.max_candidates - len(ranked),
        )
    ranked.sort(key=lambda item: item.score, reverse=True)
    return [
        CandidateMoment(
            source_range=item.source_range,
            score=item.score,
            title=item.title,
            rationale=item.rationale,
            condensation=item.condensation,
            auto_preselected=index < content_profile.auto_preselect_count,
        )
        for index, item in enumerate(ranked)
    ]
