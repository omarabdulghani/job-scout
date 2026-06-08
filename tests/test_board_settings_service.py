import tempfile
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
