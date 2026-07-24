from __future__ import annotations

import unittest

from local_clip_ai.analysis.condensation import CondensedSpan
from local_clip_ai.media.export import build_concat_filter


class ExportTests(unittest.TestCase):
    def test_filter_graph_keeps_chronological_spans_and_applies_offset(self) -> None:
        graph = build_concat_filter(
            [
                CondensedSpan(5220, 5240, 0.8, "setup"),
                CondensedSpan(5290, 5310, 1.0, "payoff"),
                CondensedSpan(5350, 5370, 0.9, "reaction"),
            ],
            source_offset_seconds=5200,
        )

        self.assertIn("trim=start=20.000000:end=40.000000", graph)
        self.assertIn("atrim=start=90.000000:end=110.000000", graph)
        self.assertTrue(graph.endswith("concat=n=3:v=1:a=1[outv][outa]"))

    def test_filter_graph_rejects_overlapping_spans(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-overlapping"):
            build_concat_filter(
                [
                    CondensedSpan(10, 20, 0.9, "one"),
                    CondensedSpan(19, 30, 0.8, "two"),
                ]
            )
