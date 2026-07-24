from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from local_clip_ai.analysis import TranscriptSegment, discover_candidates
from local_clip_ai.config import ContentProfile
from local_clip_ai.media import probe_media
from local_clip_ai.paths import AppPaths
from local_clip_ai.resources import SleepInhibitor
from local_clip_ai.sources import (
    AcquisitionCancelled,
    acquire_twitch_analysis_media,
    inspect_twitch_vod,
)
from local_clip_ai.sources.acquisition import run_cancellable_process
from local_clip_ai.storage import JobDatabase

EventCallback = Callable[[str], None]
DOWNLOAD_PERCENT = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")


class PipelineRunner:
    STAGE_PROGRESS = {
        "source": 0.05,
        "acquisition": 0.35,
        "transcription": 0.82,
        "candidates": 0.97,
    }

    def __init__(
        self,
        paths: AppPaths,
        database: JobDatabase,
        *,
        on_event: EventCallback | None = None,
    ):
        self.paths = paths
        self.database = database
        self.on_event = on_event

    def _emit(self, message: str) -> None:
        if self.on_event:
            self.on_event(message)

    def _job(self, job_id: str) -> dict[str, Any]:
        job = self.database.get_job(job_id)
        if not job:
            raise RuntimeError(f"Job does not exist: {job_id}")
        return job

    def _stop_requested(self, job_id: str) -> bool:
        job = self._job(job_id)
        return bool(job["cancel_requested"] or job["pause_requested"])

    def _handle_stop(self, job_id: str) -> None:
        job = self._job(job_id)
        if job["cancel_requested"]:
            self.database.update_job_status(job_id, "cancelled")
            self._emit("Job cancelled; completed stages were preserved.")
        else:
            self.database.update_job_status(
                job_id,
                "paused",
                paused_reason=job.get("paused_reason") or "user",
            )
            self._emit("Job paused; completed stages were preserved.")

    def _completed_artifact(self, job_id: str, stage_name: str) -> Path | None:
        for artifact in reversed(self.database.list_artifacts(job_id, stage_name=stage_name)):
            path = Path(artifact["local_path"])
            if artifact["complete"] and path.is_file():
                return path
        return None

    def _update_stage(self, job_id: str, stage_name: str, progress: float | None = None) -> None:
        self.database.update_job_status(
            job_id,
            "running",
            current_stage=stage_name,
            progress=progress if progress is not None else self.STAGE_PROGRESS[stage_name],
        )

    def _inspect_source(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        checkpoint = self.database.stage_checkpoint(job_id, "source")
        if checkpoint and checkpoint["status"] == "completed":
            return
        self._update_stage(job_id, "source", 0.01)
        if job["source_kind"] == "twitch":
            vod = inspect_twitch_vod(self.paths, str(job["source_uri"]))
            self.database.upsert_source(
                vod.canonical_url,
                source_kind="twitch",
                provider_id=vod.video_id,
                title=vod.title,
                channel=vod.channel,
                duration_seconds=vod.duration_seconds,
                metadata=vod.to_dict(),
            )
            checkpoint_values = vod.to_dict()
        else:
            media = probe_media(self.paths, str(job["source_uri"]))
            checkpoint_values = {
                "path": str(media.path),
                "duration_seconds": media.duration_seconds,
                "size_bytes": media.size_bytes,
            }
        self.database.save_stage_checkpoint(
            job_id,
            "source",
            checkpoint_values,
            status="completed",
        )
        self._update_stage(job_id, "source")

    def _acquire_media(self, job: dict[str, Any]) -> Path:
        job_id = str(job["id"])
        existing = self._completed_artifact(job_id, "acquisition")
        if existing:
            return existing
        self._update_stage(job_id, "acquisition", 0.06)
        if job["source_kind"] != "twitch":
            media_path = Path(str(job["source_uri"])).resolve()
            probe = probe_media(self.paths, media_path)
            format_selector = "local"
        else:

            def progress(line: str) -> None:
                match = DOWNLOAD_PERCENT.search(line)
                if match:
                    fraction = float(match.group(1)) / 100
                    self._update_stage(job_id, "acquisition", 0.06 + fraction * 0.28)

            acquired = acquire_twitch_analysis_media(
                self.paths,
                str(job["source_uri"]),
                analysis_mode=str(job["analysis_mode"]),
                cancel_requested=lambda: self._stop_requested(job_id),
                on_output=progress,
            )
            media_path = acquired.path
            probe = acquired.probe
            format_selector = acquired.format_selector
        self.database.save_artifact(
            job_id,
            "acquisition",
            "analysis_media",
            media_path,
            complete=True,
            size_bytes=probe.size_bytes,
            metadata={
                "duration_seconds": probe.duration_seconds,
                "format_selector": format_selector,
                "video_codec": probe.video_codec,
                "audio_codec": probe.audio_codec,
            },
        )
        self.database.save_stage_checkpoint(
            job_id,
            "acquisition",
            {"path": str(media_path), "duration_seconds": probe.duration_seconds},
            status="completed",
        )
        self._update_stage(job_id, "acquisition")
        return media_path

    def _transcribe(self, job: dict[str, Any], media_path: Path) -> Path:
        job_id = str(job["id"])
        existing = self._completed_artifact(job_id, "transcription")
        if existing:
            return existing
        self._update_stage(job_id, "transcription", 0.37)
        transcript_path = self.paths.transcripts / f"{job_id}.json"
        content = json.loads(str(job["content_profile_json"]))
        language = str(content.get("language") or "auto")
        command = [
            sys.executable,
            "-m",
            "local_clip_ai",
            "--data-dir",
            str(self.paths.root),
            "transcribe",
            str(media_path),
            "--mode",
            str(job["analysis_mode"]),
            "--language",
            language,
            "--output",
            str(transcript_path),
        ]
        log_path = self.paths.logs / f"{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        def log_output(line: str) -> None:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(line + "\n")

        return_code, lines = run_cancellable_process(
            command,
            cancel_requested=lambda: self._stop_requested(job_id),
            on_output=log_output,
        )
        if return_code or not transcript_path.is_file():
            recent_output = "\n".join(lines[-30:])
            raise RuntimeError(
                f"Transcription worker exited with code {return_code}:\n{recent_output}"
            )
        size = transcript_path.stat().st_size
        self.database.save_artifact(
            job_id,
            "transcription",
            "transcript_json",
            transcript_path,
            complete=True,
            size_bytes=size,
        )
        self.database.save_stage_checkpoint(
            job_id,
            "transcription",
            {"path": str(transcript_path), "size_bytes": size},
            status="completed",
        )
        self._update_stage(job_id, "transcription")
        return transcript_path

    @staticmethod
    def _read_segments(transcript_path: Path) -> list[TranscriptSegment]:
        values = json.loads(transcript_path.read_text(encoding="utf-8"))
        return [
            TranscriptSegment(
                start_seconds=float(segment["start_seconds"]),
                end_seconds=float(segment["end_seconds"]),
                text=str(segment["text"]),
                avg_log_probability=float(segment["avg_log_probability"]),
                no_speech_probability=float(segment["no_speech_probability"]),
            )
            for segment in values["segments"]
        ]

    def _discover_candidates(self, job: dict[str, Any], transcript_path: Path) -> int:
        job_id = str(job["id"])
        checkpoint = self.database.stage_checkpoint(job_id, "candidates")
        if checkpoint and checkpoint["status"] == "completed":
            return int(checkpoint["checkpoint"].get("candidate_count", 0))
        self._update_stage(job_id, "candidates", 0.84)
        content_values = json.loads(str(job["content_profile_json"]))
        profile = ContentProfile(**content_values)
        moments = discover_candidates(self._read_segments(transcript_path), profile)
        self.database.clear_candidates(job_id)
        for moment in moments:
            self.database.save_candidate(
                job_id,
                start_seconds=moment.source_range.start,
                end_seconds=moment.source_range.end,
                score=moment.score,
                title=moment.title,
                rationale=moment.rationale,
                spans=[
                    {
                        "start_seconds": span.start_seconds,
                        "end_seconds": span.end_seconds,
                        "score": span.score,
                        "rationale": span.rationale,
                    }
                    for span in moment.condensation.spans
                ],
                metadata={
                    "auto_preselected": moment.auto_preselected,
                    "output_duration_seconds": (
                        moment.condensation.output_duration_seconds
                    ),
                    "removed_seconds": moment.condensation.removed_seconds,
                },
            )
        self.database.save_stage_checkpoint(
            job_id,
            "candidates",
            {"candidate_count": len(moments)},
            status="completed",
        )
        self._update_stage(job_id, "candidates")
        return len(moments)

    def run_job(self, job_id: str) -> None:
        job = self._job(job_id)
        if job["status"] not in {"queued", "interrupted"}:
            return
        if job["cancel_requested"] or job["pause_requested"]:
            self._handle_stop(job_id)
            return
        try:
            self._emit(f"Inspecting {job['source_uri']}")
            self._inspect_source(job)
            if self._stop_requested(job_id):
                self._handle_stop(job_id)
                return
            self._emit("Acquiring resumable analysis media")
            media_path = self._acquire_media(job)
            if self._stop_requested(job_id):
                self._handle_stop(job_id)
                return
            self._emit("Transcribing in an isolated local AI worker")
            transcript_path = self._transcribe(job, media_path)
            if self._stop_requested(job_id):
                self._handle_stop(job_id)
                return
            self._emit("Ranking and condensing candidate moments")
            count = self._discover_candidates(job, transcript_path)
            self.database.update_job_status(job_id, "completed", progress=1)
            self._emit(f"Analysis complete with {count} candidate(s).")
        except AcquisitionCancelled:
            self._handle_stop(job_id)
        except Exception as error:
            current = self._job(job_id)
            stage = str(current.get("current_stage") or "unknown")
            self.database.save_stage_checkpoint(
                job_id,
                stage,
                {},
                status="failed",
                error=str(error),
            )
            self.database.update_job_status(
                job_id,
                "failed",
                error=str(error),
            )
            self._emit(f"Analysis failed during {stage}: {error}")

    def run_all(self) -> int:
        completed = 0
        with SleepInhibitor():
            for job in self.database.list_jobs():
                if job["status"] not in {"queued", "interrupted"}:
                    continue
                self.run_job(str(job["id"]))
                completed += 1
        return completed
