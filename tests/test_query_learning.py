import json
import tempfile
import unittest
from pathlib import Path

from agent.query_learning import QueryLearningPolicy, order_queries_with_learning


class QueryLearningTests(unittest.TestCase):
    def test_preferences_enable_linkedin_specific_query_learning(self):
        policy = QueryLearningPolicy.from_preferences(
            {
                "job_boards": {
                    "linkedin": {
                        "query_learning": {
                            "enabled": True,
                            "history_run_limit": 20,
                            "exploration_interval": 3,
                            "top_query_preview_count": 4,
                        }
                    }
                }
            },
            enabled=True,
        )

        self.assertTrue(policy.enabled)
        self.assertEqual(policy.history_run_limit, 20)
        self.assertEqual(policy.exploration_interval, 3)
        self.assertEqual(policy.top_query_preview_count, 4)

    def test_order_prioritizes_queries_with_apply_and_good_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            multi_output = Path(tmp) / "high_success_probability_jobs_multi.json"
            history = Path(tmp) / "data/scout_run_history.json"
            multi_output.write_text(
                json.dumps(
                    {
                        "per_query_summary": [
                            {
                                "query": "junior ux designer",
                                "total_scanned": 0,
                                "new_recommendations": 0,
                                "cached_previous_recommendations": 0,
                                "rejected_or_below_threshold": 0,
                                "previously_analyzed_jobs_skipped_at_card_stage": 13,
                            },
                            {
                                "query": "product coordinator",
                                "total_scanned": 8,
                                "new_recommendations": 2,
                                "cached_previous_recommendations": 0,
                                "rejected_or_below_threshold": 4,
                            },
                        ],
                        "apply_first": [
                            {
                                "best_matching_query": "product coordinator",
                                "matched_queries": ["product coordinator"],
                            }
                        ],
                        "consider_human_review": [
                            {
                                "best_matching_query": "product coordinator",
                                "matched_queries": ["product coordinator"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            history.parent.mkdir(parents=True, exist_ok=True)
            history.write_text(json.dumps({"runs": []}), encoding="utf-8")

            ordered, metadata = order_queries_with_learning(
                ["junior ux designer", "product coordinator", "content coordinator"],
                enabled=True,
                multi_output_path=multi_output,
                run_history_path=history,
            )

            self.assertEqual(ordered[0], "product coordinator")
            self.assertCountEqual(ordered, ["junior ux designer", "product coordinator", "content coordinator"])
            self.assertTrue(metadata["reordered"])
            self.assertEqual(metadata["top_queries"][0]["query"], "product coordinator")
            self.assertEqual(metadata["top_queries"][0]["apply_first"], 1)

    def test_learning_keeps_file_order_when_disabled_or_without_sources(self):
        queries = ["junior ux designer", "product coordinator"]

        ordered, metadata = order_queries_with_learning(
            queries,
            enabled=False,
            multi_output_path=Path("missing-output.json"),
            run_history_path=Path("missing-history.json"),
        )

        self.assertEqual(ordered, queries)
        self.assertFalse(metadata["enabled"])


if __name__ == "__main__":
    unittest.main()
