from __future__ import annotations

import unittest

from local_clip_ai.analysis import EvidenceWindow, discover_candidates
from local_clip_ai.analysis.transcription import TranscriptSegment
from local_clip_ai.config import ContentProfile


def segment(start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(
        start_seconds=start,
        end_seconds=end,
        text=text,
        avg_log_probability=-0.1,
        no_speech_probability=0.01,
    )


class CandidateDiscoveryTests(unittest.TestCase):
    def test_reaction_language_is_ranked_and_preselected(self) -> None:
        segments = [
            segment(0, 6, "we are walking to the next room"),
            segment(40, 47, "what the fuck, no way, that is insane!"),
            segment(90, 96, "we can put this item into storage"),
        ]

        candidates = discover_candidates(segments, ContentProfile())

        self.assertGreaterEqual(len(candidates), 1)
        self.assertTrue(candidates[0].auto_preselected)
        self.assertIn("reaction", candidates[0].rationale)
        self.assertLessEqual(
            candidates[0].condensation.output_duration_seconds,
            60,
        )

    def test_extended_reaction_can_be_condensed_from_separate_peaks(self) -> None:
        segments = [
            segment(0, 8, "holy shit what is this!"),
            segment(50, 58, "wow no way that worked!"),
            segment(108, 116, "that is insane bro!"),
        ]
        profile = ContentProfile(
            target_max_seconds=45,
            setup_context_seconds=4,
            payoff_context_seconds=4,
        )

        candidates = discover_candidates(segments, profile)

        self.assertEqual(len(candidates), 1)
        self.assertGreaterEqual(len(candidates[0].condensation.spans), 2)
        self.assertLessEqual(candidates[0].condensation.output_duration_seconds, 45.0001)

    def test_silent_visual_peak_can_create_candidate(self) -> None:
        candidates = discover_candidates(
            [],
            ContentProfile(),
            visual_evidence=[
                EvidenceWindow(120, 121, 0.95, "strong scene change"),
            ],
        )

        self.assertEqual(len(candidates), 1)
        self.assertIn("scene", candidates[0].rationale)
