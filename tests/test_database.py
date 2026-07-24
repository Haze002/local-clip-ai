from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from unittest import TestCase

from local_clip_ai.storage.database import SCHEMA, SCHEMA_VERSION, JobDatabase


class DatabaseTests(TestCase):
    def setUp(self) -> None:
        self.temporary_path = Path(".local-data") / "unit-tests" / str(uuid.uuid4())
        self.temporary_path.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary_path)

    def test_database_initializes_and_queues_jobs(self) -> None:
        database = JobDatabase(self.temporary_path / "jobs.sqlite3")
        database.initialize()

        first = database.create_job(
            "D:/recordings/first.mkv",
            analysis_mode="balanced",
            content_profile={"category": "funny"},
        )
        second = database.create_job("D:/recordings/second.mkv", analysis_mode="quick")

        jobs = database.list_jobs()

        self.assertEqual(database.schema_version(), SCHEMA_VERSION)
        self.assertEqual([job["id"] for job in jobs], [first, second])
        self.assertEqual([job["queue_position"] for job in jobs], [0, 1])
        self.assertEqual(jobs[0]["analysis_mode"], "balanced")

    def test_stage_checkpoint_is_updated_without_losing_job(self) -> None:
        database = JobDatabase(self.temporary_path / "jobs.sqlite3")
        database.initialize()
        job_id = database.create_job("D:/recordings/test.mkv")

        database.save_stage_checkpoint(
            job_id,
            "transcription",
            {"completed_seconds": 120},
        )
        database.save_stage_checkpoint(
            job_id,
            "transcription",
            {"completed_seconds": 240},
            status="completed",
        )

        checkpoint = database.stage_checkpoint(job_id, "transcription")

        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint["status"], "completed")
        self.assertEqual(checkpoint["checkpoint"], {"completed_seconds": 240})
        self.assertTrue(database.request_cancel(job_id))
        self.assertEqual(database.list_jobs()[0]["cancel_requested"], 1)

    def test_database_uses_wal_and_closes_read_sessions(self) -> None:
        database = JobDatabase(self.temporary_path / "jobs.sqlite3")
        database.initialize()
        database.create_job("D:/recordings/test.mkv")

        database.list_jobs()
        with closing(sqlite3.connect(database.path)) as connection:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertEqual(journal_mode, "wal")

    def test_job_content_profile_can_be_updated_for_local_reranking(self) -> None:
        database = JobDatabase(self.temporary_path / "jobs.sqlite3")
        database.initialize()
        job_id = database.create_job("recording.mp4", content_profile={"max_candidates": 30})

        self.assertTrue(
            database.update_job_content_profile(job_id, {"max_candidates": 50})
        )

        profile = json.loads(database.get_job(job_id)["content_profile_json"])
        self.assertEqual(profile["max_candidates"], 50)

    def test_schema_one_database_migrates_without_losing_jobs(self) -> None:
        path = self.temporary_path / "migration.sqlite3"
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', '1')"
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    id, source_uri, source_kind, status, analysis_mode,
                    content_profile_json, analysis_profile_json, queue_position,
                    created_at, updated_at
                )
                VALUES(
                    'legacy', 'D:/legacy.mkv', 'file', 'queued', 'balanced',
                    '{}', '{}', 0, '2026-01-01', '2026-01-01'
                )
                """
            )
            connection.commit()

        database = JobDatabase(path)
        database.initialize()

        self.assertEqual(database.schema_version(), SCHEMA_VERSION)
        self.assertEqual(database.get_job("legacy")["progress"], 0)

    def test_profiles_can_be_reused_independently(self) -> None:
        database = JobDatabase(self.temporary_path / "profiles.sqlite3")
        database.initialize()

        content_id = database.upsert_profile(
            "content",
            "Funny co-op",
            {"preference": "banter and surprising failures"},
            is_default=True,
        )
        analysis_id = database.upsert_profile(
            "analysis",
            "Balanced local",
            {"mode": "balanced", "target_max_seconds": 60},
            is_default=True,
        )

        profiles = database.list_profiles()
        self.assertEqual({profile["id"] for profile in profiles}, {content_id, analysis_id})
        self.assertEqual(
            database.list_profiles("content")[0]["config"]["preference"],
            "banter and surprising failures",
        )

    def test_queue_pause_resume_reorder_and_restart_recovery(self) -> None:
        database = JobDatabase(self.temporary_path / "recovery.sqlite3")
        database.initialize()
        first = database.create_job("https://www.twitch.tv/videos/1", source_kind="twitch")
        second = database.create_job("https://www.twitch.tv/videos/2", source_kind="twitch")

        self.assertTrue(database.move_job(second, 0))
        self.assertEqual(database.list_jobs()[0]["id"], second)
        self.assertTrue(database.request_pause(first, "thermal"))
        self.assertTrue(database.update_job_status(first, "paused", paused_reason="thermal"))
        self.assertTrue(database.resume_job(first))
        self.assertTrue(database.update_job_status(first, "running", progress=0.25))
        self.assertEqual(database.recover_interrupted_jobs(), 1)
        self.assertEqual(database.get_job(first)["status"], "interrupted")

    def test_candidate_preserves_condensed_source_spans(self) -> None:
        database = JobDatabase(self.temporary_path / "candidates.sqlite3")
        database.initialize()
        job_id = database.create_job("https://www.twitch.tv/videos/2823263031")

        candidate_id = database.save_candidate(
            job_id,
            start_seconds=5220,
            end_seconds=5370,
            score=0.94,
            title="Condensed highlight",
            spans=[
                {"start_seconds": 5220, "end_seconds": 5240, "score": 0.8},
                {"start_seconds": 5290, "end_seconds": 5310, "score": 1.0},
                {"start_seconds": 5350, "end_seconds": 5370, "score": 0.9},
            ],
        )

        candidate = database.list_candidates(job_id)[0]
        self.assertEqual(candidate["id"], candidate_id)
        self.assertEqual(len(candidate["spans"]), 3)
        self.assertEqual(
            sum(span["end_seconds"] - span["start_seconds"] for span in candidate["spans"]),
            60,
        )
