from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from local_clip_ai.analysis import transcribe_media
from local_clip_ai.config import default_analysis_profile
from local_clip_ai.paths import AppPaths


class TranscriptionFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        self.paths = AppPaths.from_root(self.root)
        self.paths.ensure_directories()
        self.media = self.root / "audio.mp4"
        self.media.write_bytes(b"placeholder")

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_cuda_out_of_memory_retries_on_cpu_before_any_segments(self) -> None:
        devices: list[str] = []

        class FakeWhisperModel:
            def __init__(self, _model: str, *, device: str, **_: object):
                devices.append(device)
                if device == "cuda":
                    raise RuntimeError("CUDA out of memory: failed to allocate buffer")

            def transcribe(self, *_: object, **__: object) -> tuple[object, object]:
                info = SimpleNamespace(
                    language="en",
                    language_probability=0.99,
                    duration=1,
                )
                return iter(()), info

        fake_module = SimpleNamespace(WhisperModel=FakeWhisperModel)
        with (
            patch.dict(sys.modules, {"faster_whisper": fake_module}),
            patch(
                "local_clip_ai.analysis.transcription.cuda_is_available",
                return_value=True,
            ),
        ):
            transcript = transcribe_media(
                self.paths,
                self.media,
                default_analysis_profile("quick"),
            )

        self.assertEqual(devices, ["cuda", "cpu"])
        self.assertEqual(transcript.device, "cpu")


if __name__ == "__main__":
    unittest.main()
