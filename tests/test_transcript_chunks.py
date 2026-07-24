from __future__ import annotations

import unittest

from local_clip_ai.analysis import (
    merge_transcript_documents,
    plan_transcription_chunks,
)


class TranscriptChunkTests(unittest.TestCase):
    def test_long_media_is_planned_with_small_recovery_overlap(self) -> None:
        chunks = plan_transcription_chunks(
            2_000,
            chunk_seconds=900,
            overlap_seconds=5,
        )

        self.assertEqual(
            [
                (chunk.index, chunk.start_seconds, chunk.end_seconds)
                for chunk in chunks
            ],
            [
                (0, 0, 900),
                (1, 895, 1_795),
                (2, 1_790, 2_000),
            ],
        )

    def test_merge_removes_overlap_duplicate_and_keeps_better_version(self) -> None:
        first = {
            "media_path": "vod.mp4",
            "segments": [
                {
                    "start_seconds": 894,
                    "end_seconds": 900,
                    "text": "That was incredible",
                    "avg_log_probability": -0.7,
                    "no_speech_probability": 0.01,
                }
            ],
        }
        second = {
            "media_path": "vod.mp4",
            "segments": [
                {
                    "start_seconds": 895,
                    "end_seconds": 900,
                    "text": " that was INCREDIBLE ",
                    "avg_log_probability": -0.1,
                    "no_speech_probability": 0.01,
                },
                {
                    "start_seconds": 901,
                    "end_seconds": 904,
                    "text": "Next thought",
                    "avg_log_probability": -0.2,
                    "no_speech_probability": 0.01,
                },
            ],
        }

        merged = merge_transcript_documents([first, second])

        self.assertEqual(merged["chunk_count"], 2)
        self.assertEqual(len(merged["segments"]), 2)
        self.assertEqual(merged["segments"][0]["avg_log_probability"], -0.1)

    def test_merge_removes_long_repetitive_music_hallucination(self) -> None:
        hallucinations = [
            {
                "start_seconds": index * 3,
                "end_seconds": index * 3 + 2,
                "text": "I",
                "avg_log_probability": -0.8,
                "no_speech_probability": 0.1,
            }
            for index in range(12)
        ]
        real = {
            "start_seconds": 40,
            "end_seconds": 44,
            "text": "what the fuck, that worked",
            "avg_log_probability": -0.1,
            "no_speech_probability": 0.01,
        }

        merged = merge_transcript_documents(
            [{"media_path": "vod.mp4", "segments": [*hallucinations, real]}]
        )

        self.assertEqual([segment["text"] for segment in merged["segments"]], [real["text"]])
        self.assertEqual(merged["filtered_repetitive_segments"], 12)


if __name__ == "__main__":
    unittest.main()
