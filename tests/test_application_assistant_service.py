import tempfile
from pathlib import Path
import unittest

from agent.application_assistant_service import ApplicationAssistantService
from agent.user_workspace import UserWorkspace


class ApplicationAssistantServiceTests(unittest.TestCase):
    def _service(self, root: Path) -> ApplicationAssistantService:
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "data").mkdir(parents=True, exist_ok=True)
        (root / "config" / "profile.json").write_text(
            """{
              "cv_path": "",
              "personal": {"first_name": "John", "last_name": "Doe"},
              "about_me": "Creative business graduate with digital experience.",
              "skills": ["Figma", "Research", "Content"],
              "work_experience": [{"title": "Digital Marketing Intern", "company": "PPHE"}],
              "application_answers": {"requires_sponsorship": "No"}
            }""",
            encoding="utf-8",
        )
        (root / "config" / "preferences.json").write_text(
            '{"application_behavior":{"pause_before_final_submit":true}}',
            encoding="utf-8",
        )
        (root / "search_queries.txt").write_text("ux designer\n", encoding="utf-8")
        (root / "PERFECT SUITABLE JOB PROFILE.txt").write_text("Strategy", encoding="utf-8")
        (root / "data" / "portfolio_site_notes.txt").write_text("Portfolio", encoding="utf-8")
        return ApplicationAssistantService(UserWorkspace(root))

    def test_knowledge_is_saved_to_private_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)

            result = service.save_knowledge(
                {
                    "application_answers": {"requires_sponsorship": "No"},
                    "learned_answers": {"are you available": "Yes"},
                    "cover_letter_style": "Concise",
                }
            )

            self.assertEqual(result["learned_answers"]["are you available"], "Yes")
            self.assertTrue((root / "data" / "user_workspace" / "learned_answers.json").exists())

    def test_local_cover_letter_needs_no_ai(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = self._service(Path(temporary))

            draft = service.local_cover_letter_draft(
                {"title": "Product Coordinator", "company": "Example"}
            )

            self.assertIn("Product Coordinator", draft)
            self.assertIn("Example", draft)
            self.assertIn("Dear Hiring Team", draft)


if __name__ == "__main__":
    unittest.main()
