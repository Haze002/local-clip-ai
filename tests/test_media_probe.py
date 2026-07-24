from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from local_clip_ai.media.probe import parse_ffprobe


class MediaProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        self.root.mkdir(parents=True)
        self.media = self.root / "section.mp4"
        self.media.write_bytes(b"test media placeholder")

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_parses_video_and_audio_streams(self) -> None:
        probe = parse_ffprobe(
            {
                "format": {"duration": "30.125", "format_name": "mov,mp4"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                    },
                    {
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "48000",
                    },
                ],
            },
            self.media,
        )

        self.assertEqual(probe.duration_seconds, 30.125)
        self.assertEqual((probe.video_codec, probe.width, probe.height), ("h264", 1920, 1080))
        self.assertEqual((probe.audio_codec, probe.sample_rate), ("aac", 48000))
