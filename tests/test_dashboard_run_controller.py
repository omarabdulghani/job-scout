import sys
import tempfile
import unittest
from pathlib import Path

from serve_dashboard import DashboardRunController


class DashboardRunControllerTests(unittest.TestCase):
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
                }
            )

        self.assertEqual(command[0], sys.executable)
        self.assertEqual(workflow, "linkedin_multi_fresh")
        self.assertEqual(label, "LinkedIn multi-query fresh")
        self.assertIn("scout_jobs_multi.py", command)
        self.assertIn("--fresh", command)
        self.assertIn("--resume", command)
        self.assertIn("--human-mode", command)
        self.assertIn("--browser", command)

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
                    "human_mode": False,
                    "fresh": False,
                }
            )

        self.assertEqual(workflow, "linkedin_multi_fresh")
        self.assertIn("scout_jobs_multi.py", command)
        self.assertIn("--max-pages", command)
        self.assertEqual(command[command.index("--max-pages") + 1], "1")
        self.assertEqual(command[command.index("--browser") + 1], "chromium")
        self.assertNotIn("--human-mode", command)


if __name__ == "__main__":
    unittest.main()
