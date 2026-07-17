import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent.profile_service import ProfileService
from agent.user_workspace import UserWorkspace


class ProfileServiceTests(unittest.TestCase):
    def _service(self, root: Path) -> ProfileService:
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "data").mkdir(parents=True, exist_ok=True)
        (root / "cv").mkdir(parents=True, exist_ok=True)
        profile = {
            "personal": {
                "first_name": "Test",
                "last_name": "Person",
                "email": "test@example.com",
                "phone": "123",
                "location": {"city": "Amsterdam", "country": "Netherlands"},
            },
            "about_me": "Summary",
            "work_experience": [{"title": "Designer"}],
            "education": [{"degree": "BA"}],
            "skills": ["Figma"],
            "languages": [{"language": "English", "level": "Fluent"}],
            "certifications": [],
            "projects": [],
            "cv_path": "",
        }
        (root / "config" / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        (root / "config" / "preferences.json").write_text(
            json.dumps({"job_titles": ["Designer"], "locations": ["Amsterdam"]}),
            encoding="utf-8",
        )
        (root / "PERFECT SUITABLE JOB PROFILE.txt").write_text("Strategy", encoding="utf-8")
        (root / "data" / "portfolio_site_notes.txt").write_text("", encoding="utf-8")
        (root / "search_queries.txt").write_text("designer\n", encoding="utf-8")
        return ProfileService(UserWorkspace(root))

    def test_payload_reports_profile_readiness(self):
        with TemporaryDirectory() as directory:
            service = self._service(Path(directory))
            payload = service.payload()

            self.assertEqual(payload["profile"]["personal"]["first_name"], "Test")
            self.assertFalse(payload["cv"]["available"])
            self.assertFalse(payload["readiness"]["ready"])
            self.assertFalse(payload["readiness"]["checks"]["cv"])

    def test_save_profile_validates_email(self):
        with TemporaryDirectory() as directory:
            service = self._service(Path(directory))
            profile = service.payload()["profile"]
            profile["personal"]["email"] = "not-an-email"

            with self.assertRaisesRegex(ValueError, "Email address"):
                service.save_profile(profile)

    def test_upload_rejects_non_pdf_content(self):
        with TemporaryDirectory() as directory:
            service = self._service(Path(directory))

            with self.assertRaisesRegex(ValueError, "valid PDF"):
                service.upload_cv("resume.pdf", base64.b64encode(b"not pdf").decode("ascii"))


if __name__ == "__main__":
    unittest.main()
