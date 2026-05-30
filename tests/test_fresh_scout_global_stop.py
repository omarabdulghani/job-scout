import unittest

from rich.console import Console

from agent.fresh_scout_policy import FreshScoutPolicy
from agent.scout_console_reporter import ScoutConsoleReporter
from scout_jobs_multi import _fresh_global_stop_reason, _fresh_recommendation_counts


class _ScoutThresholds:
    AI_THRESHOLD = 50
    AI_STRONG_MATCH_THRESHOLD = 70


def _report(jobs, *, collected=0):
    return {
        "stats": {"job_cards_collected": collected},
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
            },
            completed_at="2026-05-29T12:00:00+02:00",
        )
        output = console.export_text()

        self.assertIn("Fresh stop", output)
        self.assertIn("found 8 APPLY FIRST jobs", output)
        self.assertIn("Fresh APPLY FIRST", output)
        self.assertIn("Fresh good or better", output)
        self.assertIn("Fresh new jobs seen", output)


if __name__ == "__main__":
    unittest.main()
