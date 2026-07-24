from __future__ import annotations

import unittest

from local_clip_ai.analysis import normalize_scene_evidence, parse_scene_lines


class VisualSignalTests(unittest.TestCase):
    def test_parses_scene_metadata_and_aggregates_each_second(self) -> None:
        readings = parse_scene_lines(
            [
                "[metadata] frame:0 pts:160 pts_time:10.1",
                "[metadata] lavfi.scene_score=0.200000",
                "[metadata] frame:1 pts:168 pts_time:10.6",
                "[metadata] lavfi.scene_score=0.500000",
                "[metadata] frame:2 pts:200 pts_time:12.0",
                "[metadata] lavfi.scene_score=0.100000",
            ]
        )
        evidence = normalize_scene_evidence(readings)

        self.assertEqual(readings, [(10.1, 0.2), (10.6, 0.5), (12, 0.1)])
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0].start_seconds, 10)
        self.assertEqual(evidence[0].score, 1)
        self.assertEqual(evidence[0].rationale, "strong scene change")


if __name__ == "__main__":
    unittest.main()
