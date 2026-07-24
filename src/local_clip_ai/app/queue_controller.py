from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Qt,
    QUrl,
    Signal,
    Slot,
)

from local_clip_ai.config import (
    AnalysisMode,
    default_analysis_profile,
    default_content_profile,
)
from local_clip_ai.paths import AppPaths
from local_clip_ai.pipeline import PipelineRunner
from local_clip_ai.sources import inspect_twitch_vod, parse_twitch_vod_url
from local_clip_ai.storage import JobDatabase

INVALID_MODEL_INDEX = QModelIndex()


class JobListModel(QAbstractListModel):
    IdRole = Qt.ItemDataRole.UserRole + 1
    SourceRole = Qt.ItemDataRole.UserRole + 2
    StatusRole = Qt.ItemDataRole.UserRole + 3
    ModeRole = Qt.ItemDataRole.UserRole + 4
    ProgressRole = Qt.ItemDataRole.UserRole + 5
    StageRole = Qt.ItemDataRole.UserRole + 6
    PauseReasonRole = Qt.ItemDataRole.UserRole + 7
    PositionRole = Qt.ItemDataRole.UserRole + 8
    SourceTitleRole = Qt.ItemDataRole.UserRole + 9
    SourceDetailRole = Qt.ItemDataRole.UserRole + 10

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._jobs: list[dict[str, Any]] = []

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.IdRole: QByteArray(b"jobId"),
            self.SourceRole: QByteArray(b"jobSource"),
            self.StatusRole: QByteArray(b"jobStatus"),
            self.ModeRole: QByteArray(b"jobMode"),
            self.ProgressRole: QByteArray(b"jobProgress"),
            self.StageRole: QByteArray(b"jobStage"),
            self.PauseReasonRole: QByteArray(b"jobPauseReason"),
            self.PositionRole: QByteArray(b"jobPosition"),
            self.SourceTitleRole: QByteArray(b"jobSourceTitle"),
            self.SourceDetailRole: QByteArray(b"jobSourceDetail"),
        }

    def rowCount(self, parent: QModelIndex = INVALID_MODEL_INDEX) -> int:
        return 0 if parent.isValid() else len(self._jobs)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._jobs):
            return None
        job = self._jobs[index.row()]
        source_uri = str(job["source_uri"])
        source_title = str(job.get("source_title") or "")
        if not source_title and job["source_kind"] == "file":
            source_title = Path(source_uri).stem
        if not source_title:
            source_title = source_uri
        channel = str(job.get("source_channel") or "")
        source_detail = f"{channel}  /  {source_uri}" if channel else source_uri
        values = {
            self.IdRole: job["id"],
            self.SourceRole: source_uri,
            self.StatusRole: job["status"],
            self.ModeRole: job["analysis_mode"],
            self.ProgressRole: float(job.get("progress") or 0),
            self.StageRole: job.get("current_stage") or "Waiting",
            self.PauseReasonRole: job.get("paused_reason") or "",
            self.PositionRole: int(job.get("queue_position") or 0),
            self.SourceTitleRole: source_title,
            self.SourceDetailRole: source_detail,
        }
        return values.get(role)

    def replace(self, jobs: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._jobs = jobs
        self.endResetModel()


class QueueController(QObject):
    noticeChanged = Signal()
    queueChanged = Signal()
    runningChanged = Signal()
    sourceInspected = Signal(str, object)
    pipelineEvent = Signal(str)
    pipelineFinished = Signal(int)
    jobsCompleted = Signal(object)

    def __init__(
        self,
        paths: AppPaths,
        database: JobDatabase,
        model: JobListModel,
    ):
        super().__init__()
        self._paths = paths
        self._database = database
        self._model = model
        self._notice = ""
        self._notice_is_error = False
        self._running = False
        self._database.initialize()
        recovered = self._database.recover_interrupted_jobs()
        self._ensure_default_profiles()
        self.sourceInspected.connect(self._source_inspected)
        self.pipelineEvent.connect(self._pipeline_event)
        self.pipelineFinished.connect(self._pipeline_finished)
        self.refresh()
        if recovered:
            self._set_notice(
                f"Recovered {recovered} interrupted job(s). Resume them when ready.",
                False,
            )

    def _ensure_default_profiles(self) -> None:
        if not self._database.list_profiles("content"):
            self._database.upsert_profile(
                "content",
                "Default",
                default_content_profile().to_dict(),
                is_default=True,
            )
        if not self._database.list_profiles("analysis"):
            for mode in AnalysisMode:
                self._database.upsert_profile(
                    "analysis",
                    mode.value.title(),
                    default_analysis_profile(mode).to_dict(),
                    is_default=mode is AnalysisMode.BALANCED,
                )

    @Property(str, notify=noticeChanged)
    def notice(self) -> str:
        return self._notice

    @Property(bool, notify=noticeChanged)
    def noticeIsError(self) -> bool:
        return self._notice_is_error

    @Property(bool, notify=runningChanged)
    def running(self) -> bool:
        return self._running

    @Slot()
    def refresh(self) -> None:
        self._model.replace(self._database.list_jobs())
        self.queueChanged.emit()

    def _set_notice(self, message: str, is_error: bool) -> None:
        self._notice = message
        self._notice_is_error = is_error
        self.noticeChanged.emit()

    @staticmethod
    def _normalize_source(source: str) -> tuple[str, str]:
        value = source.strip()
        if not value:
            raise ValueError("Paste a Twitch VOD link or choose a local recording")
        if value.lower().startswith(("https://twitch.tv/", "https://www.twitch.tv/")):
            _, canonical = parse_twitch_vod_url(value)
            return canonical, "twitch"
        url = QUrl(value)
        local_value = url.toLocalFile() if url.isLocalFile() else value
        path = Path(local_value).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"Local recording does not exist: {path}")
        return str(path), "file"

    def _profiles_for_reuse(
        self,
        selected_mode: str,
        reuse: str,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        mode = AnalysisMode(selected_mode).value
        default_content = self._database.default_profile("content")
        content = (
            dict(default_content["config"])
            if default_content
            else default_content_profile().to_dict()
        )
        analysis = default_analysis_profile(mode).to_dict()
        previous = self._database.latest_job()
        if previous and reuse in {"content", "both"}:
            content = json.loads(previous["content_profile_json"])
        if previous and reuse in {"analysis", "both"}:
            mode = str(previous["analysis_mode"])
            analysis = json.loads(previous["analysis_profile_json"])
        return mode, content, analysis

    @Slot(str, str, str)
    def queueSource(self, source: str, selected_mode: str, reuse: str) -> None:
        try:
            normalized, source_kind = self._normalize_source(source)
            mode, content, analysis = self._profiles_for_reuse(selected_mode, reuse)
            job_id = self._database.create_job(
                normalized,
                source_kind=source_kind,
                analysis_mode=mode,
                content_profile=content,
                analysis_profile=analysis,
            )
        except (ValueError, OSError) as error:
            self._set_notice(str(error), True)
            return
        self.refresh()
        self._set_notice(f"Queued {normalized} in {mode.title()} mode.", False)
        if source_kind == "twitch":
            threading.Thread(
                target=self._inspect_source,
                args=(job_id, normalized),
                name=f"inspect-{job_id[:8]}",
                daemon=True,
            ).start()

    @Slot("QVariantList", str, str)
    def queueSources(self, sources: list[Any], selected_mode: str, reuse: str) -> None:
        for source in sources:
            value = source.toString() if isinstance(source, QUrl) else str(source)
            self.queueSource(value, selected_mode, reuse)

    def _inspect_source(self, job_id: str, source: str) -> None:
        try:
            vod = inspect_twitch_vod(self._paths, source)
            self._database.upsert_source(
                vod.canonical_url,
                source_kind="twitch",
                provider_id=vod.video_id,
                title=vod.title,
                channel=vod.channel,
                duration_seconds=vod.duration_seconds,
                metadata=vod.to_dict(),
            )
            self.sourceInspected.emit(job_id, vod)
        except Exception as error:
            self.sourceInspected.emit(job_id, error)

    @Slot(str, object)
    def _source_inspected(self, job_id: str, result: object) -> None:
        if isinstance(result, Exception):
            self._set_notice(f"Queued, but metadata inspection failed: {result}", True)
            return
        self._set_notice("Twitch VOD metadata verified and stored locally.", False)
        self.refresh()

    @Slot(str)
    def pause(self, job_id: str) -> None:
        if self._database.request_pause(job_id):
            self._set_notice("Pause requested; completed stages will be preserved.", False)
            self.refresh()

    @Slot(str)
    def resume(self, job_id: str) -> None:
        if self._database.resume_job(job_id):
            self._set_notice("Job returned to the queue.", False)
            self.refresh()

    @Slot(str)
    def cancel(self, job_id: str) -> None:
        if self._database.request_cancel(job_id):
            self._set_notice("Cancellation requested; completed stages will be preserved.", False)
            self.refresh()

    @Slot(str)
    def moveUp(self, job_id: str) -> None:
        job = self._database.get_job(job_id)
        if job and self._database.move_job(
            job_id,
            max(0, int(job["queue_position"]) - 1),
        ):
            self.refresh()
            self._set_notice("Queue order updated.", False)

    @Slot(str)
    def moveDown(self, job_id: str) -> None:
        job = self._database.get_job(job_id)
        if job and self._database.move_job(
            job_id,
            int(job["queue_position"]) + 1,
        ):
            self.refresh()
            self._set_notice("Queue order updated.", False)

    @Slot()
    def startQueue(self) -> None:
        if self._running:
            return
        self._running = True
        self.runningChanged.emit()
        self._set_notice("Queue runner started.", False)
        threading.Thread(target=self._run_pipeline, name="pipeline-runner", daemon=True).start()

    def _run_pipeline(self) -> None:
        completed_job_ids: list[str] = []
        try:
            configured_download_directory = str(
                self._database.get_setting(
                    "downloads.directory",
                    str(self._paths.downloads),
                )
            )
            runner_paths = self._paths.with_downloads(configured_download_directory)
            runner_paths.ensure_directories()
            runner = PipelineRunner(
                runner_paths,
                self._database,
                on_event=self.pipelineEvent.emit,
                on_job_completed=completed_job_ids.append,
            )
            completed = runner.run_all()
        except Exception as error:
            self.pipelineEvent.emit(f"Analysis failed before queue start: {error}")
            completed = -1
        self.jobsCompleted.emit(completed_job_ids)
        self.pipelineFinished.emit(completed)

    @Slot(str)
    def _pipeline_event(self, message: str) -> None:
        self._set_notice(message, message.lower().startswith("analysis failed"))
        self.refresh()

    @Slot(int)
    def _pipeline_finished(self, completed: int) -> None:
        self._running = False
        self.runningChanged.emit()
        self.refresh()
        if completed < 0:
            return
        if completed == 0:
            self._set_notice("No queued or interrupted jobs were ready to run.", False)
