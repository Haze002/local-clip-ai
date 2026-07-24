from __future__ import annotations

import json
import os
import re
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from local_clip_ai.analysis import (
    EvidenceWindow,
    TranscriptSegment,
    discover_candidates,
    extract_audio_evidence,
    extract_semantic_evidence,
    extract_visual_evidence,
    merge_transcript_documents,
    plan_transcription_chunks,
    rerank_candidates_with_vision,
)
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
        "signals": 0.91,
        "candidates": 0.98,
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

    def _completed_artifact(
        self,
        job_id: str,
        stage_name: str,
        artifact_kind: str,
    ) -> Path | None:
        for artifact in reversed(self.database.list_artifacts(job_id, stage_name=stage_name)):
            if artifact["artifact_kind"] != artifact_kind:
                continue
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
        existing = self._completed_artifact(job_id, "acquisition", "analysis_media")
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
        existing = self._completed_artifact(
            job_id,
            "transcription",
            "transcript_json",
        )
        if existing:
            return existing
        self._update_stage(job_id, "transcription", 0.37)
        transcript_path = self.paths.transcripts / f"{job_id}.json"
        chunk_directory = self.paths.transcripts / job_id
        chunk_directory.mkdir(parents=True, exist_ok=True)
        content = json.loads(str(job["content_profile_json"]))
        language = str(content.get("language") or "auto")
        media_duration = probe_media(self.paths, media_path).duration_seconds
        chunks = plan_transcription_chunks(media_duration)
        log_path = self.paths.logs / f"{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        def log_output(line: str) -> None:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(line + "\n")

        documents: list[dict[str, Any]] = []
        completed_chunks: list[int] = []
        for chunk in chunks:
            if self._stop_requested(job_id):
                raise AcquisitionCancelled("Transcription stopped between chunks")
            chunk_path = chunk_directory / f"chunk_{chunk.index:04d}.json"
            document = self._read_valid_transcript_document(chunk_path)
            if document is None:
                worker_prefix = (
                    [sys.executable, "--worker-cli"]
                    if getattr(sys, "frozen", False)
                    else [sys.executable, "-m", "local_clip_ai"]
                )
                command = [
                    *worker_prefix,
                    "--data-dir",
                    str(self.paths.root),
                    "transcribe",
                    str(media_path),
                    "--mode",
                    str(job["analysis_mode"]),
                    "--language",
                    language,
                    "--clip-start",
                    str(chunk.start_seconds),
                    "--clip-end",
                    str(chunk.end_seconds),
                    "--output",
                    str(chunk_path),
                ]
                return_code, lines = run_cancellable_process(
                    command,
                    cancel_requested=lambda: self._stop_requested(job_id),
                    on_output=log_output,
                )
                document = self._read_valid_transcript_document(chunk_path)
                if return_code or document is None:
                    recent_output = "\n".join(lines[-30:])
                    raise RuntimeError(
                        "Transcription chunk "
                        f"{chunk.index + 1}/{len(chunks)} exited with code "
                        f"{return_code}:\n{recent_output}"
                    )
            documents.append(document)
            completed_chunks.append(chunk.index)
            self.database.save_artifact(
                job_id,
                "transcription",
                "transcript_chunk",
                chunk_path,
                complete=True,
                size_bytes=chunk_path.stat().st_size,
                metadata={
                    "index": chunk.index,
                    "start_seconds": chunk.start_seconds,
                    "end_seconds": chunk.end_seconds,
                },
            )
            self.database.save_stage_checkpoint(
                job_id,
                "transcription",
                {
                    "completed_chunks": completed_chunks,
                    "total_chunks": len(chunks),
                    "chunk_seconds": 900,
                    "overlap_seconds": 5,
                },
                status="running",
            )
            fraction = len(completed_chunks) / len(chunks)
            self._update_stage(job_id, "transcription", 0.37 + fraction * 0.43)

        merged = merge_transcript_documents(documents)
        temporary_path = transcript_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, transcript_path)
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
    def _read_valid_transcript_document(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(values, dict) or not isinstance(values.get("segments"), list):
            return None
        return values

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

    def _discover_candidates(
        self,
        job: dict[str, Any],
        transcript_path: Path,
        media_path: Path,
    ) -> int:
        job_id = str(job["id"])
        checkpoint = self.database.stage_checkpoint(job_id, "candidates")
        if checkpoint and checkpoint["status"] == "completed":
            return int(checkpoint["checkpoint"].get("candidate_count", 0))
        self._update_stage(job_id, "candidates", 0.92)
        content_values = json.loads(str(job["content_profile_json"]))
        profile = ContentProfile(**content_values)
        signals_path = self._completed_artifact(job_id, "signals", "audio_evidence")
        audio_evidence = self._read_evidence(signals_path) if signals_path else []
        visual_path = self._completed_artifact(job_id, "signals", "visual_evidence")
        visual_evidence = self._read_evidence(visual_path) if visual_path else []
        semantic_path = self._completed_artifact(job_id, "signals", "semantic_evidence")
        semantic_evidence = self._read_evidence(semantic_path) if semantic_path else []
        moments = discover_candidates(
            self._read_segments(transcript_path),
            profile,
            audio_evidence=audio_evidence,
            visual_evidence=visual_evidence,
            semantic_evidence=semantic_evidence,
        )
        vision_assessments = []
        if str(job["analysis_mode"]) == "deep" and moments:
            self._emit("Deep mode: reranking candidate frames with local vision")
            moments, vision_assessments = rerank_candidates_with_vision(
                self.paths,
                media_path,
                moments,
                profile.preference,
                output_directory=self.paths.artifacts / job_id / "vision_frames",
                auto_preselect_count=profile.auto_preselect_count,
                cancel_requested=lambda: self._stop_requested(job_id),
            )
            vision_path = self.paths.artifacts / job_id / "vision_assessments.json"
            temporary = vision_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(
                    [
                        {
                            "candidate_index": item.candidate_index,
                            "score": item.score,
                            "similarity": item.similarity,
                            "frame_count": item.frame_count,
                        }
                        for item in vision_assessments
                    ],
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, vision_path)
            self.database.save_artifact(
                job_id,
                "candidates",
                "vision_assessments",
                vision_path,
                complete=True,
                size_bytes=vision_path.stat().st_size,
                metadata={"candidate_count": len(vision_assessments)},
            )
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
            {
                "candidate_count": len(moments),
                "vision_reranked": bool(vision_assessments),
            },
            status="completed",
        )
        self._update_stage(job_id, "candidates")
        return len(moments)

    def _analyze_audio(
        self,
        job: dict[str, Any],
        media_path: Path,
        duration_seconds: float,
    ) -> Path:
        job_id = str(job["id"])
        existing = self._completed_artifact(job_id, "signals", "audio_evidence")
        if existing:
            return existing
        self._update_stage(job_id, "signals", 0.82)
        evidence = extract_audio_evidence(
            self.paths,
            media_path,
            cancel_requested=lambda: self._stop_requested(job_id),
            duration_seconds=duration_seconds,
            on_progress=lambda fraction: self._update_stage(
                job_id,
                "signals",
                0.82 + fraction * 0.04,
            ),
        )
        output = self.paths.artifacts / job_id / "audio_evidence.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        values = [
            {
                "start_seconds": item.start_seconds,
                "end_seconds": item.end_seconds,
                "score": item.score,
                "rationale": item.rationale,
            }
            for item in evidence
        ]
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(values, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
        self.database.save_artifact(
            job_id,
            "signals",
            "audio_evidence",
            output,
            complete=True,
            size_bytes=output.stat().st_size,
            metadata={"window_count": len(evidence), "window_seconds": 1},
        )
        return output

    @staticmethod
    def _read_evidence(path: Path) -> list[EvidenceWindow]:
        values = json.loads(path.read_text(encoding="utf-8"))
        return [
            EvidenceWindow(
                start_seconds=float(item["start_seconds"]),
                end_seconds=float(item["end_seconds"]),
                score=float(item["score"]),
                rationale=str(item.get("rationale") or "audio energy"),
            )
            for item in values
        ]

    def _analyze_visual(
        self,
        job: dict[str, Any],
        media_path: Path,
        duration_seconds: float,
    ) -> Path | None:
        mode = str(job["analysis_mode"])
        if mode == "quick":
            return None
        job_id = str(job["id"])
        existing = self._completed_artifact(job_id, "signals", "visual_evidence")
        if existing:
            return existing
        self._update_stage(job_id, "signals", 0.86)
        evidence = extract_visual_evidence(
            self.paths,
            media_path,
            analysis_mode=mode,
            cancel_requested=lambda: self._stop_requested(job_id),
            duration_seconds=duration_seconds,
            on_progress=lambda fraction: self._update_stage(
                job_id,
                "signals",
                0.86 + fraction * 0.04,
            ),
        )
        output = self.paths.artifacts / job_id / "visual_evidence.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                [
                    {
                        "start_seconds": item.start_seconds,
                        "end_seconds": item.end_seconds,
                        "score": item.score,
                        "rationale": item.rationale,
                    }
                    for item in evidence
                ],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
        self.database.save_artifact(
            job_id,
            "signals",
            "visual_evidence",
            output,
            complete=True,
            size_bytes=output.stat().st_size,
            metadata={"window_count": len(evidence), "mode": mode},
        )
        return output

    def _analyze_signals(self, job: dict[str, Any], media_path: Path) -> None:
        job_id = str(job["id"])
        duration_seconds = probe_media(self.paths, media_path).duration_seconds
        audio_path = self._analyze_audio(job, media_path, duration_seconds)
        visual_path = self._analyze_visual(job, media_path, duration_seconds)
        transcript_path = self._completed_artifact(
            job_id,
            "transcription",
            "transcript_json",
        )
        if transcript_path is None:
            raise RuntimeError("Semantic analysis requires a completed transcript")
        semantic_path = self._analyze_semantic(job, transcript_path)
        self.database.save_stage_checkpoint(
            job_id,
            "signals",
            {
                "audio_path": str(audio_path),
                "visual_path": str(visual_path) if visual_path else None,
                "semantic_path": str(semantic_path),
                "mode": str(job["analysis_mode"]),
            },
            status="completed",
        )
        self._update_stage(job_id, "signals")

    def _analyze_semantic(self, job: dict[str, Any], transcript_path: Path) -> Path:
        job_id = str(job["id"])
        existing = self._completed_artifact(job_id, "signals", "semantic_evidence")
        if existing:
            return existing
        self._update_stage(job_id, "signals", 0.90)
        profile = ContentProfile(**json.loads(str(job["content_profile_json"])))
        evidence = extract_semantic_evidence(
            self.paths,
            self._read_segments(transcript_path),
            profile.preference,
        )
        output = self.paths.artifacts / job_id / "semantic_evidence.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                [
                    {
                        "start_seconds": item.start_seconds,
                        "end_seconds": item.end_seconds,
                        "score": item.score,
                        "rationale": item.rationale,
                    }
                    for item in evidence
                ],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
        self.database.save_artifact(
            job_id,
            "signals",
            "semantic_evidence",
            output,
            complete=True,
            size_bytes=output.stat().st_size,
            metadata={
                "window_count": len(evidence),
                "preference": profile.preference,
            },
        )
        return output

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
            self._emit("Measuring audio energy and reaction peaks")
            self._analyze_signals(job, media_path)
            if self._stop_requested(job_id):
                self._handle_stop(job_id)
                return
            self._emit("Ranking and condensing candidate moments")
            count = self._discover_candidates(job, transcript_path, media_path)
            self.database.update_job_status(job_id, "completed", progress=1)
            self._emit(f"Analysis complete with {count} candidate(s).")
        except AcquisitionCancelled:
            self._handle_stop(job_id)
        except Exception as error:
            with (self.paths.logs / f"{job_id}.log").open("a", encoding="utf-8") as log:
                log.write("\n--- Pipeline failure traceback ---\n")
                log.write(traceback.format_exc())
                log.write("\n")
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

    def rebuild_candidates(
        self,
        job_id: str,
        *,
        content_profile: dict[str, Any] | None = None,
    ) -> int:
        """Rerun only ranking/condensation from durable local artifacts."""
        if content_profile is not None:
            ContentProfile(**content_profile)
            if not self.database.update_job_content_profile(job_id, content_profile):
                raise RuntimeError(f"Job does not exist: {job_id}")
        job = self._job(job_id)
        transcript_path = self._completed_artifact(
            job_id,
            "transcription",
            "transcript_json",
        )
        media_path = self._completed_artifact(
            job_id,
            "acquisition",
            "analysis_media",
        )
        if transcript_path is None or media_path is None:
            raise RuntimeError(
                "Candidate rebuild requires completed acquisition and transcription"
            )
        self.database.save_stage_checkpoint(
            job_id,
            "candidates",
            {"reason": "manual_rebuild"},
            status="running",
        )
        try:
            count = self._discover_candidates(job, transcript_path, media_path)
        except Exception as error:
            self.database.save_stage_checkpoint(
                job_id,
                "candidates",
                {"reason": "manual_rebuild"},
                status="failed",
                error=str(error),
            )
            self.database.update_job_status(job_id, "failed", error=str(error))
            raise
        self.database.update_job_status(job_id, "completed", progress=1)
        self._emit(f"Candidate rebuild complete with {count} candidate(s).")
        return count

    def run_all(self) -> int:
        completed = 0
        with SleepInhibitor():
            for job in self.database.list_jobs():
                if job["status"] not in {"queued", "interrupted"}:
                    continue
                self.run_job(str(job["id"]))
                completed += 1
        return completed
