from __future__ import annotations

import unittest

from local_clip_ai.media import TimeRange, format_timecode, parse_timecode


class TimecodeTests(unittest.TestCase):
    def test_parses_calibration_timecodes(self) -> None:
        self.assertEqual(parse_timecode("03:00:05"), 10805)
        self.assertEqual(parse_timecode("01:29:30"), 5370)

    def test_formats_fractional_timecodes(self) -> None:
        self.assertEqual(format_timecode(5370.125), "01:29:30.125")

    def test_range_reports_duration(self) -> None:
        value = TimeRange.from_timecodes("01:27:00", "01:29:30")

        self.assertEqual(value.duration, 150)

    def test_rejects_reversed_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "after"):
            TimeRange(10, 9)
