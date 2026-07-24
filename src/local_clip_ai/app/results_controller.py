from __future__ import annotations

import re
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

from local_clip_ai.analysis.condensation import CondensedSpan
from local_clip_ai.media import TimeRange, export_condensed_clip, format_timecode
from local_clip_ai.paths import AppPaths
from local_clip_ai.sources import AcquisitionCancelled, acquire_twitch_section
from local_clip_ai.storage import JobDatabase

INVALID_MODEL_INDEX = QModelIndex()
DOWNLOAD_PERCENT = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")


class CandidateListModel(QAbstractListModel):
    IdRole = Qt.ItemDataRole.UserRole + 1
    JobIdRole = Qt.ItemDataRole.UserRole + 2
    SourceRole = Qt.ItemDataRole.UserRole + 3
    TitleRole = Qt.ItemDataRole.UserRole + 4
    TimeRole = Qt.ItemDataRole.UserRole + 5
    ScoreRole = Qt.ItemDataRole.UserRole + 6
    DurationRole = Qt.ItemDataRole.UserRole + 7
    RationaleRole = Qt.ItemDataRole.UserRole + 8
    PreselectedRole = Qt.ItemDataRole.UserRole + 9
    StatusRole = Qt.ItemDataRole.UserRole + 10
    SpanCountRole = Qt.ItemDataRole.UserRole + 11

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._candidates: list[dict[str, Any]] = []

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.IdRole: QByteArray(b"candidateId"),
            self.JobIdRole: QByteArray(b"candidateJobId"),
            self.SourceRole: QByteArray(b"candidateSource"),
            self.TitleRole: QByteArray(b"candidateTitle"),
            self.TimeRole: QByteArray(b"candidateTime"),
            self.ScoreRole: QByteArray(b"candidateScore"),
            self.DurationRole: QByteArray(b"candidateDuration"),
            self.RationaleRole: QByteArray(b"candidateRationale"),
            self.PreselectedRole: QByteArray(b"candidatePreselected"),
            self.StatusRole: QByteArray(b"candidateStatus"),
            self.SpanCountRole: QByteArray(b"candidateSpanCount"),
        }

    def rowCount(self, parent: QModelIndex = INVALID_MODEL_INDEX) -> int:
        return 0 if parent.isValid() else len(self._candidates)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._candidates):
            return None
        candidate = self._candidates[index.row()]
        metadata = candidate["metadata"]
        values = {
            self.IdRole: candidate["id"],
            self.JobIdRole: candidate["job_id"],
            self.SourceRole: candidate["source_uri"],
            self.TitleRole: candidate["title"] or "Untitled highlight",
            self.TimeRole: (
                f"{format_timecode(candidate['start_seconds'])} - "
                f"{format_timecode(candidate['end_seconds'])}"
            ),
            self.ScoreRole: float(candidate["score"]),
            self.DurationRole: float(metadata.get("output_duration_seconds", 0)),
            self.RationaleRole: candidate["rationale"] or "",
            self.PreselectedRole: bool(metadata.get("auto_preselected")),
            self.StatusRole: candidate["review_status"],
            self.SpanCountRole: len(candidate["spans"]),
        }
        return values.get(role)

    def replace(self, candidates: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._candidates = candidates
        self.endResetModel()


class ResultsController(QObject):
    noticeChanged = Signal()
    exportingChanged = Signal()
    previewChanged = Signal()
    progressChanged = Signal()
    exportFinished = Signal(str, bool)
    previewReady = Signal(str, bool)

    def __init__(
        self,
        paths: AppPaths,
        database: JobDatabase,
        model: CandidateListModel,
    ):
        super().__init__()
        self._paths = paths
        self._database = database
        self._model = model
        self._notice = ""
        self._notice_is_error = False
        self._exporting = False
        self._previewing = False
        self._progress = 0.0
        self._preview_source = QUrl()
        self._preview_title = ""
        self._cancel_event = threading.Event()
        self.exportFinished.connect(self._export_finished)
        self.previewReady.connect(self._preview_ready)
        self.refresh()

    @Property(str, notify=noticeChanged)
    def notice(self) -> str:
        return self._notice

    @Property(bool, notify=noticeChanged)
    def noticeIsError(self) -> bool:
        return self._notice_is_error

    @Property(bool, notify=exportingChanged)
    def exporting(self) -> bool:
        return self._exporting

    @Property(bool, notify=previewChanged)
    def previewing(self) -> bool:
        return self._previewing

    @Property(float, notify=progressChanged)
    def operationProgress(self) -> float:
        return self._progress

    @Property(QUrl, notify=previewChanged)
    def previewSource(self) -> QUrl:
        return self._preview_source

    @Property(str, notify=previewChanged)
    def previewTitle(self) -> str:
        return self._preview_title

    def _set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, value))
        self.progressChanged.emit()

    def _set_notice(self, message: str, is_error: bool = False) -> None:
        self._notice = message
        self._notice_is_error = is_error
        self.noticeChanged.emit()

    @Slot()
    def refresh(self) -> None:
        candidates: list[dict[str, Any]] = []
        for job in self._database.list_jobs():
            for candidate in self._database.list_candidates(str(job["id"])):
                candidate["source_uri"] = job["source_uri"]
                candidates.append(candidate)
        candidates.sort(
            key=lambda item: (
                not item["metadata"].get("auto_preselected"),
                -item["score"],
            )
        )
        self._model.replace(candidates)

    @Slot(str, str)
    def review(self, candidate_id: str, status: str) -> None:
        try:
            changed = self._database.set_candidate_review_status(candidate_id, status)
        except ValueError as error:
            self._set_notice(str(error), True)
            return
        if changed:
            self._set_notice(f"Candidate marked {status}.")
            self.refresh()

    @Slot(str)
    def exportCandidate(self, candidate_id: str) -> None:
        if self._exporting or self._previewing:
            return
        self._cancel_event = threading.Event()
        self._set_progress(0)
        self._exporting = True
        self.exportingChanged.emit()
        self._set_notice("Preparing source-quality export...")
        threading.Thread(
            target=self._export_candidate,
            args=(candidate_id,),
            name=f"export-{candidate_id[:8]}",
            daemon=True,
        ).start()

    def _export_candidate(self, candidate_id: str) -> None:
        export_id: str | None = None
        try:
            candidate, job, spans = self._candidate_context(candidate_id)
            source, source_offset, source_label, export_start = self._prepare_source(
                candidate,
                job,
                prefer_analysis_media=False,
                download_progress=lambda value: self._set_progress(value * 0.45),
            )
            output = self._paths.exports / (
                f"{source_label}_{int(candidate['start_seconds']):06d}_"
                f"{candidate_id[:8]}.mp4"
            )
            export_id = self._database.create_export(
                str(job["id"]),
                output,
                candidate_id=candidate_id,
                settings={
                    "source_offset_seconds": source_offset,
                    "spans": [span for span in candidate["spans"]],
                },
            )
            result = export_condensed_clip(
                self._paths,
                source,
                spans,
                output,
                source_offset_seconds=source_offset,
                cancel_requested=self._cancel_event.is_set,
                on_progress=lambda value: self._set_progress(
                    export_start + value * (1 - export_start)
                ),
            )
            self._database.finish_export(export_id)
            self._database.set_candidate_review_status(candidate_id, "exported")
            self.exportFinished.emit(str(result.path), False)
        except AcquisitionCancelled:
            if export_id:
                self._database.finish_export(export_id, error="Cancelled by user")
            self.exportFinished.emit("__cancelled__", False)
        except Exception as error:
            if export_id:
                self._database.finish_export(export_id, error=str(error))
            self.exportFinished.emit(str(error), True)

    @Slot(str, bool)
    def _export_finished(self, value: str, failed: bool) -> None:
        self._exporting = False
        self._set_progress(0)
        self.exportingChanged.emit()
        if value == "__cancelled__":
            self._set_notice("Export cancelled; no partial output was kept.")
        elif failed:
            self._set_notice(f"Export failed: {value}", True)
        else:
            self._set_notice(f"Export complete: {value}")
            self.refresh()

    @Slot(str)
    def previewCandidate(self, candidate_id: str) -> None:
        if self._exporting or self._previewing:
            return
        self._cancel_event = threading.Event()
        self._set_progress(0)
        self._previewing = True
        self.previewChanged.emit()
        self._set_notice("Preparing condensed preview...")
        threading.Thread(
            target=self._prepare_preview,
            args=(candidate_id,),
            name=f"preview-{candidate_id[:8]}",
            daemon=True,
        ).start()

    def _prepare_preview(self, candidate_id: str) -> None:
        try:
            candidate, job, spans = self._candidate_context(candidate_id)
            output = (
                self._paths.artifacts
                / str(job["id"])
                / "previews"
                / f"{candidate_id}.mp4"
            )
            if not output.is_file():
                source, source_offset, _, export_start = self._prepare_source(
                    candidate,
                    job,
                    prefer_analysis_media=True,
                    download_progress=lambda value: self._set_progress(value * 0.45),
                )
                export_condensed_clip(
                    self._paths,
                    source,
                    spans,
                    output,
                    source_offset_seconds=source_offset,
                    cancel_requested=self._cancel_event.is_set,
                    on_progress=lambda value: self._set_progress(
                        export_start + value * (1 - export_start)
                    ),
                )
            self._preview_title = str(candidate["title"] or "Untitled highlight")
            self.previewReady.emit(str(output), False)
        except AcquisitionCancelled:
            self.previewReady.emit("__cancelled__", False)
        except Exception as error:
            self.previewReady.emit(str(error), True)

    @Slot(str, bool)
    def _preview_ready(self, value: str, failed: bool) -> None:
        self._previewing = False
        self._set_progress(0)
        if value == "__cancelled__":
            self._set_notice("Preview preparation cancelled.")
        elif failed:
            self._set_notice(f"Preview failed: {value}", True)
        else:
            self._preview_source = QUrl.fromLocalFile(value)
            self._set_notice("Preview ready. Use the player before selecting or exporting.")
        self.previewChanged.emit()

    @Slot()
    def closePreview(self) -> None:
        self._preview_source = QUrl()
        self._preview_title = ""
        self.previewChanged.emit()

    @Slot()
    def cancelCurrentOperation(self) -> None:
        if self._exporting or self._previewing:
            self._cancel_event.set()
            self._set_notice("Cancellation requested; finishing the current safe boundary.")

    def _candidate_context(
        self,
        candidate_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], tuple[CondensedSpan, ...]]:
        candidate = self._database.get_candidate(candidate_id)
        if not candidate:
            raise RuntimeError("Candidate no longer exists")
        job = self._database.get_job(str(candidate["job_id"]))
        if not job:
            raise RuntimeError("Candidate job no longer exists")
        spans = tuple(
            CondensedSpan(
                float(span["start_seconds"]),
                float(span["end_seconds"]),
                float(span["score"] or 0),
                str(span["rationale"] or ""),
            )
            for span in candidate["spans"]
        )
        return candidate, job, spans

    def _prepare_source(
        self,
        candidate: dict[str, Any],
        job: dict[str, Any],
        *,
        prefer_analysis_media: bool,
        download_progress: Any,
    ) -> tuple[Path, float, str, float]:
        if job["source_kind"] != "twitch":
            source = Path(str(job["source_uri"]))
            return source, 0.0, source.stem, 0.0
        if prefer_analysis_media:
            artifacts = self._database.list_artifacts(
                str(job["id"]),
                stage_name="acquisition",
            )
            for artifact in reversed(artifacts):
                media_path = Path(str(artifact["local_path"]))
                if (
                    artifact["artifact_kind"] == "analysis_media"
                    and artifact["complete"]
                    and artifact["metadata"].get("video_codec")
                    and media_path.is_file()
                ):
                    return media_path, 0.0, str(job["id"])[:8], 0.0
        source_range = TimeRange(
            float(candidate["start_seconds"]),
            float(candidate["end_seconds"]),
        )

        def output(line: str) -> None:
            match = DOWNLOAD_PERCENT.search(line)
            if match:
                download_progress(float(match.group(1)) / 100)

        acquired = acquire_twitch_section(
            self._paths,
            str(job["source_uri"]),
            source_range,
            destination=self._paths.artifacts / str(job["id"]) / "export-source",
            cancel_requested=self._cancel_event.is_set,
            on_output=output,
        )
        return acquired.path, source_range.start, acquired.video_id, 0.45
