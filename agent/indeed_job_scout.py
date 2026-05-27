from __future__ import annotations

import re
import urllib.parse
from datetime import datetime
from pathlib import Path

from agent.description_log import DescriptionLogWriter
from agent.job_scout import LinkedInJobScout
from scrapers.indeed import IndeedScraper


class IndeedJobScout(LinkedInJobScout):
    """Indeed description-extraction mode.

    This adapter intentionally reuses the existing scout filtering and
    description-log pipeline, while keeping Indeed selectors, URLs, storage, and
    browser behavior separate from LinkedIn.
    """

    OUTPUT_PATH = Path("indeed_high_success_probability_jobs.json")
    REJECTED_DEBUG_PATH = Path("indeed_rejected_jobs_debug.json")
    AI_DEBUG_PATH = Path("indeed_scout_ai_debug.json")
    SCORE_CACHE_PATH = Path("indeed_scored_jobs_cache.json")
    COLLECTED_JOBS_PATH = Path("indeed_scout_collected_jobs.json")
    DESCRIPTION_LOG_DIR = Path("indeed-description-logs")
    RUN_HISTORY_PATH = Path("indeed_scout_run_history.json")
    RESULTS_PER_PAGE = IndeedScraper.RESULTS_PER_PAGE
    DEFAULT_LOCATION = "Amstelveen"

    def __init__(
        self,
        profile: dict,
        preferences: dict,
        browser,
        output_path: Path | None = None,
        rejected_debug_path: Path | None = None,
        ai_debug_path: Path | None = None,
        score_cache_path: Path | None = None,
        collected_jobs_path: Path | None = None,
        tracking_status_path: Path | None = None,
        run_history_path: Path | None = None,
        reporter=None,
    ):
        super().__init__(
            profile=profile,
            preferences=preferences,
            browser=browser,
            output_path=output_path,
            rejected_debug_path=rejected_debug_path,
            ai_debug_path=ai_debug_path,
            score_cache_path=score_cache_path,
            collected_jobs_path=collected_jobs_path,
            tracking_status_path=tracking_status_path,
            run_history_path=run_history_path,
            reporter=reporter,
        )
        self.linkedin = None
        self.indeed = IndeedScraper(browser) if browser else None

    async def run(
        self,
        query: str,
        location: str = DEFAULT_LOCATION,
        max_pages: int | None = 2,
        human_mode: bool = False,
        same_run_job_registry: dict[str, dict] | None = None,
        start_page: int = 1,
        page_scanned_callback=None,
        job_processed_callback=None,
        live_result_callback=None,
        run_started_at: str | None = None,
        description_only: bool = True,
    ) -> dict:
        if not description_only:
            raise RuntimeError("Indeed mode only supports description extraction.")
        query = (query or "").strip()
        if not query:
            raise ValueError("A search query is required.")
        if not self.indeed:
            raise RuntimeError("Browser-backed Indeed scouting is unavailable without a browser controller.")

        page_limit = None if max_pages is None else max(1, int(max_pages or 1))
        self._reset_human_mode_state(enabled=True)
        self._reset_global_known_job_counters()
        self._get_description_log_writer()
        await self.indeed.ensure_manual_access(self.preferences)

        self._search_urls_used = []
        self._results_layout_types_encountered = []
        summaries, pages_scanned = await self._collect_job_summaries(
            query,
            location,
            page_limit,
            start_page=max(1, int(start_page or 1)),
            page_scanned_callback=page_scanned_callback,
        )
        return await self._process_summaries_to_output(
            query=query,
            location=location,
            summaries=summaries,
            pages_scanned=pages_scanned,
            same_run_job_registry=same_run_job_registry,
            job_processed_callback=job_processed_callback,
            live_result_callback=live_result_callback,
            run_started_at=run_started_at or datetime.now().astimezone().isoformat(),
            description_only=True,
        )

    async def process_collected_jobs(
        self,
        query: str,
        location: str = DEFAULT_LOCATION,
        max_pages: int | None = 2,
        same_run_job_registry: dict[str, dict] | None = None,
        job_processed_callback=None,
        live_result_callback=None,
        run_started_at: str | None = None,
        description_only: bool = True,
    ) -> dict:
        if not description_only:
            raise RuntimeError("Indeed mode only supports description extraction.")
        query = (query or "").strip()
        if not query:
            raise ValueError("A search query is required.")

        page_limit = None if max_pages is None else max(1, int(max_pages or 1))
        self._search_urls_used = []
        self._results_layout_types_encountered = ["indeed_process_only_reuse"]
        self._reset_global_known_job_counters()
        self._get_description_log_writer()
        summaries = self._load_collected_job_summaries(query=query, max_pages=page_limit)
        return await self._process_summaries_to_output(
            query=query,
            location=location,
            summaries=summaries,
            pages_scanned=0,
            same_run_job_registry=same_run_job_registry,
            job_processed_callback=job_processed_callback,
            live_result_callback=live_result_callback,
            source_mode="process_only",
            run_started_at=run_started_at or datetime.now().astimezone().isoformat(),
            description_only=True,
        )

    async def _process_summaries_to_output(self, *args, **kwargs) -> dict:
        report = await super()._process_summaries_to_output(*args, **kwargs)
        if report.get("mode") == "linkedin_scout_description_only":
            report["mode"] = "indeed_scout_description_only"
        return report

    async def _collect_job_summaries(
        self,
        query: str,
        location: str,
        max_pages: int | None,
        start_page: int = 1,
        page_scanned_callback=None,
    ) -> tuple[list[dict], int]:
        all_jobs = []
        seen_urls = set()
        pages_scanned = 0
        page_number = max(1, int(start_page or 1))

        while True:
            if max_pages is not None and page_number > max_pages:
                break

            total_label = str(max_pages) if max_pages is not None else "all"
            start = (page_number - 1) * self.RESULTS_PER_PAGE
            search_url = self._build_search_url(query, location, start=start)
            self._search_urls_used.append(search_url)
            self._report(
                "PAGE",
                f"Scanning Indeed page {page_number}/{total_label} for '{self._safe_console_text(query)}' in '{self._safe_console_text(location)}'",
                style="bright_blue",
            )
            await self.browser.goto(search_url)
            await self.indeed._pause_if_manual_action_required("search results")
            await self._human_pause_after_page_navigation()

            for _ in range(self.indeed.SEARCH_SCROLL_ROUNDS):
                await self.indeed.scroll_results()
                await self._human_pause_between_scroll_rounds()

            page_jobs = await self.indeed._extract_jobs()
            if not page_jobs and page_number > 1:
                break

            pages_scanned += 1
            self._record_results_layout_type({"layout_type": "indeed_search_results"})
            unique_jobs_added = 0
            for job in page_jobs:
                job = dict(job)
                url_analysis = self._analyze_indeed_job_url(
                    job.get("_raw_url") or job.get("url", "")
                )
                if not url_analysis["valid"]:
                    self._log_invalid_job_url(
                        analysis=url_analysis,
                        source="fresh extraction",
                        title=job.get("title", ""),
                    )
                    continue
                url = url_analysis["canonical_url"]
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                job["url"] = url
                job["job_id"] = url_analysis["job_id"]
                job["_url_validation"] = url_analysis
                known_analyzed, known_source = self._is_globally_analyzed(job)
                if known_analyzed:
                    self._touch_known_job_seen(job, query)
                    self._record_previously_analyzed_skip(stage="card_stage")
                    if (
                        self._known_job_counters["previously_analyzed_jobs_skipped_at_card_stage"] % 25
                        == 0
                    ):
                        self._report(
                            "STATE",
                            (
                                "Previously analyzed Indeed jobs skipped at card stage: "
                                f"{self._known_job_counters['previously_analyzed_jobs_skipped_at_card_stage']} "
                                f"(latest source: {known_source})"
                            ),
                            style="yellow",
                        )
                    continue
                job["page_number"] = page_number
                job["source"] = "indeed"
                all_jobs.append(job)
                unique_jobs_added += 1

            self.reporter.record_page_scan(
                page_number=page_number,
                new_cards=unique_jobs_added,
                total_collected=len(all_jobs),
                results_layout_type="indeed_search_results",
            )

            if page_scanned_callback:
                page_scanned_callback(
                    query=query,
                    page_number=page_number,
                    pages_scanned=pages_scanned,
                    total_jobs_collected=len(all_jobs),
                )

            has_next_page = await self.indeed.has_next_page()
            if len(page_jobs) < self.RESULTS_PER_PAGE and not has_next_page:
                break
            if not has_next_page and max_pages is None:
                break

            self._human_pages_since_break += 1
            page_number += 1

        return all_jobs, pages_scanned

    async def _get_full_job_details(self, job: dict) -> dict:
        details = dict(job)
        url_analysis = self._analyze_indeed_job_url(details.get("url", ""))
        details["url"] = url_analysis["canonical_url"]
        details["_url_validation"] = url_analysis
        if not url_analysis["valid"]:
            details["description"] = ""
            details["description_debug"] = {
                "text_length": 0,
                "notes": ["invalid_job_url_blocked_before_navigation"],
                "url_validation_result": url_analysis.get("result", ""),
            }
            return details

        details["job_id"] = url_analysis["job_id"]
        details = await self.indeed.get_job_details(details)
        self.reporter.record_description_extracted(
            length=int((details.get("description_debug") or {}).get("text_length", 0) or 0),
            extracted=bool(details.get("description")),
        )
        return details

    def _get_description_log_writer(self) -> DescriptionLogWriter:
        if self.description_log_writer is None:
            self.description_log_writer = DescriptionLogWriter(self.DESCRIPTION_LOG_DIR)
        return self.description_log_writer

    def _write_description_only_record(
        self,
        query: str,
        job: dict,
        preopen_verdict: dict,
        post_filter_verdict: dict,
    ) -> bool:
        writer = self._get_description_log_writer()
        description = (job.get("description") or "").strip()
        language = self._description_language_metadata(job)
        post_reasons = post_filter_verdict.get("reasons") or []
        extraction_status = "extracted" if description else "failed_empty_description"
        record = {
            "recorded_at": datetime.now().astimezone().isoformat(),
            "source": "indeed",
            "query": query,
            "job_title": job.get("title", ""),
            "company_name": job.get("company", ""),
            "link": self._canonicalize_linkedin_job_url(job.get("url", "")),
            "canonical_job_id": (job.get("job_id") or self._linkedin_job_id(job.get("url", ""))).strip(),
            "location": job.get("location", ""),
            "description": description,
            "description_length": len(description),
            "description_language": language["description_language"],
            "language_tag": language["language_tag"],
            "language_risk": language["language_risk"],
            "english_preferred": language["english_preferred"],
            "prefilter_status": preopen_verdict.get("status", "open"),
            "survived_pre_filters": preopen_verdict.get("status", "open") == "open",
            "post_filter_status": post_filter_verdict.get("status", ""),
            "post_filter_reason": post_reasons[0] if post_reasons else "",
            "extraction_status": extraction_status,
        }
        written = writer.write(record, self._same_run_job_identity_keys(job))
        if written:
            self.reporter.record_description_saved(
                count=writer.records_written,
                file_name=writer.path.name,
                language_tag=language["language_tag"],
            )
        return written

    def _build_search_url(self, query: str, location: str, start: int = 0) -> str:
        return self.indeed._build_url(query, location, self.preferences, start=start)

    def _cache_key_from_parts(self, job_id: str, url: str) -> str:
        if job_id:
            return f"indeed_job_id:{job_id}"
        canonical_url = self._canonicalize_linkedin_job_url(url)
        if canonical_url:
            return f"url:{canonical_url}"
        return ""

    def _linkedin_job_id(self, url: str) -> str:
        return self._extract_indeed_job_id(url)

    def _same_run_job_identity_keys(self, job: dict) -> list[str]:
        keys = []
        seen = set()
        job_id = (job.get("job_id") or self._extract_indeed_job_id(job.get("url", ""))).strip()
        canonical_url = self._canonicalize_linkedin_job_url(job.get("url", ""))
        title = self._normalize_text(job.get("title", ""))
        company = self._normalize_text(job.get("company", ""))

        candidates = [
            f"indeed_job_id:{job_id}" if job_id else "",
            f"url:{canonical_url}" if canonical_url else "",
            f"indeed_title_company:{title}::{company}" if title and company else "",
        ]
        for key in candidates:
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    def _canonicalize_linkedin_job_url(self, url: str) -> str:
        return self._analyze_indeed_job_url(url).get("canonical_url", "")

    def _resolve_preferred_linkedin_job_url(self, primary_url: str, fallback_url: str = "") -> str:
        primary = self._canonicalize_linkedin_job_url(primary_url)
        if primary:
            return primary
        return self._canonicalize_linkedin_job_url(fallback_url)

    def _analyze_linkedin_job_url(self, url: str) -> dict:
        return self._analyze_indeed_job_url(url)

    def _analyze_indeed_job_url(self, url: str) -> dict:
        raw_url = (url or "").strip()
        analysis = {
            "raw_url": raw_url,
            "absolute_url": "",
            "canonical_url": "",
            "job_id": "",
            "valid": False,
            "result": "invalid_empty_url",
        }
        if not raw_url:
            return analysis

        absolute_url = urllib.parse.urljoin(IndeedScraper.BASE_URL, raw_url)
        analysis["absolute_url"] = absolute_url
        parsed = urllib.parse.urlparse(absolute_url)
        scheme = (parsed.scheme or "").strip().lower()
        host = (parsed.netloc or "").strip().lower()
        if scheme and scheme not in {"http", "https"}:
            analysis["result"] = "invalid_scheme"
            return analysis
        if not self._is_indeed_host(host):
            analysis["result"] = "invalid_non_indeed_domain"
            return analysis

        job_id = self._extract_indeed_job_id(absolute_url)
        if not job_id:
            analysis["result"] = "invalid_non_job_indeed_page"
            return analysis

        analysis["job_id"] = job_id
        analysis["canonical_url"] = f"{IndeedScraper.BASE_URL}/viewjob?jk={urllib.parse.quote(job_id)}"
        analysis["valid"] = True
        analysis["result"] = "valid_job_detail_url"
        return analysis

    def _extract_indeed_job_id(self, text: str) -> str:
        if not text:
            return ""
        for pattern in (
            r"[?&]jk=([A-Za-z0-9]+)",
            r"[?&]vjk=([A-Za-z0-9]+)",
            r"data-jk=[\"']?([A-Za-z0-9]+)",
            r"\bjob_([A-Za-z0-9]+)",
        ):
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ""

    def _is_indeed_host(self, host: str) -> bool:
        normalized = (host or "").strip().lower()
        return normalized == "indeed.com" or normalized.endswith(".indeed.com")

    def _load_historical_analyzed_identity_sources(self) -> dict[str, str]:
        return {}

    def _upsert_collected_job(self, job: dict, query: str) -> dict | None:
        if not self._description_extracted(job):
            return None

        identity_keys = self._same_run_job_identity_keys(job)
        if not identity_keys:
            return None

        now = datetime.now().astimezone().isoformat()
        record = {
            "query": query,
            "queries_seen": [query],
            "page_number": int(job.get("page_number", 0) or 0),
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": self._canonicalize_linkedin_job_url(job.get("url", "")),
            "job_id": (job.get("job_id") or self._extract_indeed_job_id(job.get("url", ""))).strip(),
            "description": (job.get("description") or "").strip(),
            "description_debug": dict(job.get("description_debug", {}) or {}),
            "collected_at": now,
            "last_seen_at": now,
            "identity_keys": identity_keys,
        }
        return self.collected_jobs.upsert_job(record)
