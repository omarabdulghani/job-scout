import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from agent.ai_settings_service import AISettingsService
from agent.user_workspace import UserWorkspace


class AISettingsServiceTests(unittest.TestCase):
    def _service(self, root: Path) -> AISettingsService:
        config_dir = root / "config"
        data_dir = root / "data"
        cv_dir = root / "cv"
        config_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        cv_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "profile.json").write_text('{"cv_path": ""}', encoding="utf-8")
        (config_dir / "preferences.json").write_text("{}", encoding="utf-8")
        (root / "search_queries.txt").write_text("ux designer\n", encoding="utf-8")
        (root / "PERFECT SUITABLE JOB PROFILE.txt").write_text("Strategy", encoding="utf-8")
        (data_dir / "portfolio_site_notes.txt").write_text("Portfolio", encoding="utf-8")
        return AISettingsService(UserWorkspace(root))

    def test_payload_never_returns_secret_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            (root / ".env").write_text(
                "AI_BACKEND=auto\nGEMINI_API_KEY=super-secret\nGEMINI_MODEL=gemini-2.5-flash\n",
                encoding="utf-8",
            )

            payload = service.payload()

            gemini = next(item for item in payload["providers"] if item["id"] == "gemini")
            self.assertTrue(gemini["configured"])
            self.assertNotIn("super-secret", str(payload))
            self.assertNotIn("api_key", gemini)

    def test_blank_key_preserves_existing_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            (root / ".env").write_text(
                "AI_BACKEND=auto\nAI_BACKEND_ORDER=gemini\nGEMINI_API_KEY=keep-me\nGEMINI_MODEL=old-model\n",
                encoding="utf-8",
            )

            service.save(
                {
                    "backend": "auto",
                    "backend_order": ["gemini"],
                    "rate_limit_cooldown_seconds": 90,
                    "providers": [
                        {
                            "id": "gemini",
                            "model": "new-model",
                            "api_key": "",
                            "extra": {},
                        }
                    ],
                }
            )

            env_text = (root / ".env").read_text(encoding="utf-8")
            self.assertIn("GEMINI_API_KEY=keep-me", env_text)
            self.assertIn("GEMINI_MODEL=new-model", env_text)

    def test_explicit_remove_key_deletes_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            (root / ".env").write_text(
                "AI_BACKEND=gemini\nAI_BACKEND_ORDER=gemini\nGEMINI_API_KEY=remove-me\nGEMINI_MODEL=gemini-2.5-flash\n",
                encoding="utf-8",
            )

            service.save(
                {
                    "backend": "gemini",
                    "backend_order": ["gemini"],
                    "providers": [
                        {
                            "id": "gemini",
                            "model": "gemini-2.5-flash",
                            "remove_key": True,
                            "extra": {},
                        }
                    ],
                }
            )

            self.assertNotIn("GEMINI_API_KEY", (root / ".env").read_text(encoding="utf-8"))

    def test_unused_openai_compatible_slot_may_remain_blank(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            (root / ".env").write_text(
                "AI_BACKEND=auto\nAI_BACKEND_ORDER=gemini\nGEMINI_API_KEY=configured\nGEMINI_MODEL=gemini-2.5-flash\n",
                encoding="utf-8",
            )

            payload = service.payload()
            submitted = []
            for provider in payload["providers"]:
                submitted.append(
                    {
                        "id": provider["id"],
                        "model": provider["model"],
                        "base_url": provider["base_url"],
                        "api_key": "",
                        "extra": provider["extra"],
                    }
                )
            service.save(
                {
                    "backend": "auto",
                    "backend_order": ["gemini"],
                    "providers": submitted,
                }
            )

            self.assertEqual(service.payload()["backend_order"], ["gemini"])

    def test_connection_status_is_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = self._service(root)
            (root / ".env").write_text(
                "AI_BACKEND=auto\nAI_BACKEND_ORDER=gemini\nGEMINI_API_KEY=configured\nGEMINI_MODEL=gemini-2.5-flash\n",
                encoding="utf-8",
            )

            with patch.object(service, "_request_provider_models", return_value=18):
                result = service.test_connection("gemini")

            self.assertTrue(result["ok"])
            self.assertEqual(result["model_count"], 18)
            self.assertTrue(
                service.payload()["providers"][2]["last_test"]["ok"]
            )


if __name__ == "__main__":
    unittest.main()
