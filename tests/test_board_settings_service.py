import tempfile
from pathlib import Path
import tempfile
import unittest

from agent.board_settings_service import BoardSettingsService
from agent.user_workspace import UserWorkspace


class BoardSettingsServiceTests(unittest.TestCase):
    def _service(self, root: Path) -> BoardSettingsService:
        (root / "config").mkdir(parents=True)
        (root / "data").mkdir(parents=True)
        (root / "config" / "profile.json").write_text('{"cv_path": ""}', encoding="utf-8")
        (root / "config" / "preferences.json").write_text(
            '{"job_boards":{"linkedin":{"enabled":true}},"application_behavior":{}}',
            encoding="utf-8",
        )
        (root / "search_queries.txt").write_text("ux designer\n", encoding="utf-8")
        (root / "PERFECT SUITABLE JOB PROFILE.txt").write_text("Strategy", encoding="utf-8")
        (root / "data" / "portfolio_site_notes.txt").write_text("Portfolio", encoding="utf-8")
        return BoardSettingsService(UserWorkspace(root))

    def test_save_keeps_final_submission_paused(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            payload = service.save(
                {
                    "job_boards": {
                        "linkedin": {"enabled": True, "distance_miles": 40},
                        "indeed": {
                            "enabled": True,
                            "search_url": "https://nl.indeed.com/jobs",
                        },
                    },
                    "application_behavior": {"pause_before_final_submit": False},
                    "dashboard_defaults": {"browser": "firefox"},
                }
            )

            self.assertTrue(payload["application_behavior"]["pause_before_final_submit"])
            self.assertEqual(payload["dashboard_defaults"]["browser"], "firefox")
            self.assertEqual(payload["job_boards"]["linkedin"]["distance_miles"], 40)

    def test_saved_mission_preserves_supported_platform_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            submitted = service.payload()
            submitted["search_missions"] = [
                {
                    "id": "indeed-local",
                    "name": "Indeed Local",
                    "platform": "indeed",
                    "search_market": "netherlands",
                    "location": "Amstelveen",
                    "radius_km": 25,
                    "employment": "any",
                    "search_goal": "career-growth",
                    "search_groups": ["primary", "bridge"],
                }
            ]

            result = service.save(submitted)

            self.assertEqual(result["search_missions"][0]["platform"], "indeed")
            self.assertEqual(result["search_missions"][0]["search_market"], "netherlands")
            self.assertEqual(result["search_missions"][0]["radius_km"], 25)
            self.assertEqual(result["search_missions"][0]["employment"], "any")

    def test_saved_missions_reject_duplicate_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            submitted = service.payload()
            submitted["search_missions"] = [
                {"id": "one", "name": "My Search", "platform": "linkedin"},
                {"id": "two", "name": "my search", "platform": "linkedin"},
            ]

            with self.assertRaisesRegex(ValueError, "already exists"):
                service.save(submitted)

    def test_saved_missions_cannot_shadow_built_in_missions(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            submitted = service.payload()
            submitted["search_missions"] = [
                {
                    "id": "shadow",
                    "name": "Local Career Hunt",
                    "platform": "linkedin",
                }
            ]

            with self.assertRaisesRegex(ValueError, "already exists"):
                service.save(submitted)

    def test_saved_mission_rejects_unsupported_platform_market_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))
            submitted = service.payload()
            submitted["search_missions"] = [
                {
                    "id": "invalid",
                    "name": "Invalid Indeed Germany",
                    "platform": "indeed",
                    "search_market": "germany",
                }
            ]

            with self.assertRaisesRegex(ValueError, "does not support"):
                service.save(submitted)


if __name__ == "__main__":
    unittest.main()
