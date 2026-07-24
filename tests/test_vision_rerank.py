from __future__ import annotations

import unittest

from local_clip_ai.analysis import (
    CandidateMoment,
    CondensationPlan,
    VisionAssessment,
    apply_vision_assessments,
    candidate_frame_timestamps,
)
from local_clip_ai.analysis.condensation import CondensedSpan
from local_clip_ai.media import TimeRange


def candidate(score: float, start: float = 10, end: float = 70) -> CandidateMoment:
    source_range = TimeRange(start, end)
    spans = (
        CondensedSpan(start + 2, start + 12, 0.9, "peak one"),
        CondensedSpan(end - 14, end - 4, 0.8, "peak two"),
    )
    return CandidateMoment(
        source_range,
        score,
        "Candidate",
        "speech evidence",
        CondensationPlan(source_range, 30, spans, 40),
    )


class VisionRerankTests(unittest.TestCase):
    def test_frame_timestamps_target_strong_spans_and_middle(self) -> None:
        timestamps = candidate_frame_timestamps(candidate(0.8))

        self.assertEqual(timestamps, [17, 40, 61])

    def test_visual_assessment_can_change_candidate_order(self) -> None:
        candidates = [candidate(0.8), candidate(0.7, 100, 160)]
        reranked = apply_vision_assessments(
            candidates,
            [
                VisionAssessment(0, 0.1, 0.16, 3),
                VisionAssessment(1, 1, 0.34, 3),
            ],
            auto_preselect_count=1,
        )

        self.assertEqual(reranked[0].source_range.start, 100)
        self.assertTrue(reranked[0].auto_preselected)
        self.assertFalse(reranked[1].auto_preselected)
        self.assertIn("local vision", reranked[0].rationale)


if __name__ == "__main__":
    unittest.main()
