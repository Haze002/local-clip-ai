from __future__ import annotations

import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from local_clip_ai.app.diagnostics_controller import (
    DiagnosticsController,
    DiagnosticsListModel,
)
from local_clip_ai.app.profiles_controller import ProfilesController
from local_clip_ai.app.queue_controller import JobListModel, QueueController
from local_clip_ai.app.resource_controller import ResourceController
from local_clip_ai.app.results_controller import CandidateListModel, ResultsController
from local_clip_ai.app.tray_controller import TrayController
from local_clip_ai.app.twitch_controller import TwitchController
from local_clip_ai.paths import AppPaths
from local_clip_ai.storage import JobDatabase


class QmlSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication(sys.argv[:1])

    def setUp(self) -> None:
        self.root = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        self.paths = AppPaths.from_root(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_main_window_loads_with_real_controllers(self) -> None:
        diagnostics_model = DiagnosticsListModel()
        diagnostics = DiagnosticsController(self.paths, diagnostics_model)
        jobs_model = JobListModel()
        queue = QueueController(
            self.paths,
            JobDatabase(self.paths.database),
            jobs_model,
        )
        candidates_model = CandidateListModel()
        results = ResultsController(
            self.paths,
            JobDatabase(self.paths.database),
            candidates_model,
        )
        resources = ResourceController(JobDatabase(self.paths.database))
        tray = TrayController(queue.startQueue)
        profiles = ProfilesController(JobDatabase(self.paths.database))
        twitch = TwitchController(JobDatabase(self.paths.database))
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("diagnosticsController", diagnostics)
        engine.rootContext().setContextProperty("diagnosticsModel", diagnostics_model)
        engine.rootContext().setContextProperty("queueController", queue)
        engine.rootContext().setContextProperty("jobsModel", jobs_model)
        engine.rootContext().setContextProperty("resultsController", results)
        engine.rootContext().setContextProperty("candidatesModel", candidates_model)
        engine.rootContext().setContextProperty("resourceController", resources)
        engine.rootContext().setContextProperty("trayController", tray)
        engine.rootContext().setContextProperty("profilesController", profiles)
        engine.rootContext().setContextProperty("twitchController", twitch)
        qml_path = (
            Path(__file__).parents[1]
            / "src"
            / "local_clip_ai"
            / "app"
            / "qml"
            / "Main.qml"
        )

        engine.load(qml_path)
        self.application.processEvents()

        self.assertEqual(len(engine.rootObjects()), 1)
