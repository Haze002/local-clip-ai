from __future__ import annotations

import unittest
from datetime import UTC, datetime

from local_clip_ai.diagnostics.models import (
    CheckStatus,
    DiagnosticCheck,
    DiagnosticReport,
)
from local_clip_ai.diagnostics.probes import parse_nvidia_smi_row


class DiagnosticsTests(unittest.TestCase):
    def test_parse_nvidia_smi_row(self) -> None:
        output = "0, NVIDIA GeForce RTX 5070, 610.62, 12227, 1342, 18, 51, 42.5, 250.0, 2100"

        result = parse_nvidia_smi_row(output)

        self.assertEqual(result["name"], "NVIDIA GeForce RTX 5070")
        self.assertEqual(result["memory.total"], "12227")
        self.assertEqual(result["temperature.gpu"], "51")

    def test_parse_nvidia_smi_row_rejects_incomplete_output(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected"):
            parse_nvidia_smi_row("0, NVIDIA GeForce RTX 5070")

    def test_diagnostic_report_uses_worst_status(self) -> None:
        timestamp = datetime.now(UTC)
        report = DiagnosticReport(
            checks=(
                DiagnosticCheck("one", CheckStatus.PASS, "ok"),
                DiagnosticCheck("two", CheckStatus.WARN, "warm"),
                DiagnosticCheck("three", CheckStatus.FAIL, "missing"),
            ),
            started_at=timestamp,
            completed_at=timestamp,
        )

        self.assertIs(report.overall_status, CheckStatus.FAIL)
        self.assertEqual(report.to_dict()["overall_status"], "fail")
