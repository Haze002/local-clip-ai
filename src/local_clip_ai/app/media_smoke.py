from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QApplication


def run_media_smoke(path: Path | str, *, timeout_ms: int = 15_000) -> int:
    """Prove that the packaged Qt backend can decode and advance a local video."""
    media_path = Path(path).expanduser().resolve()
    if not media_path.is_file():
        return 2

    application = QApplication.instance() or QApplication(sys.argv[:1])
    player = QMediaPlayer()
    audio = QAudioOutput()
    audio.setMuted(True)
    video_sink = QVideoSink()
    player.setAudioOutput(audio)
    player.setVideoSink(video_sink)
    state = {"frame": False, "finished": False}

    def finish(exit_code: int) -> None:
        if state["finished"]:
            return
        state["finished"] = True
        player.stop()
        application.exit(exit_code)

    def maybe_pass(position: int = 0) -> None:
        if state["frame"] and player.duration() > 0 and position > 0:
            finish(0)

    def media_status_changed(status: QMediaPlayer.MediaStatus) -> None:
        if status in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            player.play()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            finish(3)
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            finish(0 if state["frame"] and player.duration() > 0 else 4)

    def video_frame_changed(frame: object) -> None:
        is_valid = getattr(frame, "isValid", None)
        state["frame"] = bool(is_valid and is_valid())
        maybe_pass(player.position())

    player.mediaStatusChanged.connect(media_status_changed)
    player.positionChanged.connect(maybe_pass)
    player.errorOccurred.connect(lambda _error, _message: finish(5))
    video_sink.videoFrameChanged.connect(video_frame_changed)
    QTimer.singleShot(timeout_ms, lambda: finish(6))
    player.setSource(QUrl.fromLocalFile(str(media_path)))
    return application.exec()
