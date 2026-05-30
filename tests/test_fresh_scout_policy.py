import unittest

from agent.fresh_scout_policy import FreshScoutPolicy


class FreshScoutPolicyTests(unittest.TestCase):
    def test_defaults_are_reasonable_for_daily_fresh_scouting(self):
        policy = FreshScoutPolicy.from_preferences({}, enabled=True)

        self.assertTrue(policy.enabled)
        self.assertEqual(policy.max_pages_per_query, 4)
        self.assertEqual(policy.known_ratio_continue_threshold, 0.80)
        self.assertEqual(policy.duplicate_heavy_stop_threshold, 0.90)
        self.assertEqual(policy.stop_after_duplicate_heavy_pages, 2)
        self.assertEqual(policy.min_new_jobs_per_useful_query, 3)
        self.assertEqual(policy.target_apply_first_jobs, 8)
        self.assertEqual(policy.target_good_or_better_jobs, 20)
        self.assertEqual(policy.global_new_jobs_soft_cap, 80)
        self.assertTrue(policy.ai_budget_guard_enabled)
        self.assertEqual(policy.ai_calls_quality_check, 40)
        self.assertEqual(policy.min_apply_first_after_ai_quality_check, 2)
        self.assertEqual(policy.min_good_or_better_after_ai_quality_check, 5)
        self.assertEqual(policy.ai_calls_strict_check, 80)
        self.assertEqual(policy.min_apply_first_after_ai_strict_check, 4)
        self.assertEqual(policy.min_good_or_better_after_ai_strict_check, 10)
        self.assertEqual(policy.ai_calls_soft_cap, 120)

    def test_preferences_can_override_defaults(self):
        policy = FreshScoutPolicy.from_preferences(
            {
                "fresh_scout": {
                    "max_pages_per_query": 3,
                    "known_ratio_continue_threshold": 85,
                    "duplicate_heavy_stop_threshold": 95,
                    "stop_after_duplicate_heavy_pages": 3,
                    "min_new_jobs_per_useful_query": 4,
                    "target_apply_first_jobs": 6,
                    "target_good_or_better_jobs": 15,
                    "global_new_jobs_soft_cap": 60,
                    "ai_budget_guard_enabled": False,
                    "ai_calls_quality_check": 30,
                    "min_apply_first_after_ai_quality_check": 1,
                    "min_good_or_better_after_ai_quality_check": 3,
                    "ai_calls_strict_check": 70,
                    "min_apply_first_after_ai_strict_check": 3,
                    "min_good_or_better_after_ai_strict_check": 8,
                    "ai_calls_soft_cap": 100,
                }
            },
            enabled=True,
        )

        self.assertEqual(policy.max_pages_per_query, 3)
        self.assertEqual(policy.known_ratio_continue_threshold, 0.85)
        self.assertEqual(policy.duplicate_heavy_stop_threshold, 0.95)
        self.assertEqual(policy.stop_after_duplicate_heavy_pages, 3)
        self.assertEqual(policy.min_new_jobs_per_useful_query, 4)
        self.assertEqual(policy.target_apply_first_jobs, 6)
        self.assertEqual(policy.target_good_or_better_jobs, 15)
        self.assertEqual(policy.global_new_jobs_soft_cap, 60)
        self.assertFalse(policy.ai_budget_guard_enabled)
        self.assertEqual(policy.ai_calls_quality_check, 30)
        self.assertEqual(policy.min_apply_first_after_ai_quality_check, 1)
        self.assertEqual(policy.min_good_or_better_after_ai_quality_check, 3)
        self.assertEqual(policy.ai_calls_strict_check, 70)
        self.assertEqual(policy.min_apply_first_after_ai_strict_check, 3)
        self.assertEqual(policy.min_good_or_better_after_ai_strict_check, 8)
        self.assertEqual(policy.ai_calls_soft_cap, 100)

    def test_linkedin_specific_preferences_override_defaults(self):
        policy = FreshScoutPolicy.from_preferences(
            {
                "job_boards": {
                    "linkedin": {
                        "fresh_scout": {
                            "min_new_jobs_per_useful_query": 5,
                            "global_new_jobs_soft_cap": 140,
                            "ai_calls_soft_cap": 120,
                        }
                    }
                }
            },
            enabled=True,
        )

        self.assertEqual(policy.min_new_jobs_per_useful_query, 5)
        self.assertEqual(policy.global_new_jobs_soft_cap, 140)
        self.assertEqual(policy.ai_calls_soft_cap, 120)

    def test_panel_label_is_clear_when_enabled_or_disabled(self):
        self.assertEqual(FreshScoutPolicy.from_preferences({}, enabled=False).panel_label(), "disabled")

        enabled_label = FreshScoutPolicy.from_preferences({}, enabled=True).panel_label()
        self.assertIn("max 4 pages/query", enabled_label)
        self.assertIn("8 APPLY FIRST", enabled_label)
        self.assertIn("20 good+", enabled_label)
        self.assertIn("AI guard on", enabled_label)


if __name__ == "__main__":
    unittest.main()
