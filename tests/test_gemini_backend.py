import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.brain import JobBrain


class GeminiBackendTests(unittest.TestCase):
    def test_default_scoring_backend_is_auto(self):
        with patch.dict(os.environ, {}, clear=True):
            brain = JobBrain({}, {})

        self.assertEqual(brain.scoring_backend, "auto")
        self.assertEqual(brain.ai_backend_order, ["cerebras", "ollama_cloud", "gemini"])
        self.assertEqual(brain.gemini_model, "gemini-2.5-flash")

    def test_gemini_model_label_uses_configured_model(self):
        with patch.dict(
            os.environ,
            {
                "AI_BACKEND": "gemini",
                "GEMINI_MODEL": "gemini-test-model",
            },
            clear=True,
        ):
            brain = JobBrain({}, {})

        self.assertEqual(brain.scoring_model_label, "gemini:gemini-test-model")

    def test_gemini_config_requires_api_key(self):
        with patch.dict(os.environ, {"AI_BACKEND": "gemini"}, clear=True):
            brain = JobBrain({}, {})

        with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
            brain._validate_gemini_scoring_config()

    def test_gemini_generate_content_uses_structured_json_config(self):
        class FakeModels:
            def __init__(self):
                self.calls = []

            def generate_content(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    text='{"interview_probability_score": 74, "reason": "Good match for a graduate role."}',
                    usage_metadata=SimpleNamespace(
                        prompt_token_count=123,
                        candidates_token_count=18,
                        total_token_count=141,
                    ),
                )

        fake_models = FakeModels()
        fake_client = SimpleNamespace(models=fake_models)
        with patch.dict(
            os.environ,
            {
                "AI_BACKEND": "gemini",
                "GEMINI_API_KEY": "test-key",
                "GEMINI_MODEL": "gemini-test-model",
                "GEMINI_THINKING_BUDGET": "0",
            },
            clear=True,
        ):
            brain = JobBrain({}, {})
            brain.gemini_client = fake_client
            raw, model_label = brain._gemini_generate_content(
                prompt="Score this job.",
                max_tokens=256,
            )

        self.assertEqual(model_label, "gemini:gemini-test-model")
        parsed = brain._parse_scoring_payload(raw, backend="gemini")
        self.assertEqual(parsed["interview_probability_score"], 74)

        call = fake_models.calls[0]
        self.assertEqual(call["model"], "gemini-test-model")
        self.assertEqual(call["contents"], "Score this job.")
        self.assertEqual(call["config"]["response_mime_type"], "application/json")
        self.assertEqual(call["config"]["max_output_tokens"], 256)
        self.assertEqual(call["config"]["thinking_config"]["thinking_budget"], 0)
        self.assertIn("response_schema", call["config"])

    def test_request_scoring_response_routes_to_gemini(self):
        with patch.dict(
            os.environ,
            {
                "AI_BACKEND": "gemini",
                "GEMINI_API_KEY": "test-key",
                "GEMINI_MODEL": "gemini-test-model",
            },
            clear=True,
        ):
            brain = JobBrain({}, {})

        with patch.object(
            brain,
            "_gemini_generate_content",
            return_value=('{"interview_probability_score": 88, "reason": "Strong fit."}', "gemini:gemini-test-model"),
        ) as generate_content:
            raw, model_label = brain._request_scoring_response("prompt", max_tokens=128)

        generate_content.assert_called_once_with(prompt="prompt", max_tokens=128)
        self.assertEqual(model_label, "gemini:gemini-test-model")
        self.assertIn("interview_probability_score", raw)


if __name__ == "__main__":
    unittest.main()
