from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source_uri TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_fingerprint TEXT,
    status TEXT NOT NULL,
    analysis_mode TEXT NOT NULL,
    content_profile_json TEXT NOT NULL,
    analysis_profile_json TEXT NOT NULL,
    queue_position INTEGER NOT NULL,
    current_stage TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS jobs_queue_index
ON jobs(status, queue_position, created_at);

CREATE TABLE IF NOT EXISTS job_stages (
    job_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (job_id, stage_name),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS job_stages_status_index
ON job_stages(status, updated_at);
"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobDatabase:
    """Authoritative, crash-resistant job and stage storage."""

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser().resolve()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        connection = self.connect()
        try:
            connection.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA}")
            connection.execute(
                """
                INSERT INTO schema_meta(key, value)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO NOTHING
                """,
                (str(SCHEMA_VERSION),),
            )
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            installed_version = int(row["value"])
            if installed_version != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema {installed_version} is not supported by "
                    f"application schema {SCHEMA_VERSION}"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def schema_version(self) -> int:
        with self.session() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        if row is None:
            raise RuntimeError("Database has not been initialized")
        return int(row["value"])

    def create_job(
        self,
        source_uri: str,
        *,
        source_kind: str = "file",
        analysis_mode: str = "balanced",
        content_profile: Mapping[str, Any] | None = None,
        analysis_profile: Mapping[str, Any] | None = None,
        source_fingerprint: str | None = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        timestamp = _utc_now()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(queue_position), -1) + 1 AS next_position FROM jobs"
            ).fetchone()
            queue_position = int(row["next_position"])
            connection.execute(
                """
                INSERT INTO jobs(
                    id, source_uri, source_kind, source_fingerprint, status,
                    analysis_mode, content_profile_json, analysis_profile_json,
                    queue_position, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    source_uri,
                    source_kind,
                    source_fingerprint,
                    analysis_mode,
                    json.dumps(dict(content_profile or {}), sort_keys=True),
                    json.dumps(dict(analysis_profile or {}), sort_keys=True),
                    queue_position,
                    timestamp,
                    timestamp,
                ),
            )
        return job_id

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY queue_position, created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def request_cancel(self, job_id: str) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET cancel_requested = 1, updated_at = ?
                WHERE id = ?
                """,
                (_utc_now(), job_id),
            )
        return cursor.rowcount == 1

    def save_stage_checkpoint(
        self,
        job_id: str,
        stage_name: str,
        checkpoint: Mapping[str, Any],
        *,
        status: str = "running",
        error: str | None = None,
    ) -> None:
        timestamp = _utc_now()
        completed_at = timestamp if status == "completed" else None
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO job_stages(
                    job_id, stage_name, status, checkpoint_json,
                    started_at, completed_at, updated_at, error
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, stage_name) DO UPDATE SET
                    status = excluded.status,
                    checkpoint_json = excluded.checkpoint_json,
                    completed_at = excluded.completed_at,
                    updated_at = excluded.updated_at,
                    error = excluded.error
                """,
                (
                    job_id,
                    stage_name,
                    status,
                    json.dumps(dict(checkpoint), sort_keys=True),
                    timestamp,
                    completed_at,
                    timestamp,
                    error,
                ),
            )
            connection.execute(
                """
                UPDATE jobs
                SET current_stage = ?, updated_at = ?
                WHERE id = ?
                """,
                (stage_name, timestamp, job_id),
            )

    def stage_checkpoint(self, job_id: str, stage_name: str) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                """
                SELECT * FROM job_stages
                WHERE job_id = ? AND stage_name = ?
                """,
                (job_id, stage_name),
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["checkpoint"] = json.loads(value.pop("checkpoint_json"))
        return value
