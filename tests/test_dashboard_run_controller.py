import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from serve_dashboard import DashboardRunController


class DashboardRunControllerTests(unittest.TestCase):
    def _command_fingerprint(self, command):
        encoded = json.dumps(
            command,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _write_live_run(self, path: Path, *, status: str = "running") -> None:
        path.write_text(
            json.dumps(
                {
                    "schema_version": "live_dashboard.v1",
                    "active_run_id": "run_1" if status == "running" else "",
                    "runs": [
                        {
                            "run_id": "run_1",
                            "run_number": 1,
                            "run_label": "Run 1",
                            "started_at": "2026-06-08T10:00:00+02:00",
                            "completed_at": "",
                            "status": status,
                            "stats": {},
                            "fresh_scout": {
                                "enabled": True,
                                "policy": {},
                                "progress": {
                                    "phase": "processing_jobs",
                                    "current_query": "ux designer",
                                    "current_query_index": 2,
                                    "total_queries": 10,
                                },
                                "page_history": [],
                            },
                        }
                    ],
                    "jobs": [],
                    "summary": {},
                    "filter_options": {},
                }
            ),
            encoding="utf-8",
        )

    def test_recommended_multi_command_uses_allowlisted_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            command, workflow, label = controller.build_command(
                {
                    "workflow": "linkedin_multi_fresh",
                    "location": "Amstelveen",
                    "max_pages": "1",
                    "browser": "chromium",
                    "human_mode": True,
                    "fresh": True,
                    "resume": True,
                    "ai_budget_mode": "deep",
                }
            )

        self.assertEqual(command[0], sys.executable)
        self.assertEqual(workflow, "linkedin_multi_fresh")
        self.assertEqual(label, "LinkedIn multi-query fresh")
        self.assertIn("scout_jobs_multi.py", command)
        self.assertIn("--fresh", command)
        self.assertIn("--resume", command)
        self.assertIn("--human-mode", command)
        self.assertIn("--ai-budget-mode", command)
        self.assertEqual(command[command.index("--ai-budget-mode") + 1], "deep")
        self.assertIn("--browser", command)
        self.assertIn("--search-goal", command)
        self.assertEqual(command[command.index("--search-goal") + 1], "career-growth")

    def test_custom_search_goal_allows_only_approved_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            command, _workflow, _label = controller.build_command(
                {
                    "workflow": "linkedin_multi_fresh",
                    "search_goal": "custom",
                    "search_groups": ["fallback", "primary", "not-a-group"],
                }
            )

        self.assertEqual(command[command.index("--search-goal") + 1], "custom")
        self.assertEqual(
            command[command.index("--search-groups") + 1],
            "primary,fallback",
        )

    def test_custom_search_goal_requires_a_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            with self.assertRaisesRegex(ValueError, "at least one"):
                controller.build_command(
                    {
                        "workflow": "linkedin_multi_fresh",
                        "search_goal": "custom",
                        "search_groups": [],
                    }
                )

    def test_all_search_goal_presets_are_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            for goal in ("career-growth", "career-focus", "broad", "income"):
                with self.subTest(goal=goal):
                    command, _workflow, _label = controller.build_command(
                        {
                            "workflow": "linkedin_multi_fresh",
                            "search_goal": goal,
                        }
                    )
                    self.assertEqual(
                        command[command.index("--search-goal") + 1],
                        goal,
                    )
                    self.assertNotIn("--search-groups", command)

    def test_single_query_requires_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            with self.assertRaises(ValueError):
                controller.build_command({"workflow": "linkedin_single", "query": ""})

    def test_rejects_unapproved_values_by_falling_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            command, workflow, _label = controller.build_command(
                {
                    "workflow": "rm -rf nope",
                    "location": "Amstelveen; bad",
                    "max_pages": "999",
                    "browser": "bad-browser",
                    "ai_budget_mode": "bad-mode",
                    "human_mode": False,
                    "fresh": False,
                }
            )

        self.assertEqual(workflow, "linkedin_multi_fresh")
        self.assertIn("scout_jobs_multi.py", command)
        self.assertIn("--max-pages", command)
        self.assertEqual(command[command.index("--max-pages") + 1], "1")
        self.assertEqual(command[command.index("--browser") + 1], "chromium")
        self.assertNotIn("--ai-budget-mode", command)
        self.assertNotIn("--human-mode", command)

    def test_smart_ai_budget_mode_is_default_and_not_added_to_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            command, _workflow, _label = controller.build_command(
                {
                    "workflow": "linkedin_multi_fresh",
                    "location": "Amstelveen",
                    "max_pages": "1",
                    "browser": "chromium",
                    "human_mode": True,
                    "fresh": True,
                }
            )

        self.assertNotIn("--ai-budget-mode", command)

    def test_germany_beta_scope_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            command, _workflow, _label = controller.build_command(
                {
                    "workflow": "linkedin_multi_fresh",
                    "search_market": "germany",
                    "location": "Berlin",
                    "radius_km": 40,
                    "employment": "full-time-preferred",
                }
            )

        self.assertEqual(command[command.index("--search-market") + 1], "germany")
        self.assertEqual(command[command.index("--location") + 1], "Berlin")
        self.assertEqual(command[command.index("--radius-km") + 1], "40")

    def test_experimental_market_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            with patch.dict(
                "serve_dashboard.MARKET_PROFILES",
                {"uae": {"label": "United Arab Emirates", "availability": "experimental"}},
            ):
                with self.assertRaisesRegex(ValueError, "experimental"):
                    controller.build_command(
                        {
                            "workflow": "linkedin_multi_fresh",
                            "search_market": "uae",
                            "location": "Dubai",
                        }
                    )
                command, _workflow, _label = controller.build_command(
                    {
                        "workflow": "linkedin_multi_fresh",
                        "search_market": "uae",
                        "location": "Dubai",
                        "experimental_confirmed": True,
                    }
                )
        self.assertEqual(command[command.index("--search-market") + 1], "uae")

    def test_disabled_market_cannot_start_from_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            with patch.dict(
                "serve_dashboard.MARKET_PROFILES",
                {"qatar": {"label": "Qatar", "availability": "disabled"}},
            ):
                with self.assertRaisesRegex(ValueError, "not enabled"):
                    controller.build_command(
                        {
                            "workflow": "linkedin_multi_fresh",
                            "search_market": "qatar",
                            "location": "Doha",
                        }
                    )

    def test_validation_workflow_uses_exact_non_applying_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = DashboardRunController(Path(tmp))
            command, workflow, label = controller.build_command(
                {
                    "workflow": "validate_boards",
                    "query": "ignored",
                    "location": "ignored",
                    "max_pages": "all",
                    "browser": "firefox",
                    "human_mode": True,
                    "fresh": True,
                    "resume": True,
                    "ai_budget_mode": "off",
                }
            )

        self.assertEqual(command, [sys.executable, "main.py", "--validate-boards"])
        self.assertEqual(workflow, "validate_boards")
        self.assertEqual(label, "Validate job boards (no applications)")
        self.assertNotIn("--dry-run", command)
        self.assertNotIn("--browser", command)
        self.assertNotIn("--resume", command)

    def test_restart_reconstructs_missing_process_as_interrupted_and_resumable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run_state.json"
            progress_path = root / "progress.json"
            dashboard_path = root / "dashboard.json"
            self._write_live_run(dashboard_path)
            state_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "active": True,
                        "workflow": "linkedin_multi_fresh",
                        "started_at": "2026-06-08T10:00:00+02:00",
                        "completed_at": "",
                        "return_code": None,
                        "log_path": "",
                        "command": [],
                        "run_id": "run_1",
                    }
                ),
                encoding="utf-8",
            )
            progress_path.write_text(
                '{"status":"in_progress","current_query_index":12}',
                encoding="utf-8",
            )

            controller = DashboardRunController(
                root,
                progress_path=progress_path,
                state_path=state_path,
                dashboard_data_path=dashboard_path,
            )
            status = controller.status()

            self.assertEqual(status["status"], "interrupted")
            self.assertFalse(status["active"])
            self.assertTrue(status["resume_available"])
            self.assertTrue(status["resumable"])
            self.assertIn("reporting a final result", status["interruption_reason"])
            live = json.loads(dashboard_path.read_text(encoding="utf-8"))
            self.assertEqual(live["active_run_id"], "")
            self.assertEqual(live["runs"][0]["status"], "interrupted")

    def test_restart_keeps_matching_live_process_as_detached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run_state.json"
            progress_path = root / "progress.json"
            dashboard_path = root / "dashboard.json"
            command = ["python.exe", "scout_jobs_multi.py", "--linkedin"]
            self._write_live_run(dashboard_path)
            state_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "active": True,
                        "workflow": "linkedin_multi_fresh",
                        "started_at": "2026-06-08T10:00:00+02:00",
                        "completed_at": "",
                        "return_code": None,
                        "log_path": "",
                        "command": command,
                        "run_id": "run_1",
                        "process_id": 1234,
                        "process_creation_token": "token-1",
                        "process_executable": "c:\\python.exe",
                        "command_fingerprint": self._command_fingerprint(command),
                    }
                ),
                encoding="utf-8",
            )
            progress_path.write_text(
                '{"status":"in_progress","current_query_index":1}',
                encoding="utf-8",
            )

            controller = DashboardRunController(
                root,
                progress_path=progress_path,
                state_path=state_path,
                dashboard_data_path=dashboard_path,
                process_inspector=lambda _pid: {
                    "alive": True,
                    "process_id": 1234,
                    "creation_token": "token-1",
                    "executable": "c:\\python.exe",
                },
            )
            status = controller.status()

            self.assertEqual(status["status"], "running")
            self.assertTrue(status["active"])
            self.assertTrue(status["detached"])
            with self.assertRaisesRegex(ValueError, "already active"):
                controller.start({"workflow": "linkedin_multi_fresh"})

    def test_reused_pid_is_interrupted_instead_of_treated_as_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run_state.json"
            progress_path = root / "progress.json"
            dashboard_path = root / "dashboard.json"
            command = ["python.exe", "scout_jobs_multi.py", "--linkedin"]
            self._write_live_run(dashboard_path)
            state_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "active": True,
                        "started_at": "2026-06-08T10:00:00+02:00",
                        "command": command,
                        "run_id": "run_1",
                        "process_id": 1234,
                        "process_creation_token": "old-token",
                        "process_executable": "c:\\python.exe",
                        "command_fingerprint": self._command_fingerprint(command),
                    }
                ),
                encoding="utf-8",
            )
            progress_path.write_text('{"status":"in_progress"}', encoding="utf-8")

            controller = DashboardRunController(
                root,
                progress_path=progress_path,
                state_path=state_path,
                dashboard_data_path=dashboard_path,
                process_inspector=lambda _pid: {
                    "alive": True,
                    "process_id": 1234,
                    "creation_token": "new-token",
                    "executable": "c:\\python.exe",
                },
            )

            self.assertEqual(controller.status()["status"], "interrupted")

    def test_terminal_controller_reconciles_stale_live_run_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run_state.json"
            progress_path = root / "progress.json"
            dashboard_path = root / "dashboard.json"
            self._write_live_run(dashboard_path)
            state_path.write_text(
                json.dumps(
                    {
                        "status": "interrupted",
                        "active": False,
                        "started_at": "2026-06-08T10:00:00+02:00",
                        "completed_at": "2026-06-08T10:30:00+02:00",
                        "run_id": "run_1",
                        "interrupted_at": "2026-06-08T10:30:00+02:00",
                        "interruption_reason": "Process disappeared.",
                    }
                ),
                encoding="utf-8",
            )
            progress_path.write_text('{"status":"in_progress"}', encoding="utf-8")

            controller = DashboardRunController(
                root,
                progress_path=progress_path,
                state_path=state_path,
                dashboard_data_path=dashboard_path,
            )
            first = dashboard_path.read_text(encoding="utf-8")
            controller.status()
            second = dashboard_path.read_text(encoding="utf-8")

            payload = json.loads(second)
            self.assertEqual(payload["active_run_id"], "")
            self.assertEqual(payload["runs"][0]["status"], "interrupted")
            self.assertEqual(first, second)

    def test_legacy_restart_failure_is_persisted_as_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run_state.json"
            progress_path = root / "progress.json"
            dashboard_path = root / "dashboard.json"
            self._write_live_run(dashboard_path)
            state_path.write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "active": False,
                        "started_at": "2026-06-08T10:00:00+02:00",
                        "completed_at": "2026-06-08T10:30:00+02:00",
                        "return_code": None,
                        "run_id": "run_1",
                        "failure_reason": (
                            "Dashboard server restarted while the scout process was active."
                        ),
                    }
                ),
                encoding="utf-8",
            )
            progress_path.write_text('{"status":"in_progress"}', encoding="utf-8")

            controller = DashboardRunController(
                root,
                progress_path=progress_path,
                state_path=state_path,
                dashboard_data_path=dashboard_path,
            )

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(controller.status()["status"], "interrupted")
            self.assertEqual(persisted["status"], "interrupted")
            self.assertEqual(persisted["failure_reason"], "")

    def test_reconciliation_write_warning_does_not_hide_controller_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run_state.json"
            progress_path = root / "progress.json"
            dashboard_path = root / "dashboard.json"
            self._write_live_run(dashboard_path)
            state_path.write_text(
                json.dumps(
                    {
                        "status": "interrupted",
                        "active": False,
                        "run_id": "run_1",
                        "completed_at": "2026-06-08T10:30:00+02:00",
                        "interruption_reason": "Process disappeared.",
                    }
                ),
                encoding="utf-8",
            )
            progress_path.write_text('{"status":"in_progress"}', encoding="utf-8")

            with patch(
                "serve_dashboard.LiveRecommendedJobsDashboard.transition_run",
                side_effect=PermissionError("locked"),
            ):
                controller = DashboardRunController(
                    root,
                    progress_path=progress_path,
                    state_path=state_path,
                    dashboard_data_path=dashboard_path,
                )
                status = controller.status()
            self.assertEqual(status["status"], "interrupted")
            self.assertIn("locked", status["lifecycle_reconciliation_warning"])

    def test_restart_reconstructs_completed_progress_as_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run_state.json"
            progress_path = root / "progress.json"
            state_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "active": True,
                        "workflow": "linkedin_multi_fresh",
                        "started_at": "2026-06-08T10:00:00+02:00",
                        "completed_at": "",
                        "return_code": None,
                        "log_path": "",
                        "command": [],
                        "run_id": "",
                    }
                ),
                encoding="utf-8",
            )
            progress_path.write_text('{"status":"completed"}', encoding="utf-8")

            controller = DashboardRunController(
                root,
                progress_path=progress_path,
                state_path=state_path,
            )

            self.assertEqual(controller.status()["status"], "completed")
            self.assertFalse(controller.status()["resume_available"])

    def test_completed_controller_state_overrides_stale_in_progress_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run_state.json"
            progress_path = root / "progress.json"
            state_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "active": False,
                        "workflow": "linkedin_multi_fresh",
                        "started_at": "2026-06-08T10:00:00+02:00",
                        "completed_at": "2026-06-08T11:00:00+02:00",
                        "return_code": 0,
                        "log_path": "",
                        "command": [],
                        "run_id": "",
                    }
                ),
                encoding="utf-8",
            )
            progress_path.write_text(
                '{"status":"in_progress","current_query_index":46}',
                encoding="utf-8",
            )

            controller = DashboardRunController(
                root,
                progress_path=progress_path,
                state_path=state_path,
            )

            self.assertEqual(controller.status()["status"], "completed")
            self.assertFalse(controller.status()["resume_available"])

    def test_restart_promotes_completed_progress_candidate_before_reconstruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run_state.json"
            progress_path = root / "progress.json"
            state_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "active": True,
                        "workflow": "linkedin_multi_fresh",
                        "started_at": "2026-06-08T10:00:00+02:00",
                        "completed_at": "",
                        "return_code": None,
                        "log_path": "",
                        "command": [],
                        "run_id": "",
                    }
                ),
                encoding="utf-8",
            )
            progress_path.write_text(
                '{"updated_at":"2026-06-08T10:30:00+02:00","status":"in_progress"}',
                encoding="utf-8",
            )
            progress_path.with_suffix(".json.tmp").write_text(
                '{"updated_at":"2026-06-08T11:00:00+02:00","status":"completed"}',
                encoding="utf-8",
            )

            controller = DashboardRunController(
                root,
                progress_path=progress_path,
                state_path=state_path,
            )

            self.assertEqual(controller.status()["status"], "completed")
            self.assertFalse(controller.status()["resume_available"])
            self.assertEqual(
                json.loads(progress_path.read_text(encoding="utf-8"))["status"],
                "completed",
            )

    def test_attached_nonzero_exit_is_failed(self):
        class FinishedProcess:
            def poll(self):
                return 7

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dashboard_path = root / "dashboard.json"
            progress_path = root / "progress.json"
            self._write_live_run(dashboard_path)
            progress_path.write_text('{"status":"in_progress"}', encoding="utf-8")
            controller = DashboardRunController(
                root,
                dashboard_data_path=dashboard_path,
                progress_path=progress_path,
            )
            controller.process = FinishedProcess()
            controller.state.update(
                {
                    "status": "running",
                    "active": True,
                    "run_id": "run_1",
                    "completed_at": "",
                    "failure_reason": "",
                }
            )

            status = controller.status()

            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["return_code"], 7)
            self.assertIn("code 7", status["failure_reason"])

    def test_attached_zero_exit_is_completed(self):
        class FinishedProcess:
            def poll(self):
                return 0

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dashboard_path = root / "dashboard.json"
            progress_path = root / "progress.json"
            self._write_live_run(dashboard_path)
            progress_path.write_text('{"status":"completed"}', encoding="utf-8")
            controller = DashboardRunController(
                root,
                dashboard_data_path=dashboard_path,
                progress_path=progress_path,
            )
            controller.process = FinishedProcess()
            controller.state.update(
                {
                    "status": "running",
                    "active": True,
                    "run_id": "run_1",
                    "completed_at": "",
                }
            )

            status = controller.status()

            self.assertEqual(status["status"], "completed")
            self.assertFalse(status["resume_available"])

    def test_detached_stop_request_finishes_as_stopped(self):
        alive = iter([True, False])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run_state.json"
            progress_path = root / "progress.json"
            dashboard_path = root / "dashboard.json"
            command = ["python.exe", "scout_jobs_multi.py", "--linkedin"]
            self._write_live_run(dashboard_path)
            state_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "active": True,
                        "started_at": "2026-06-08T10:00:00+02:00",
                        "completed_at": "",
                        "command": command,
                        "run_id": "run_1",
                        "process_id": 1234,
                        "process_creation_token": "token-1",
                        "process_executable": "c:\\python.exe",
                        "command_fingerprint": self._command_fingerprint(command),
                    }
                ),
                encoding="utf-8",
            )
            progress_path.write_text('{"status":"in_progress"}', encoding="utf-8")

            def inspector(_pid):
                return {
                    "alive": next(alive),
                    "process_id": 1234,
                    "creation_token": "token-1",
                    "executable": "c:\\python.exe",
                }

            controller = DashboardRunController(
                root,
                progress_path=progress_path,
                state_path=state_path,
                dashboard_data_path=dashboard_path,
                process_inspector=inspector,
            )
            controller.state["status"] = "stopping_after_page"
            status = controller.status()

            self.assertEqual(status["status"], "stopped")
            self.assertTrue(status["resume_available"])

    def test_resume_ignores_progress_from_another_explicit_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress_path = root / "progress.json"
            progress_path.write_text(
                json.dumps(
                    {
                        "status": "in_progress",
                        "run_id": "run_new",
                        "updated_at": "2026-06-14T15:00:00+02:00",
                        "queries": ["junior product designer"],
                    }
                ),
                encoding="utf-8",
            )
            controller = DashboardRunController(root, progress_path=progress_path)
            controller.state.update(
                {
                    "status": "interrupted",
                    "active": False,
                    "run_id": "run_old",
                    "started_at": "2026-06-13T00:10:00+02:00",
                    "completed_at": "2026-06-13T01:46:00+02:00",
                    "log_path": str(root / "old-run.txt"),
                }
            )

            status = controller.status()

            self.assertFalse(status["resume_available"])
            self.assertEqual(status["resume_context"], {})

    def test_resume_ignores_newer_legacy_progress_after_terminal_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress_path = root / "progress.json"
            progress_path.write_text(
                json.dumps(
                    {
                        "status": "in_progress",
                        "updated_at": "2026-06-14T15:00:00+02:00",
                        "queries": ["junior product designer"],
                    }
                ),
                encoding="utf-8",
            )
            controller = DashboardRunController(root, progress_path=progress_path)
            controller.state.update(
                {
                    "status": "interrupted",
                    "active": False,
                    "run_id": "run_old",
                    "started_at": "2026-06-13T00:10:00+02:00",
                    "completed_at": "2026-06-13T01:46:00+02:00",
                    "log_path": str(root / "old-run.txt"),
                }
            )

            status = controller.status()

            self.assertFalse(status["resume_available"])
            self.assertEqual(status["resume_context"], {})

    def test_resume_uses_progress_with_matching_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress_path = root / "progress.json"
            progress_path.write_text(
                json.dumps(
                    {
                        "status": "in_progress",
                        "run_id": "run_1",
                        "updated_at": "2026-06-13T00:18:00+02:00",
                        "queries": ["ux designer", "product designer"],
                        "current_query_index": 1,
                        "current_query": "product designer",
                    }
                ),
                encoding="utf-8",
            )
            controller = DashboardRunController(root, progress_path=progress_path)
            controller.state.update(
                {
                    "status": "interrupted",
                    "active": False,
                    "run_id": "run_1",
                    "started_at": "2026-06-13T00:10:00+02:00",
                    "completed_at": "2026-06-13T01:46:00+02:00",
                    "log_path": str(root / "run-1.txt"),
                }
            )

            status = controller.status()

            self.assertTrue(status["resume_available"])
            self.assertEqual(
                status["resume_context"]["current_query"],
                "product designer",
            )
            self.assertEqual(
                status["resume_context"]["log_path"],
                str(root / "run-1.txt"),
            )


if __name__ == "__main__":
    unittest.main()
