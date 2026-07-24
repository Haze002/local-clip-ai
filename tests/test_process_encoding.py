from __future__ import annotations

import io
import sys
import unittest
from unittest.mock import patch

# Import through the pipeline's established module order; the process helper is
# intentionally shared by acquisition, analysis, and export stages.
from local_clip_ai.frozen_entry import configure_utf8_standard_streams
from local_clip_ai.pipeline.runner import run_cancellable_process


class ProcessEncodingTests(unittest.TestCase):
    def test_python_worker_round_trips_unicode_with_legacy_parent_locale(self) -> None:
        return_code, lines = run_cancellable_process(
            [
                sys.executable,
                "-c",
                "print('clip: naïve café — 日本語 下')",
            ]
        )

        self.assertEqual(return_code, 0)
        self.assertEqual(lines, ["clip: naïve café — 日本語 下"])

    def test_frozen_worker_reconfigures_existing_cp1253_stream(self) -> None:
        output_bytes = io.BytesIO()
        error_bytes = io.BytesIO()
        legacy_output = io.TextIOWrapper(output_bytes, encoding="cp1253")
        legacy_error = io.TextIOWrapper(error_bytes, encoding="cp1253")

        with (
            patch.object(sys, "stdout", legacy_output),
            patch.object(sys, "stderr", legacy_error),
        ):
            configure_utf8_standard_streams()
            print("clip: naïve café — 日本語 下")
            sys.stdout.flush()
            self.assertEqual(sys.stdout.encoding.lower(), "utf-8")
            self.assertEqual(sys.stdout.errors, "backslashreplace")

        self.assertEqual(
            output_bytes.getvalue().decode("utf-8").splitlines(),
            ["clip: naïve café — 日本語 下"],
        )

    def test_frozen_gui_initializes_missing_standard_streams(self) -> None:
        with (
            patch.object(sys, "stdout", None),
            patch.object(sys, "stderr", None),
        ):
            configure_utf8_standard_streams()
            self.assertIsNotNone(sys.stdout)
            self.assertIsNotNone(sys.stderr)
            sys.stdout.write("GUI stdout ready")
            sys.stderr.write("GUI stderr ready")


if __name__ == "__main__":
    unittest.main()
