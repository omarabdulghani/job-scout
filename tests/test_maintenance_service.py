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
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "data").mkdir(parents=True, exist_ok=True)
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
            (root / "data" / ".env").write_text("SECRET=value", encoding="utf-8")
            (root / "data" / "browser_profile").mkdir(exist_ok=True)
            (root / "data" / "browser_profile" / "Cookies").write_text("secret", encoding="utf-8")
            (root / "data/recommended_jobs_dashboard_user_state.json").parent.mkdir(parents=True, exist_ok=True)
            (root / "data/recommended_jobs_dashboard_user_state.json").write_text("{}", encoding="utf-8")

            record = service.create_backup()

            with zipfile.ZipFile(root / "backups" / record["name"]) as archive:
                names = archive.namelist()
            self.assertIn("backup_manifest.json", names)
            self.assertIn("data/recommended_jobs_dashboard_user_state.json", names)
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
            service.logs_dir.mkdir(exist_ok=True)
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
            service.logs_dir.mkdir(exist_ok=True)
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
            (root / "data/recommended_jobs_dashboard_data.json").parent.mkdir(parents=True, exist_ok=True)
            (root / "data/recommended_jobs_dashboard_data.json").write_text(
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
            service.logs_dir.mkdir(exist_ok=True)
            log_path = service.logs_dir / "dashboard_run_failed.txt"
            log_path.write_text("Traceback: example failure\n", encoding="utf-8")

            latest_error = service.payload()["diagnostics"]["latest_error"]

            self.assertEqual(latest_error["status"], "active")
            self.assertFalse(latest_error["resolved"])

    def test_server_disconnect_traceback_is_not_reported_as_scout_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            service.logs_dir.mkdir(exist_ok=True)
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
            service.logs_dir.mkdir(exist_ok=True)
            log_path = service.logs_dir / "dashboard_run_persistence.txt"
            log_path.write_text(
                "[PERSISTENCE WARNING] Live dashboard job update: Access is denied\n",
                encoding="utf-8",
            )
            warning_time = datetime.now().astimezone() - timedelta(minutes=5)
            os.utime(log_path, (warning_time.timestamp(), warning_time.timestamp()))
            (root / "data/recommended_jobs_dashboard_data.json").parent.mkdir(parents=True, exist_ok=True)
            (root / "data/recommended_jobs_dashboard_data.json").write_text(
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
            service.logs_dir.mkdir(exist_ok=True)
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
            service.recovery_dir.mkdir(parents=True, exist_ok=True)
            (service.recovery_dir / "recovery_example.json").write_text(
                json.dumps(
                    {
                        "recorded_at": "2026-06-12T10:00:00+02:00",
                        "target": "data/scout_progress.json",
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
                "data/scout_progress.json",
            )

    def test_interrupted_controller_is_exposed_as_latest_run_incident(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            service.logs_dir.mkdir(exist_ok=True)
            log_path = service.logs_dir / "dashboard_run_interrupted.txt"
            log_path.write_text("last useful line\n", encoding="utf-8")
            controller_path = root / "data" / "user_workspace" / "dashboard_run_state.json"
            controller_path.parent.mkdir(parents=True, exist_ok=True)
            controller_path.write_text(
                json.dumps(
                    {
                        "status": "interrupted",
                        "run_id": "run_36",
                        "interrupted_at": "2026-06-13T01:46:00+02:00",
                        "interruption_reason": "The process disappeared.",
                        "log_path": str(log_path),
                    }
                ),
                encoding="utf-8",
            )
            (root / "data/scout_progress.json").write_text(
                '{"status":"in_progress"}',
                encoding="utf-8",
            )
            (root / "data/recommended_jobs_dashboard_data.json").parent.mkdir(parents=True, exist_ok=True)
            (root / "data/recommended_jobs_dashboard_data.json").write_text(
                json.dumps(
                    {
                        "runs": [
                            {
                                "run_id": "run_36",
                                "run_label": "Run 36",
                                "status": "interrupted",
                                "started_at": "2026-06-13T00:10:00+02:00",
                                "completed_at": "2026-06-13T01:46:00+02:00",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            incident = service.payload()["diagnostics"]["latest_run_incident"]

            self.assertEqual(incident["status"], "interrupted")
            self.assertEqual(incident["run_id"], "run_36")
            self.assertEqual(incident["run_label"], "Run 36")
            self.assertEqual(incident["log"], log_path.name)
            self.assertTrue(incident["resume_available"])

    def test_session_backup_and_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            
            # Create session profiles
            bp = root / "data" / "browser_profile"
            ibp = root / "data" / "indeed_browser_profile"
            bp.mkdir(parents=True, exist_ok=True)
            ibp.mkdir(parents=True, exist_ok=True)
            
            cookie1 = bp / "Cookies"
            cookie1.write_text("linkedin_cookie_data", encoding="utf-8")
            cookie2 = ibp / "Cookies"
            cookie2.write_text("indeed_cookie_data", encoding="utf-8")
            
            # 1. Test Backup
            zip_path = service.create_session_backup_zip()
            self.assertTrue(zip_path.exists())
            
            with zipfile.ZipFile(zip_path, "r") as archive:
                names = archive.namelist()
            self.assertIn("data/browser_profile/Cookies", names)
            self.assertIn("data/indeed_browser_profile/Cookies", names)
            
            # Create a junk file in the profiles to verify it gets cleared on import
            junk_file = bp / "junk.txt"
            junk_file.write_text("should be removed", encoding="utf-8")
            self.assertTrue(junk_file.exists())
            
            # 2. Test Import
            service.import_session_backup_zip(zip_path)
            self.assertFalse(junk_file.exists())
            self.assertEqual(cookie1.read_text(encoding="utf-8"), "linkedin_cookie_data")
            self.assertEqual(cookie2.read_text(encoding="utf-8"), "indeed_cookie_data")

    def test_migration_backup_and_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            
            # Create root data files and workspace files
            scored_cache = root / "data/scored_jobs_cache.json"
            scored_cache.write_text('{"scored": []}', encoding="utf-8")
            
            ws_db = service.workspace.path / "job_scout.db"
            ws_db.parent.mkdir(parents=True, exist_ok=True)
            ws_db.write_text("sqlite database data", encoding="utf-8")
            
            # 1. Test Backup Creation
            zip_path = service.create_migration_zip()
            self.assertTrue(zip_path.exists())
            
            with zipfile.ZipFile(zip_path, "r") as archive:
                names = archive.namelist()
            self.assertIn("data/scored_jobs_cache.json", names)
            
            relative_db_path = ws_db.relative_to(root).as_posix()
            self.assertIn(relative_db_path, names)
            
            # Write a junk file inside workspace that should be deleted on import
            junk_file = service.workspace.path / "junk.txt"
            junk_file.write_text("to be deleted", encoding="utf-8")
            self.assertTrue(junk_file.exists())
            
            # 2. Test Import
            service.import_migration_zip(zip_path)
            self.assertFalse(junk_file.exists())
            self.assertEqual(scored_cache.read_text(encoding="utf-8"), '{"scored": []}')
            self.assertEqual(ws_db.read_text(encoding="utf-8"), "sqlite database data")



if __name__ == "__main__":
    unittest.main()


