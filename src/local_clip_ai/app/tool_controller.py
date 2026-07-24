from __future__ import annotations

import threading

from PySide6.QtCore import Property, QObject, Signal, Slot

from local_clip_ai.paths import AppPaths
from local_clip_ai.tools import find_ffmpeg, find_yt_dlp, install_portable_tools


class ToolController(QObject):
    changed = Signal()
    installFinished = Signal(str, bool)

    def __init__(self, paths: AppPaths):
        super().__init__()
        self._paths = paths
        self._busy = False
        ffmpeg, ffprobe = find_ffmpeg(paths)
        yt_dlp = find_yt_dlp(paths)
        if ffmpeg and ffprobe and yt_dlp:
            self._status = (
                "Verified portable FFmpeg, ffprobe, and yt-dlp are ready. "
                "Install / repair downloads a fresh verified copy if needed."
            )
        else:
            self._status = (
                "Portable media tools are incomplete. Select Install / repair to "
                "download verified copies; nothing is installed system-wide."
            )
        self.installFinished.connect(self._finished)

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @Slot()
    def installTools(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._status = "Downloading and verifying portable media tools..."
        self.changed.emit()
        threading.Thread(
            target=self._install,
            name="portable-tool-installer",
            daemon=True,
        ).start()

    def _install(self) -> None:
        try:
            installs = install_portable_tools(self._paths)
            summary = ", ".join(
                f"{install.name} {install.release}" for install in installs
            )
            self.installFinished.emit(f"Portable tools ready: {summary}.", False)
        except Exception as error:
            self.installFinished.emit(f"Tool installation failed: {error}", True)

    @Slot(str, bool)
    def _finished(self, message: str, failed: bool) -> None:
        self._busy = False
        self._status = message
        self.changed.emit()
