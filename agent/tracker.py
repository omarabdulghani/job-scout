import sqlite3
import json
from datetime import datetime
from pathlib import Path


class ApplicationTracker:
    """Tracks all job applications to avoid duplicates and log progress."""

    def __init__(self, db_path: str = "data/applications.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS applications (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id       TEXT UNIQUE,
                title        TEXT,
                company      TEXT,
                location     TEXT,
                url          TEXT,
                source       TEXT,
                status       TEXT DEFAULT 'applied',
                match_score  INTEGER,
                applied_at   TEXT,
                notes        TEXT
            );

            CREATE TABLE IF NOT EXISTS seen_jobs (
                job_id TEXT PRIMARY KEY,
                seen_at TEXT
            );

            CREATE TABLE IF NOT EXISTS job_reviews (
                job_id       TEXT PRIMARY KEY,
                title        TEXT,
                company      TEXT,
                location     TEXT,
                url          TEXT,
                source       TEXT,
                decision     TEXT,
                match_score  INTEGER,
                reasons      TEXT,
                reviewed_at  TEXT
            );
        """)
        self.conn.commit()

    def already_applied(self, job_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM applications WHERE job_id = ?", (job_id,)
        )
        return cur.fetchone() is not None

    def already_processed(self, job_id: str) -> bool:
        return self.already_applied(job_id)

    def already_rejected(self, job_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM job_reviews WHERE job_id = ? AND decision = 'rejected'",
            (job_id,),
        )
        return cur.fetchone() is not None

    def already_seen(self, job_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM seen_jobs WHERE job_id = ?", (job_id,)
        )
        return cur.fetchone() is not None

    def mark_seen(self, job_id: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_jobs VALUES (?, ?)",
            (job_id, datetime.now().isoformat())
        )
        self.conn.commit()

    def record_application(self, job: dict, status: str = "applied", notes: str = ""):
        self.conn.execute("""
            INSERT OR REPLACE INTO applications
            (job_id, title, company, location, url, source, status, match_score, applied_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job.get("id"), job.get("title"), job.get("company"),
            job.get("location"), job.get("url"), job.get("source"),
            status, job.get("match_score"), datetime.now().isoformat(), notes
        ))
        self.conn.commit()

    def record_review(self, job: dict, decision: str, reasons: str = ""):
        self.conn.execute("""
            INSERT OR REPLACE INTO job_reviews
            (job_id, title, company, location, url, source, decision, match_score, reasons, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job.get("id"), job.get("title"), job.get("company"),
            job.get("location"), job.get("url"), job.get("source"),
            decision, job.get("match_score"), reasons, datetime.now().isoformat()
        ))
        self.conn.commit()

    def get_today_count(self) -> int:
        today = datetime.now().date().isoformat()
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status = 'applied' AND applied_at LIKE ?",
            (f"{today}%",),
        )
        return cur.fetchone()[0]

    def get_all_applications(self) -> list:
        cur = self.conn.execute(
            "SELECT * FROM applications ORDER BY applied_at DESC"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_recent_reviews(self, decision: str = None, limit: int = 10) -> list:
        if decision:
            cur = self.conn.execute(
                "SELECT * FROM job_reviews WHERE decision = ? ORDER BY reviewed_at DESC LIMIT ?",
                (decision, limit),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM job_reviews ORDER BY reviewed_at DESC LIMIT ?",
                (limit,),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def print_summary(self):
        apps = self.get_all_applications()
        print(f"\nTotal applications: {len(apps)}")
        by_status = {}
        for a in apps:
            by_status[a["status"]] = by_status.get(a["status"], 0) + 1
        for status, count in by_status.items():
            print(f"   {status}: {count}")

        reviews = self.get_recent_reviews(limit=1)
        if reviews:
            review_count = self.conn.execute(
                "SELECT COUNT(*) FROM job_reviews"
            ).fetchone()[0]
            print(f"Total reviewed jobs: {review_count}")
