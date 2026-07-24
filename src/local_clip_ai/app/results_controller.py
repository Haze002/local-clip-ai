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
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from local_clip_ai.analysis.condensation import CondensedSpan
from local_clip_ai.media import TimeRange, export_condensed_clip, format_timecode
from local_clip_ai.paths import AppPaths
from local_clip_ai.sources import AcquisitionCancelled, acquire_twitch_section
from local_clip_ai.storage import JobDatabase

INVALID_MODEL_INDEX = QModelIndex()
DOWNLOAD_PERCENT = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
INVALID_WINDOWS_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
EXPORT_RESOLUTION_HEIGHTS = {
    "source": None,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
}
EXPORT_RESOLUTION_LABELS = {
    "source": "Source",
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
}
WINDOWS_RESERVED_COMPONENTS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{value}" for value in range(1, 10)),
    *(f"LPT{value}" for value in range(1, 10)),
}


def normalize_export_resolution(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in EXPORT_RESOLUTION_HEIGHTS:
        raise ValueError(f"Unsupported export resolution: {value}")
    return normalized


def safe_path_component(value: str, *, fallback: str, max_length: int = 96) -> str:
    cleaned = INVALID_WINDOWS_COMPONENT.sub(" ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    if cleaned.split(".", 1)[0].upper() in WINDOWS_RESERVED_COMPONENTS:
        cleaned = f"_{cleaned}"
    return cleaned[:max_length].rstrip(" .") or fallback


def job_display_title(job: dict[str, Any]) -> str:
    title = str(job.get("source_title") or "").strip()
    if title:
        return title
    if job["source_kind"] == "file":
        return Path(str(job["source_uri"])).stem
    provider_id = str(job.get("source_provider_id") or "").strip()
    return f"Twitch VOD {provider_id}" if provider_id else "Twitch VOD"


def job_export_folder(job: dict[str, Any]) -> str:
    title = safe_path_component(job_display_title(job), fallback="Untitled VOD")
    provider_id = str(job.get("source_provider_id") or "").strip()
    if provider_id:
        return safe_path_component(f"{title} [{provider_id}]", fallback=provider_id)
    return title


def available_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    for copy_number in range(2, 10_000):
        candidate = path.with_name(f"{path.stem} ({copy_number}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not choose an unused output name below {path.parent}")


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
    GroupKeyRole = Qt.ItemDataRole.UserRole + 12
    GroupTitleRole = Qt.ItemDataRole.UserRole + 13
    GroupSubtitleRole = Qt.ItemDataRole.UserRole + 14
    GroupFirstRole = Qt.ItemDataRole.UserRole + 15
    GroupCountRole = Qt.ItemDataRole.UserRole + 16

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
            self.GroupKeyRole: QByteArray(b"candidateGroupKey"),
            self.GroupTitleRole: QByteArray(b"candidateGroupTitle"),
            self.GroupSubtitleRole: QByteArray(b"candidateGroupSubtitle"),
            self.GroupFirstRole: QByteArray(b"candidateGroupFirst"),
            self.GroupCountRole: QByteArray(b"candidateGroupCount"),
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
            self.GroupKeyRole: candidate["group_key"],
            self.GroupTitleRole: candidate["group_title"],
            self.GroupSubtitleRole: candidate["group_subtitle"],
            self.GroupFirstRole: candidate["group_first"],
            self.GroupCountRole: candidate["group_count"],
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
    settingsChanged = Signal()
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
        try:
            self._export_resolution = normalize_export_resolution(
                str(database.get_setting("export.resolution", "1080p"))
            )
        except ValueError:
            self._export_resolution = "1080p"
        configured_export_directory = str(
            database.get_setting("export.directory", str(paths.exports))
        )
        self._export_directory = Path(configured_export_directory).expanduser().resolve()
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

    @Property(str, notify=settingsChanged)
    def exportResolution(self) -> str:
        return EXPORT_RESOLUTION_LABELS[self._export_resolution]

    @Property(str, notify=settingsChanged)
    def exportDirectory(self) -> str:
        return str(self._export_directory)

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
        for job in reversed(self._database.list_jobs()):
            group_candidates = self._database.list_candidates(str(job["id"]))
            group_candidates.sort(
                key=lambda item: (
                    not item["metadata"].get("auto_preselected"),
                    -item["score"],
                )
            )
            group_title = job_display_title(job)
            channel = str(job.get("source_channel") or "").strip()
            group_subtitle = (
                f"{channel}  /  {job['source_uri']}" if channel else str(job["source_uri"])
            )
            group_count = len(group_candidates)
            for index, candidate in enumerate(group_candidates):
                candidate["source_uri"] = job["source_uri"]
                candidate["group_key"] = str(job["id"])
                candidate["group_title"] = group_title
                candidate["group_subtitle"] = group_subtitle
                candidate["group_first"] = index == 0
                candidate["group_count"] = group_count
                candidates.append(candidate)
        self._model.replace(candidates)

    @Slot(str)
    def setExportResolution(self, value: str) -> None:
        try:
            normalized = normalize_export_resolution(value)
        except ValueError as error:
            self._set_notice(str(error), True)
            return
        if normalized == self._export_resolution:
            return
        self._export_resolution = normalized
        self._database.set_setting("export.resolution", normalized)
        self.settingsChanged.emit()
        self._set_notice(
            f"Future clips will use a maximum resolution of {EXPORT_RESOLUTION_LABELS[normalized]}."
        )

    @Slot(str)
    def setExportDirectory(self, value: str) -> None:
        try:
            directory = Path(value).expanduser().resolve()
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.is_dir():
                raise OSError(f"Not a directory: {directory}")
        except OSError as error:
            self._set_notice(f"Could not use export folder: {error}", True)
            return
        self._export_directory = directory
        self._database.set_setting("export.directory", str(directory))
        self.settingsChanged.emit()
        self._set_notice(f"Export folder changed to {directory}.")

    @Slot()
    def chooseExportDirectory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            None,
            "Choose Local Clip AI export folder",
            str(self._export_directory),
        )
        if selected:
            self.setExportDirectory(selected)

    @Slot()
    def resetExportDirectory(self) -> None:
        self.setExportDirectory(str(self._paths.exports))

    @Slot()
    def openExportDirectory(self) -> None:
        self._export_directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._export_directory)))

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
            export_resolution = self._export_resolution
            max_output_height = EXPORT_RESOLUTION_HEIGHTS[export_resolution]
            source, source_offset, export_start = self._prepare_source(
                candidate,
                job,
                max_height=max_output_height,
                download_progress=lambda value: self._set_progress(value * 0.45),
            )
            output_directory = self._export_directory / job_export_folder(job)
            clip_title = safe_path_component(
                str(candidate["title"] or "Untitled highlight"),
                fallback="Untitled highlight",
                max_length=72,
            )
            start_label = format_timecode(float(candidate["start_seconds"])).replace(
                ":",
                "-",
            )
            resolution_label = EXPORT_RESOLUTION_LABELS[export_resolution]
            output = available_output_path(
                output_directory
                / (
                    f"{start_label} - {clip_title} [{resolution_label}] "
                    f"[{candidate_id[:8]}].mp4"
                )
            )
            export_id = self._database.create_export(
                str(job["id"]),
                output,
                candidate_id=candidate_id,
                settings={
                    "source_offset_seconds": source_offset,
                    "spans": [span for span in candidate["spans"]],
                    "resolution": export_resolution,
                    "max_output_height": max_output_height,
                },
            )
            result = export_condensed_clip(
                self._paths,
                source,
                spans,
                output,
                source_offset_seconds=source_offset,
                max_output_height=max_output_height,
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
        self._preview_source = QUrl()
        self._preview_title = ""
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
            selected_height = EXPORT_RESOLUTION_HEIGHTS[self._export_resolution]
            preview_height = min(selected_height or 720, 720)
            output = (
                self._paths.artifacts
                / str(job["id"])
                / "previews"
                / f"{candidate_id}_{preview_height}p.mp4"
            )
            if not output.is_file():
                source, source_offset, export_start = self._prepare_source(
                    candidate,
                    job,
                    max_height=preview_height,
                    download_progress=lambda value: self._set_progress(value * 0.45),
                )
                export_condensed_clip(
                    self._paths,
                    source,
                    spans,
                    output,
                    source_offset_seconds=source_offset,
                    max_output_height=preview_height,
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

    @Slot(str)
    def previewPlaybackFailed(self, message: str) -> None:
        detail = message.strip() or "The multimedia backend could not open the preview"
        self._set_notice(f"Preview playback failed: {detail}", True)

    @Slot(float)
    def previewPlaybackReady(self, duration_ms: float) -> None:
        if duration_ms > 0:
            self._set_notice(f"Preview playing ({duration_ms / 1000:.1f}s, up to 720p).")

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
        max_height: int | None,
        download_progress: Any,
    ) -> tuple[Path, float, float]:
        if job["source_kind"] != "twitch":
            source = Path(str(job["source_uri"]))
            return source, 0.0, 0.0
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
            max_height=max_height,
            cancel_requested=self._cancel_event.is_set,
            on_output=output,
        )
        return acquired.path, source_range.start, 0.45
