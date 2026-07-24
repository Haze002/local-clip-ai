from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

from local_clip_ai.app.resource_controller import ResourceController
from local_clip_ai.paths import AppPaths
from local_clip_ai.storage import JobDatabase


class ResourcePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])

    def setUp(self) -> None:
        self.root = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        paths = AppPaths.from_root(self.root)
        self.database = JobDatabase(paths.database)
        self.database.initialize()
        self.job_id = self.database.create_job("recording.mp4", source_kind="file")
        self.database.update_job_status(self.job_id, "running")
        self.controller = ResourceController(self.database)
        self.controller._timer.stop()
        self.controller._above_since = None
        self.controller._below_since = None
        self.controller._thermal_pause_active = False

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_sustained_heat_pauses_then_stable_cooldown_resumes(self) -> None:
        hot = {"gpu_temperature_c": 95.0, "cpu_temperature_c": None}
        with patch(
            "local_clip_ai.app.resource_controller.time.monotonic",
            side_effect=[0, 121],
        ):
            self.controller._apply_thermal_policy(hot)
            self.controller._apply_thermal_policy(hot)

        paused_pending = self.database.get_job(self.job_id)
        self.assertEqual(paused_pending["status"], "pause_pending")
        self.assertEqual(paused_pending["paused_reason"], "gpu_temperature")

        self.database.update_job_status(
            self.job_id,
            "paused",
            paused_reason="gpu_temperature",
        )
        cool = {"gpu_temperature_c": 80.0, "cpu_temperature_c": None}
        with patch(
            "local_clip_ai.app.resource_controller.time.monotonic",
            side_effect=[130, 161],
        ):
            self.controller._apply_thermal_policy(cool)
            self.controller._apply_thermal_policy(cool)

        self.assertEqual(self.database.get_job(self.job_id)["status"], "queued")


if __name__ == "__main__":
    unittest.main()
