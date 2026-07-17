"""Run logs, diagnostics, backups, and conservative maintenance tools."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
from typing import Any
import zipfile

from agent.user_workspace import UserWorkspace, now_iso


class MaintenanceService:
    """Expose operational health without exposing credentials or browser profiles."""

    LOG_SUFFIXES = {".txt", ".log"}
    BACKUP_SOURCE_FILES = (
        "data/.env",
        "data/recommended_jobs_dashboard_data.json",
        "data/recommended_jobs_dashboard_user_state.json",
        "data/scout_run_history.json",
        "data/scored_jobs_cache.json",
        "data/scout_collected_jobs.json",
        "data/job_tracking_status.json",
        "data/applications.db",
    )

    def __init__(self, workspace: UserWorkspace) -> None:
        self.workspace = workspace.ensure_initialized()
        self.root = workspace.root
        self.logs_dir = self.root / "logs"
        self.backups_dir = self.root / "backups"
        self.recovery_dir = self.backups_dir / "runtime-recovery"
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def payload(self) -> dict[str, Any]:
        logs = self.log_records()
        runs = self.run_history()
        lifecycle_runs = self.dashboard_run_history()
        return {
            "logs": logs,
            "runs": runs,
            "lifecycle_runs": lifecycle_runs,
            "diagnostics": self.diagnostics(
                logs=logs,
                runs=runs,
                lifecycle_runs=lifecycle_runs,
            ),
            "backups": self.backup_records(),
        }

    def log_records(self) -> list[dict[str, Any]]:
        if not self.logs_dir.exists():
            return []
        records = []
        for path in self.logs_dir.iterdir():
            if not path.is_file() or path.suffix.lower() not in self.LOG_SUFFIXES:
                continue
            stat = path.stat()
            records.append(
                {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
                    "kind": self._log_kind(path.name),
                }
            )
        return sorted(records, key=lambda item: item["modified_at"], reverse=True)

    def read_log(self, name: str, *, max_chars: int = 200_000) -> dict[str, Any]:
        path = self._safe_child(self.logs_dir, name, allowed_suffixes=self.LOG_SUFFIXES)
        text = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        if truncated:
            text = text[-max_chars:]
        return {
            "name": path.name,
            "text": text,
            "truncated": truncated,
            "size_bytes": path.stat().st_size,
        }

    def run_history(self) -> list[dict[str, Any]]:
        path = self.root / "data" / "scout_run_history.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        runs = payload.get("runs", []) if isinstance(payload, dict) else []
        if not isinstance(runs, list):
            return []
        output = [dict(item) for item in runs if isinstance(item, dict)]
        return sorted(
            output,
            key=lambda item: str(
                item.get("completed_at")
                or item.get("timestamp")
                or item.get("started_at")
                or ""
            ),
            reverse=True,
        )[:200]

    def dashboard_run_history(self) -> list[dict[str, Any]]:
        payload = self._read_json(self.root / "data" / "recommended_jobs_dashboard_data.json")
        runs = payload.get("runs", []) if isinstance(payload, dict) else []
        output = [dict(item) for item in runs if isinstance(item, dict)]
        return sorted(
            output,
            key=lambda item: str(item.get("completed_at") or item.get("started_at") or ""),
            reverse=True,
        )[:200]

    def diagnostics(
        self,
        *,
        logs: list[dict[str, Any]] | None = None,
        runs: list[dict[str, Any]] | None = None,
        lifecycle_runs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        logs = logs if logs is not None else self.log_records()
        runs = runs if runs is not None else self.run_history()
        lifecycle_runs = (
            lifecycle_runs if lifecycle_runs is not None else self.dashboard_run_history()
        )
        progress = self._read_json(self.root / "data" / "scout_progress.json")
        controller_state = self._read_json(
            self.root / "data" / "user_workspace" / "dashboard_run_state.json"
        )
        latest_error = self._latest_error(logs, lifecycle_runs=lifecycle_runs)
        latest_run_incident = self._latest_run_incident(
            controller_state,
            lifecycle_runs=lifecycle_runs,
        )
        persistence = self._persistence_diagnostics(
            logs,
            lifecycle_runs=lifecycle_runs,
        )
        important_paths = {
            "profile": self.workspace.profile_path,
            "preferences": self.workspace.preferences_path,
            "strategy": self.workspace.strategy_path,
            "queries": self.workspace.search_queries_path,
            "dashboard_data": self.root / "data" / "recommended_jobs_dashboard_data.json",
            "dashboard_state": self.root / "data" / "recommended_jobs_dashboard_user_state.json",
            "operational_database": self.workspace.path / "job_scout.db",
        }
        files = {
            label: {
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            }
            for label, path in important_paths.items()
        }
        return {
            "checked_at": now_iso(),
            "workspace_ready": all(
                files[label]["exists"]
                for label in ("profile", "preferences", "strategy", "queries")
            ),
            "dashboard_ready": files["dashboard_data"]["exists"],
            "operational_database": files["operational_database"],
            "resume_available": bool(progress and progress.get("status") != "completed"),
            "progress_status": str(progress.get("status") or "none"),
            "log_count": len(logs),
            "log_size_bytes": sum(int(item.get("size_bytes") or 0) for item in logs),
            "run_history_count": len(runs),
            "lifecycle_run_count": len(lifecycle_runs),
            "latest_error": latest_error,
            "latest_run_incident": latest_run_incident,
            "persistence_health": persistence["health"],
            "persistence_warning_count": persistence["warning_count"],
            "latest_persistence_warning": persistence["latest_warning"],
            "recovered_temporary_files": persistence["recovered_temporary_files"],
            "recovery_records": persistence["recovery_records"],
            "files": files,
        }

    def _latest_run_incident(
        self,
        controller_state: dict[str, Any],
        *,
        lifecycle_runs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        status = str(controller_state.get("status") or "")
        if status not in {"interrupted", "failed"}:
            return {}
        run_id = str(controller_state.get("run_id") or "")
        related = next(
            (
                run
                for run in lifecycle_runs
                if str(run.get("run_id") or "") == run_id
            ),
            {},
        )
        if status == "interrupted":
            message = str(
                controller_state.get("interruption_reason")
                or "The scout process ended before reporting a final result."
            )
            timestamp = str(
                controller_state.get("interrupted_at")
                or controller_state.get("completed_at")
                or controller_state.get("started_at")
                or ""
            )
        else:
            message = str(controller_state.get("failure_reason") or "Scout run failed.")
            timestamp = str(
                controller_state.get("completed_at")
                or controller_state.get("started_at")
                or ""
            )
        log_path = Path(str(controller_state.get("log_path") or ""))
        return {
            "status": status,
            "message": message,
            "timestamp": timestamp,
            "run_id": run_id,
            "run_label": str(related.get("run_label") or ""),
            "log": log_path.name if log_path.name else "",
            "resume_available": bool(
                self._read_json(self.root / "data" / "scout_progress.json").get("status")
                not in {"", "completed"}
            ),
        }

    def archive_historical_data(self) -> dict[str, Any]:
        """Orchestrate historical data migration to SQLite and trim JSON payloads."""
        from agent.operational_store import OperationalStore
        from agent.live_recommended_jobs_dashboard import LiveRecommendedJobsDashboard
        from agent.scout_collected_jobs import ScoutCollectedJobsStore

        dashboard_data_path = self.root / "data" / "recommended_jobs_dashboard_data.json"
        user_state_path = self.root / "data" / "recommended_jobs_dashboard_user_state.json"
        db_path = self.workspace.path / "job_scout.db"

        # 1. Initialize DB and sync dashboard/user state
        store = OperationalStore(db_path)
        sync_result = store.sync_if_changed(dashboard_data_path, user_state_path)

        # 2. Sync collected jobs
        collected_jobs_store = ScoutCollectedJobsStore(
            path=self.root / "data" / "scout_collected_jobs.json",
            operational_store=store,
        )
        collected_jobs_synced = store.sync_collected_jobs(collected_jobs_store.jobs)

        # 3. Trim live dashboard payload
        live_dashboard = LiveRecommendedJobsDashboard(dashboard_data_path)
        live_dashboard.trim_historical_runs(keep_latest_runs=10)

        # 4. Trim collected jobs payload
        collected_jobs_store.trim_old_records(keep_days=14)

        return {
            "dashboard_sync_result": sync_result,
            "collected_jobs_synced": collected_jobs_synced,
            "dashboard_runs_kept": len(live_dashboard.data.get("runs", [])),
            "dashboard_jobs_kept": len(live_dashboard.data.get("jobs", [])),
            "collected_jobs_kept": len(collected_jobs_store.jobs),
            "archived_at": now_iso(),
        }

    def create_backup(self) -> dict[str, Any]:
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        destination = self.backups_dir / f"job_scout_backup_{timestamp}.zip"
        manifest = {
            "created_at": now_iso(),
            "contains_secrets": False,
            "note": "API keys, browser profiles, cookies, and logs are intentionally excluded.",
            "files": [],
        }
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if self.workspace.path.exists():
                for path in self.workspace.path.rglob("*"):
                    if not path.is_file() or self.workspace.backup_dir in path.parents:
                        continue
                    if path.name.endswith((".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")):
                        continue
                    relative = path.relative_to(self.root)
                    archive.write(path, relative.as_posix())
                    manifest["files"].append(relative.as_posix())
            for name in self.BACKUP_SOURCE_FILES:
                path = self.root / name
                if path.exists() and path.is_file():
                    archive.write(path, name)
                    manifest["files"].append(name)
            archive.writestr(
                "backup_manifest.json",
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            )
        return self._backup_record(destination)

    def create_migration_zip(self) -> Path:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        destination = self.backups_dir / f"job_scout_migration_{timestamp}.zip"
        root_files = (
            ".env",
            "recommended_jobs_dashboard_data.json",
            "recommended_jobs_dashboard_user_state.json",
            "scout_run_history.json",
            "scored_jobs_cache.json",
            "scout_collected_jobs.json",
            "scout_progress.json",
            "job_tracking_status.json",
            "applications.db",
        )
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if self.workspace.path.exists():
                for path in self.workspace.path.rglob("*"):
                    if not path.is_file() or self.workspace.backup_dir in path.parents:
                        continue
                    relative = path.relative_to(self.root)
                    archive.write(path, relative.as_posix())
            for name in root_files:
                path = self.root / "data" / name
                if path.exists() and path.is_file():
                    archive.write(path, f"data/{path.name}")
        return destination

    def import_migration_zip(self, zip_path: Path) -> None:
        root_files = {
            ".env",
            "recommended_jobs_dashboard_data.json",
            "recommended_jobs_dashboard_user_state.json",
            "scout_run_history.json",
            "scored_jobs_cache.json",
            "scout_collected_jobs.json",
            "scout_progress.json",
            "job_tracking_status.json",
            "applications.db",
        }
        # 1. Clean existing workspace files (except backup dir itself)
        if self.workspace.path.exists():
            for path in self.workspace.path.glob("*"):
                if path == self.workspace.backup_dir:
                    continue
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()

        # 2. Extract files from zip
        with zipfile.ZipFile(zip_path, "r") as archive:
            for member in archive.namelist():
                normalized_member = Path(member).as_posix()
                try:
                    member_path = self.root / normalized_member
                    is_workspace_file = self.workspace.path in member_path.parents
                except Exception:
                    is_workspace_file = False
                
                is_root_file = normalized_member in root_files
                is_data_file = normalized_member in [f"data/{f}" for f in root_files]
                if is_workspace_file or is_data_file:
                    archive.extract(member, self.root)
                elif is_root_file:
                    # Backward compatibility for old ZIPs: redirect to data/
                    data_file_path = self.root / "data" / Path(member).name
                    data_file_path.parent.mkdir(parents=True, exist_ok=True)
                    data_file_path.write_bytes(archive.read(member))

    def create_session_backup_zip(self) -> Path:

        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        destination = self.backups_dir / f"job_scout_sessions_{timestamp}.zip"
        dirs_to_backup = []
        for name in ("browser_profile", "indeed_browser_profile"):
            p = self.root / "data" / name
            if p.exists() and p.is_dir():
                dirs_to_backup.append(p)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for dir_path in dirs_to_backup:
                for path in dir_path.rglob("*"):
                    if not path.is_file():
                        continue
                    # Skip heavy browser cache, temporary, and GPU cache files to keep the ZIP tiny
                    parts = [part.lower() for part in path.parts]
                    if any(
                        term in parts
                        for term in (
                            "cache",
                            "code cache",
                            "gpucache",
                            "crashpad",
                            "logs",
                            "cachestorage",
                            "scriptcache",
                        )
                    ) or path.name.lower() in ("lock", "lockfile", "lockfile.lock", "lockfile_lock"):
                        continue
                    relative = path.relative_to(self.root)
                    archive.write(path, relative.as_posix())
        return destination

    def import_session_backup_zip(self, zip_path: Path) -> None:
        for name in ("browser_profile", "indeed_browser_profile"):
            p = self.root / "data" / name
            if p.exists():
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
        with zipfile.ZipFile(zip_path, "r") as archive:
            for member in archive.namelist():
                normalized_member = Path(member).as_posix()
                if normalized_member.startswith(("data/browser_profile/", "data/indeed_browser_profile/")):
                    archive.extract(member, self.root)

    def backup_records(self) -> list[dict[str, Any]]:
        records = [
            self._backup_record(path)
            for path in self.backups_dir.glob("job_scout_backup_*.zip")
            if path.is_file()
        ]
        return sorted(records, key=lambda item: item["modified_at"], reverse=True)

    def backup_path(self, name: str) -> Path:
        return self._safe_child(self.backups_dir, name, allowed_suffixes={".zip"})

    def prune_logs(self, *, older_than_days: int = 90, keep_latest: int = 10) -> dict[str, Any]:
        older_than_days = max(7, min(3650, int(older_than_days)))
        keep_latest = max(5, min(100, int(keep_latest)))
        records = self.log_records()
        protected = {item["name"] for item in records[:keep_latest]}
        cutoff = datetime.now().astimezone() - timedelta(days=older_than_days)
        deleted: list[str] = []
        bytes_removed = 0
        for record in records:
            if record["name"] in protected:
                continue
            modified = datetime.fromisoformat(record["modified_at"])
            if modified >= cutoff:
                continue
            path = self._safe_child(
                self.logs_dir,
                record["name"],
                allowed_suffixes=self.LOG_SUFFIXES,
            )
            bytes_removed += path.stat().st_size
            path.unlink()
            deleted.append(path.name)
        return {
            "deleted_count": len(deleted),
            "bytes_removed": bytes_removed,
            "older_than_days": older_than_days,
            "kept_latest": keep_latest,
        }

    def _latest_error(
        self,
        logs: list[dict[str, Any]],
        *,
        lifecycle_runs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        markers = ("fatal error", "traceback", "resource_exhausted", "unhandled exception")
        for record in logs[:20]:
            if record.get("kind") not in {"dashboard_run", "scout"}:
                continue
            try:
                payload = self.read_log(record["name"], max_chars=40_000)
            except OSError:
                continue
            lines = payload["text"].splitlines()
            for line in reversed(lines):
                lowered = line.lower()
                if any(marker in lowered for marker in markers):
                    error_at = str(record.get("modified_at") or "")
                    related_run = self._related_run(error_at, lifecycle_runs)
                    latest_success = max(
                        (
                            str(run.get("completed_at") or "")
                            for run in lifecycle_runs
                            if run.get("status") == "completed"
                        ),
                        default="",
                    )
                    resolved = bool(latest_success and latest_success > error_at)
                    return {
                        "log": record["name"],
                        "message": line.strip()[:500],
                        "timestamp": error_at,
                        "status": "resolved" if resolved else "active",
                        "resolved": resolved,
                        "run_id": str(related_run.get("run_id") or ""),
                        "run_label": str(related_run.get("run_label") or ""),
                    }
        return {}

    def _persistence_diagnostics(
        self,
        logs: list[dict[str, Any]],
        *,
        lifecycle_runs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        warnings: list[dict[str, Any]] = []
        latest_success = max(
            (
                str(run.get("completed_at") or "")
                for run in lifecycle_runs
                if run.get("status") == "completed"
            ),
            default="",
        )
        for record in logs[:50]:
            try:
                payload = self.read_log(record["name"], max_chars=200_000)
            except OSError:
                continue
            for line in reversed(payload["text"].splitlines()):
                lowered = line.lower()
                is_warning = "[persistence warning]" in lowered
                is_legacy_lock = (
                    "live dashboard progress update skipped" in lowered
                    and ("access is denied" in lowered or "winerror 5" in lowered)
                )
                if not is_warning and not is_legacy_lock:
                    continue
                warning_at = str(record.get("modified_at") or "")
                related_run = self._related_run(warning_at, lifecycle_runs)
                resolved = (
                    related_run.get("status") == "completed"
                    or bool(latest_success and latest_success > warning_at)
                )
                warnings.append(
                    {
                        "log": record["name"],
                        "message": line.strip()[:500],
                        "timestamp": warning_at,
                        "status": "recovered" if resolved else "active",
                        "resolved": resolved,
                        "run_id": str(related_run.get("run_id") or ""),
                        "run_label": str(related_run.get("run_label") or ""),
                    }
                )

        recovery_records = self._recovery_records()
        promoted_count = sum(
            1 for record in recovery_records if record.get("action") == "promoted"
        )
        active_warnings = [warning for warning in warnings if not warning["resolved"]]
        health = "degraded" if active_warnings else ("recovered" if warnings else "healthy")
        return {
            "health": health,
            "warning_count": len(warnings),
            "latest_warning": warnings[0] if warnings else {},
            "recovered_temporary_files": promoted_count,
            "recovery_records": recovery_records[:20],
        }

    def _recovery_records(self) -> list[dict[str, Any]]:
        if not self.recovery_dir.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in self.recovery_dir.glob("recovery_*.json"):
            payload = self._read_json(path)
            if not payload:
                continue
            records.append(
                {
                    "recorded_at": str(payload.get("recorded_at") or ""),
                    "target": str(payload.get("target") or ""),
                    "candidate": str(payload.get("candidate") or ""),
                    "action": str(payload.get("action") or ""),
                }
            )
        return sorted(
            records,
            key=lambda record: record["recorded_at"],
            reverse=True,
        )[:200]

    def _related_run(
        self,
        timestamp: str,
        lifecycle_runs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        candidates = [
            run
            for run in lifecycle_runs
            if str(run.get("started_at") or "") <= timestamp
        ]
        if not candidates:
            return {}
        return max(candidates, key=lambda run: str(run.get("started_at") or ""))

    def _log_kind(self, name: str) -> str:
        lowered = name.lower()
        if lowered.startswith("dashboard_run_"):
            return "dashboard_run"
        if lowered.startswith("scout_log_"):
            return "scout"
        if "server" in lowered:
            return "server"
        return "other"

    def _backup_record(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "name": path.name,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
        }

    def _safe_child(
        self,
        directory: Path,
        name: str,
        *,
        allowed_suffixes: set[str],
    ) -> Path:
        clean_name = Path(str(name or "")).name
        if not clean_name or clean_name != str(name or ""):
            raise ValueError("Invalid file name")
        path = (directory / clean_name).resolve()
        directory_resolved = directory.resolve()
        if path.parent != directory_resolved or path.suffix.lower() not in allowed_suffixes:
            raise ValueError("File is outside the allowed directory")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(clean_name)
        return path

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
