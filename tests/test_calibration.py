from __future__ import annotations

import unittest

from local_clip_ai.calibration import evaluate_moment


class CalibrationEvaluationTests(unittest.TestCase):
    def test_long_moment_requires_budget_and_multiple_spans(self) -> None:
        moment = {
            "start_seconds": 100,
            "end_seconds": 250,
            "expectation": "highlight_requiring_condensation",
            "target_max_seconds": 60,
            "require_multiple_source_spans": True,
        }
        candidate = {
            "start_seconds": 95,
            "end_seconds": 255,
            "score": 0.9,
            "metadata": {"output_duration_seconds": 55},
            "spans": [
                {"position": 0, "start_seconds": 110, "end_seconds": 130},
                {"position": 1, "start_seconds": 200, "end_seconds": 235},
            ],
        }

        result = evaluate_moment("123", moment, [candidate])

        self.assertTrue(result.detected)
        self.assertTrue(result.condensation_passed)
        self.assertTrue(result.passed)

    def test_small_boundary_touch_does_not_count_as_detection(self) -> None:
        moment = {
            "start_seconds": 100,
            "end_seconds": 130,
            "expectation": "highlight",
        }
        candidate = {
            "start_seconds": 129,
            "end_seconds": 150,
            "score": 0.9,
            "metadata": {"output_duration_seconds": 21},
            "spans": [
                {"position": 0, "start_seconds": 129, "end_seconds": 150},
            ],
        }

        result = evaluate_moment("123", moment, [candidate])

        self.assertFalse(result.detected)
        self.assertFalse(result.passed)

    def test_broad_source_window_does_not_pass_when_exported_spans_miss_label(self) -> None:
        moment = {
            "start_seconds": 100,
            "end_seconds": 130,
            "expectation": "highlight",
        }
        candidate = {
            "start_seconds": 80,
            "end_seconds": 150,
            "score": 0.9,
            "metadata": {"output_duration_seconds": 20},
            "spans": [
                {"position": 0, "start_seconds": 80, "end_seconds": 90},
                {"position": 1, "start_seconds": 140, "end_seconds": 150},
            ],
        }

        result = evaluate_moment("123", moment, [candidate])

        self.assertEqual(result.source_overlap_seconds, 30)
        self.assertEqual(result.output_overlap_seconds, 0)
        self.assertFalse(result.detected)


if __name__ == "__main__":
    unittest.main()
