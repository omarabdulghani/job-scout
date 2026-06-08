"""Incremental SQLite index for growing dashboard operational data."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from agent.dashboard_user_state import (
    APPLICATION_STAGE_APPLIED,
    APPLICATION_STAGE_LABELS,
    build_job_key,
    normalize_application_stage,
    normalize_status,
)


SCHEMA_VERSION = 1


class OperationalStore:
    """Index JSON outputs in SQLite without removing their recovery value."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def sync(
        self,
        dashboard_data: dict[str, Any],
        user_state: dict[str, Any],
    ) -> dict[str, int]:
        jobs = dashboard_data.get("jobs", []) if isinstance(dashboard_data, dict) else []
        runs = dashboard_data.get("runs", []) if isinstance(dashboard_data, dict) else []
        saved_jobs = user_state.get("jobs", {}) if isinstance(user_state, dict) else {}
        saved_jobs = saved_jobs if isinstance(saved_jobs, dict) else {}
        active_application_keys: list[str] = []
        with self._connect() as connection:
            connection.execute("BEGIN")
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                job_key = build_job_key(job)
                if not job_key:
                    continue
                connection.execute(
                    """
                    INSERT INTO jobs (
                        job_key, board, job_id, title, company, location, url,
                        decision_category, score, run_id, processed_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_key) DO UPDATE SET
                        board=excluded.board,
                        job_id=excluded.job_id,
                        title=excluded.title,
                        company=excluded.company,
                        location=excluded.location,
                        url=excluded.url,
                        decision_category=excluded.decision_category,
                        score=excluded.score,
                        run_id=excluded.run_id,
                        processed_at=excluded.processed_at,
                        payload_json=excluded.payload_json
                    """,
                    (
                        job_key,
                        str(job.get("board") or "linkedin"),
                        str(job.get("job_id") or ""),
                        str(job.get("title") or ""),
                        str(job.get("company") or ""),
                        str(job.get("location") or ""),
                        str(job.get("url") or ""),
                        str(job.get("decision_category") or ""),
                        int(job.get("score") or 0),
                        str(job.get("run_id") or ""),
                        str(job.get("processed_at") or ""),
                        json.dumps(job, ensure_ascii=False),
                    ),
                )
            for run in runs:
                if not isinstance(run, dict):
                    continue
                run_id = str(run.get("run_id") or "")
                if not run_id:
                    continue
                connection.execute(
                    """
                    INSERT INTO runs (run_id, run_label, started_at, completed_at, status, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        run_label=excluded.run_label,
                        started_at=excluded.started_at,
                        completed_at=excluded.completed_at,
                        status=excluded.status,
                        payload_json=excluded.payload_json
                    """,
                    (
                        run_id,
                        str(run.get("run_label") or ""),
                        str(run.get("started_at") or ""),
                        str(run.get("completed_at") or ""),
                        str(run.get("status") or ""),
                        json.dumps(run, ensure_ascii=False),
                    ),
                )
            for job_key, record in saved_jobs.items():
                if not isinstance(record, dict):
                    continue
                stage = normalize_application_stage(record.get("application_stage"))
                if not stage and normalize_status(record.get("status")) == "applied":
                    stage = APPLICATION_STAGE_APPLIED
                if not stage:
                    continue
                active_application_keys.append(str(job_key))
                connection.execute(
                    """
                    INSERT INTO applications (
                        job_key, stage, stage_label, notes, applied_at, follow_up_at,
                        updated_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_key) DO UPDATE SET
                        stage=excluded.stage,
                        stage_label=excluded.stage_label,
                        notes=excluded.notes,
                        applied_at=excluded.applied_at,
                        follow_up_at=excluded.follow_up_at,
                        updated_at=excluded.updated_at,
                        payload_json=excluded.payload_json
                    """,
                    (
                        str(job_key),
                        stage,
                        APPLICATION_STAGE_LABELS[stage],
                        str(record.get("notes") or ""),
                        str(record.get("applied_at") or ""),
                        str(record.get("follow_up_at") or ""),
                        str(record.get("application_updated_at") or record.get("updated_at") or ""),
                        json.dumps(record, ensure_ascii=False),
                    ),
                )
            if active_application_keys:
                placeholders = ",".join("?" for _ in active_application_keys)
                connection.execute(
                    f"DELETE FROM applications WHERE job_key NOT IN ({placeholders})",
                    active_application_keys,
                )
            else:
                connection.execute("DELETE FROM applications")
            connection.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()
            counts = {
                "jobs": connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                "runs": connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
                "applications": connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0],
            }
        return counts

    def application_records(
        self,
        *,
        stage: str = "",
        search: str = "",
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = []
        parameters: list[Any] = []
        if stage:
            clauses.append("a.stage = ?")
            parameters.append(stage)
        if search:
            clauses.append(
                "(lower(coalesce(j.title,'')) LIKE ? OR lower(coalesce(j.company,'')) LIKE ? "
                "OR lower(coalesce(j.location,'')) LIKE ? OR lower(coalesce(a.notes,'')) LIKE ?)"
            )
            needle = f"%{search.lower()}%"
            parameters.extend([needle, needle, needle, needle])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.extend([max(1, min(5000, int(limit))), max(0, int(offset))])
        query = f"""
            SELECT a.job_key, a.stage, a.stage_label, a.notes, a.applied_at,
                   a.follow_up_at, a.updated_at, a.payload_json, j.payload_json
            FROM applications a
            LEFT JOIN jobs j ON j.job_key = a.job_key
            {where}
            ORDER BY a.updated_at DESC, j.title COLLATE NOCASE
            LIMIT ? OFFSET ?
        """
        records: list[dict[str, Any]] = []
        with self._connect() as connection:
            for row in connection.execute(query, parameters):
                saved = self._json_object(row[7])
                job = self._json_object(row[8])
                merged = dict(job)
                merged.update(saved)
                merged.update(
                    {
                        "job_key": row[0],
                        "application_stage": row[1],
                        "application_stage_label": row[2],
                        "notes": row[3] or "",
                        "applied_at": row[4] or "",
                        "follow_up_at": row[5] or "",
                        "application_updated_at": row[6] or "",
                    }
                )
                records.append(merged)
        return records

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                "jobs": connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                "runs": connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
                "applications": connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0],
            }

    def stage_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                str(stage): int(count)
                for stage, count in connection.execute(
                    "SELECT stage, COUNT(*) FROM applications GROUP BY stage"
                )
            }

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_key TEXT PRIMARY KEY,
                    board TEXT,
                    job_id TEXT,
                    title TEXT,
                    company TEXT,
                    location TEXT,
                    url TEXT,
                    decision_category TEXT,
                    score INTEGER,
                    run_id TEXT,
                    processed_at TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_decision_score
                    ON jobs(decision_category, score DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_company
                    ON jobs(company COLLATE NOCASE);
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    run_label TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    status TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS applications (
                    job_key TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    stage_label TEXT NOT NULL,
                    notes TEXT,
                    applied_at TEXT,
                    follow_up_at TEXT,
                    updated_at TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_applications_stage_updated
                    ON applications(stage, updated_at DESC);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
        finally:
            connection.close()

    def _json_object(self, value: Any) -> dict[str, Any]:
        try:
            payload = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
