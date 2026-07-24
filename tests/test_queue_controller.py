from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from local_clip_ai.app.queue_controller import JobListModel, QueueController
from local_clip_ai.paths import AppPaths
from local_clip_ai.storage import JobDatabase


class QueueControllerTests(TestCase):
    def setUp(self) -> None:
        self.root = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        self.paths = AppPaths.from_root(self.root)
        self.database = JobDatabase(self.paths.database)
        self.controller = QueueController(
            self.paths,
            self.database,
            JobListModel(),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_pipeline_uses_configured_download_root_and_reports_completed_jobs(
        self,
    ) -> None:
        download_root = self.root / "media-on-another-drive"
        self.database.set_setting("downloads.directory", str(download_root))
        captured_paths: list[AppPaths] = []
        completed_signals: list[list[str]] = []
        self.controller.jobsCompleted.connect(completed_signals.append)

        class FakeRunner:
            def __init__(
                self,
                paths: AppPaths,
                _database: JobDatabase,
                *,
                on_event: object,
                on_job_completed: object,
            ):
                captured_paths.append(paths)
                self.on_job_completed = on_job_completed

            def run_all(self) -> int:
                self.on_job_completed("completed-job")  # type: ignore[operator]
                return 1

        with patch(
            "local_clip_ai.app.queue_controller.PipelineRunner",
            FakeRunner,
        ):
            self.controller._run_pipeline()

        self.assertEqual(captured_paths[0].downloads, download_root.resolve())
        self.assertEqual(captured_paths[0].database, self.paths.database)
        self.assertEqual(completed_signals, [["completed-job"]])
        self.assertTrue(download_root.is_dir())
