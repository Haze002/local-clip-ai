from __future__ import annotations

import unittest
from pathlib import Path

from local_clip_ai.paths import AppPaths
from local_clip_ai.sources.twitch import parse_twitch_vod_url, yt_dlp_section_command


class TwitchSourceTests(unittest.TestCase):
    def test_parses_vod_url_and_removes_query(self) -> None:
        video_id, canonical = parse_twitch_vod_url(
            "https://www.twitch.tv/videos/2816862211?filter=all&sort=time"
        )

        self.assertEqual(video_id, "2816862211")
        self.assertEqual(canonical, "https://www.twitch.tv/videos/2816862211")

    def test_rejects_channel_and_non_twitch_urls(self) -> None:
        for value in ("https://twitch.tv/haze002", "https://example.com/videos/123"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_twitch_vod_url(value)

    def test_section_command_uses_portable_tools(self) -> None:
        paths = AppPaths.from_root(Path(".local-data/test-command"))
        yt_dlp = paths.tools / "yt-dlp" / "yt-dlp.exe"
        ffmpeg = paths.tools / "ffmpeg" / "bin" / "ffmpeg.exe"
        ffprobe = paths.tools / "ffmpeg" / "bin" / "ffprobe.exe"
        for executable in (yt_dlp, ffmpeg, ffprobe):
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.touch()
        try:
            command = yt_dlp_section_command(
                paths,
                url="https://www.twitch.tv/videos/2823263031",
                start_seconds=5220,
                end_seconds=5370,
                output=paths.downloads / "section.%(ext)s",
            )

            self.assertIn("*5220.000-5370.000", command)
            self.assertIn(str(ffmpeg.parent), command)
            self.assertEqual(command[-1], "https://www.twitch.tv/videos/2823263031")
        finally:
            import shutil

            shutil.rmtree(paths.root)
