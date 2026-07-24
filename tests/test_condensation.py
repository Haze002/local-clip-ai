from __future__ import annotations

import unittest

from local_clip_ai.analysis.condensation import EvidenceWindow, condense_moment
from local_clip_ai.media import TimeRange


class CondensationTests(unittest.TestCase):
    def test_long_moment_becomes_multiple_chronological_spans(self) -> None:
        source = TimeRange(5220, 5370)
        evidence = [
            EvidenceWindow(5228, 5236, 0.88, "setup"),
            EvidenceWindow(5286, 5296, 1.0, "payoff"),
            EvidenceWindow(5354, 5364, 0.93, "reaction"),
            EvidenceWindow(5310, 5320, 0.2, "low-value middle"),
        ]

        plan = condense_moment(
            source,
            evidence,
            target_max_seconds=60,
            context_seconds=5,
        )

        self.assertGreaterEqual(len(plan.spans), 2)
        self.assertLessEqual(plan.output_duration_seconds, 60.0001)
        self.assertEqual(
            list(plan.spans),
            sorted(plan.spans, key=lambda span: span.start_seconds),
        )
        self.assertGreaterEqual(plan.removed_seconds, 90)

    def test_short_moment_remains_intact(self) -> None:
        source = TimeRange(100, 135)

        plan = condense_moment(source, [], target_max_seconds=60)

        self.assertEqual(len(plan.spans), 1)
        self.assertEqual(plan.output_duration_seconds, 35)

    def test_no_evidence_uses_bounded_fallback(self) -> None:
        plan = condense_moment(TimeRange(0, 150), [], target_max_seconds=60)

        self.assertEqual(plan.output_duration_seconds, 60)
        self.assertEqual(plan.spans[0].start_seconds, 45)
