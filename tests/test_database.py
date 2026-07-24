from __future__ import annotations

import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from unittest import TestCase

from local_clip_ai.storage.database import SCHEMA_VERSION, JobDatabase


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
