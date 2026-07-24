from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from local_clip_ai import __version__
from local_clip_ai.app.diagnostics_controller import (
    DiagnosticsController,
    DiagnosticsListModel,
)
from local_clip_ai.app.profiles_controller import ProfilesController
from local_clip_ai.app.queue_controller import JobListModel, QueueController
from local_clip_ai.app.resource_controller import ResourceController
from local_clip_ai.app.results_controller import CandidateListModel, ResultsController
from local_clip_ai.app.tool_controller import ToolController
from local_clip_ai.app.tray_controller import TrayController
from local_clip_ai.app.twitch_controller import TwitchController
from local_clip_ai.paths import AppPaths
from local_clip_ai.storage import JobDatabase


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data-dir", type=Path)
    arguments, _ = parser.parse_known_args(argv)
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    raw_arguments = list(argv if argv is not None else sys.argv[1:])
    arguments = _arguments(raw_arguments)

    application = QApplication([sys.argv[0], *raw_arguments])
    application.setApplicationName("Local Clip AI")
    application.setApplicationDisplayName("Local Clip AI")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("Haze002")

    paths = AppPaths.default(arguments.data_dir)
    diagnostics_model = DiagnosticsListModel()
    diagnostics_controller = DiagnosticsController(paths, diagnostics_model)
    jobs_model = JobListModel()
    database = JobDatabase(paths.database)
    queue_controller = QueueController(paths, database, jobs_model)
    candidates_model = CandidateListModel()
    results_controller = ResultsController(paths, database, candidates_model)
    resource_controller = ResourceController(database)
    profiles_controller = ProfilesController(database)
    twitch_controller = TwitchController(database)
    tool_controller = ToolController(paths)
    tool_controller.installFinished.connect(
        lambda _message, _failed: diagnostics_controller.refresh()
    )
    resource_controller.resumeRequested.connect(queue_controller.startQueue)
    tray_controller = TrayController(queue_controller.startQueue)
    if tray_controller.available:
        application.setQuitOnLastWindowClosed(False)
    queue_controller.pipelineFinished.connect(
        lambda count: tray_controller.notify(
            "Local Clip AI",
            f"Queue pass finished after processing {count} job(s).",
        )
    )
    queue_controller.jobsCompleted.connect(results_controller.handleJobsCompleted)
    results_controller.exportFinished.connect(
        lambda value, failed: tray_controller.notify(
            "Local Clip AI export",
            (
                "Export cancelled by user."
                if value == "__cancelled__"
                else (f"Failed: {value}" if failed else f"Saved: {value}")
            ),
        )
    )

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("diagnosticsController", diagnostics_controller)
    engine.rootContext().setContextProperty("diagnosticsModel", diagnostics_model)
    engine.rootContext().setContextProperty("queueController", queue_controller)
    engine.rootContext().setContextProperty("jobsModel", jobs_model)
    engine.rootContext().setContextProperty("resultsController", results_controller)
    engine.rootContext().setContextProperty("candidatesModel", candidates_model)
    engine.rootContext().setContextProperty("resourceController", resource_controller)
    engine.rootContext().setContextProperty("profilesController", profiles_controller)
    engine.rootContext().setContextProperty("twitchController", twitch_controller)
    engine.rootContext().setContextProperty("toolController", tool_controller)
    engine.rootContext().setContextProperty("trayController", tray_controller)

    qml_path = Path(__file__).with_name("qml") / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path.resolve())))
    if not engine.rootObjects():
        return 1

    QTimer.singleShot(100, diagnostics_controller.refresh)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
