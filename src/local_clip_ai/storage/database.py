from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_SCHEMA_VERSION = 1
SCHEMA_VERSION = 3

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

MIGRATION_2 = """
ALTER TABLE jobs ADD COLUMN progress REAL NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN pause_requested INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN paused_reason TEXT;
ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    profile_kind TEXT NOT NULL CHECK(profile_kind IN ('content', 'analysis')),
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(profile_kind, name)
);

CREATE INDEX IF NOT EXISTS profiles_kind_index
ON profiles(profile_kind, is_default DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    uri TEXT NOT NULL UNIQUE,
    source_kind TEXT NOT NULL,
    provider_id TEXT,
    title TEXT,
    channel TEXT,
    duration_seconds REAL,
    metadata_json TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS sources_provider_index
ON sources(source_kind, provider_id);

CREATE TABLE IF NOT EXISTS job_artifacts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    local_path TEXT NOT NULL,
    complete INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER,
    sha256 TEXT,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(job_id, stage_name, artifact_kind, local_path),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS job_artifacts_job_index
ON job_artifacts(job_id, stage_name, complete);

CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    start_seconds REAL NOT NULL,
    end_seconds REAL NOT NULL,
    score REAL NOT NULL,
    title TEXT,
    rationale TEXT,
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS candidates_job_score_index
ON candidates(job_id, score DESC, start_seconds);

CREATE TABLE IF NOT EXISTS candidate_spans (
    candidate_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    start_seconds REAL NOT NULL,
    end_seconds REAL NOT NULL,
    score REAL,
    rationale TEXT,
    PRIMARY KEY (candidate_id, position),
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exports (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    candidate_id TEXT,
    status TEXT NOT NULL,
    local_path TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    error TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS exports_job_index
ON exports(job_id, created_at DESC);
"""

MIGRATION_3 = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

MIGRATIONS = {2: MIGRATION_2, 3: MIGRATION_3}

ANALYSIS_MODES = {"quick", "balanced", "deep"}
PROFILE_KINDS = {"content", "analysis"}
JOB_STATUSES = {
    "queued",
    "running",
    "pause_pending",
    "paused",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _execute_statements(connection: sqlite3.Connection, script: str) -> None:
    statement = ""
    for line in script.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("Incomplete database migration statement")


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
                (str(BASE_SCHEMA_VERSION),),
            )
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            installed_version = int(row["value"])
            if installed_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema {installed_version} is not supported by "
                    f"application schema {SCHEMA_VERSION}"
                )
            while installed_version < SCHEMA_VERSION:
                next_version = installed_version + 1
                _execute_statements(connection, MIGRATIONS[next_version])
                connection.execute(
                    "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
                    (str(next_version),),
                )
                installed_version = next_version
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
        if analysis_mode not in ANALYSIS_MODES:
            raise ValueError(f"Unsupported analysis mode: {analysis_mode}")
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

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def latest_job(self) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def update_job_content_profile(
        self,
        job_id: str,
        content_profile: Mapping[str, Any],
    ) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET content_profile_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(dict(content_profile), sort_keys=True),
                    _utc_now(),
                    job_id,
                ),
            )
        return cursor.rowcount == 1

    def update_job_status(
        self,
        job_id: str,
        status: str,
        *,
        current_stage: str | None = None,
        progress: float | None = None,
        paused_reason: str | None = None,
        error: str | None = None,
    ) -> bool:
        if status not in JOB_STATUSES:
            raise ValueError(f"Unsupported job status: {status}")
        if progress is not None and not 0 <= progress <= 1:
            raise ValueError("Job progress must be between 0 and 1")
        assignments = [
            "status = ?",
            "current_stage = COALESCE(?, current_stage)",
            "paused_reason = ?",
            "last_error = ?",
            "updated_at = ?",
        ]
        values: list[Any] = [
            status,
            current_stage,
            paused_reason,
            error,
            _utc_now(),
        ]
        if progress is not None:
            assignments.append("progress = ?")
            values.append(progress)
        if status not in {"pause_pending", "paused"}:
            assignments.append("pause_requested = 0")
        if status in {"completed", "cancelled"}:
            assignments.append("cancel_requested = 0")
        values.append(job_id)
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        return cursor.rowcount == 1

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

    def request_pause(self, job_id: str, reason: str = "user") -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET pause_requested = 1, status = 'pause_pending',
                    paused_reason = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'running')
                """,
                (reason, _utc_now(), job_id),
            )
        return cursor.rowcount == 1

    def resume_job(self, job_id: str) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'queued', pause_requested = 0, cancel_requested = 0,
                    paused_reason = NULL, last_error = NULL, updated_at = ?
                WHERE id = ? AND status IN ('paused', 'interrupted', 'failed')
                """,
                (_utc_now(), job_id),
            )
        return cursor.rowcount == 1

    def recover_interrupted_jobs(self) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'interrupted', pause_requested = 0,
                    paused_reason = 'application_restart', updated_at = ?
                WHERE status IN ('running', 'pause_pending')
                """,
                (_utc_now(),),
            )
        return cursor.rowcount

    def move_job(self, job_id: str, new_position: int) -> bool:
        if new_position < 0:
            raise ValueError("Queue position cannot be negative")
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs ORDER BY queue_position, created_at"
            ).fetchall()
            identifiers = [str(row["id"]) for row in rows]
            if job_id not in identifiers:
                return False
            identifiers.remove(job_id)
            identifiers.insert(min(new_position, len(identifiers)), job_id)
            for position, identifier in enumerate(identifiers):
                connection.execute(
                    "UPDATE jobs SET queue_position = ?, updated_at = ? WHERE id = ?",
                    (position, _utc_now(), identifier),
                )
        return True

    def upsert_profile(
        self,
        kind: str,
        name: str,
        config: Mapping[str, Any],
        *,
        is_default: bool = False,
    ) -> str:
        if kind not in PROFILE_KINDS:
            raise ValueError(f"Unsupported profile kind: {kind}")
        timestamp = _utc_now()
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM profiles WHERE profile_kind = ? AND name = ?",
                (kind, name),
            ).fetchone()
            profile_id = str(existing["id"]) if existing else str(uuid.uuid4())
            if is_default:
                connection.execute(
                    "UPDATE profiles SET is_default = 0 WHERE profile_kind = ?",
                    (kind,),
                )
            connection.execute(
                """
                INSERT INTO profiles(
                    id, profile_kind, name, config_json, is_default, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_kind, name) DO UPDATE SET
                    config_json = excluded.config_json,
                    is_default = excluded.is_default,
                    updated_at = excluded.updated_at
                """,
                (
                    profile_id,
                    kind,
                    name,
                    json.dumps(dict(config), sort_keys=True),
                    int(is_default),
                    timestamp,
                    timestamp,
                ),
            )
        return profile_id

    def list_profiles(self, kind: str | None = None) -> list[dict[str, Any]]:
        if kind is not None and kind not in PROFILE_KINDS:
            raise ValueError(f"Unsupported profile kind: {kind}")
        query = "SELECT * FROM profiles"
        parameters: tuple[str, ...] = ()
        if kind:
            query += " WHERE profile_kind = ?"
            parameters = (kind,)
        query += " ORDER BY profile_kind, is_default DESC, updated_at DESC, name"
        with self.session() as connection:
            rows = connection.execute(query, parameters).fetchall()
        profiles = [dict(row) for row in rows]
        for profile in profiles:
            profile["config"] = json.loads(profile.pop("config_json"))
        return profiles

    def default_profile(self, kind: str) -> dict[str, Any] | None:
        if kind not in PROFILE_KINDS:
            raise ValueError(f"Unsupported profile kind: {kind}")
        profiles = self.list_profiles(kind)
        return next(
            (profile for profile in profiles if profile["is_default"]),
            profiles[0] if profiles else None,
        )

    def upsert_source(
        self,
        uri: str,
        *,
        source_kind: str,
        provider_id: str | None = None,
        title: str | None = None,
        channel: str | None = None,
        duration_seconds: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        timestamp = _utc_now()
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM sources WHERE uri = ?",
                (uri,),
            ).fetchone()
            source_id = str(existing["id"]) if existing else str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO sources(
                    id, uri, source_kind, provider_id, title, channel, duration_seconds,
                    metadata_json, discovered_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uri) DO UPDATE SET
                    source_kind = excluded.source_kind,
                    provider_id = excluded.provider_id,
                    title = excluded.title,
                    channel = excluded.channel,
                    duration_seconds = excluded.duration_seconds,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    source_id,
                    uri,
                    source_kind,
                    provider_id,
                    title,
                    channel,
                    duration_seconds,
                    json.dumps(dict(metadata or {}), sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
        return source_id

    def list_sources(self) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                "SELECT * FROM sources ORDER BY updated_at DESC"
            ).fetchall()
        sources = [dict(row) for row in rows]
        for source in sources:
            source["metadata"] = json.loads(source.pop("metadata_json"))
        return sources

    def save_artifact(
        self,
        job_id: str,
        stage_name: str,
        artifact_kind: str,
        local_path: Path | str,
        *,
        complete: bool,
        size_bytes: int | None = None,
        sha256: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        resolved_path = str(Path(local_path).expanduser().resolve())
        timestamp = _utc_now()
        with self.transaction() as connection:
            existing = connection.execute(
                """
                SELECT id FROM job_artifacts
                WHERE job_id = ? AND stage_name = ? AND artifact_kind = ? AND local_path = ?
                """,
                (job_id, stage_name, artifact_kind, resolved_path),
            ).fetchone()
            artifact_id = str(existing["id"]) if existing else str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO job_artifacts(
                    id, job_id, stage_name, artifact_kind, local_path, complete,
                    size_bytes, sha256, metadata_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, stage_name, artifact_kind, local_path) DO UPDATE SET
                    complete = excluded.complete,
                    size_bytes = excluded.size_bytes,
                    sha256 = excluded.sha256,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    artifact_id,
                    job_id,
                    stage_name,
                    artifact_kind,
                    resolved_path,
                    int(complete),
                    size_bytes,
                    sha256,
                    json.dumps(dict(metadata or {}), sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
        return artifact_id

    def list_artifacts(
        self,
        job_id: str,
        *,
        stage_name: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM job_artifacts WHERE job_id = ?"
        parameters: tuple[str, ...] | tuple[str, str] = (job_id,)
        if stage_name:
            query += " AND stage_name = ?"
            parameters = (job_id, stage_name)
        query += " ORDER BY created_at"
        with self.session() as connection:
            rows = connection.execute(query, parameters).fetchall()
        artifacts = [dict(row) for row in rows]
        for artifact in artifacts:
            artifact["metadata"] = json.loads(artifact.pop("metadata_json"))
        return artifacts

    def clear_candidates(self, job_id: str) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM candidates WHERE job_id = ?",
                (job_id,),
            )
        return cursor.rowcount

    def save_candidate(
        self,
        job_id: str,
        *,
        start_seconds: float,
        end_seconds: float,
        score: float,
        spans: list[Mapping[str, Any]],
        title: str | None = None,
        rationale: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        candidate_id: str | None = None,
    ) -> str:
        if end_seconds <= start_seconds:
            raise ValueError("Candidate end must be after its start")
        identifier = candidate_id or str(uuid.uuid4())
        timestamp = _utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO candidates(
                    id, job_id, start_seconds, end_seconds, score, title, rationale,
                    metadata_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    start_seconds = excluded.start_seconds,
                    end_seconds = excluded.end_seconds,
                    score = excluded.score,
                    title = excluded.title,
                    rationale = excluded.rationale,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    identifier,
                    job_id,
                    start_seconds,
                    end_seconds,
                    score,
                    title,
                    rationale,
                    json.dumps(dict(metadata or {}), sort_keys=True),
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                "DELETE FROM candidate_spans WHERE candidate_id = ?",
                (identifier,),
            )
            for position, span in enumerate(spans):
                span_start = float(span["start_seconds"])
                span_end = float(span["end_seconds"])
                if span_end <= span_start:
                    raise ValueError("Candidate span end must be after its start")
                connection.execute(
                    """
                    INSERT INTO candidate_spans(
                        candidate_id, position, start_seconds, end_seconds, score, rationale
                    )
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identifier,
                        position,
                        span_start,
                        span_end,
                        span.get("score"),
                        span.get("rationale"),
                    ),
                )
        return identifier

    def list_candidates(self, job_id: str) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT * FROM candidates
                WHERE job_id = ?
                ORDER BY score DESC, start_seconds
                """,
                (job_id,),
            ).fetchall()
            result = []
            for row in rows:
                candidate = dict(row)
                candidate["metadata"] = json.loads(candidate.pop("metadata_json"))
                spans = connection.execute(
                    """
                    SELECT position, start_seconds, end_seconds, score, rationale
                    FROM candidate_spans
                    WHERE candidate_id = ?
                    ORDER BY position
                    """,
                    (candidate["id"],),
                ).fetchall()
                candidate["spans"] = [dict(span) for span in spans]
                result.append(candidate)
        return result

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute(
                "SELECT * FROM candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                return None
            candidate = dict(row)
            candidate["metadata"] = json.loads(candidate.pop("metadata_json"))
            spans = connection.execute(
                """
                SELECT position, start_seconds, end_seconds, score, rationale
                FROM candidate_spans
                WHERE candidate_id = ?
                ORDER BY position
                """,
                (candidate_id,),
            ).fetchall()
            candidate["spans"] = [dict(span) for span in spans]
        return candidate

    def set_candidate_review_status(self, candidate_id: str, status: str) -> bool:
        if status not in {"unreviewed", "selected", "rejected", "exported"}:
            raise ValueError(f"Unsupported review status: {status}")
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE candidates
                SET review_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, _utc_now(), candidate_id),
            )
        return cursor.rowcount == 1

    def create_export(
        self,
        job_id: str,
        local_path: Path | str,
        *,
        candidate_id: str | None,
        settings: Mapping[str, Any],
    ) -> str:
        export_id = str(uuid.uuid4())
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO exports(
                    id, job_id, candidate_id, status, local_path,
                    settings_json, created_at
                )
                VALUES(?, ?, ?, 'running', ?, ?, ?)
                """,
                (
                    export_id,
                    job_id,
                    candidate_id,
                    str(Path(local_path).expanduser().resolve()),
                    json.dumps(dict(settings), sort_keys=True),
                    _utc_now(),
                ),
            )
        return export_id

    def finish_export(self, export_id: str, *, error: str | None = None) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE exports
                SET status = ?, completed_at = ?, error = ?
                WHERE id = ?
                """,
                ("failed" if error else "completed", _utc_now(), error, export_id),
            )
        return cursor.rowcount == 1

    def list_exports(self, job_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM exports"
        parameters: tuple[str, ...] = ()
        if job_id:
            query += " WHERE job_id = ?"
            parameters = (job_id,)
        query += " ORDER BY created_at DESC"
        with self.session() as connection:
            rows = connection.execute(query, parameters).fetchall()
        exports = [dict(row) for row in rows]
        for value in exports:
            value["settings"] = json.loads(value.pop("settings_json"))
        return exports

    def set_setting(self, key: str, value: Any) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO app_settings(key, value_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, sort_keys=True), _utc_now()),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.session() as connection:
            row = connection.execute(
                "SELECT value_json FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
        return default if row is None else json.loads(row["value_json"])

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
