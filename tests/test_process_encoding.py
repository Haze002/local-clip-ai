from __future__ import annotations

import sys
import unittest

# Import through the pipeline's established module order; the process helper is
# intentionally shared by acquisition, analysis, and export stages.
from local_clip_ai.pipeline.runner import run_cancellable_process


class ProcessEncodingTests(unittest.TestCase):
    def test_python_worker_round_trips_unicode_with_legacy_parent_locale(self) -> None:
        return_code, lines = run_cancellable_process(
            [
                sys.executable,
                "-c",
                "print('clip: naïve café — 日本語')",
            ]
        )

        self.assertEqual(return_code, 0)
        self.assertEqual(lines, ["clip: naïve café — 日本語"])


if __name__ == "__main__":
    unittest.main()
