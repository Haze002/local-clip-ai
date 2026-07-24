from __future__ import annotations

import unittest

from local_clip_ai.analysis import (
    SemanticPassage,
    build_semantic_passages,
    semantic_evidence_from_vectors,
)
from local_clip_ai.analysis.transcription import TranscriptSegment


def segment(start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(start, end, text, -0.1, 0.01)


class SemanticAnalysisTests(unittest.TestCase):
    def test_passages_split_on_large_time_gap(self) -> None:
        passages = build_semantic_passages(
            [
                segment(0, 4, "quiet setup"),
                segment(5, 9, "continued setup"),
                segment(30, 35, "surprising victory"),
            ]
        )

        self.assertEqual(len(passages), 2)
        self.assertEqual(passages[0].text, "quiet setup continued setup")
        self.assertEqual(passages[1].start_seconds, 30)

    def test_vector_similarity_becomes_timestamped_evidence(self) -> None:
        passages = [
            SemanticPassage(10, 20, "ordinary inventory"),
            SemanticPassage(40, 50, "unexpected funny failure"),
        ]
        evidence = semantic_evidence_from_vectors(
            passages,
            [1, 0],
            [[0, 1], [1, 0]],
        )

        self.assertEqual(evidence[0].score, 0)
        self.assertEqual(evidence[1].score, 1)
        self.assertIn("100%", evidence[1].rationale)


if __name__ == "__main__":
    unittest.main()
