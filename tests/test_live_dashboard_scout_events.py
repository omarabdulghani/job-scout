import json
import unittest
from pathlib import Path

from agent.fresh_scout_policy import FreshScoutPolicy
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
                "easy_apply": True,
                "apply_method": "easy_apply",
                "apply_method_detection_source": "detail_apply_button",
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
        self.assertTrue(event["easy_apply"])
        self.assertEqual(event["apply_method"], "easy_apply")
        self.assertEqual(event["apply_method_detection_source"], "detail_apply_button")
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


class _FakePageQualityBrowser:
    def __init__(self):
        self.page = type("Page", (), {"url": "https://www.linkedin.com/jobs/search/"})()

    async def goto(self, _url):
        self.page.url = _url


class _FakePageQualityLinkedIn:
    SEARCH_SCROLL_ROUNDS = 0

    def __init__(self, cards):
        self.cards = cards

    async def _scroll_search_results(self, _distance):
        return None

    async def _extract_job_cards(self):
        return list(self.cards)


class _PageQualityScout(LinkedInJobScout):
    def __init__(self, profile, preferences, cards, known_job_ids):
        super().__init__(profile, preferences, browser=_FakePageQualityBrowser())
        self.linkedin = _FakePageQualityLinkedIn(cards)
        self.known_job_ids = set(known_job_ids)

    async def _wait_for_search_state_stable(self, query, location, search_url):
        return None

    async def _human_pause_after_page_navigation(self):
        return None

    async def _human_pause_between_scroll_rounds(self):
        return None

    async def _ensure_full_results_list_ready(self, query, location, search_url, page_number):
        return {}

    async def _inspect_results_layout(self, page_number):
        return {"layout_type": "full_paginated_results", "has_additional_pages": False}

    def _log_results_layout(self, layout, page_number):
        return None

    def _log_invalid_job_url(self, *, analysis, source, title):
        return None

    def _is_globally_analyzed(self, job):
        job_id = (job.get("job_id") or self._linkedin_job_id(job.get("url", ""))).strip()
        if job_id in self.known_job_ids:
            return True, "test_known_store"
        return False, ""

    def _touch_known_job_seen(self, job, query):
        return None


class _FreshDecisionLinkedIn:
    SEARCH_SCROLL_ROUNDS = 0

    def __init__(self, pages):
        self.pages = pages
        self.current_page = 1

    async def _scroll_search_results(self, _distance):
        return None

    async def _extract_job_cards(self):
        return list(self.pages.get(self.current_page, []))


class _FreshDecisionScout(_PageQualityScout):
    def __init__(self, profile, preferences, pages, known_job_ids):
        first_page = pages.get(1, [])
        super().__init__(profile, preferences, cards=first_page, known_job_ids=known_job_ids)
        self.linkedin = _FreshDecisionLinkedIn(pages)
        self.max_available_page = max(pages)
        self.navigation_pages = []

    async def _inspect_results_layout(self, page_number):
        return {
            "layout_type": "full_paginated_results",
            "has_additional_pages": page_number < self.max_available_page,
        }

    async def _navigate_to_results_page(self, page_number, query, location):
        self.navigation_pages.append(page_number)
        self.linkedin.current_page = page_number
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
        fresh_policy=None,
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
    def _card(self, job_id: int) -> dict:
        return {
            "title": f"Job {job_id}",
            "company": "Example",
            "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
        }

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

    async def test_collect_page_reports_known_new_and_duplicate_quality(self):
        profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
        preferences = json.loads((ROOT / "config" / "preferences.json").read_text(encoding="utf-8"))
        cards = [
            {
                "title": "Fresh UX",
                "company": "A",
                "url": "https://www.linkedin.com/jobs/view/111/",
            },
            {
                "title": "Known UX",
                "company": "B",
                "url": "https://www.linkedin.com/jobs/view/222/",
            },
            {
                "title": "Duplicate Fresh UX",
                "company": "A",
                "url": "https://www.linkedin.com/jobs/view/111/",
            },
            {
                "title": "Invalid",
                "company": "C",
                "url": "https://example.com/jobs/333",
            },
        ]
        scout = _PageQualityScout(profile, preferences, cards=cards, known_job_ids={"222"})
        callbacks = []

        async for page_jobs, pages_scanned, page_number in scout._collect_job_summary_pages(
            query="junior ux designer",
            location="Amsterdam",
            max_pages=1,
            page_scanned_callback=lambda **kwargs: callbacks.append(kwargs),
        ):
            self.assertEqual(pages_scanned, 1)
            self.assertEqual(page_number, 1)
            self.assertEqual([job["url"] for job in page_jobs], ["https://www.linkedin.com/jobs/view/111/"])

        quality = callbacks[0]["page_quality"]
        self.assertEqual(quality["cards_seen"], 4)
        self.assertEqual(quality["valid_unique_cards"], 2)
        self.assertEqual(quality["known_jobs"], 1)
        self.assertEqual(quality["new_jobs"], 1)
        self.assertEqual(quality["duplicate_cards"], 1)
        self.assertEqual(quality["invalid_cards"], 1)
        self.assertEqual(quality["known_ratio"], 0.5)
        self.assertEqual(scout._page_quality_records, [quality])

    async def test_fresh_mode_continues_past_first_page_when_page_is_duplicate_heavy(self):
        profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
        preferences = json.loads((ROOT / "config" / "preferences.json").read_text(encoding="utf-8"))
        pages = {
            1: [self._card(job_id) for job_id in range(100, 110)],
            2: [self._card(job_id) for job_id in range(200, 210)],
            3: [self._card(job_id) for job_id in range(300, 310)],
        }
        known_ids = {str(job_id) for job_id in range(101, 110)} | {str(job_id) for job_id in range(200, 210)}
        scout = _FreshDecisionScout(profile, preferences, pages=pages, known_job_ids=known_ids)
        policy = FreshScoutPolicy.from_preferences({}, enabled=True)
        seen_pages = []

        async for _page_jobs, _pages_scanned, page_number in scout._collect_job_summary_pages(
            query="junior ux designer",
            location="Amsterdam",
            max_pages=policy.max_pages_per_query,
            fresh_policy=policy,
        ):
            seen_pages.append(page_number)

        self.assertEqual(seen_pages, [1, 2])
        self.assertEqual([item["known_jobs"] for item in scout._page_quality_records], [9, 10])
        self.assertEqual([item["new_jobs"] for item in scout._page_quality_records], [1, 0])
        self.assertEqual(scout.navigation_pages, [2])

    async def test_fresh_mode_stops_query_after_enough_new_jobs(self):
        profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
        preferences = json.loads((ROOT / "config" / "preferences.json").read_text(encoding="utf-8"))
        pages = {
            1: [self._card(100), self._card(101), self._card(102)],
            2: [self._card(200), self._card(201), self._card(202)],
        }
        scout = _FreshDecisionScout(profile, preferences, pages=pages, known_job_ids=set())
        policy = FreshScoutPolicy.from_preferences({}, enabled=True)
        seen_pages = []

        async for _page_jobs, _pages_scanned, page_number in scout._collect_job_summary_pages(
            query="junior ux designer",
            location="Amsterdam",
            max_pages=policy.max_pages_per_query,
            fresh_policy=policy,
        ):
            seen_pages.append(page_number)

        self.assertEqual(seen_pages, [1])
        self.assertEqual(scout._page_quality_records[0]["new_jobs"], 3)
        self.assertEqual(scout.navigation_pages, [])


if __name__ == "__main__":
    unittest.main()
