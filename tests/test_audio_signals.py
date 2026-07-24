from __future__ import annotations

import unittest

from local_clip_ai.analysis import normalize_audio_evidence, parse_audio_rms_lines


class AudioSignalTests(unittest.TestCase):
    def test_parses_ffmpeg_metadata_pairs(self) -> None:
        readings = parse_audio_rms_lines(
            [
                "[Parsed_ametadata_3] frame:0 pts:0 pts_time:0",
                "[Parsed_ametadata_3] lavfi.astats.Overall.RMS_level=-42.5",
                "[Parsed_ametadata_3] frame:1 pts:16000 pts_time:1",
                "[Parsed_ametadata_3] lavfi.astats.Overall.RMS_level=-inf",
            ]
        )

        self.assertEqual(readings, [(0, -42.5), (1, -100)])

    def test_normalization_scores_loud_and_sudden_windows_highest(self) -> None:
        evidence = normalize_audio_evidence(
            [(0, -50), (1, -49), (2, -20), (3, -30), (4, -48)]
        )

        self.assertEqual(len(evidence), 5)
        self.assertGreater(evidence[2].score, evidence[1].score)
        self.assertGreater(evidence[2].score, 0.8)
        self.assertEqual(evidence[2].rationale, "audio energy peak")


if __name__ == "__main__":
    unittest.main()
