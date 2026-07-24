from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from local_clip_ai import __version__
from local_clip_ai.app.diagnostics_controller import (
    DiagnosticsController,
    DiagnosticsListModel,
)
from local_clip_ai.paths import AppPaths


def _arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data-dir", type=Path)
    arguments, _ = parser.parse_known_args(argv)
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    raw_arguments = list(argv if argv is not None else sys.argv[1:])
    arguments = _arguments(raw_arguments)

    application = QGuiApplication([sys.argv[0], *raw_arguments])
    application.setApplicationName("Local Clip AI")
    application.setApplicationDisplayName("Local Clip AI")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("Haze002")

    paths = AppPaths.default(arguments.data_dir)
    model = DiagnosticsListModel()
    controller = DiagnosticsController(paths, model)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("diagnosticsController", controller)
    engine.rootContext().setContextProperty("diagnosticsModel", model)

    qml_path = Path(__file__).with_name("qml") / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path.resolve())))
    if not engine.rootObjects():
        return 1

    QTimer.singleShot(100, controller.refresh)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
