import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.brain import JobBrain


class AiQueriesTests(unittest.TestCase):
    def test_generate_ai_search_queries_prompt_and_sanitization(self):
        profile = {
            "personal": {
                "first_name": "John",
                "last_name": "Doe",
                "location": {"city": "Amsterdam", "country": "Netherlands"},
            },
            "language_policy": "dutch_nuanced",
            "about_me": "Experienced designer",
            "work_experience": [
                {"title": "UX Designer", "company": "Company A"}
            ],
            "skills": ["Figma", "UI Design"],
            "cv_path": "cv.pdf",
        }
        preferences = {
            "ai_backend": "claude",
            "anthropic_model": "claude-3-5-sonnet",
        }

        # Mock the profile knowledge loading
        with patch.object(JobBrain, "_build_profile_knowledge") as mock_kb:
            mock_kb.return_value = {
                "cv_excerpt": "John Doe UX designer expert",
                "portfolio_excerpt": "",
            }

            brain = JobBrain(profile, preferences)

            # Mock _request_scoring_response to simulate LLM output
            mock_llm_response = (
                "1. UX Designer Amsterdam\n"
                "- UI Specialist Utrecht\n"
                "• Figma Prototyper\n"
                "\"Product Owner\"\n"
                "UX Designer Amsterdam\n" # Duplicate to test deduplication
            )

            # We also mock the workspace strategy path reading
            with patch("agent.user_workspace.UserWorkspace.ensure_initialized") as mock_ws:
                with tempfile.TemporaryDirectory() as tempdir:
                    root = Path(tempdir)
                    strategy_file = root / "job_strategy.txt"
                    strategy_file.write_text("Omar's Opportunity-First strategy details", encoding="utf-8")
                    
                    mock_ws.return_value.strategy_path = strategy_file
                    
                    with patch.object(brain, "_request_scoring_response") as mock_scoring:
                        mock_scoring.return_value = (mock_llm_response, "claude-3-5-sonnet")
                        
                        queries = brain.generate_ai_search_queries(
                            count=3,
                            recent_queries=["customer support", "office assistant"],
                        )

                        # Check mock parameters to see if strategy and exclusions were included in prompt
                        prompt_arg = mock_scoring.call_args[0][0]
                        self.assertIn("John Doe", prompt_arg)
                        self.assertIn("Omar's Opportunity-First strategy", prompt_arg)
                        self.assertIn("customer support", prompt_arg)
                        self.assertIn("dutch_nuanced", prompt_arg)
                        
                        # Assert result sanitization and count truncation (original response has 4 unique clean items)
                        self.assertEqual(len(queries), 3)
                        self.assertEqual(queries[0], "UX Designer Amsterdam")
                        self.assertEqual(queries[1], "UI Specialist Utrecht")
                        self.assertEqual(queries[2], "Figma Prototyper")


if __name__ == "__main__":
    unittest.main()
