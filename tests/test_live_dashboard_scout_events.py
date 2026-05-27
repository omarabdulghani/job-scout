import json
import unittest
from pathlib import Path

from agent.job_scout import LinkedInJobScout


ROOT = Path(__file__).resolve().parents[1]


class LiveDashboardScoutEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
        preferences = json.loads((ROOT / "config" / "preferences.json").read_text(encoding="utf-8"))
        cls.scout = LinkedInJobScout(profile, preferences, browser=None)

    def test_build_live_ai_event_contains_dashboard_fields(self):
        event = self.scout._build_live_result_event(
            query="junior ux designer",
            index=4,
            job={
                "title": "Junior UX Designer",
                "company": "Example",
                "location": "Amsterdam, Netherlands",
                "url": "https://www.linkedin.com/jobs/view/123456789/",
                "page_number": 2,
                "description": "Junior UX role using Figma and prototypes.",
            },
            terminal_status="accepted",
            source_stage="ai_scored",
            reason="Strong junior UX fit.",
            verdict={"reasons": ["Entry-level signal found: junior"]},
            ai_result={
                "job_id": "123456789",
                "interview_probability_score": 82,
                "model": "gemini:gemini-2.5-flash",
                "match_tier": "strong_match",
                "cache_status": "new",
                "second_stage_used": True,
            },
        )

        self.assertEqual(event["board"], "linkedin")
        self.assertEqual(event["query"], "junior ux designer")
        self.assertEqual(event["page_number"], 2)
        self.assertEqual(event["job_index"], 4)
        self.assertEqual(event["score"], 82)
        self.assertEqual(event["terminal_status"], "accepted")
        self.assertEqual(event["source_stage"], "ai_scored")
        self.assertEqual(event["job_id"], "123456789")
        self.assertEqual(event["match_tier"], "strong_match")
        self.assertTrue(event["used_cv_second_stage"])

    def test_build_live_rejected_event_uses_filter_reason(self):
        event = self.scout._build_live_result_event(
            query="data analyst",
            index=1,
            job={
                "title": "Senior Data Engineer",
                "company": "Example",
                "location": "Amsterdam, Netherlands",
                "url": "https://www.linkedin.com/jobs/view/987/",
                "page_number": 1,
                "preview_text": "Requires 5+ years Snowflake and dbt.",
            },
            terminal_status="rejected_entry_level",
            source_stage="non_ai_filter",
            verdict={"reasons": ["Title suggests non-entry-level seniority: senior"]},
        )

        self.assertEqual(event["score"], 0)
        self.assertEqual(event["terminal_status"], "rejected_entry_level")
        self.assertEqual(event["source_stage"], "non_ai_filter")
        self.assertEqual(event["reason"], "Title suggests non-entry-level seniority: senior")
        self.assertEqual(event["filter_notes"], ["Title suggests non-entry-level seniority: senior"])

    def test_live_callback_failure_does_not_raise(self):
        def failing_callback(_event):
            raise RuntimeError("write failed")

        self.scout._emit_live_result(failing_callback, {"title": "Example"})


class _FakeLoggedInLinkedIn:
    async def ensure_logged_in(self):
        return True


class _PageByPageScout(LinkedInJobScout):
    def __init__(self, profile, preferences):
        super().__init__(profile, preferences, browser=None)
        self.linkedin = _FakeLoggedInLinkedIn()
        self.events = []

    async def _collect_job_summary_pages(
        self,
        query,
        location,
        max_pages,
        start_page=1,
        page_scanned_callback=None,
    ):
        self.events.append("collect-page-1")
        yield [{"title": "One", "company": "A", "url": "https://www.linkedin.com/jobs/view/1/"}], 1, 1
        self.events.append("collect-page-2")
        yield [{"title": "Two", "company": "B", "url": "https://www.linkedin.com/jobs/view/2/"}], 2, 2

    async def _process_summaries_to_output(
        self,
        *,
        query,
        location,
        summaries,
        pages_scanned,
        same_run_job_registry=None,
        job_processed_callback=None,
        live_result_callback=None,
        source_mode="scraped",
        run_started_at=None,
        description_only=False,
        processing_state=None,
        start_index=1,
        finalize=True,
    ):
        if finalize:
            self.events.append("finalize")
            return {
                "pages_scanned": pages_scanned,
                "stats": processing_state["stats"],
            }

        self.events.append(f"process-page-{pages_scanned}-start-{start_index}")
        processing_state["stats"]["pages_scanned"] = pages_scanned
        processing_state["stats"]["job_cards_collected"] += len(summaries)
        return {"processing_state": processing_state}


class LinkedInPageByPageRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_run_processes_each_page_before_collecting_next_page(self):
        profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
        preferences = json.loads((ROOT / "config" / "preferences.json").read_text(encoding="utf-8"))
        scout = _PageByPageScout(profile, preferences)

        result = await scout.run("junior ux designer", location="Amsterdam", max_pages=2)

        self.assertEqual(
            scout.events,
            [
                "collect-page-1",
                "process-page-1-start-1",
                "collect-page-2",
                "process-page-2-start-2",
                "finalize",
            ],
        )
        self.assertEqual(result["pages_scanned"], 2)
        self.assertEqual(result["stats"]["job_cards_collected"], 2)


if __name__ == "__main__":
    unittest.main()
