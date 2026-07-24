from __future__ import annotations

import shutil
import unittest
import uuid
import zipfile
from pathlib import Path

from local_clip_ai.paths import AppPaths
from local_clip_ai.tools import find_ffmpeg, find_yt_dlp
from local_clip_ai.tools.portable import _expected_sha256, _safe_extract


class PortableToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        self.paths = AppPaths.from_root(self.root)
        self.paths.ensure_directories()

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_finds_repository_local_executables(self) -> None:
        ffmpeg = self.paths.tools / "ffmpeg" / "bin" / "ffmpeg.exe"
        ffprobe = self.paths.tools / "ffmpeg" / "bin" / "ffprobe.exe"
        yt_dlp = self.paths.tools / "yt-dlp" / "yt-dlp.exe"
        for executable in (ffmpeg, ffprobe, yt_dlp):
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.touch()

        self.assertEqual(find_ffmpeg(self.paths, include_path=False), (ffmpeg, ffprobe))
        self.assertEqual(find_yt_dlp(self.paths, include_path=False), yt_dlp)

    def test_requires_github_sha256_digest(self) -> None:
        value = "a" * 64
        self.assertEqual(_expected_sha256({"name": "tool", "digest": f"sha256:{value}"}), value)
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            _expected_sha256({"name": "tool", "digest": None})

    def test_safe_extract_rejects_parent_traversal(self) -> None:
        archive = self.paths.temporary / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("../outside.txt", "unsafe")

        with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
            _safe_extract(archive, self.paths.temporary / "extract")
