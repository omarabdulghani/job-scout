import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent.live_recommended_jobs_dashboard import (
    LiveRecommendedJobsDashboard,
    classify_domain,
)


class FixedClock:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return datetime(2026, 5, 26, 14, 3, self.calls % 60, tzinfo=timezone.utc)


class LiveDashboardWriterTests(unittest.TestCase):
    def test_historical_lane_backfill_is_conservative_versioned_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "data/recommended_jobs_dashboard_data.json"
            original = {
                "schema_version": "live_dashboard.v1",
                "active_run_id": "",
                "runs": [],
                "jobs": [
                    {
                        "job_id": "strong",
                        "title": "Junior Product Designer",
                        "company": "Example",
                        "domain_category": "UX_UI_PRODUCT_DESIGN",
                        "career_lane": "other",
                    },
                    {
                        "job_id": "uncertain",
                        "title": "Coordinator",
                        "company": "Example",
                        "description": "May occasionally support content tasks.",
                        "domain_category": "OTHER",
                        "career_lane": "other",
                    },
                    {
                        "job_id": "explicit",
                        "title": "Product Designer",
                        "company": "Example",
                        "domain_category": "UX_UI_PRODUCT_DESIGN",
                        "career_lane": "bridge",
                    },
                ],
                "summary": {},
                "filter_options": {},
            }
            data_path.parent.mkdir(parents=True, exist_ok=True)
            data_path.write_text(json.dumps(original), encoding="utf-8")

            first = LiveRecommendedJobsDashboard(
                data_path,
                now_provider=FixedClock(),
            )
            first_payload = json.loads(data_path.read_text(encoding="utf-8"))
            second = LiveRecommendedJobsDashboard(
                data_path,
                now_provider=FixedClock(),
            )
            second_payload = json.loads(data_path.read_text(encoding="utf-8"))

            by_id = {job["job_id"]: job for job in first_payload["jobs"]}
            self.assertEqual(len(first.data["jobs"]), len(original["jobs"]))
            self.assertEqual(by_id["strong"]["career_lane"], "primary")
            self.assertEqual(by_id["uncertain"]["career_lane"], "other")
            self.assertEqual(by_id["explicit"]["career_lane"], "bridge")
            report = first_payload["migrations"]["career_lane_backfill"]
            self.assertEqual(report["version"], 1)
            self.assertEqual(report["changed_count"], 1)
            scope_report = first_payload["migrations"]["scope_metadata_backfill"]
            self.assertEqual(scope_report["version"], 1)
            self.assertEqual(scope_report["changed_count"], 3)
            self.assertIn("contract_type", by_id["strong"])
            self.assertEqual(first_payload, second_payload)
            self.assertEqual(second.data, first.data)

    def test_start_run_writes_contract_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "data/recommended_jobs_dashboard_data.json"
            writer = LiveRecommendedJobsDashboard(data_path, now_provider=FixedClock())

            run = writer.start_run(
                mode="linkedin_scout_multi",
                board="linkedin",
                location="Amstelveen",
                max_pages=2,
                queries=["junior ux designer", "data analyst"],
                started_at="2026-05-26T14:03:00+02:00",
            )

            payload = json.loads(data_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "live_dashboard.v1")
            self.assertEqual(payload["active_run_id"], run["run_id"])
            self.assertEqual(payload["runs"][0]["run_label"], "Run 1 - 2026-05-26 14:03")
            self.assertEqual(payload["runs"][0]["stats"]["processed_jobs"], 0)

    def test_record_job_maps_apply_first_and_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = LiveRecommendedJobsDashboard(
                Path(tmp) / "data/recommended_jobs_dashboard_data.json",
                now_provider=FixedClock(),
            )
            run = writer.start_run(
                mode="linkedin_scout_ai",
                board="linkedin",
                location="Amsterdam",
                max_pages=1,
                queries=["junior ux designer"],
                started_at="2026-05-26T14:03:00+02:00",
            )

            job = writer.record_job(
                {
                    "run_id": run["run_id"],
                    "query": "junior ux designer",
                    "page_number": 1,
                    "job_index": 3,
                    "title": "Junior UX Designer",
                    "company": "Example",
                    "location": "Amsterdam, Netherlands",
                    "url": "https://www.linkedin.com/jobs/view/123456789/",
                    "score": 82,
                    "terminal_status": "accepted",
                    "source_stage": "ai_scored",
                    "reason": "Strong junior UX fit.",
                    "ai_model": "gemini:gemini-2.5-flash",
                    "easy_apply": True,
                    "apply_method": "easy_apply",
                }
            )

            self.assertEqual(job["decision_category"], "APPLY_FIRST")
            self.assertEqual(job["decision_label"], "APPLY FIRST")
            self.assertEqual(job["domain_category"], "UX_UI_PRODUCT_DESIGN")
            payload = json.loads(
                (Path(tmp) / "data/recommended_jobs_dashboard_data.json").read_text(
                    encoding="utf-8"
                )
            )
            run_stats = payload["runs"][0]["stats"]
            self.assertEqual(run_stats["by_career_lane"]["primary"]["apply_first"], 1)
            self.assertEqual(
                run_stats["by_search_market"]["netherlands"]["apply_first"],
                1,
            )
            self.assertEqual(job["job_id"], "123456789")
            self.assertTrue(job["easy_apply"])
            self.assertEqual(job["apply_method"], "easy_apply")
            self.assertEqual(job["apply_method_label"], "Easy Apply")
            self.assertIn("easy_apply", job["flags"])
            self.assertEqual(writer.data["summary"]["by_decision"]["APPLY_FIRST"], 1)
            self.assertEqual(writer.data["summary"]["by_apply_method"]["easy_apply"], 1)
            self.assertIn("UX_UI_PRODUCT_DESIGN", writer.data["filter_options"]["domains"])
            self.assertIn("easy_apply", writer.data["filter_options"]["apply_methods"])

    def test_record_job_persists_international_scope_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = LiveRecommendedJobsDashboard(
                Path(tmp) / "data/recommended_jobs_dashboard_data.json",
                now_provider=FixedClock(),
            )
            run = writer.start_run(
                mode="linkedin_scout_ai",
                board="linkedin",
                location="Dubai",
                max_pages=1,
                queries=["junior product designer"],
                started_at="2026-05-26T14:03:00+02:00",
                search_scope={
                    "platform": "linkedin",
                    "search_market": "uae",
                    "location": "Dubai",
                    "radius_km": 40,
                    "employment": "full-time-preferred",
                },
            )

            job = writer.record_job(
                {
                    "run_id": run["run_id"],
                    "query": "junior product designer",
                    "page_number": 1,
                    "title": "Junior Product Designer",
                    "company": "Example Gulf",
                    "location": "Dubai, United Arab Emirates",
                    "url": "https://www.linkedin.com/jobs/view/987654321/",
                    "score": 69,
                    "terminal_status": "accepted",
                    "source_stage": "ai_scored",
                    "description": (
                        "Permanent contract with relocation package, housing allowance, "
                        "health insurance, annual flight, and visa sponsorship provided."
                    ),
                }
            )

            self.assertEqual(job["search_market"], "uae")
            self.assertEqual(job["sponsorship_status"], "confirmed")
            self.assertEqual(job["relocation_support"], "confirmed")
            self.assertEqual(job["housing_support"], "confirmed")
            self.assertEqual(job["health_insurance"], "confirmed")
            self.assertEqual(job["annual_flight_support"], "confirmed")
            self.assertEqual(job["contract_type"], "permanent")
            payload = json.loads(
                (Path(tmp) / "data/recommended_jobs_dashboard_data.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["runs"][0]["stats"]["by_search_market"]["uae"]["good_options"], 1)

    def test_fresh_run_progress_tracks_goals_and_page_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = LiveRecommendedJobsDashboard(
                Path(tmp) / "data/recommended_jobs_dashboard_data.json",
                now_provider=FixedClock(),
            )
            run = writer.start_run(
                mode="linkedin_multi_query_scout",
                board="linkedin",
                location="Amstelveen",
                max_pages="smart up to 4",
                queries=["junior ux designer", "product coordinator"],
                started_at="2026-05-26T14:03:00+02:00",
                fresh_policy={
                    "enabled": True,
                    "max_pages_per_query": 4,
                    "min_new_jobs_per_useful_query": 5,
                    "target_apply_first_jobs": 8,
                    "target_good_or_better_jobs": 20,
                    "global_new_jobs_soft_cap": 140,
                },
            )

            writer.update_run_progress(
                run["run_id"],
                phase="collecting_pages",
                current_query_index=1,
                total_queries=2,
                current_query="junior ux designer",
                current_page_number=1,
                pages_scanned=1,
                fresh_jobs_seen=2,
                page_quality={
                    "query": "junior ux designer",
                    "page_number": 1,
                    "cards_seen": 25,
                    "valid_unique_cards": 25,
                    "known_jobs": 23,
                    "new_jobs": 2,
                    "known_ratio": 0.92,
                },
            )
            writer.record_job(
                {
                    "run_id": run["run_id"],
                    "query": "junior ux designer",
                    "title": "Junior UX Designer",
                    "company": "Example",
                    "location": "Amsterdam, Netherlands",
                    "url": "https://www.linkedin.com/jobs/view/123456789/",
                    "score": 82,
                    "terminal_status": "accepted",
                    "source_stage": "ai_scored",
                }
            )

            fresh = writer.data["runs"][0]["fresh_scout"]
            self.assertTrue(fresh["enabled"])
            self.assertEqual(fresh["policy"]["global_new_jobs_soft_cap"], 140)
            self.assertEqual(fresh["progress"]["current_query"], "junior ux designer")
            self.assertEqual(fresh["progress"]["apply_first"], 1)
            self.assertEqual(fresh["progress"]["good_or_better"], 1)
            self.assertEqual(fresh["progress"]["known_jobs_skipped"], 23)
            self.assertEqual(fresh["progress"]["fresh_jobs_seen"], 2)
            self.assertEqual(fresh["page_history"][0]["known_ratio"], 0.92)

    def test_record_job_maps_rejected_and_good_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = LiveRecommendedJobsDashboard(
                Path(tmp) / "data/recommended_jobs_dashboard_data.json",
                now_provider=FixedClock(),
            )
            run = writer.start_run(
                mode="linkedin_scout_ai",
                board="linkedin",
                location="Amsterdam",
                max_pages=1,
                queries=["ui designer"],
                started_at="2026-05-26T14:03:00+02:00",
            )

            rejected = writer.record_job(
                {
                    "run_id": run["run_id"],
                    "query": "ui designer",
                    "title": "Senior UI Designer",
                    "company": "Example",
                    "location": "Amsterdam, Netherlands",
                    "score": 0,
                    "terminal_status": "rejected_entry_level",
                    "source_stage": "non_ai_filter",
                    "reason": "Title suggests seniority.",
                }
            )
            good = writer.record_job(
                {
                    "run_id": run["run_id"],
                    "query": "research assistant",
                    "title": "Research Assistant",
                    "company": "ProPharma",
                    "location": "Utrecht, Netherlands",
                    "score": 65,
                    "terminal_status": "accepted",
                    "source_stage": "ai_scored",
                    "reason": "Useful bridge but part-time and commute risk.",
                }
            )

            self.assertEqual(rejected["decision_category"], "REJECTED")
            self.assertEqual(good["decision_category"], "GOOD_OPTIONS")
            self.assertIn("commute_risk", good["flags"])
            self.assertEqual(writer.data["summary"]["by_decision"]["REJECTED"], 1)
            self.assertEqual(writer.data["summary"]["by_decision"]["GOOD_OPTIONS"], 1)

    def test_duplicate_job_in_same_run_merges_queries_and_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = LiveRecommendedJobsDashboard(
                Path(tmp) / "data/recommended_jobs_dashboard_data.json",
                now_provider=FixedClock(),
            )
            run = writer.start_run(
                mode="linkedin_scout_multi",
                board="linkedin",
                location="Amsterdam",
                max_pages=2,
                queries=["junior ux designer", "product designer"],
                started_at="2026-05-26T14:03:00+02:00",
                search_goal="career-growth",
                selected_search_groups=["primary", "bridge"],
            )

            base_event = {
                "run_id": run["run_id"],
                "title": "Junior Product Designer",
                "company": "Example",
                "location": "Amsterdam, Netherlands",
                "url": "https://www.linkedin.com/jobs/view/555/",
                "score": 74,
                "terminal_status": "accepted",
                "source_stage": "ai_scored",
            }
            writer.record_job({
                **base_event,
                "query": "junior ux designer",
                "page_number": 1,
                "search_group": "primary",
                "matched_search_groups": ["primary"],
            })
            merged = writer.record_job({
                **base_event,
                "query": "product designer",
                "page_number": 2,
                "search_group": "bridge",
                "matched_search_groups": ["bridge"],
            })

            self.assertEqual(len(writer.data["jobs"]), 1)
            self.assertEqual(merged["seen_queries"], ["junior ux designer", "product designer"])
            self.assertEqual(merged["seen_pages"], [1, 2])
            self.assertEqual(merged["duplicate_count"], 1)
            self.assertEqual(merged["search_goal"], "career-growth")
            self.assertEqual(merged["matched_search_groups"], ["primary", "bridge"])
            self.assertIn("primary", writer.data["filter_options"]["search_groups"])
            self.assertIn("bridge", writer.data["filter_options"]["search_groups"])
            self.assertEqual(
                writer.data["runs"][0]["stats"]["by_search_group"]["bridge"]["processed_jobs"],
                1,
            )

    def test_complete_run_updates_status_and_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = LiveRecommendedJobsDashboard(
                Path(tmp) / "data/recommended_jobs_dashboard_data.json",
                now_provider=FixedClock(),
            )
            run = writer.start_run(
                mode="linkedin_scout_ai",
                board="linkedin",
                location="Amsterdam",
                max_pages=1,
                queries=["customer success coordinator"],
                started_at="2026-05-26T14:03:00+02:00",
            )
            writer.record_job(
                {
                    "run_id": run["run_id"],
                    "query": "customer success coordinator",
                    "title": "Customer Success Coordinator",
                    "company": "SaaSCo",
                    "location": "Amsterdam, Netherlands",
                    "score": 88,
                    "terminal_status": "accepted",
                    "source_stage": "ai_scored",
                }
            )

            completed = writer.complete_run(run["run_id"], completed_at="2026-05-26T14:20:00+02:00")

            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["completed_at"], "2026-05-26T14:20:00+02:00")
            self.assertEqual(writer.data["active_run_id"], "")
            self.assertEqual(writer.data["runs"][0]["stats"]["apply_first"], 1)

    def test_interrupted_run_clears_active_id_and_preserves_resume_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = LiveRecommendedJobsDashboard(
                Path(tmp) / "data/recommended_jobs_dashboard_data.json"
            )
            run = writer.start_run(
                mode="linkedin_multi_query_scout",
                board="linkedin",
                location="Amstelveen",
                max_pages="4",
                queries=["ux designer"],
            )

            interrupted = writer.transition_run(
                run["run_id"],
                status="interrupted",
                reason="Process disappeared.",
            )

            self.assertEqual(interrupted["status"], "interrupted")
            self.assertEqual(
                interrupted["interruption_reason"],
                "Process disappeared.",
            )
            self.assertEqual(writer.data["active_run_id"], "")
            resumed = writer.resume_run(run["run_id"])
            self.assertEqual(resumed["run_id"], run["run_id"])
            self.assertEqual(resumed["status"], "running")
            self.assertEqual(resumed["interruption_reason"], "")


class LiveDashboardClassifierTests(unittest.TestCase):
    def test_domain_classifier_uses_other_for_unknown_jobs(self):
        self.assertEqual(
            classify_domain(title="Mystery Associate", query="", description="General tasks."),
            "OTHER",
        )

    def test_domain_classifier_identifies_customer_operations(self):
        self.assertEqual(
            classify_domain(
                title="Customer Case Investigation Specialist",
                query="customer operations specialist",
                description="Payment issue investigation and support operations.",
            ),
            "CUSTOMER_SUCCESS_OPS_SUPPORT",
        )


if __name__ == "__main__":
    unittest.main()
