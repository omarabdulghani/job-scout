from contextlib import closing
from datetime import datetime, timedelta, timezone
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent.legacy_tools_service import LegacyToolsService


class LegacyToolsServiceTests(unittest.TestCase):
    def test_missing_database_is_reported_without_creating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = LegacyToolsService(root)

            payload = service.payload()

            self.assertFalse(payload["database_available"])
            self.assertEqual(payload["applications"]["total"], 0)
            self.assertFalse(service.database_path.exists())
            self.assertTrue(payload["safety"]["validation_only"])
            self.assertTrue(payload["safety"]["pause_before_final_submit"])
            self.assertFalse(payload["safety"]["automatic_submission_exposed"])

    def test_statistics_are_read_from_existing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_path = root / "data" / "applications.db"
            database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(database_path)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE applications (
                        title TEXT, company TEXT, status TEXT, applied_at TEXT
                    );
                    CREATE TABLE job_reviews (
                        title TEXT, company TEXT, decision TEXT, reviewed_at TEXT
                    );
                    CREATE TABLE seen_jobs (job_id TEXT);
                    INSERT INTO applications VALUES
                        ('UX Designer', 'Example', 'applied', '2026-06-09T00:15:00+02:00'),
                        ('Product Designer', 'Studio', 'interview', '2026-01-01');
                    INSERT INTO job_reviews VALUES
                        ('Researcher', 'Lab', 'rejected', '2026-01-02');
                    INSERT INTO seen_jobs VALUES ('1'), ('2'), ('3');
                    """
                )
                connection.commit()

            local_now = datetime(
                2026,
                6,
                9,
                0,
                30,
                tzinfo=timezone(timedelta(hours=2)),
            )
            payload = LegacyToolsService(
                root,
                now_provider=lambda: local_now,
            ).payload()

            self.assertTrue(payload["database_available"])
            self.assertEqual(payload["applications"]["total"], 2)
            self.assertEqual(payload["applications"]["today"], 1)
            self.assertEqual(payload["applications"]["by_status"]["applied"], 1)
            self.assertEqual(payload["reviews"]["total"], 1)
            self.assertEqual(payload["reviews"]["by_decision"]["rejected"], 1)
            self.assertEqual(payload["seen_jobs"], 3)
            self.assertFalse(payload["approved_workflows"][0]["can_apply"])

    def test_today_count_uses_injected_local_date_at_utc_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_path = root / "data" / "applications.db"
            database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(database_path)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE applications (
                        title TEXT, company TEXT, status TEXT, applied_at TEXT
                    );
                    INSERT INTO applications VALUES
                        ('Local Today', 'Example', 'applied', '2026-06-09T00:05:00+02:00'),
                        ('UTC Yesterday', 'Example', 'applied', '2026-06-08T22:30:00+00:00');
                    """
                )
                connection.commit()
            local_now = datetime(
                2026,
                6,
                9,
                0,
                30,
                tzinfo=timezone(timedelta(hours=2)),
            )

            payload = LegacyToolsService(
                root,
                now_provider=lambda: local_now,
            ).payload()

            self.assertEqual(payload["applications"]["total"], 2)
            self.assertEqual(payload["applications"]["today"], 1)
