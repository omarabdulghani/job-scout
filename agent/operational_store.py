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
from agent.job_metadata import normalize_apply_method_fields


SCHEMA_VERSION = 3
SYNC_VERSION = 2


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
        active_job_keys: list[str] = []
        active_run_ids: list[str] = []
        active_application_keys: list[str] = []
        with self._connect() as connection:
            connection.execute("BEGIN")
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                job_key = build_job_key(job)
                if not job_key:
                    continue
                active_job_keys.append(job_key)
                saved = saved_jobs.get(job_key, {})
                saved = saved if isinstance(saved, dict) else {}
                merged_job = normalize_apply_method_fields(job)
                merged_job["job_key"] = job_key
                merged_job["manual_status"] = normalize_status(saved.get("status"))
                merged_job["manual_status_label"] = str(saved.get("status_label") or "")
                for source, target in (
                    ("application_stage", "application_stage"),
                    ("application_stage_label", "application_stage_label"),
                    ("application_updated_at", "application_updated_at"),
                    ("applied_at", "applied_at"),
                    ("follow_up_at", "follow_up_at"),
                    ("notes", "application_notes"),
                ):
                    if saved.get(source) not in (None, ""):
                        merged_job[target] = saved[source]
                flags = [
                    str(flag).strip()
                    for flag in merged_job.get("flags", [])
                    if str(flag).strip()
                ]
                connection.execute(
                    """
                    INSERT INTO jobs (
                        job_key, board, job_id, title, company, location, url,
                        decision_category, score, run_id, processed_at,
                        domain_category, flags_text, apply_method, manual_status,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        domain_category=excluded.domain_category,
                        flags_text=excluded.flags_text,
                        apply_method=excluded.apply_method,
                        manual_status=excluded.manual_status,
                        payload_json=excluded.payload_json
                    """,
                    (
                        job_key,
                        str(merged_job.get("board") or "linkedin"),
                        str(merged_job.get("job_id") or ""),
                        str(merged_job.get("title") or ""),
                        str(merged_job.get("company") or ""),
                        str(merged_job.get("location") or ""),
                        str(merged_job.get("url") or ""),
                        str(merged_job.get("decision_category") or ""),
                        int(merged_job.get("score") or 0),
                        str(merged_job.get("run_id") or ""),
                        str(merged_job.get("processed_at") or ""),
                        str(merged_job.get("domain_category") or ""),
                        "\n".join(flags),
                        str(merged_job["apply_method"]),
                        str(merged_job.get("manual_status") or "unreviewed"),
                        json.dumps(merged_job, ensure_ascii=False),
                    ),
                )
            for run in runs:
                if not isinstance(run, dict):
                    continue
                run_id = str(run.get("run_id") or "")
                if not run_id:
                    continue
                active_run_ids.append(run_id)
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
            self._delete_missing(connection, "jobs", "job_key", active_job_keys)
            self._delete_missing(connection, "runs", "run_id", active_run_ids)
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
            self._delete_missing(
                connection,
                "applications",
                "job_key",
                active_application_keys,
            )
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

    def sync_if_changed(
        self,
        dashboard_path: Path | str,
        user_state_path: Path | str,
    ) -> dict[str, Any]:
        dashboard_path = Path(dashboard_path)
        user_state_path = Path(user_state_path)
        signature = self._source_signature(dashboard_path, user_state_path)
        with self._connect() as connection:
            previous = connection.execute(
                "SELECT value FROM metadata WHERE key = 'source_signature'"
            ).fetchone()
            if previous and previous[0] == signature:
                return {**self.counts(), "synced": False}
        dashboard = self._read_json_file(dashboard_path)
        user_state = self._read_json_file(user_state_path)
        counts = self.sync(dashboard, user_state)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('source_signature', ?)",
                (signature,),
            )
            connection.commit()
        return {**counts, "synced": True}

    def job_records(
        self,
        *,
        search: str = "",
        decision: str = "",
        run: str = "",
        domain: str = "",
        flag: str = "",
        apply_method: str = "",
        status: str = "",
        preset: str = "",
        sort: str = "newest",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses, parameters = self._job_filters(
            search=search,
            decision=decision,
            run=run,
            domain=domain,
            flag=flag,
            apply_method=apply_method,
            status=status,
            preset=preset,
        )
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        order_by = {
            "score": "score DESC, processed_at DESC",
            "company": "company COLLATE NOCASE, processed_at DESC",
            "location": "location COLLATE NOCASE, processed_at DESC",
            "newest": "processed_at DESC, score DESC",
        }.get(sort, "processed_at DESC, score DESC")
        safe_limit = max(1, min(500, int(limit)))
        safe_offset = max(0, int(offset))
        with self._connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM jobs{where}",
                    parameters,
                ).fetchone()[0]
            )
            by_decision = {
                str(key): int(count)
                for key, count in connection.execute(
                    f"SELECT decision_category, COUNT(*) FROM jobs{where} "
                    "GROUP BY decision_category",
                    parameters,
                )
            }
            rows = connection.execute(
                f"SELECT payload_json FROM jobs{where} "
                f"ORDER BY {order_by} LIMIT ? OFFSET ?",
                [*parameters, safe_limit, safe_offset],
            ).fetchall()
        items = [self._json_object(row[0]) for row in rows]
        return {
            "jobs": items,
            "total": total,
            "offset": safe_offset,
            "limit": safe_limit,
            "has_more": safe_offset + len(items) < total,
            "by_decision": by_decision,
        }

    def application_count(self, *, stage: str = "", search: str = "") -> int:
        where, parameters = self._application_filters(stage=stage, search=search)
        with self._connect() as connection:
            return int(
                connection.execute(
                    f"SELECT COUNT(*) FROM applications a "
                    f"LEFT JOIN jobs j ON j.job_key = a.job_key{where}",
                    parameters,
                ).fetchone()[0]
            )

    def application_records(
        self,
        *,
        stage: str = "",
        search: str = "",
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where, parameters = self._application_filters(stage=stage, search=search)
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
                    domain_category TEXT,
                    flags_text TEXT,
                    apply_method TEXT,
                    manual_status TEXT,
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
            self._ensure_column(connection, "jobs", "domain_category", "TEXT")
            self._ensure_column(connection, "jobs", "flags_text", "TEXT")
            self._ensure_column(connection, "jobs", "apply_method", "TEXT")
            self._ensure_column(connection, "jobs", "manual_status", "TEXT")
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_run_processed
                    ON jobs(run_id, processed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_jobs_domain
                    ON jobs(domain_category);
                CREATE INDEX IF NOT EXISTS idx_jobs_apply_method
                    ON jobs(apply_method);
                CREATE INDEX IF NOT EXISTS idx_jobs_manual_status
                    ON jobs(manual_status);
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

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table: str,
        column: str,
        declaration: str,
    ) -> None:
        existing = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def _delete_missing(
        self,
        connection: sqlite3.Connection,
        table: str,
        key_column: str,
        active_keys: list[str],
    ) -> None:
        if active_keys:
            temporary_table = f"active_{table}_keys"
            connection.execute(
                f"CREATE TEMP TABLE IF NOT EXISTS {temporary_table} (value TEXT PRIMARY KEY)"
            )
            connection.execute(f"DELETE FROM {temporary_table}")
            connection.executemany(
                f"INSERT OR IGNORE INTO {temporary_table} (value) VALUES (?)",
                ((key,) for key in active_keys),
            )
            connection.execute(
                f"DELETE FROM {table} WHERE NOT EXISTS ("
                f"SELECT 1 FROM {temporary_table} active "
                f"WHERE active.value = {table}.{key_column})"
            )
            connection.execute(f"DROP TABLE {temporary_table}")
        else:
            connection.execute(f"DELETE FROM {table}")

    def _job_filters(
        self,
        *,
        search: str,
        decision: str,
        run: str,
        domain: str,
        flag: str,
        apply_method: str,
        status: str,
        preset: str,
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if search:
            needle = f"%{search.lower()}%"
            clauses.append(
                "(lower(coalesce(title,'')) LIKE ? OR lower(coalesce(company,'')) LIKE ? "
                "OR lower(coalesce(location,'')) LIKE ? OR lower(payload_json) LIKE ?)"
            )
            parameters.extend([needle, needle, needle, needle])
        if decision:
            decisions = [item.strip() for item in decision.split(",") if item.strip()]
            if decisions:
                placeholders = ",".join("?" for _ in decisions)
                clauses.append(f"decision_category IN ({placeholders})")
                parameters.extend(decisions)
        if run:
            clauses.append("run_id = ?")
            parameters.append(run)
        if domain:
            clauses.append("domain_category = ?")
            parameters.append(domain)
        if flag:
            clauses.append("lower(coalesce(flags_text,'')) LIKE ?")
            parameters.append(f"%{flag.lower()}%")
        if apply_method:
            clauses.append("apply_method = ?")
            parameters.append(apply_method)
        if status:
            clauses.append("manual_status = ?")
            parameters.append(status)
        if preset == "dutch_risk":
            clauses.append(
                "(lower(payload_json) LIKE '%dutch%' OR lower(payload_json) LIKE '%nederlands%' "
                "OR lower(payload_json) LIKE '%taal%')"
            )
        elif preset == "remote_hybrid":
            clauses.append(
                "(lower(location) LIKE '%remote%' OR lower(location) LIKE '%hybrid%' "
                "OR lower(payload_json) LIKE '%remote%' OR lower(payload_json) LIKE '%hybrid%')"
            )
        return clauses, parameters

    def _application_filters(
        self,
        *,
        stage: str,
        search: str,
    ) -> tuple[str, list[Any]]:
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
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters

    def _source_signature(self, *paths: Path) -> str:
        parts = [f"sync_version:{SYNC_VERSION}"]
        for path in paths:
            try:
                stat = path.stat()
                parts.append(f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}")
            except OSError:
                parts.append(f"{path.resolve()}:missing")
        return "|".join(parts)

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
