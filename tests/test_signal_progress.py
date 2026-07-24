from __future__ import annotations

import unittest

from local_clip_ai.analysis.signal_progress import metadata_progress_reporter


class SignalProgressTests(unittest.TestCase):
    def test_reports_throttled_metadata_fractions(self) -> None:
        values: list[float] = []
        reporter = metadata_progress_reporter(100, values.append, minimum_step=0.1)
        assert reporter is not None

        reporter("[metadata] pts_time:0")
        reporter("[metadata] pts_time:5")
        reporter("[metadata] pts_time:10")
        reporter("[metadata] pts_time:19")
        reporter("[metadata] pts_time:20")
        reporter("[metadata] pts_time:120")

        self.assertEqual(values, [0, 0.1, 0.2, 1])

    def test_disabled_without_known_duration(self) -> None:
        self.assertIsNone(metadata_progress_reporter(None, lambda _: None))


if __name__ == "__main__":
    unittest.main()
