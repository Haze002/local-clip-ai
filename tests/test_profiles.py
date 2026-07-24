from __future__ import annotations

import unittest

from local_clip_ai.config import (
    AnalysisMode,
    ContentProfile,
    default_analysis_profile,
)


class ProfileTests(unittest.TestCase):
    def test_analysis_modes_enable_progressively_deeper_signals(self) -> None:
        quick = default_analysis_profile(AnalysisMode.QUICK)
        balanced = default_analysis_profile(AnalysisMode.BALANCED)
        deep = default_analysis_profile(AnalysisMode.DEEP)

        self.assertIsNone(quick.frame_sample_interval_seconds)
        self.assertIsNotNone(balanced.frame_sample_interval_seconds)
        self.assertTrue(deep.vision_rerank)
        self.assertLess(deep.frame_sample_interval_seconds, balanced.frame_sample_interval_seconds)

    def test_content_profile_rejects_invalid_duration_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "Maximum"):
            ContentProfile(target_min_seconds=90, target_max_seconds=60)
