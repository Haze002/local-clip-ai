from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from local_clip_ai.analysis import EvidenceWindow
from local_clip_ai.config import default_analysis_profile, default_content_profile
from local_clip_ai.media.probe import MediaProbe
from local_clip_ai.paths import AppPaths
from local_clip_ai.pipeline import PipelineRunner
from local_clip_ai.storage import JobDatabase


class PipelineRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        self.paths = AppPaths.from_root(self.root)
        self.paths.ensure_directories()
        self.media = self.root / "source.mp4"
        self.media.write_bytes(b"placeholder")
        self.database = JobDatabase(self.paths.database)
        self.database.initialize()

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def _job(self) -> str:
        return self.database.create_job(
            str(self.media.resolve()),
            source_kind="file",
            analysis_mode="quick",
            content_profile=default_content_profile().to_dict(),
            analysis_profile=default_analysis_profile("quick").to_dict(),
        )

    def test_local_job_completes_all_durable_stages(self) -> None:
        job_id = self._job()
        probe = MediaProbe(
            path=self.media.resolve(),
            duration_seconds=120,
            size_bytes=self.media.stat().st_size,
            format_name="mp4",
            video_codec="h264",
            audio_codec="aac",
            width=1280,
            height=720,
            sample_rate=48000,
        )
        worker_commands: list[list[str]] = []
        completed_jobs: list[str] = []

        def fake_worker(command: list[str], **_: object) -> tuple[int, list[str]]:
            worker_commands.append(command)
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    {
                        "segments": [
                            {
                                "start_seconds": 40,
                                "end_seconds": 48,
                                "text": "holy shit, no way, that is insane!",
                                "avg_log_probability": -0.1,
                                "no_speech_probability": 0.01,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return 0, ["worker complete"]

        with (
            patch("local_clip_ai.pipeline.runner.probe_media", return_value=probe),
            patch(
                "local_clip_ai.pipeline.runner.run_cancellable_process",
                side_effect=fake_worker,
            ),
            patch(
                "local_clip_ai.pipeline.runner.extract_audio_evidence",
                return_value=[EvidenceWindow(40, 41, 0.9, "audio peak")],
            ),
            patch(
                "local_clip_ai.pipeline.runner.extract_semantic_evidence",
                return_value=[],
            ),
            patch.object(sys, "frozen", True, create=True),
        ):
            PipelineRunner(
                self.paths,
                self.database,
                on_job_completed=completed_jobs.append,
            ).run_job(job_id)

        job = self.database.get_job(job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["progress"], 1)
        self.assertEqual(
            self.database.stage_checkpoint(job_id, "candidates")["status"],
            "completed",
        )
        self.assertGreaterEqual(len(self.database.list_candidates(job_id)), 1)
        self.assertEqual(worker_commands[0][1], "--worker-cli")
        self.assertEqual(completed_jobs, [job_id])

    def test_preexisting_cancel_request_preserves_unstarted_stages(self) -> None:
        job_id = self._job()
        self.database.request_cancel(job_id)

        PipelineRunner(self.paths, self.database).run_job(job_id)

        self.assertEqual(self.database.get_job(job_id)["status"], "cancelled")
        self.assertEqual(self.database.list_artifacts(job_id), [])
