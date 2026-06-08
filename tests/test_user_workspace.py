import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent.user_workspace import SCHEMA_VERSION, UserWorkspace


class UserWorkspaceTests(unittest.TestCase):
    def _seed_project(self, root: Path) -> None:
        (root / "config").mkdir(parents=True)
        (root / "data").mkdir(parents=True)
        (root / "cv").mkdir(parents=True)
        (root / "config" / "profile.json").write_text(
            json.dumps({"personal": {"first_name": "Test"}, "cv_path": "cv/test.pdf"}),
            encoding="utf-8",
        )
        (root / "config" / "preferences.json").write_text(
            json.dumps({"job_titles": ["Designer"], "locations": ["Amsterdam"]}),
            encoding="utf-8",
        )
        (root / "PERFECT SUITABLE JOB PROFILE.txt").write_text("Strategy", encoding="utf-8")
        (root / "data" / "portfolio_site_notes.txt").write_text("Portfolio", encoding="utf-8")
        (root / "search_queries.txt").write_text("junior designer\n", encoding="utf-8")
        (root / "cv" / "test.pdf").write_bytes(b"%PDF-test")

    def test_initializes_private_workspace_and_migrates_cv(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._seed_project(root)

            workspace = UserWorkspace(root).ensure_initialized()
            profile = workspace.load_profile()
            manifest = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
            self.assertEqual(profile["cv_path"], "data/user_workspace/cv/test.pdf")
            self.assertTrue((workspace.cv_dir / "test.pdf").exists())
            self.assertEqual(workspace.strategy_path.read_text(encoding="utf-8"), "Strategy")
            self.assertEqual(workspace.search_queries_path.read_text(encoding="utf-8"), "junior designer\n")

    def test_saving_profile_creates_backup_and_preserves_defaults(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._seed_project(root)
            workspace = UserWorkspace(root).ensure_initialized()

            profile = workspace.load_profile()
            profile["personal"]["first_name"] = "Changed"
            workspace.save_profile(profile)

            saved = json.loads(workspace.profile_path.read_text(encoding="utf-8"))
            original = json.loads((root / "config" / "profile.json").read_text(encoding="utf-8"))
            backups = list(workspace.backup_dir.glob("profile_*.json"))

            self.assertEqual(saved["personal"]["first_name"], "Changed")
            self.assertEqual(original["personal"]["first_name"], "Test")
            self.assertEqual(len(backups), 1)

    def test_existing_workspace_is_not_overwritten_by_defaults(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._seed_project(root)
            workspace = UserWorkspace(root).ensure_initialized()
            saved = workspace.load_preferences()
            saved["job_titles"] = ["Product Designer"]
            workspace.save_preferences(saved)

            (root / "config" / "preferences.json").write_text(
                json.dumps({"job_titles": ["Other"], "locations": ["Other"]}),
                encoding="utf-8",
            )
            reloaded = UserWorkspace(root).load_preferences()

            self.assertEqual(reloaded["job_titles"], ["Product Designer"])


if __name__ == "__main__":
    unittest.main()
