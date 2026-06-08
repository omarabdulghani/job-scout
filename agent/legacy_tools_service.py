"""Read-only information for audited legacy capabilities."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any


class LegacyToolsService:
    """Expose tracker statistics without creating or mutating tracker data."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self.database_path = self.root / "data" / "applications.db"

    def payload(self) -> dict[str, Any]:
        applications = {"total": 0, "today": 0, "by_status": {}, "recent": []}
        reviews = {"total": 0, "by_decision": {}, "recent": []}
        seen_jobs = 0
        if self.database_path.exists():
            try:
                with closing(self._connect_read_only()) as connection:
                    if self._table_exists(connection, "applications"):
                        applications["total"] = self._table_count(connection, "applications")
                        applications["today"] = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM applications WHERE applied_at LIKE ?",
                                (f"{datetime.now().date().isoformat()}%",),
                            ).fetchone()[0]
                        )
                        applications["by_status"] = {
                            str(status or "unknown"): int(count)
                            for status, count in connection.execute(
                                "SELECT status, COUNT(*) FROM applications GROUP BY status"
                            )
                        }
                        applications["recent"] = [
                            {
                                "title": str(title or ""),
                                "company": str(company or ""),
                                "status": str(status or ""),
                                "applied_at": str(applied_at or ""),
                            }
                            for title, company, status, applied_at in connection.execute(
                                "SELECT title, company, status, applied_at "
                                "FROM applications ORDER BY applied_at DESC LIMIT 5"
                            )
                        ]
                    if self._table_exists(connection, "job_reviews"):
                        reviews["total"] = self._table_count(connection, "job_reviews")
                        reviews["by_decision"] = {
                            str(decision or "unknown"): int(count)
                            for decision, count in connection.execute(
                                "SELECT decision, COUNT(*) FROM job_reviews GROUP BY decision"
                            )
                        }
                        reviews["recent"] = [
                            {
                                "title": str(title or ""),
                                "company": str(company or ""),
                                "decision": str(decision or ""),
                                "reviewed_at": str(reviewed_at or ""),
                            }
                            for title, company, decision, reviewed_at in connection.execute(
                                "SELECT title, company, decision, reviewed_at "
                                "FROM job_reviews ORDER BY reviewed_at DESC LIMIT 5"
                            )
                        ]
                    seen_jobs = self._table_count(connection, "seen_jobs")
            except sqlite3.Error:
                pass
        return {
            "read_only": True,
            "database_available": self.database_path.exists(),
            "database_path": str(self.database_path.relative_to(self.root)),
            "applications": applications,
            "reviews": reviews,
            "seen_jobs": seen_jobs,
            "approved_workflows": [
                {
                    "value": "validate_boards",
                    "label": "Validate job boards",
                    "description": (
                        "Opens enabled job boards and inspects selectors. "
                        "It cannot submit applications."
                    ),
                    "can_apply": False,
                }
            ],
            "blocked_capabilities": [
                "Automatic final application submission",
                "Unaudited Glassdoor execution",
            ],
            "safety": {
                "validation_only": True,
                "pause_before_final_submit": True,
                "automatic_submission_exposed": False,
                "glassdoor_execution_exposed": False,
            },
        }

    def _connect_read_only(self) -> sqlite3.Connection:
        uri = f"file:{self.database_path.as_posix()}?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=5)

    def _table_exists(self, connection: sqlite3.Connection, table: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _table_count(self, connection: sqlite3.Connection, table: str) -> int:
        if not self._table_exists(connection, table):
            return 0
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
