from __future__ import annotations

import json
import threading
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Property,
    Qt,
    Signal,
    Slot,
)

from local_clip_ai.diagnostics import collect_diagnostics
from local_clip_ai.diagnostics.models import DiagnosticCheck, DiagnosticReport
from local_clip_ai.paths import AppPaths


class DiagnosticsListModel(QAbstractListModel):
    NameRole = Qt.ItemDataRole.UserRole + 1
    StatusRole = Qt.ItemDataRole.UserRole + 2
    SummaryRole = Qt.ItemDataRole.UserRole + 3
    DetailsRole = Qt.ItemDataRole.UserRole + 4

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._checks: tuple[DiagnosticCheck, ...] = ()

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.NameRole: QByteArray(b"checkName"),
            self.StatusRole: QByteArray(b"checkStatus"),
            self.SummaryRole: QByteArray(b"checkSummary"),
            self.DetailsRole: QByteArray(b"checkDetails"),
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._checks)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._checks):
            return None
        check = self._checks[index.row()]
        if role == self.NameRole:
            return check.name
        if role == self.StatusRole:
            return check.status.value
        if role == self.SummaryRole:
            return check.summary
        if role == self.DetailsRole:
            return json.dumps(check.details, ensure_ascii=False)
        return None

    def replace(self, checks: tuple[DiagnosticCheck, ...]) -> None:
        self.beginResetModel()
        self._checks = checks
        self.endResetModel()


class DiagnosticsController(QObject):
    runningChanged = Signal()
    statusChanged = Signal()
    reportReady = Signal(object)

    def __init__(self, paths: AppPaths, model: DiagnosticsListModel):
        super().__init__()
        self._paths = paths
        self._model = model
        self._running = False
        self._overall_status = "waiting"
        self._summary = "Run diagnostics to validate this PC."
        self.reportReady.connect(self._apply_report)

    @Property(bool, notify=runningChanged)
    def running(self) -> bool:
        return self._running

    @Property(str, notify=statusChanged)
    def overallStatus(self) -> str:
        return self._overall_status

    @Property(str, notify=statusChanged)
    def summary(self) -> str:
        return self._summary

    @Property(str, constant=True)
    def dataRoot(self) -> str:
        return str(self._paths.root)

    @Slot()
    def refresh(self) -> None:
        if self._running:
            return
        self._running = True
        self._summary = "Checking hardware and dependencies…"
        self.runningChanged.emit()
        self.statusChanged.emit()
        threading.Thread(target=self._collect, name="diagnostics", daemon=True).start()

    def _collect(self) -> None:
        self.reportReady.emit(collect_diagnostics(self._paths))

    @Slot(object)
    def _apply_report(self, report: DiagnosticReport) -> None:
        self._model.replace(report.checks)
        self._overall_status = report.overall_status.value
        failed = sum(check.status.value == "fail" for check in report.checks)
        warned = sum(check.status.value == "warn" for check in report.checks)
        if failed:
            self._summary = f"{failed} required check(s) need attention."
        elif warned:
            self._summary = f"Ready with {warned} warning(s)."
        else:
            self._summary = "This PC passed every foundation check."
        self._running = False
        self.statusChanged.emit()
        self.runningChanged.emit()

