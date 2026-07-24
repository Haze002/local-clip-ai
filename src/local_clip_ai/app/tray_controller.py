from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QStyle,
    QSystemTrayIcon,
)


class TrayController(QObject):
    showRequested = Signal()
    quitStateChanged = Signal()

    def __init__(self, start_queue: Callable[[], None]):
        super().__init__()
        self._quit_requested = False
        self._available = QSystemTrayIcon.isSystemTrayAvailable()
        self._tray: QSystemTrayIcon | None = None
        self._menu: QMenu | None = None
        if not self._available:
            return
        application = QApplication.instance()
        if application is None:
            return
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("Local Clip AI")
        self._tray.setIcon(
            application.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self._menu = QMenu()
        show_action = self._menu.addAction("Show Local Clip AI")
        start_action = self._menu.addAction("Start queue")
        self._menu.addSeparator()
        exit_action = self._menu.addAction("Exit")
        show_action.triggered.connect(self.showRequested.emit)
        start_action.triggered.connect(start_queue)
        exit_action.triggered.connect(self.quit)
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._activated)
        self._tray.show()

    @Property(bool, constant=True)
    def available(self) -> bool:
        return self._available

    @Property(bool, notify=quitStateChanged)
    def quitRequested(self) -> bool:
        return self._quit_requested

    @Slot(str, str)
    def notify(self, title: str, message: str) -> None:
        if self._tray and self._tray.supportsMessages():
            self._tray.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    @Slot()
    def quit(self) -> None:
        self._quit_requested = True
        self.quitStateChanged.emit()
        if self._tray:
            self._tray.hide()
        application = QApplication.instance()
        if application:
            application.quit()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.showRequested.emit()
