import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
import os
import unittest
import zipfile

from agent.maintenance_service import MaintenanceService
from agent.user_workspace import UserWorkspace


class MaintenanceServiceTests(unittest.TestCase):
    def _service(self, root: Path) -> MaintenanceService:
        (root / "config").mkdir(parents=True)
        (root / "data").mkdir(parents=True)
        (root / "config" / "profile.json").write_text('{"cv_path": ""}', encoding="utf-8")
        (root / "config" / "preferences.json").write_text("{}", encoding="utf-8")
        (root / "search_queries.txt").write_text("ux designer\n", encoding="utf-8")
        (root / "PERFECT SUITABLE JOB PROFILE.txt").write_text("Strategy", encoding="utf-8")
        (root / "data" / "portfolio_site_notes.txt").write_text("Portfolio", encoding="utf-8")
        return MaintenanceService(UserWorkspace(root))

    def test_backup_excludes_env_and_browser_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            (root / ".env").write_text("SECRET=value", encoding="utf-8")
            (root / "data" / "browser_profile").mkdir()
            (root / "data" / "browser_profile" / "Cookies").write_text("secret", encoding="utf-8")
            (root / "recommended_jobs_dashboard_user_state.json").write_text("{}", encoding="utf-8")

            record = service.create_backup()

            with zipfile.ZipFile(root / "backups" / record["name"]) as archive:
                names = archive.namelist()
            self.assertIn("backup_manifest.json", names)
            self.assertIn("recommended_jobs_dashboard_user_state.json", names)
            self.assertNotIn(".env", names)
            self.assertFalse(any("browser_profile" in name for name in names))

    def test_log_reader_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            with self.assertRaises(ValueError):
                service.read_log("../secret.txt")

    def test_prune_keeps_recent_and_latest_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            service.logs_dir.mkdir()
            old_time = (datetime.now() - timedelta(days=120)).timestamp()
            for index in range(7):
                path = service.logs_dir / f"scout_log_{index}.txt"
                path.write_text("log", encoding="utf-8")
                os.utime(path, (old_time + index, old_time + index))

            result = service.prune_logs(older_than_days=90, keep_latest=5)

            self.assertEqual(result["deleted_count"], 2)
            self.assertEqual(len(list(service.logs_dir.glob("*.txt"))), 5)

    def test_diagnostic_error_is_tied_to_run_and_marked_resolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            service.logs_dir.mkdir()
            log_path = service.logs_dir / "dashboard_run_2026-06-08_10-00-00.txt"
            log_path.write_text("Fatal error: example failure\n", encoding="utf-8")
            error_time = datetime.now().astimezone() - timedelta(minutes=10)
            os.utime(log_path, (error_time.timestamp(), error_time.timestamp()))
            dashboard = {
                "runs": [
                    {
                        "run_id": "run_1",
                        "run_label": "Run 1",
                        "status": "completed",
                        "started_at": (error_time - timedelta(minutes=20)).isoformat(),
                        "completed_at": (error_time + timedelta(minutes=5)).isoformat(),
                    }
                ]
            }
            (root / "recommended_jobs_dashboard_data.json").write_text(
                json.dumps(dashboard),
                encoding="utf-8",
            )

            diagnostics = service.payload()["diagnostics"]
            latest_error = diagnostics["latest_error"]

            self.assertEqual(latest_error["run_id"], "run_1")
            self.assertEqual(latest_error["status"], "resolved")
            self.assertTrue(latest_error["resolved"])
            self.assertEqual(latest_error["log"], log_path.name)

    def test_unresolved_diagnostic_error_remains_active(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            service.logs_dir.mkdir()
            log_path = service.logs_dir / "dashboard_run_failed.txt"
            log_path.write_text("Traceback: example failure\n", encoding="utf-8")

            latest_error = service.payload()["diagnostics"]["latest_error"]

            self.assertEqual(latest_error["status"], "active")
            self.assertFalse(latest_error["resolved"])

    def test_server_disconnect_traceback_is_not_reported_as_scout_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            service.logs_dir.mkdir()
            (service.logs_dir / "dashboard_server_stderr.log").write_text(
                "Traceback (most recent call last):\n"
                "ConnectionAbortedError: [WinError 10053] connection aborted\n",
                encoding="utf-8",
            )

            latest_error = service.payload()["diagnostics"]["latest_error"]

            self.assertEqual(latest_error, {})

    def test_completed_run_marks_persistence_warning_recovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            service.logs_dir.mkdir()
            log_path = service.logs_dir / "dashboard_run_persistence.txt"
            log_path.write_text(
                "[PERSISTENCE WARNING] Live dashboard job update: Access is denied\n",
                encoding="utf-8",
            )
            warning_time = datetime.now().astimezone() - timedelta(minutes=5)
            os.utime(log_path, (warning_time.timestamp(), warning_time.timestamp()))
            (root / "recommended_jobs_dashboard_data.json").write_text(
                json.dumps(
                    {
                        "runs": [
                            {
                                "run_id": "run_2",
                                "run_label": "Run 2",
                                "status": "completed",
                                "started_at": (
                                    warning_time - timedelta(minutes=30)
                                ).isoformat(),
                                "completed_at": (
                                    warning_time + timedelta(minutes=1)
                                ).isoformat(),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            diagnostics = service.payload()["diagnostics"]

            self.assertEqual(diagnostics["persistence_health"], "recovered")
            self.assertEqual(diagnostics["persistence_warning_count"], 1)
            self.assertTrue(diagnostics["latest_persistence_warning"]["resolved"])
            self.assertEqual(
                diagnostics["latest_persistence_warning"]["run_id"],
                "run_2",
            )

    def test_unresolved_persistence_warning_is_degraded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            service.logs_dir.mkdir()
            (service.logs_dir / "dashboard_run_persistence.txt").write_text(
                "[PERSISTENCE WARNING] Scout progress checkpoint: Access is denied\n",
                encoding="utf-8",
            )

            diagnostics = service.payload()["diagnostics"]

            self.assertEqual(diagnostics["persistence_health"], "degraded")
            self.assertFalse(diagnostics["latest_persistence_warning"]["resolved"])

    def test_recovery_events_are_counted_without_exposing_payloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            service.recovery_dir.mkdir(parents=True)
            (service.recovery_dir / "recovery_example.json").write_text(
                json.dumps(
                    {
                        "recorded_at": "2026-06-12T10:00:00+02:00",
                        "target": "scout_progress.json",
                        "candidate": ".scout_progress.json.example.tmp",
                        "action": "promoted",
                    }
                ),
                encoding="utf-8",
            )

            diagnostics = service.payload()["diagnostics"]

            self.assertEqual(diagnostics["recovered_temporary_files"], 1)
            self.assertEqual(
                diagnostics["recovery_records"][0]["target"],
                "scout_progress.json",
            )


if __name__ == "__main__":
    unittest.main()
