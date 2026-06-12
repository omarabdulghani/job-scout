import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent.strategy_service import StrategyService
from agent.user_workspace import UserWorkspace


class StrategyServiceTests(unittest.TestCase):
    def _service(self, root: Path) -> StrategyService:
        (root / "config").mkdir(parents=True)
        (root / "data").mkdir(parents=True)
        (root / "config" / "profile.json").write_text(
            json.dumps(
                {
                    "personal": {},
                    "career_strategy": {
                        "core_goal": "Find growth",
                        "primary_paths": ["Designer"],
                        "strong_bridge_roles": ["Coordinator"],
                        "fallback_roles_for_income": ["Support"],
                    },
                }
            ),
            encoding="utf-8",
        )
        (root / "config" / "preferences.json").write_text(
            json.dumps(
                {
                    "job_titles": ["Designer"],
                    "locations": ["Amsterdam"],
                    "hard_exclude_keywords": ["Director"],
                    "soft_negative_keywords": ["Cold calling"],
                    "fallback_keywords": ["Support"],
                    "filters": {"min_match_score": 70},
                    "job_boards": {"linkedin": {"distance_miles": 25}},
                }
            ),
            encoding="utf-8",
        )
        (root / "PERFECT SUITABLE JOB PROFILE.txt").write_text("Full strategy", encoding="utf-8")
        (root / "data" / "portfolio_site_notes.txt").write_text("Portfolio evidence", encoding="utf-8")
        (root / "search_queries.txt").write_text("junior designer\nproject coordinator\n", encoding="utf-8")
        return StrategyService(UserWorkspace(root))

    def test_payload_combines_strategy_preferences_and_queries(self):
        with TemporaryDirectory() as directory:
            payload = self._service(Path(directory)).payload()

            self.assertEqual(payload["career_strategy"]["core_goal"], "Find growth")
            self.assertEqual(payload["preferences"]["locations"], ["Amsterdam"])
            self.assertEqual(payload["queries"], ["junior designer", "project coordinator"])
            self.assertEqual(payload["strategy_text"], "Full strategy")

    def test_save_updates_private_workspace_without_touching_defaults(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = self._service(root)
            payload = service.payload()
            payload["queries"] = ["product designer"]
            payload["preferences"]["locations"] = ["Utrecht"]
            payload["career_strategy"]["core_goal"] = "Updated goal"
            payload["strategy_text"] = "Updated full strategy"

            saved = service.save(payload)
            defaults = json.loads((root / "config" / "preferences.json").read_text(encoding="utf-8"))

            self.assertEqual(saved["queries"], ["product designer"])
            self.assertEqual(saved["preferences"]["locations"], ["Utrecht"])
            self.assertEqual(defaults["locations"], ["Amsterdam"])

    def test_save_requires_at_least_one_query(self):
        with TemporaryDirectory() as directory:
            service = self._service(Path(directory))
            payload = service.payload()
            payload["queries"] = []

            with self.assertRaisesRegex(ValueError, "At least one"):
                service.save(payload)

    def test_string_lists_preserve_internal_punctuation(self):
        with TemporaryDirectory() as directory:
            service = self._service(Path(directory))

            values = service._string_list(
                "Product/web operations involving CMS, e-commerce, QA\n"
                "UX/UI; AI-assisted prototyping\n"
                "The Hague, Netherlands\n"
            )

            self.assertEqual(
                values,
                [
                    "Product/web operations involving CMS, e-commerce, QA",
                    "UX/UI; AI-assisted prototyping",
                    "The Hague, Netherlands",
                ],
            )

    def test_string_lists_normalize_bullets_blanks_and_duplicates(self):
        with TemporaryDirectory() as directory:
            service = self._service(Path(directory))

            values = service._string_list(
                "- Junior UX/UI Designer\r\n"
                "\r\n"
                "* Product Designer\r\n"
                "\u2022 Digital Designer\r\n"
                "1. Creative Technologist\r\n"
                "junior ux/ui designer\r\n"
            )

            self.assertEqual(
                values,
                [
                    "Junior UX/UI Designer",
                    "Product Designer",
                    "Digital Designer",
                    "Creative Technologist",
                ],
            )

    def test_save_round_trip_preserves_comma_rich_entries(self):
        with TemporaryDirectory() as directory:
            service = self._service(Path(directory))
            payload = service.payload()
            payload["career_strategy"]["primary_paths"] = [
                "Product/web operations involving CMS, e-commerce, QA",
                "Marketing communications roles when content, brand, web, or event focused",
            ]
            payload["preferences"]["locations"] = ["The Hague, Netherlands"]
            payload["preferences"]["companies_whitelist"] = ["Example Company, B.V."]

            saved = service.save(payload)

            self.assertEqual(
                saved["career_strategy"]["primary_paths"],
                payload["career_strategy"]["primary_paths"],
            )
            self.assertEqual(saved["preferences"]["locations"], ["The Hague, Netherlands"])
            self.assertEqual(
                saved["preferences"]["companies_whitelist"],
                ["Example Company, B.V."],
            )


if __name__ == "__main__":
    unittest.main()
