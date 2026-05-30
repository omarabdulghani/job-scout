import unittest

from rich.console import Console

from agent.fresh_scout_policy import FreshScoutPolicy
from agent.scout_console_reporter import ScoutConsoleReporter
from scout_jobs_multi import (
    _combine_fresh_counts,
    _fresh_global_stop_reason,
    _fresh_recommendation_counts,
)


class _ScoutThresholds:
    AI_THRESHOLD = 50
    AI_STRONG_MATCH_THRESHOLD = 70


def _report(jobs, *, collected=0, ai_calls=0):
    stats = {"job_cards_collected": collected}
    if ai_calls:
        stats["ai_scored_new"] = ai_calls
    return {
        "stats": stats,
        "new_recommendations": {
            "strong_match": [job for job in jobs if job.get("ai_match_tier") == "strong_match"],
            "possible_match": [job for job in jobs if job.get("ai_match_tier") == "possible_match"],
        },
        "cached_previous_recommendations": {"strong_match": [], "possible_match": []},
        "rejected_or_below_threshold": [],
    }


def _job(job_id, score, tier):
    return {
        "job_id": str(job_id),
        "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
        "output_status": "accepted",
        "interview_probability_score": score,
        "ai_match_tier": tier,
    }


class FreshScoutGlobalStopTests(unittest.TestCase):
    def test_counts_unique_apply_first_and_good_jobs(self):
        reports = [
            _report(
                [
                    _job(1, 85, "strong_match"),
                    _job(2, 65, "possible_match"),
                    _job(1, 85, "strong_match"),
                ],
                collected=3,
            )
        ]

        counts = _fresh_recommendation_counts(reports, _ScoutThresholds())

        self.assertEqual(counts["apply_first"], 1)
        self.assertEqual(counts["good_or_better"], 2)
        self.assertEqual(counts["new_jobs_seen"], 3)

    def test_fresh_counts_combine_resume_base_counts(self):
        counts = _combine_fresh_counts(
            {"apply_first": 3, "good_or_better": 7, "new_jobs_seen": 86, "ai_calls": 75},
            {"apply_first": 1, "good_or_better": 2, "new_jobs_seen": 12, "ai_calls": 10},
        )

        self.assertEqual(
            counts,
            {
                "apply_first": 4,
                "good_or_better": 9,
                "new_jobs_seen": 98,
                "ai_calls": 85,
            },
        )

    def test_stop_reason_prefers_apply_first_target(self):
        policy = FreshScoutPolicy.from_preferences(
            {
                "fresh_scout": {
                    "target_apply_first_jobs": 2,
                    "target_good_or_better_jobs": 5,
                    "global_new_jobs_soft_cap": 20,
                }
            },
            enabled=True,
        )
        reports = [_report([_job(1, 85, "strong_match"), _job(2, 75, "strong_match")], collected=2)]

        reason, counts = _fresh_global_stop_reason(reports, _ScoutThresholds(), policy)

        self.assertIn("APPLY FIRST", reason)
        self.assertEqual(counts["apply_first"], 2)

    def test_stop_reason_uses_resume_base_counts(self):
        policy = FreshScoutPolicy.from_preferences(
            {
                "fresh_scout": {
                    "target_apply_first_jobs": 4,
                    "target_good_or_better_jobs": 20,
                    "global_new_jobs_soft_cap": 140,
                }
            },
            enabled=True,
        )

        reason, counts = _fresh_global_stop_reason(
            [_report([_job(4, 72, "strong_match")], collected=8, ai_calls=7)],
            _ScoutThresholds(),
            policy,
            base_counts={"apply_first": 3, "good_or_better": 8, "new_jobs_seen": 86, "ai_calls": 75},
        )

        self.assertIn("APPLY FIRST", reason)
        self.assertEqual(counts["apply_first"], 4)
        self.assertEqual(counts["new_jobs_seen"], 94)
        self.assertEqual(counts["ai_calls"], 82)

    def test_stop_reason_uses_good_jobs_target_and_soft_cap(self):
        good_policy = FreshScoutPolicy.from_preferences(
            {
                "fresh_scout": {
                    "target_apply_first_jobs": 4,
                    "target_good_or_better_jobs": 5,
                    "global_new_jobs_soft_cap": 20,
                }
            },
            enabled=True,
        )
        reason, _counts = _fresh_global_stop_reason(
            [
                _report(
                    [
                        _job(1, 65, "possible_match"),
                        _job(2, 55, "possible_match"),
                        _job(3, 60, "possible_match"),
                        _job(4, 68, "possible_match"),
                        _job(5, 50, "possible_match"),
                    ],
                    collected=5,
                )
            ],
            _ScoutThresholds(),
            good_policy,
        )
        self.assertIn("GOOD OPTIONS", reason)

        cap_policy = FreshScoutPolicy.from_preferences(
            {
                "fresh_scout": {
                    "target_apply_first_jobs": 4,
                    "target_good_or_better_jobs": 5,
                    "global_new_jobs_soft_cap": 3,
                }
            },
            enabled=True,
        )
        reason, counts = _fresh_global_stop_reason([_report([], collected=3)], _ScoutThresholds(), cap_policy)
        self.assertIn("soft cap", reason)
        self.assertEqual(counts["new_jobs_seen"], 3)

    def test_ai_budget_guard_stops_low_yield_fresh_runs(self):
        policy = FreshScoutPolicy.from_preferences(
            {
                "fresh_scout": {
                    "target_apply_first_jobs": 8,
                    "target_good_or_better_jobs": 20,
                    "global_new_jobs_soft_cap": 140,
                    "ai_calls_quality_check": 40,
                    "min_apply_first_after_ai_quality_check": 2,
                    "min_good_or_better_after_ai_quality_check": 5,
                }
            },
            enabled=True,
        )

        reason, counts = _fresh_global_stop_reason(
            [_report([_job(1, 55, "possible_match")], collected=44, ai_calls=44)],
            _ScoutThresholds(),
            policy,
        )

        self.assertIn("AI budget guard", reason)
        self.assertEqual(counts["ai_calls"], 44)

    def test_ai_budget_guard_allows_productive_fresh_runs_like_observed_test_log(self):
        policy = FreshScoutPolicy.from_preferences(
            {
                "fresh_scout": {
                    "target_apply_first_jobs": 8,
                    "target_good_or_better_jobs": 20,
                    "global_new_jobs_soft_cap": 140,
                    "ai_calls_soft_cap": 120,
                }
            },
            enabled=True,
        )
        jobs = [
            _job(1, 85, "strong_match"),
            _job(2, 75, "strong_match"),
            _job(3, 72, "strong_match"),
            _job(4, 70, "strong_match"),
            *[_job(100 + index, 60, "possible_match") for index in range(7)],
        ]

        reason, counts = _fresh_global_stop_reason(
            [_report(jobs, collected=86, ai_calls=75)],
            _ScoutThresholds(),
            policy,
        )

        self.assertEqual(reason, "")
        self.assertEqual(counts["apply_first"], 4)
        self.assertEqual(counts["good_or_better"], 11)
        self.assertEqual(counts["ai_calls"], 75)

    def test_ai_budget_guard_soft_cap_stops_before_unbounded_model_spend(self):
        policy = FreshScoutPolicy.from_preferences(
            {
                "fresh_scout": {
                    "target_apply_first_jobs": 8,
                    "target_good_or_better_jobs": 20,
                    "global_new_jobs_soft_cap": 140,
                    "ai_calls_soft_cap": 120,
                }
            },
            enabled=True,
        )
        jobs = [
            *[_job(1 + index, 75, "strong_match") for index in range(7)],
            *[_job(100 + index, 60, "possible_match") for index in range(12)],
        ]

        reason, counts = _fresh_global_stop_reason(
            [_report(jobs, collected=119, ai_calls=120)],
            _ScoutThresholds(),
            policy,
        )

        self.assertIn("soft cap 120", reason)
        self.assertEqual(counts["apply_first"], 7)
        self.assertEqual(counts["good_or_better"], 19)

    def test_run_summary_prints_fresh_stop_details(self):
        console = Console(record=True, width=120)
        reporter = ScoutConsoleReporter(console=console)

        reporter.finish_run(
            final_stats={
                "fresh_stopped_early": True,
                "fresh_stop_reason": "found 8 APPLY FIRST jobs (target 8)",
                "fresh_apply_first_jobs": 8,
                "fresh_good_or_better_jobs": 14,
                "fresh_new_jobs_seen": 44,
                "fresh_ai_calls": 40,
            },
            completed_at="2026-05-29T12:00:00+02:00",
        )
        output = console.export_text()

        self.assertIn("Fresh stop", output)
        self.assertIn("found 8 APPLY FIRST jobs", output)
        self.assertIn("Fresh APPLY FIRST", output)
        self.assertIn("Fresh good or better", output)
        self.assertIn("Fresh new jobs seen", output)
        self.assertIn("Fresh AI calls", output)


if __name__ == "__main__":
    unittest.main()
