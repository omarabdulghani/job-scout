import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.brain import JobBrain


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class HostedAIBackendTests(unittest.TestCase):
    def test_cerebras_chat_completion_uses_openai_compatible_json_schema(self):
        captured = {}

        def fake_urlopen(request, timeout=120):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHTTPResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "interview_probability_score": 81,
                                        "reason": "Strong realistic fit.",
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                }
            )

        with patch.dict(
            os.environ,
            {
                "AI_BACKEND": "cerebras",
                "CEREBRAS_API_KEY": "test-cerebras-key",
                "CEREBRAS_MODEL": "gpt-oss-120b",
            },
            clear=True,
        ), patch("agent.brain.urlopen", fake_urlopen):
            brain = JobBrain({}, {})
            raw, model_label = brain._openai_compatible_chat_completion(
                backend="cerebras",
                prompt="Score this job.",
                max_tokens=256,
            )

        self.assertEqual(model_label, "cerebras:gpt-oss-120b")
        self.assertEqual(captured["url"], "https://api.cerebras.ai/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "gpt-oss-120b")
        self.assertEqual(captured["body"]["messages"][0]["content"], "Score this job.")
        self.assertEqual(captured["body"]["max_tokens"], 256)
        self.assertEqual(captured["body"]["temperature"], 0)
        self.assertEqual(captured["body"]["response_format"]["type"], "json_schema")
        self.assertEqual(captured["headers"]["User-agent"], "job-agent/1.0")
        self.assertEqual(captured["headers"]["Accept"], "application/json")
        parsed = brain._parse_scoring_payload(raw, backend="cerebras")
        self.assertEqual(parsed["interview_probability_score"], 81)

    def test_ollama_cloud_chat_completion_uses_native_cloud_api_without_schema_by_default(self):
        captured = {}

        def fake_urlopen(request, timeout=120):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHTTPResponse(
                {
                    "model": "gpt-oss:120b",
                    "message": {
                        "content": json.dumps(
                            {
                                "interview_probability_score": 67,
                                "reason": "Possible bridge role.",
                            }
                        )
                    },
                    "done": True,
                    "prompt_eval_count": 50,
                    "eval_count": 16,
                }
            )

        with patch.dict(
            os.environ,
            {
                "AI_BACKEND": "ollama_cloud",
                "OLLAMA_API_KEY": "test-ollama-key",
                "OLLAMA_MODEL": "gpt-oss:120b",
            },
            clear=True,
        ), patch("agent.brain.urlopen", fake_urlopen):
            brain = JobBrain({}, {})
            raw, model_label = brain._ollama_cloud_chat_completion(
                prompt="Score this job.",
                max_tokens=256,
            )

        self.assertEqual(model_label, "ollama_cloud:gpt-oss:120b")
        self.assertEqual(captured["url"], "https://ollama.com/api/chat")
        self.assertEqual(captured["body"]["model"], "gpt-oss:120b")
        self.assertEqual(captured["body"]["messages"][0]["content"], "Score this job.")
        self.assertIs(captured["body"]["stream"], False)
        self.assertIs(captured["body"]["think"], False)
        self.assertNotIn("format", captured["body"])
        self.assertEqual(captured["body"]["options"]["num_predict"], 256)
        self.assertEqual(captured["headers"]["User-agent"], "job-agent/1.0")
        self.assertEqual(captured["headers"]["Accept"], "application/json")
        parsed = brain._parse_scoring_payload(raw, backend="ollama_cloud")
        self.assertEqual(parsed["interview_probability_score"], 67)

    def test_ollama_schema_mode_is_opt_in_for_supported_endpoints(self):
        captured = {}

        def fake_urlopen(request, timeout=120):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHTTPResponse(
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "interview_probability_score": 67,
                                "reason": "Possible bridge role.",
                            }
                        )
                    },
                    "done": True,
                }
            )

        with patch.dict(
            os.environ,
            {
                "AI_BACKEND": "ollama_cloud",
                "OLLAMA_API_KEY": "test-ollama-key",
                "OLLAMA_MODEL": "gpt-oss:120b",
                "OLLAMA_STRUCTURED_OUTPUTS": "true",
            },
            clear=True,
        ), patch("agent.brain.urlopen", fake_urlopen):
            brain = JobBrain({}, {})
            brain._ollama_cloud_chat_completion(
                prompt="Score this job.",
                max_tokens=256,
            )

        self.assertEqual(captured["body"]["format"]["required"], ["interview_probability_score", "reason"])

    def test_auto_backend_falls_back_to_gemini_when_primary_fails(self):
        with patch.dict(
            os.environ,
            {
                "AI_BACKEND": "auto",
                "AI_BACKEND_ORDER": "cerebras,gemini",
                "CEREBRAS_API_KEY": "test-cerebras-key",
                "GEMINI_API_KEY": "test-gemini-key",
                "GEMINI_MODEL": "gemini-test-model",
            },
            clear=True,
        ):
            brain = JobBrain({}, {})

        calls = []

        def fake_request(backend, *, prompt):
            calls.append((backend, prompt))
            if backend == "cerebras":
                raise RuntimeError("quota reached")
            return (
                {
                    "interview_probability_score": 72,
                    "reason": "Fallback scorer worked.",
                },
                "gemini:gemini-test-model",
            )

        with patch.object(brain, "_request_backend_scoring_response", side_effect=fake_request):
            parsed, model_label = brain._request_auto_scoring_response(prompt="Score this job.")

        self.assertEqual([call[0] for call in calls], ["cerebras", "gemini"])
        self.assertEqual(model_label, "gemini:gemini-test-model")
        self.assertEqual(parsed["interview_probability_score"], 72)

    def test_score_cache_accepts_all_auto_provider_model_labels(self):
        with patch.dict(
            os.environ,
            {
                "AI_BACKEND": "auto",
                "AI_BACKEND_ORDER": "cerebras,ollama_cloud,gemini",
                "CEREBRAS_API_KEY": "test-cerebras-key",
                "OLLAMA_API_KEY": "test-ollama-key",
                "GEMINI_API_KEY": "test-gemini-key",
            },
            clear=True,
        ):
            brain = JobBrain({}, {})

        self.assertEqual(
            brain.scoring_model_labels_for_cache(),
            {
                "cerebras:gpt-oss-120b",
                "ollama_cloud:gpt-oss:120b",
                "gemini:gemini-2.5-flash",
            },
        )


if __name__ == "__main__":
    unittest.main()
