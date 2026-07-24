from __future__ import annotations

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
    Signal,
    Slot,
)

from local_clip_ai.analysis.condensation import CondensedSpan
from local_clip_ai.media import TimeRange, export_condensed_clip, format_timecode
from local_clip_ai.paths import AppPaths
from local_clip_ai.sources import acquire_twitch_section
from local_clip_ai.storage import JobDatabase

INVALID_MODEL_INDEX = QModelIndex()


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
    exportFinished = Signal(str, bool)

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
        self.exportFinished.connect(self._export_finished)
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
        if self._exporting:
            return
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
            source_offset = 0.0
            if job["source_kind"] == "twitch":
                source_range = TimeRange(
                    float(candidate["start_seconds"]),
                    float(candidate["end_seconds"]),
                )
                acquired = acquire_twitch_section(
                    self._paths,
                    str(job["source_uri"]),
                    source_range,
                    destination=self._paths.artifacts / str(job["id"]) / "export-source",
                )
                source = acquired.path
                source_offset = source_range.start
                source_label = acquired.video_id
            else:
                source = Path(str(job["source_uri"]))
                source_label = source.stem
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
            )
            self._database.finish_export(export_id)
            self._database.set_candidate_review_status(candidate_id, "exported")
            self.exportFinished.emit(str(result.path), False)
        except Exception as error:
            if export_id:
                self._database.finish_export(export_id, error=str(error))
            self.exportFinished.emit(str(error), True)

    @Slot(str, bool)
    def _export_finished(self, value: str, failed: bool) -> None:
        self._exporting = False
        self.exportingChanged.emit()
        if failed:
            self._set_notice(f"Export failed: {value}", True)
        else:
            self._set_notice(f"Export complete: {value}")
            self.refresh()
