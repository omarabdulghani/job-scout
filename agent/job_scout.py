import asyncio
import copy
import hashlib
import json
import os
import random
import re
import urllib.parse
from datetime import datetime
from pathlib import Path

from agent.brain import JobBrain
from agent.description_log import DescriptionLogWriter
from agent.fresh_scout_policy import FreshScoutPolicy
from agent.scout_collected_jobs import ScoutCollectedJobsStore
from agent.scout_console_reporter import NullScoutConsoleReporter
from agent.scout_stop import stop_reason, stop_requested
from agent.scout_run_history import ScoutRunHistoryStore
from agent.job_tracking import JobTrackingStore
from agent.job_scope_metadata import (
    cap_score_for_scope,
    enrich_job_scope_metadata,
    evaluate_employment_policy,
    infer_employment_metadata,
    market_eligibility,
)
from agent.search_scope import (
    MARKET_PROFILES,
    linkedin_employment_codes,
    linkedin_workplace_type_codes,
    normalize_search_scope,
)
from scrapers.linkedin import LinkedInScraper


class LinkedInJobScout:
    """LinkedIn scouting mode that finds only manually-worthwhile jobs.

    This mode is intentionally separate from the application flow:
    - no applying
    - no Easy Apply control
    - AI scoring only after non-AI survival
    """

    OUTPUT_PATH = Path("data/high_success_probability_jobs.json")
    REJECTED_DEBUG_PATH = Path("data/rejected_jobs_debug.json")
    AI_DEBUG_PATH = Path("data/scout_ai_debug.json")
    SCORE_CACHE_PATH = Path("data/scored_jobs_cache.json")
    COLLECTED_JOBS_PATH = Path("data/scout_collected_jobs.json")
    DESCRIPTION_LOG_DIR = Path("data/description_logs")
    TRACKING_STATUS_PATH = Path("data/job_tracking_status.json")
    RUN_HISTORY_PATH = Path("data/scout_run_history.json")
    AI_PAYLOAD_AUDIT_FILE_TEMPLATE = "ai_payload_audit_{timestamp}.json"
    AI_SCORING_VERSION = "2026-05-26-opportunity-first-v1"
    AI_THRESHOLD = 50
    AI_STRONG_MATCH_THRESHOLD = 70
    PERFECT_JOB_PROFILE_CANDIDATES = (
        Path("data/user_workspace/job_strategy.txt"),
        Path("PERFECT SUITABLE JOB PROFILE.txt"),
        Path("The Perfect Suitable Job.txt"),
        Path("The Perfect Suitable Job"),
        Path("data/PERFECT SUITABLE JOB PROFILE.txt"),
        Path("data/The Perfect Suitable Job.txt"),
    )
    RESULTS_PER_PAGE = 25
    DEFAULT_LOCATION = "Amstelveen"
    DEFAULT_DISTANCE_MILES = 25
    DEFAULT_EXPERIENCE_LEVELS = ("2", "3")
    DEFAULT_SEARCH_ORIGIN = "JOB_SEARCH_PAGE_KEYWORD_AUTOCOMPLETE"
    LINKEDIN_GEO_IDS = {
        "amstelveen": "102938188",
        "amstelveen north holland netherlands": "102938188",
        "amsterdam": "102011674",
        "amsterdam north holland netherlands": "102011674",
        "netherlands": "102890719",
        "nederland": "102890719",
    }

    SHORT_QUERY_TOKENS = {"ux", "ui", "it", "hr", "bi", "cx"}
    QUERY_STOPWORDS = {
        "a",
        "an",
        "and",
        "for",
        "in",
        "of",
        "role",
        "job",
        "the",
        "to",
        "with",
    }
    ENTRY_LEVEL_MARKERS = {
        "junior",
        "entry",
        "entry level",
        "entry-level",
        "graduate",
        "trainee",
        "starter",
        "workstudent",
        "apprentice",
        "assistant",
        "associate",
        "coordinator",
    }
    INTERNSHIP_TITLE_MARKERS = {
        "intern",
        "internship",
        "stagiaire",
        "stage",
        "bbl",
        "meewerkstage",
        "stageplek",
        "afstudeerstage",
    }
    INTERNSHIP_DESCRIPTION_MARKERS = {
        "internship",
        "intern role",
        "intern position",
        "stagiaire",
        "bbl",
        "meewerkstage",
        "stageplek",
        "afstudeerstage",
    }
    CURRENT_STUDENT_REQUIRED_MARKERS = {
        "current student",
        "currently a student",
        "currently enrolled",
        "currently enrolled student",
        "enrolled at a university",
        "enrolled at university",
        "enrolled in a bachelor",
        "enrolled in a master",
        "registered as a student",
        "must be enrolled",
        "student status required",
        "current bachelor",
        "current master",
        "bachelor student",
        "bachelor's student",
        "master student",
        "master's student",
        "hbo student",
        "wo student",
        "dutch university student",
        "student at a dutch university",
        "afstudeerstage",
        "thesis internship",
        "graduation internship",
    }
    INTERNSHIP_ALLOW_MARKERS = {
        "recent graduate",
        "recent graduates",
        "graduates welcome",
        "graduate welcome",
        "early career",
        "early-career",
        "not suited if still studying",
        "trainee",
        "traineeship",
        "graduate programme",
        "graduate program",
        "associate programme",
        "associate program",
        "associate",
    }
    STRATEGIC_INTERNSHIP_MARKERS = {
        "creative",
        "product",
        "ai",
        "ux",
        "ui",
        "design",
        "designer",
        "content",
        "brand",
        "marketing",
        "e-commerce",
        "ecommerce",
        "web",
        "portfolio",
    }

    SOFT_SENIORITY_SIGNAL_MARKERS = {
        "people management",
        "line management",
        "manage a team",
        "lead a team",
        "lead the team",
        "manage direct reports",
        "direct reports",
        "budget ownership",
        "budget responsibility",
        "budget management",
        "team ownership",
        "own the strategy",
        "own strategy",
        "strategy ownership",
        "strategic ownership",
        "p&l",
        "p and l",
        "strong leadership",
        "leadership experience",
        "proven track record",
        "extensive experience",
    }
    HARD_SENIOR_RESPONSIBILITY_MARKERS = {
        "manage direct reports",
        "direct reports",
        "performance reviews",
        "full p&l ownership",
        "full p and l ownership",
        "people leadership responsibility",
        "line management responsibility",
    }
    CREATIVE_BRAND_GROUPS = {
        "brand": {
            "brand",
            "branding",
            "brand identity",
            "brand experience",
            "brand design",
            "positioning",
        },
        "strategy": {
            "strategy",
            "strategic",
            "strategist",
            "content strategy",
            "creative strategy",
            "go to market",
        },
        "creative": {
            "creative",
            "designer",
            "design",
            "visual",
            "digital designer",
            "graphic",
            "art direction",
            "concept",
        },
        "content": {
            "content",
            "copywriting",
            "copywriter",
            "storytelling",
            "editorial",
        },
        "marketing": {
            "marketing",
            "campaign",
            "communications",
            "social media",
            "activation",
        },
    }
    CREATIVE_BRAND_ADJACENT_TITLE_MARKERS = {
        "brand designer",
        "junior brand strategist",
        "brand strategist",
        "creative strategist",
        "content strategist",
        "visual designer",
        "digital designer",
        "graphic designer",
        "brand assistant",
        "design assistant",
        "creative assistant",
        "marketing designer",
    }
    UX_PRODUCT_GROUPS = {
        "ux": {
            "ux",
            "user experience",
            "ui",
            "user interface",
            "ux ui",
            "ui ux",
            "interaction design",
            "service design",
        },
        "design": {
            "designer",
            "design",
            "product design",
            "digital design",
            "visual design",
            "figma",
        },
        "research": {
            "research",
            "user research",
            "prototype",
            "wireframe",
            "testing",
            "journey",
        },
        "product": {
            "product",
            "app",
            "web",
            "platform",
            "digital product",
        },
        "brand": {
            "brand",
            "branding",
            "creative strategy",
            "visual identity",
        },
    }
    ANALYSIS_GROUPS = {
        "analysis": {
            "analysis",
            "analyst",
            "business analysis",
            "requirements",
            "stakeholder",
            "process",
            "reporting",
            "insights",
        },
        "data": {
            "data",
            "sql",
            "dashboard",
            "metrics",
            "analytics",
            "visualization",
        },
        "consulting": {
            "consulting",
            "consultant",
            "implementation",
            "solution",
            "client",
        },
    }
    SUPPORT_GROUPS = {
        "support": {
            "support",
            "help desk",
            "service desk",
            "customer support",
            "technical support",
            "it support",
        },
        "technical": {
            "technical",
            "troubleshoot",
            "incident",
            "ticket",
            "systems",
            "hardware",
            "software",
        },
        "service": {
            "service",
            "desk",
            "sla",
            "end user",
            "users",
        },
    }
    PREOPEN_LANGUAGE_MARKERS = {
        "professional dutch",
        "professional level dutch",
        "native dutch",
        "native-level dutch",
        "near native dutch",
        "near-native dutch",
        "excellent dutch",
        "dutch c1",
        "dutch c2",
        "c1 dutch",
        "c2 dutch",
        "professioneel nederlands",
        "uitstekend nederlands",
        "moedertaal nederlands",
        "nederlands op c1 niveau",
        "nederlands op c2 niveau",
        "french speaking",
        "french-speaking",
        "french required",
        "fluent french",
        "german speaking",
        "german-speaking",
        "german required",
        "fluent german",
        "japanese speaking",
        "japanese-speaking",
        "japanese required",
        "mandarin speaking",
        "mandarin required",
        "cantonese required",
        "chinese speaking",
        "chinese-speaking",
        "chinese required",
        "danish required",
        "fluent danish",
        "swedish required",
        "fluent swedish",
        "norwegian required",
        "fluent norwegian",
        "spanish required",
        "fluent spanish",
        "italian required",
        "fluent italian",
    }
    DUTCH_REQUIREMENT_MARKERS = {
        "professional dutch",
        "professional level dutch",
        "native dutch",
        "native-level dutch",
        "near native dutch",
        "near-native dutch",
        "excellent dutch",
        "dutch c1",
        "dutch c2",
        "c1 dutch",
        "c2 dutch",
        "professioneel nederlands",
        "uitstekend nederlands",
        "moedertaal nederlands",
        "nederlands op c1 niveau",
        "nederlands op c2 niveau",
    }
    FLUENT_DUTCH_MARKERS = {
        "fluent dutch",
        "fluent in dutch",
        "must be fluent in dutch",
        "vloeiend nederlands",
    }
    DUTCH_COMMUNICATION_CONTEXT_MARKERS = {
        "dutch copywriting",
        "copywriting in dutch",
        "newsletters",
        "social media content",
        "social content",
        "client calls",
        "sales calls",
        "recruitment calls",
        "customer-facing phone",
        "phone support",
        "telephone support",
        "call center",
        "customer service phone",
        "dutch public sector",
        "public-sector communication",
        "dutch labour law",
        "labor law",
        "arbeidsrecht",
        "policy writing",
        "hr advisory",
        "legal",
        "compliance",
        "recruitment",
        "sales",
    }
    PREOPEN_UNRELATED_TITLE_MARKERS = {
        "annotator",
        "annotation",
        "warehouse",
        "warehouse operative",
        "picker packer",
        "driver",
        "courier",
        "forklift",
        "nurse",
        "registered nurse",
        "caregiver",
        "teacher",
        "electrician",
        "electrical maintenance",
        "instrumentation specialist",
        "maintenance technician",
        "field technician",
        "mechanic",
        "welder",
        "plumber",
        "construction worker",
        "machine operator",
        "production operator",
        "cashier",
        "sales advisor",
        "shop assistant",
        "retail associate",
        "barista",
        "waiter",
        "server",
    }
    NON_ROLE_LISTING_MARKERS = {
        "freelancing at",
        "freelance community",
        "talent community",
        "register your interest",
        "join our community",
        "join our freelance network",
    }
    CREATIVE_FALSE_POSITIVE_MARKERS = {
        "ai annotator",
        "annotator",
        "data annotation",
    }
    SOFT_PREFERENCE_EXCLUDE_MARKERS = {
        "dutch",
        "fluent dutch",
        "fluent in dutch",
        "professional dutch",
        "professional level dutch",
        "native dutch",
        "native-level dutch",
        "near native dutch",
        "near-native dutch",
        "excellent dutch",
        "business dutch",
        "c1 dutch",
        "c2 dutch",
        "c1 nederlands",
        "c2 nederlands",
        "vloeiend nederlands vereist",
        "vloeiend nederlands",
        "professioneel nederlands",
        "uitstekend nederlands",
        "moedertaal nederlands",
        "internship",
        "intern",
        "stage",
        "werkstudent",
        "working student",
        "talent acquisition",
        "talent sourcing",
        "headhunter",
        "recruitment consultant",
        "recruiting",
        "freight",
        "airfreight",
        "logistics",
        "supply chain",
        "sales engineer",
        "technical sales",
        "sales development",
        "account executive",
        "account manager",
        "pre-sales",
        "presales",
        "business development",
        "payroll",
        "seo",
        "compliance",
    }
    NETHERLANDS_LOCATION_MARKERS = {
        "netherlands",
        "nederland",
        "amsterdam",
        "utrecht",
        "rotterdam",
        "the hague",
        "den haag",
        "eindhoven",
        "haarlem",
        "hoofddorp",
        "amstelveen",
        "groningen",
        "maastricht",
        "delft",
        "breda",
        "leiden",
        "arnhem",
        "nijmegen",
        "hilversum",
        "almere",
        "schiphol",
        "oude meer",
        "weesp",
        "veenendaal",
        "randstad",
    }
    REMOTE_LOCATION_MARKERS = {
        "remote",
        "hybrid",
        "home based",
        "work from home",
        "home office",
        "distributed",
    }
    NETHERLANDS_REMOTE_COMPATIBILITY_MARKERS = {
        "netherlands",
        "nederland",
        "dutch market",
        "netherlands market",
        "based in the netherlands",
        "located in the netherlands",
        "must live in the netherlands",
        "candidates in the netherlands",
        "reside in the netherlands",
        "within the netherlands",
    }
    QUERY_EXPANSIONS = {
        "brand": {
            "brand",
            "branding",
            "brand strategy",
            "brand strategist",
            "positioning",
            "campaign",
            "creative",
            "marketing",
        },
        "strategy": {
            "strategy",
            "strategic",
            "strategist",
            "positioning",
            "go to market",
            "brand strategy",
        },
        "ux": {
            "ux",
            "user experience",
            "ui",
            "ui ux",
            "product design",
            "interaction design",
            "service design",
            "user research",
            "figma",
        },
        "ui": {
            "ui",
            "user interface",
            "ux",
            "figma",
            "visual design",
            "product design",
        },
        "business": {
            "business",
            "analysis",
            "analyst",
            "stakeholder",
            "requirements",
            "process",
            "consulting",
        },
        "analyst": {
            "analyst",
            "analysis",
            "requirements",
            "reporting",
            "stakeholder",
            "insights",
            "data",
        },
        "data": {
            "data",
            "analytics",
            "sql",
            "reporting",
            "dashboard",
            "insights",
        },
        "support": {
            "support",
            "help desk",
            "service desk",
            "technical support",
            "it support",
        },
        "design": {
            "design",
            "designer",
            "creative",
            "visual design",
            "digital design",
            "product design",
            "brand design",
        },
        "marketing": {
            "marketing",
            "campaign",
            "content",
            "digital marketing",
            "brand",
            "communications",
        },
        "product": {
            "product",
            "product design",
            "product designer",
            "user experience",
        },
        "copywriting": {
            "copywriting",
            "copywriter",
            "content writing",
            "content",
        },
    }

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
        test_run: bool = False,
    ):
        self.test_run = test_run
        self.profile = profile
        self.preferences = preferences
        self.search_scope = normalize_search_scope(
            preferences.get("_runtime_search_scope"),
            platform="linkedin",
            location=self.DEFAULT_LOCATION,
            legacy_distance_miles=int(
                (preferences.get("job_boards", {}).get("linkedin", {}) or {}).get(
                    "distance_miles",
                    self.DEFAULT_DISTANCE_MILES,
                )
                or self.DEFAULT_DISTANCE_MILES
            ),
        )
        self.search_scope_fingerprint = self._fingerprint_text(
            json.dumps(self.search_scope, sort_keys=True, ensure_ascii=True)
        )
        self.browser = browser
        self.brain = JobBrain(profile, preferences)
        self.linkedin = LinkedInScraper(browser) if browser else None
        self.output_path = output_path or self.OUTPUT_PATH
        self.rejected_debug_path = rejected_debug_path or self.REJECTED_DEBUG_PATH
        self.ai_debug_path = ai_debug_path or self.AI_DEBUG_PATH
        self.score_cache_path = score_cache_path or self.SCORE_CACHE_PATH
        self.collected_jobs_path = collected_jobs_path or self.COLLECTED_JOBS_PATH
        self.tracking_status_path = tracking_status_path or self.TRACKING_STATUS_PATH
        self.run_history_path = run_history_path or self.RUN_HISTORY_PATH
        self._search_urls_used: list[str] = []
        self._results_layout_types_encountered: list[str] = []
        self.human_mode = False
        self._human_jobs_since_break = 0
        self._human_pages_since_break = 0
        self._human_next_job_break_after = 0
        self._human_next_page_break_after = 0
        self.perfect_job_profile_path = self._resolve_perfect_job_profile_path()
        self.perfect_job_profile_text = self._load_perfect_job_profile_text()
        self.perfect_job_profile_fingerprint = self._fingerprint_text(
            self.perfect_job_profile_text
        )
        self.score_cache = self._load_score_cache()
        self.collected_jobs = ScoutCollectedJobsStore(self.collected_jobs_path)
        self._historical_analyzed_identity_sources = self._load_historical_analyzed_identity_sources()
        self.job_tracking = JobTrackingStore(self.tracking_status_path)
        self.run_history = ScoutRunHistoryStore(self.run_history_path)
        self.reporter = reporter or NullScoutConsoleReporter()
        self._page_quality_records: list[dict] = []
        self.description_log_writer: DescriptionLogWriter | None = None
        self.ai_payload_audit_enabled = self._env_bool("SCOUT_AI_PAYLOAD_AUDIT", False)
        self.ai_payload_audit_limit = self._env_int("SCOUT_AI_PAYLOAD_AUDIT_LIMIT", 5, minimum=1)
        self.ai_payload_audit_path = (
            self._build_ai_payload_audit_path() if self.ai_payload_audit_enabled else None
        )
        self.ai_payload_audit_records: list[dict] = []
        self.ai_payload_audit_started_at = datetime.now().astimezone().isoformat()
        self.brain.scoring_audit_enabled = self.ai_payload_audit_enabled
        self.brain.scoring_event_logger = self._handle_scoring_event
        self._reset_global_known_job_counters()

        if self.test_run:
            self.collected_jobs._write = lambda: None
            self.job_tracking._write = lambda: None
            self.run_history._write = lambda: None
            self._write_score_cache = lambda: None

    def _reset_global_known_job_counters(self) -> None:
        self._known_job_counters = {
            "previously_analyzed_jobs_skipped": 0,
            "previously_analyzed_jobs_skipped_at_card_stage": 0,
            "duplicate_job_records_prevented": 0,
        }
        self._known_skip_cache_dirty = False

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
        description_only: bool = False,
        fresh_policy: FreshScoutPolicy | None = None,
    ) -> dict:
        query = (query or "").strip()
        if not query:
            raise ValueError("A search query is required.")

        fresh_policy = fresh_policy if fresh_policy and fresh_policy.enabled else None
        page_limit = None if max_pages is None else max(1, int(max_pages or 1))
        if fresh_policy:
            page_limit = max(1, int(fresh_policy.max_pages_per_query or 1))
        self._reset_human_mode_state(enabled=human_mode)
        self._reset_global_known_job_counters()
        if description_only:
            self._get_description_log_writer()
        if not self.linkedin:
            raise RuntimeError("Browser-backed LinkedIn scouting is unavailable without a browser controller.")
        if not await self.linkedin.ensure_logged_in():
            raise RuntimeError("LinkedIn login is required before scouting jobs.")

        self._search_urls_used = []
        self._results_layout_types_encountered = []
        self._page_quality_records = []
        run_started_at = run_started_at or datetime.now().astimezone().isoformat()
        processing_state = self._new_processing_state(
            query=query,
            location=location,
            pages_scanned=0,
            source_mode="scraped",
            run_started_at=run_started_at,
            initial_job_count=0,
        )
        pages_scanned = 0
        next_job_index = 1
        async for page_summaries, pages_scanned, _page_number in self._collect_job_summary_pages(
            query=query,
            location=location,
            max_pages=page_limit,
            start_page=max(1, int(start_page or 1)),
            page_scanned_callback=page_scanned_callback,
            fresh_policy=fresh_policy,
        ):
            await self._process_summaries_to_output(
                query=query,
                location=location,
                summaries=page_summaries,
                pages_scanned=pages_scanned,
                same_run_job_registry=same_run_job_registry,
                job_processed_callback=job_processed_callback,
                live_result_callback=live_result_callback,
                run_started_at=run_started_at,
                description_only=description_only,
                processing_state=processing_state,
                start_index=next_job_index,
                finalize=False,
            )
            next_job_index += len(page_summaries)
            if stop_requested("after_current_page", "after_current_job", "now"):
                self._report(
                    "STOP",
                    stop_reason() or "Dashboard stop requested; finalizing current scout output.",
                    style="yellow",
                )
                break

        return await self._process_summaries_to_output(
            query=query,
            location=location,
            summaries=[],
            pages_scanned=pages_scanned,
            same_run_job_registry=same_run_job_registry,
            job_processed_callback=job_processed_callback,
            live_result_callback=live_result_callback,
            run_started_at=run_started_at,
            description_only=description_only,
            processing_state=processing_state,
            start_index=next_job_index,
            finalize=True,
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
        description_only: bool = False,
    ) -> dict:
        query = (query or "").strip()
        if not query:
            raise ValueError("A search query is required.")

        page_limit = None if max_pages is None else max(1, int(max_pages or 1))
        self._search_urls_used = []
        self._results_layout_types_encountered = ["process_only_reuse"]
        self._reset_global_known_job_counters()
        if description_only:
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
            description_only=description_only,
        )

    def _report(self, category: str, message: str, *, style: str | None = None) -> None:
        self.reporter.log(category, message, style=style)

    def _handle_scoring_event(self, kind: str, message: str) -> None:
        normalized = (kind or "").strip().lower()
        style = "yellow"
        if normalized == "failure":
            style = "red"
        self._report("AI", message, style=style)

    def _env_bool(self, name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return bool(default)
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        return bool(default)

    def _env_int(self, name: str, default: int, minimum: int = 0) -> int:
        value = os.getenv(name)
        if value is None:
            return max(minimum, int(default))
        try:
            return max(minimum, int(str(value).strip()))
        except (TypeError, ValueError):
            return max(minimum, int(default))

    def _build_ai_payload_audit_path(self) -> Path:
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        return Path(self.AI_PAYLOAD_AUDIT_FILE_TEMPLATE.format(timestamp=timestamp))

    def _decision_label(self, score: int) -> str:
        try:
            numeric = int(score or 0)
        except (TypeError, ValueError):
            numeric = 0
        if numeric >= self.AI_STRONG_MATCH_THRESHOLD:
            return "GO"
        if numeric >= self.AI_THRESHOLD:
            return "CONSIDER"
        return "NO GO"

    def _write_ai_payload_audit_file(self) -> None:
        if not self.ai_payload_audit_enabled or not self.ai_payload_audit_path:
            return
        payload = {
            "started_at": self.ai_payload_audit_started_at,
            "generated_at": datetime.now().astimezone().isoformat(),
            "mode": "scout_ai_payload_audit",
            "audit_limit": self.ai_payload_audit_limit,
            "backend": self.brain.scoring_backend,
            "model": self.brain.scoring_model_label,
            "records": self.ai_payload_audit_records,
        }
        self.ai_payload_audit_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _get_description_log_writer(self) -> DescriptionLogWriter:
        if self.description_log_writer is None:
            self.description_log_writer = DescriptionLogWriter(self.DESCRIPTION_LOG_DIR)
        return self.description_log_writer

    def _description_language_metadata(self, job: dict) -> dict:
        detected = self._detect_description_language(job)
        if detected == "english":
            label = "English"
            risk = "low"
            english_preferred = True
        elif detected == "dutch":
            label = "Dutch"
            risk = "moderate_b1_dutch_review"
            english_preferred = False
        elif detected == "english_friendly":
            label = "Mixed"
            risk = "low_to_moderate"
            english_preferred = True
        else:
            label = "Unknown"
            risk = "unknown"
            english_preferred = False
        return {
            "description_language": label,
            "language_tag": f"This job is in: {label}",
            "language_risk": risk,
            "english_preferred": english_preferred,
        }

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

    def _maybe_record_ai_payload_audit(
        self,
        *,
        query: str,
        job: dict,
        ai_result: dict,
        cache_status: str,
    ) -> None:
        if not self.ai_payload_audit_enabled:
            return
        if len(self.ai_payload_audit_records) >= self.ai_payload_audit_limit:
            return
        if cache_status == "reused_unchanged":
            return

        snapshot = self.brain.get_last_scoring_audit_snapshot()
        if not snapshot:
            return
        backend = str(snapshot.get("backend", "")).strip().lower()
        if backend not in {"lmstudio", "gemini"}:
            return

        score = int(ai_result.get("interview_probability_score", 0) or 0)
        actual_prompt_tokens = snapshot.get("prompt_tokens_actual")
        record = {
            "recorded_at": datetime.now().astimezone().isoformat(),
            "job_title": job.get("title", ""),
            "company": job.get("company", ""),
            "link": self._canonicalize_linkedin_job_url(job.get("url", "")),
            "query": query,
            "full_original_description": job.get("description", ""),
            "compressed_ai_payload": snapshot.get("compressed_ai_payload", {}),
            "prompt_token_estimate": (
                actual_prompt_tokens
                if actual_prompt_tokens is not None
                else snapshot.get("prompt_token_estimate", 0)
            ),
            "prompt_token_estimate_source": (
                f"{backend}_usage"
                if actual_prompt_tokens is not None
                else "local_estimate"
            ),
            "prompt_char_count": snapshot.get("prompt_char_count", 0),
            "prompt_word_count": snapshot.get("prompt_word_count", 0),
            "backend": snapshot.get("backend", self.brain.scoring_backend),
            "model": snapshot.get("model", self.brain.scoring_model_label),
            "prompt_variant": snapshot.get("prompt_variant", ""),
            "request_config": snapshot.get("request_config", {}),
            "usage": snapshot.get("usage", {}),
            "final_score": score,
            "final_reason": ai_result.get("reason", ""),
            "decision_label": self._decision_label(score),
            "match_tier": ai_result.get("match_tier", self._match_tier(score)),
            "used_cv": bool(snapshot.get("include_cv")),
        }
        self.ai_payload_audit_records.append(record)
        self._write_ai_payload_audit_file()
        self._report(
            "AUDIT",
            (
                f"Wrote compressed AI payload audit record "
                f"{len(self.ai_payload_audit_records)}/{self.ai_payload_audit_limit}"
            ),
            style="cyan",
        )

    def _record_summary_processed(self, *, query: str, index: int, page_number: int, callback=None) -> None:
        self.reporter.record_summary_processed(page_number=page_number, processed_index=index)
        if callback:
            callback(query=query, processed_jobs=index, page_number=page_number)

    def _emit_live_result(self, callback, event: dict) -> None:
        if not callback:
            return
        try:
            callback(event)
        except Exception as exc:
            self._report(
                "DASHBOARD",
                f"Live dashboard update failed; continuing scout run: {str(exc).strip()}",
                style="yellow",
            )

    def _build_live_result_event(
        self,
        *,
        query: str,
        index: int,
        job: dict,
        terminal_status: str,
        source_stage: str,
        reason: str = "",
        verdict: dict | None = None,
        ai_result: dict | None = None,
        flags: list[str] | None = None,
    ) -> dict:
        ai_result = ai_result or {}
        verdict = verdict or {}
        score = ai_result.get("interview_probability_score", 0)
        url = self._canonicalize_linkedin_job_url(job.get("url", ""))
        job_id = ai_result.get("job_id") or self._linkedin_job_id(url)
        filter_notes = list(verdict.get("reasons") or [])
        description = job.get("description") or job.get("preview_text") or ""
        scope_metadata = enrich_job_scope_metadata(
            job,
            self.search_scope,
            ai_result=ai_result,
            user_country=self.profile.get("personal", {}).get("location", {}).get("country", ""),
        )
        return {
            "board": self._live_dashboard_board_name(),
            "query": query,
            "page_number": job.get("page_number", 0),
            "job_index": index,
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": url,
            "job_id": job_id,
            "score": score,
            "terminal_status": terminal_status,
            "source_stage": source_stage,
            "reason": reason or (filter_notes[0] if filter_notes else ""),
            "filter_notes": filter_notes,
            "description_preview": self._description_preview(description, max_chars=260),
            "flags": flags or [],
            "easy_apply": bool(job.get("easy_apply")),
            "apply_method": job.get("apply_method", "unknown"),
            "apply_method_detection_source": job.get("apply_method_detection_source", ""),
            "ai_model": ai_result.get("model", self.brain.scoring_model_label if ai_result else ""),
            "match_tier": ai_result.get("match_tier", ""),
            "cache_status": ai_result.get("cache_status", ""),
            "used_cv_second_stage": bool(ai_result.get("second_stage_used")),
            "search_scope": dict(self.search_scope),
            **scope_metadata,
        }

    def _live_dashboard_board_name(self) -> str:
        if getattr(self, "indeed", None) is not None and getattr(self, "linkedin", None) is None:
            return "indeed"
        return "linkedin"

    def _record_previously_analyzed_skip(self, *, stage: str) -> None:
        self._known_job_counters["previously_analyzed_jobs_skipped"] += 1
        if (stage or "").strip().lower() == "card_stage":
            self._known_job_counters["previously_analyzed_jobs_skipped_at_card_stage"] += 1
        self._known_job_counters["duplicate_job_records_prevented"] += 1
        self.reporter.record_previously_analyzed_skip(stage=stage, count=1)

    def _touch_known_job_seen(self, job: dict, query: str) -> None:
        now = datetime.now().astimezone().isoformat()
        cache_key = self._cache_key_from_parts(
            (job.get("job_id") or self._linkedin_job_id(job.get("url", ""))).strip(),
            job.get("url", ""),
        )
        cached_entry = self.score_cache.get(cache_key) if cache_key else None
        historical_source = ""
        identity_keys = self._same_run_job_identity_keys(job)
        for key in identity_keys:
            if key in self._historical_analyzed_identity_sources:
                historical_source = self._historical_analyzed_identity_sources[key]
                break
        if identity_keys:
            existing = self.collected_jobs.get_by_identity_keys(identity_keys)
            if existing:
                existing["query"] = existing.get("query", "") or query
                existing["queries_seen"] = self._append_unique_query(existing.get("queries_seen", []), query)
                existing["last_seen_at"] = now
                if not ((existing.get("analyzed_at") or "").strip() or (existing.get("analysis_status") or "").strip()):
                    if cached_entry:
                        existing["analyzed_at"] = cached_entry.get("first_seen_at", "") or cached_entry.get("scored_at", "") or now
                        existing["analysis_status"] = "migrated_from_score_cache"
                        existing["analysis_reason"] = "Previously analyzed job migrated from score cache during suppression."
                    elif historical_source:
                        existing["analyzed_at"] = now
                        existing["analysis_status"] = "migrated_from_historical_outputs"
                        existing["analysis_reason"] = f"Previously analyzed job imported from {historical_source}."
                self.collected_jobs.upsert_job(existing)
            else:
                if cached_entry:
                    self.collected_jobs.upsert_job(
                        {
                            "query": query,
                            "queries_seen": [query],
                            "page_number": int(job.get("page_number", 0) or 0),
                            "title": job.get("title", ""),
                            "company": job.get("company", ""),
                            "location": job.get("location", ""),
                            "url": self._canonicalize_linkedin_job_url(job.get("url", "")),
                            "job_id": (job.get("job_id") or self._linkedin_job_id(job.get("url", ""))).strip(),
                            "description": "",
                            "description_debug": {},
                            "easy_apply": bool(job.get("easy_apply")),
                            "apply_method": job.get("apply_method", "unknown"),
                            "apply_method_detection_source": job.get("apply_method_detection_source", ""),
                            "collected_at": cached_entry.get("first_seen_at", "") or cached_entry.get("scored_at", "") or now,
                            "last_seen_at": now,
                            "analyzed_at": cached_entry.get("first_seen_at", "") or cached_entry.get("scored_at", "") or now,
                            "analysis_status": "migrated_from_score_cache",
                            "analysis_reason": "Previously analyzed job migrated from score cache during suppression.",
                            "identity_keys": identity_keys,
                        }
                    )
                else:
                    if historical_source:
                        self.collected_jobs.upsert_job(
                            {
                                "query": query,
                                "queries_seen": [query],
                                "page_number": int(job.get("page_number", 0) or 0),
                                "title": job.get("title", ""),
                                "company": job.get("company", ""),
                                "location": job.get("location", ""),
                                "url": self._canonicalize_linkedin_job_url(job.get("url", "")),
                                "job_id": (job.get("job_id") or self._linkedin_job_id(job.get("url", ""))).strip(),
                                "description": "",
                                "description_debug": {},
                                "easy_apply": bool(job.get("easy_apply")),
                                "apply_method": job.get("apply_method", "unknown"),
                                "apply_method_detection_source": job.get("apply_method_detection_source", ""),
                                "collected_at": now,
                                "last_seen_at": now,
                                "analyzed_at": now,
                                "analysis_status": "migrated_from_historical_outputs",
                                "analysis_reason": f"Previously analyzed job imported from {historical_source}.",
                                "identity_keys": identity_keys,
                            }
                        )

        if cache_key and cache_key in self.score_cache:
            cached_entry = self.score_cache[cache_key]
            cached_entry["last_seen_at"] = now
            cached_entry["last_query"] = query
            cached_entry["search_queries"] = self._append_unique_query(
                cached_entry.get("search_queries", []),
                query,
            )
            self._known_skip_cache_dirty = True

    def _new_processing_state(
        self,
        *,
        query: str,
        location: str,
        pages_scanned: int,
        source_mode: str,
        run_started_at: str | None,
        initial_job_count: int = 0,
    ) -> dict:
        run_started_at = run_started_at or datetime.now().astimezone().isoformat()
        return {
            "new_recommendations": [],
            "cached_previous_recommendations": [],
            "rejected_or_below_threshold": [],
            "rejected_jobs": [],
            "ai_debug_jobs": [],
            "cache_dirty": False,
            "run_started_at": run_started_at,
            "stats": {
                "query": query,
                "location": location,
                "search_scope": dict(self.search_scope),
                "pages_scanned": pages_scanned,
                "ai_threshold": self.AI_THRESHOLD,
                "ai_strong_match_threshold": self.AI_STRONG_MATCH_THRESHOLD,
                "ai_scoring_version": self.AI_SCORING_VERSION,
                "perfect_job_profile_path": str(self.perfect_job_profile_path),
                "search_urls_used": [],
                "page_quality": [],
                "job_cards_collected": initial_job_count,
                "preopen_skipped_total": 0,
                "skipped_preopen_outside_netherlands": 0,
                "skipped_preopen_internship": 0,
                "skipped_preopen_seniority": 0,
                "skipped_preopen_language": 0,
                "skipped_preopen_irrelevant": 0,
                "same_run_cross_query_reused": 0,
                "same_run_same_query_reused": 0,
                "persistent_collected_reused": 0,
                "collected_jobs_persisted": 0,
                "jobs_opened": 0,
                "description_extracted_true": 0,
                "description_extracted_false": 0,
                "description_only_records_written": 0,
                "description_only_duplicate_records_skipped": 0,
                "rejected_outside_netherlands": 0,
                "rejected_internship": 0,
                "rejected_dutch": 0,
                "rejected_irrelevant": 0,
                "rejected_entry_level": 0,
                "rejected_excluded": 0,
                "rejected_employment_type": 0,
                "survived_non_ai": 0,
                "ai_scored_new": 0,
                "ai_cache_reused": 0,
                "ai_cache_refreshed": 0,
                "ai_second_stage_cv_checks": 0,
                "ai_below_threshold": 0,
                "ai_duplicate_suppressed": 0,
                "ai_errors": 0,
                "new_recommendations": 0,
                "cached_previous_recommendations": 0,
                "rejected_or_below_threshold": 0,
                "accepted": 0,
                "accepted_after_ai": 0,
                "previously_analyzed_jobs_skipped": 0,
                "previously_analyzed_jobs_skipped_at_card_stage": 0,
                "duplicate_job_records_prevented": 0,
                "source_mode": source_mode,
            },
        }

    async def _process_summaries_to_output(
        self,
        query: str,
        location: str,
        summaries: list[dict],
        pages_scanned: int,
        same_run_job_registry: dict[str, dict] | None = None,
        job_processed_callback=None,
        live_result_callback=None,
        source_mode: str = "scraped",
        run_started_at: str | None = None,
        description_only: bool = False,
        processing_state: dict | None = None,
        start_index: int = 1,
        finalize: bool = True,
    ) -> dict:
        if processing_state is None:
            processing_state = self._new_processing_state(
                query=query,
                location=location,
                pages_scanned=pages_scanned,
                source_mode=source_mode,
                run_started_at=run_started_at,
                initial_job_count=len(summaries),
            )
        else:
            processing_state["stats"]["pages_scanned"] = pages_scanned
            processing_state["stats"]["job_cards_collected"] += len(summaries)
        processing_state["stats"]["page_quality"] = list(self._page_quality_records)

        new_recommendations = processing_state["new_recommendations"]
        cached_previous_recommendations = processing_state["cached_previous_recommendations"]
        rejected_or_below_threshold = processing_state["rejected_or_below_threshold"]
        rejected_jobs = processing_state["rejected_jobs"]
        ai_debug_jobs = processing_state["ai_debug_jobs"]
        cache_dirty = bool(processing_state.get("cache_dirty", False))
        run_started_at = processing_state["run_started_at"]
        stats = processing_state["stats"]

        if source_mode == "process_only" and len(summaries):
            self.reporter.record_collected_import(total_collected=len(summaries))

        batch_start_index = max(1, int(start_index or 1))
        batch_display_total = max(len(summaries), batch_start_index + len(summaries) - 1)
        for index, summary in enumerate(summaries, start=batch_start_index):
            if stop_requested("after_current_job", "now"):
                self._report(
                    "STOP",
                    stop_reason() or "Dashboard stop requested after the current job.",
                    style="yellow",
                )
                break
            found_at = datetime.now().astimezone().isoformat()
            summary = dict(summary)
            already_analyzed, _ = self._is_globally_analyzed(summary)
            if already_analyzed:
                self._touch_known_job_seen(summary, query)
                self._record_previously_analyzed_skip(
                    stage="process_only" if source_mode == "process_only" else "summary_stage"
                )
                continue
            summary_url_analysis = self._analyze_linkedin_job_url(
                summary.get("_raw_url") or summary.get("url", "")
            )
            summary["url"] = summary_url_analysis["canonical_url"]
            summary["_url_validation"] = summary_url_analysis
            summary["_found_at"] = found_at
            safe_title = self._safe_console_text(summary.get("title", "Untitled"))
            safe_company = self._safe_console_text(summary.get("company", "Unknown company"))
            self.reporter.start_job(
                index=index,
                total=batch_display_total,
                title=safe_title,
                company=safe_company,
                url=summary.get("url", ""),
            )
            if not summary_url_analysis["valid"]:
                self._skip_invalid_job_url(
                    job=summary,
                    analysis=summary_url_analysis,
                    source="process-only input" if source_mode == "process_only" else "fresh extraction",
                    stats=stats,
                    rejected_jobs=rejected_jobs,
                    query=query,
                    index=index,
                    job_processed_callback=job_processed_callback,
                    live_result_callback=live_result_callback,
                )
                continue
            preopen_verdict = self._evaluate_preopen_job(query, summary)
            if preopen_verdict["status"] != "open":
                stats["preopen_skipped_total"] += 1
                stats[preopen_verdict["status"]] += 1
                if not description_only:
                    self._record_terminal_job_analysis(
                        job=summary,
                        query=query,
                        status=preopen_verdict["status"],
                        reason=(preopen_verdict.get("reasons") or [""])[0],
                    )
                self.reporter.record_preopen_skip(
                    reason=preopen_verdict["reasons"][0],
                )
                rejected_jobs.append(self._build_rejected_job_record(summary, preopen_verdict))
                self._emit_live_result(
                    live_result_callback,
                    self._build_live_result_event(
                        query=query,
                        index=index,
                        job=summary,
                        terminal_status=preopen_verdict["status"],
                        source_stage="non_ai_preopen_filter",
                        reason=preopen_verdict["reasons"][0],
                        verdict=preopen_verdict,
                    ),
                )
                self._record_summary_processed(
                    query=query,
                    index=index,
                    page_number=summary.get("page_number", 0),
                    callback=job_processed_callback,
                )
                self.reporter.end_job()
                continue

            summary_has_description = self._description_extracted(summary)
            if summary_has_description:
                details = copy.deepcopy(summary)
                description_debug = dict(details.get("description_debug") or {})
                notes = list(description_debug.get("notes") or [])
                if "process_only_input" not in notes:
                    notes.append("process_only_input")
                description_debug["notes"] = notes
                details["description_debug"] = description_debug
                self.reporter.record_reuse(
                    kind="stored",
                    detail="process-only input",
                )
                self.reporter.record_description_extracted(
                    length=len((details.get("description") or "").strip()),
                    extracted=self._description_extracted(details),
                    mode="reused",
                )
                if self._description_extracted(details):
                    stats["description_extracted_true"] += 1
                else:
                    stats["description_extracted_false"] += 1
                self._store_same_run_job_entry(same_run_job_registry, details, query)
            else:
                same_run_entry = self._find_same_run_job_entry(same_run_job_registry, summary)
                if same_run_entry:
                    details = copy.deepcopy(same_run_entry.get("details") or {})
                    details["url"] = self._resolve_preferred_linkedin_job_url(
                        details.get("url", ""),
                        summary.get("url", ""),
                    )
                    for field in ("title", "company", "location", "preview_text", "easy_apply", "apply_method"):
                        if not details.get(field) and summary.get(field):
                            details[field] = summary.get(field)
                    if summary.get("page_number"):
                        details["page_number"] = summary.get("page_number")
                    details_url_analysis = self._analyze_linkedin_job_url(details.get("url", ""))
                    details["_url_validation"] = details_url_analysis
                    if not details_url_analysis["valid"]:
                        self._skip_invalid_job_url(
                            job=details,
                            analysis=details_url_analysis,
                            source="same-run reuse",
                            stats=stats,
                            rejected_jobs=rejected_jobs,
                            query=query,
                            index=index,
                            job_processed_callback=job_processed_callback,
                            live_result_callback=live_result_callback,
                        )
                        continue

                    description_debug = dict(details.get("description_debug") or {})
                    notes = list(description_debug.get("notes") or [])
                    if "same_run_reused" not in notes:
                        notes.append("same_run_reused")
                    description_debug["notes"] = notes
                    description_debug["same_run_reused"] = True
                    description_debug["same_run_first_query"] = same_run_entry.get("first_query", "")
                    description_debug["same_run_last_query"] = same_run_entry.get("last_query", "")
                    details["description_debug"] = description_debug

                    if same_run_entry.get("first_query") and same_run_entry.get("first_query") != query:
                        stats["same_run_cross_query_reused"] += 1
                    else:
                        stats["same_run_same_query_reused"] += 1
                    self.reporter.record_reuse(
                        kind="same_run",
                        detail=(
                            f"first seen under '{same_run_entry.get('first_query', '')}'"
                            if same_run_entry.get("first_query")
                            else ""
                        ),
                    )
                    self.reporter.record_description_extracted(
                        length=len((details.get("description") or "").strip()),
                        extracted=self._description_extracted(details),
                        mode="reused",
                    )
                else:
                    persistent_entry = self._find_persistent_collected_job(summary)
                    if persistent_entry:
                        details = copy.deepcopy(persistent_entry)
                        details["url"] = self._resolve_preferred_linkedin_job_url(
                            details.get("url", ""),
                            summary.get("url", ""),
                        )
                        for field in ("title", "company", "location", "preview_text", "easy_apply", "apply_method"):
                            if not details.get(field) and summary.get(field):
                                details[field] = summary.get(field)
                        if summary.get("page_number"):
                            details["page_number"] = summary.get("page_number")
                        details_url_analysis = self._analyze_linkedin_job_url(details.get("url", ""))
                        details["_url_validation"] = details_url_analysis
                        if not details_url_analysis["valid"]:
                            self._skip_invalid_job_url(
                                job=details,
                                analysis=details_url_analysis,
                                source="persistent collected-job reuse",
                                stats=stats,
                                rejected_jobs=rejected_jobs,
                                query=query,
                                index=index,
                                job_processed_callback=job_processed_callback,
                                live_result_callback=live_result_callback,
                            )
                            continue
                        description_debug = dict(details.get("description_debug") or {})
                        notes = list(description_debug.get("notes") or [])
                        if "persistent_collected_reused" not in notes:
                            notes.append("persistent_collected_reused")
                        description_debug["notes"] = notes
                        description_debug["persistent_collected_reused"] = True
                        details["description_debug"] = description_debug
                        stats["persistent_collected_reused"] += 1
                        self.reporter.record_reuse(
                            kind="persistent",
                            detail="persistent collected store",
                        )
                        self.reporter.record_description_extracted(
                            length=len((details.get("description") or "").strip()),
                            extracted=self._description_extracted(details),
                            mode="reused",
                        )
                        if self._description_extracted(details):
                            stats["description_extracted_true"] += 1
                        else:
                            stats["description_extracted_false"] += 1
                        self._store_same_run_job_entry(same_run_job_registry, details, query)
                        if self._description_extracted(details):
                            persisted = self._upsert_collected_job(details, query)
                            if persisted:
                                details = persisted
                    else:
                        open_url_analysis = self._analyze_linkedin_job_url(summary.get("url", ""))
                        summary["_url_validation"] = open_url_analysis
                        if not open_url_analysis["valid"]:
                            self._skip_invalid_job_url(
                                job=summary,
                                analysis=open_url_analysis,
                                source="fresh extraction",
                                stats=stats,
                                rejected_jobs=rejected_jobs,
                                query=query,
                                index=index,
                                job_processed_callback=job_processed_callback,
                                live_result_callback=live_result_callback,
                            )
                            continue
                        self.reporter.record_job_open()
                        await self._human_pause_before_opening_job()
                        details = await self._get_full_job_details(summary)
                        stats["jobs_opened"] += 1
                        self._human_jobs_since_break += 1
                        if self._description_extracted(details):
                            stats["description_extracted_true"] += 1
                            persisted = self._upsert_collected_job(details, query)
                            if persisted:
                                details = persisted
                                stats["collected_jobs_persisted"] += 1
                        else:
                            stats["description_extracted_false"] += 1
                        self._store_same_run_job_entry(same_run_job_registry, details, query)

            details["_found_at"] = found_at
            verdict = self._evaluate_job(query, details)
            rejected_stat_key = {
                "rejected_dutch": "rejected_dutch",
                "rejected_outside_netherlands": "rejected_outside_netherlands",
                "rejected_outside_search_market": "rejected_outside_netherlands",
                "rejected_internship": "rejected_internship",
                "rejected_irrelevant": "rejected_irrelevant",
                "rejected_entry_level": "rejected_entry_level",
                "rejected_excluded": "rejected_excluded",
                "rejected_market_eligibility": "rejected_excluded",
                "rejected_employment_type": "rejected_employment_type",
            }.get(verdict["status"])
            if rejected_stat_key:
                stats[rejected_stat_key] += 1
                if not description_only:
                    self._record_terminal_job_analysis(
                        job=details,
                        query=query,
                        status=verdict["status"],
                        reason=(verdict.get("reasons") or [""])[0],
                    )
                rejected_jobs.append(self._build_rejected_job_record(details, verdict))
                self._emit_live_result(
                    live_result_callback,
                    self._build_live_result_event(
                        query=query,
                        index=index,
                        job=details,
                        terminal_status=verdict["status"],
                        source_stage="non_ai_filter",
                        reason=verdict["reasons"][0],
                        verdict=verdict,
                    ),
                )
                self.reporter.record_postopen_reject(
                    reason=verdict["reasons"][0],
                )
                self._record_summary_processed(
                    query=query,
                    index=index,
                    page_number=details.get("page_number", 0),
                    callback=job_processed_callback,
                )
                self.reporter.end_job()
                continue

            stats["survived_non_ai"] += 1
            self.reporter.record_non_ai_survivor()
            if description_only:
                if self._write_description_only_record(query, details, preopen_verdict, verdict):
                    stats["description_only_records_written"] += 1
                else:
                    stats["description_only_duplicate_records_skipped"] += 1
                self._record_summary_processed(
                    query=query,
                    index=index,
                    page_number=details.get("page_number", 0),
                    callback=job_processed_callback,
                )
                self.reporter.end_job()
                continue

            ai_result = self._score_surviving_job(query, details, verdict)
            ai_debug_jobs.append(ai_result["debug_record"])
            cache_dirty = cache_dirty or ai_result["cache_dirty"]
            if ai_result.get("status", "") != "ai_error":
                self._record_terminal_job_analysis(
                    job=details,
                    query=query,
                    status=ai_result.get("status", ""),
                    reason=ai_result.get("reason", ""),
                )

            if ai_result["cache_status"] == "reused_unchanged":
                stats["ai_cache_reused"] += 1
            elif ai_result["cache_status"] == "rescored_changed":
                stats["ai_cache_refreshed"] += 1
            elif ai_result["cache_status"] == "new":
                stats["ai_scored_new"] += 1

            if ai_result["second_stage_used"]:
                stats["ai_second_stage_cv_checks"] += 1

            self.reporter.record_ai_result(
                title=self._safe_console_text(details.get("title", "Untitled job")),
                score=int(ai_result.get("interview_probability_score", 0) or 0),
                match_tier=ai_result.get("match_tier", "weak_match"),
                status=ai_result.get("status", ""),
                cache_status=ai_result.get("cache_status", ""),
                reason=self._safe_console_text(ai_result.get("reason", "")),
            )

            if ai_result["status"] == "ai_error":
                stats["ai_errors"] += 1
                output_record = self._build_ai_output_job_record(details, verdict, ai_result)
            elif ai_result["status"] == "rejected_employment_type":
                stats["rejected_employment_type"] += 1
                output_record = self._build_ai_output_job_record(details, verdict, ai_result)
                rejected_or_below_threshold.append(output_record)
            elif ai_result["status"] == "below_threshold":
                stats["ai_below_threshold"] += 1
                output_record = self._build_ai_output_job_record(details, verdict, ai_result)
                rejected_or_below_threshold.append(output_record)
            elif ai_result["status"] == "duplicate_suppressed":
                stats["ai_duplicate_suppressed"] += 1
                output_record = self._build_ai_output_job_record(details, verdict, ai_result)
                cached_previous_recommendations.append(output_record)
            else:
                output_record = self._build_ai_output_job_record(details, verdict, ai_result)
                new_recommendations.append(output_record)

            live_flags = []
            if ai_result["status"] == "ai_error":
                live_flags.append("ai_error")
            if ai_result["status"] == "duplicate_suppressed":
                live_flags.append("duplicate_suppressed")
            if ai_result["cache_status"] == "reused_unchanged":
                live_flags.append("cached_score")
            self._emit_live_result(
                live_result_callback,
                self._build_live_result_event(
                    query=query,
                    index=index,
                    job=details,
                    terminal_status=ai_result.get("status", ""),
                    source_stage="ai_scored",
                    reason=ai_result.get("reason", ""),
                    verdict=verdict,
                    ai_result=ai_result,
                    flags=live_flags,
                ),
            )

            self._record_summary_processed(
                query=query,
                index=index,
                page_number=details.get("page_number", 0),
                callback=job_processed_callback,
            )
            self.reporter.end_job()

        processing_state["cache_dirty"] = cache_dirty
        stats["pages_scanned"] = pages_scanned
        stats["page_quality"] = list(self._page_quality_records)
        if not finalize:
            return {
                "started_at": run_started_at,
                "generated_at": datetime.now().astimezone().isoformat(),
                "completed_at": None,
                "mode": "linkedin_scout_processing_batch",
                "query": query,
                "location": location,
                "search_scope": dict(self.search_scope),
                "pages_scanned": pages_scanned,
                "stats": stats,
                "processing_state": processing_state,
            }

        if not description_only and (cache_dirty or self._known_skip_cache_dirty):
            self._write_score_cache()

        run_completed_at = datetime.now().astimezone().isoformat()
        stats["new_recommendations"] = len(new_recommendations)
        stats["cached_previous_recommendations"] = len(cached_previous_recommendations)
        stats["rejected_or_below_threshold"] = len(rejected_or_below_threshold)
        stats["accepted"] = len(new_recommendations) + len(cached_previous_recommendations)
        stats["accepted_after_ai"] = stats["accepted"]
        stats["search_urls_used"] = list(self._search_urls_used)
        stats["results_layout_types"] = list(self._results_layout_types_encountered)
        stats["page_quality"] = list(self._page_quality_records)
        stats["previously_analyzed_jobs_skipped"] = int(
            self._known_job_counters.get("previously_analyzed_jobs_skipped", 0) or 0
        )
        stats["previously_analyzed_jobs_skipped_at_card_stage"] = int(
            self._known_job_counters.get("previously_analyzed_jobs_skipped_at_card_stage", 0) or 0
        )
        stats["duplicate_job_records_prevented"] = int(
            self._known_job_counters.get("duplicate_job_records_prevented", 0) or 0
        )
        if description_only:
            description_log_path = (
                str(self.description_log_writer.path)
                if self.description_log_writer
                else ""
            )
            return {
                "started_at": run_started_at,
                "generated_at": run_completed_at,
                "completed_at": run_completed_at,
                "mode": "linkedin_scout_description_only",
                "query": query,
                "location": location,
                "pages_scanned": pages_scanned,
                "stats": stats,
                "description_log_path": description_log_path,
            }

        grouped_new_recommendations = self._group_recommendations_by_tier(new_recommendations)
        grouped_cached_recommendations = self._group_recommendations_by_tier(
            cached_previous_recommendations
        )
        apply_first_jobs = (
            grouped_new_recommendations["strong_match"]
            + grouped_cached_recommendations["strong_match"]
        )
        consider_jobs = (
            grouped_new_recommendations["possible_match"]
            + grouped_cached_recommendations["possible_match"]
        )

        output = {
            "started_at": run_started_at,
            "generated_at": run_completed_at,
            "completed_at": run_completed_at,
            "mode": "linkedin_scout_ai",
            "query": query,
            "location": location,
            "search_scope": dict(self.search_scope),
            "pages_scanned": pages_scanned,
            "ai_threshold": self.AI_THRESHOLD,
            "ai_strong_match_threshold": self.AI_STRONG_MATCH_THRESHOLD,
            "ai_scoring_version": self.AI_SCORING_VERSION,
            "perfect_job_profile_path": str(self.perfect_job_profile_path),
            "stats": stats,
            "new_recommendations": grouped_new_recommendations,
            "cached_previous_recommendations": grouped_cached_recommendations,
            "apply_first": apply_first_jobs,
            "consider_human_review": consider_jobs,
            "rejected": rejected_or_below_threshold,
            "rejected_or_below_threshold": rejected_or_below_threshold,
        }
        rejected_output = {
            "started_at": run_started_at,
            "generated_at": output["generated_at"],
            "completed_at": run_completed_at,
            "mode": "linkedin_scout_non_ai_debug",
            "query": query,
            "location": location,
            "search_scope": dict(self.search_scope),
            "pages_scanned": pages_scanned,
            "stats": stats,
            "rejected_jobs": rejected_jobs,
        }
        ai_debug_output = {
            "started_at": run_started_at,
            "generated_at": output["generated_at"],
            "completed_at": run_completed_at,
            "mode": "linkedin_scout_ai_debug",
            "query": query,
            "location": location,
            "search_scope": dict(self.search_scope),
            "pages_scanned": pages_scanned,
            "ai_threshold": self.AI_THRESHOLD,
            "ai_strong_match_threshold": self.AI_STRONG_MATCH_THRESHOLD,
            "ai_scoring_version": self.AI_SCORING_VERSION,
            "perfect_job_profile_path": str(self.perfect_job_profile_path),
            "stats": stats,
            "processed_jobs": ai_debug_jobs,
        }
        self._write_output(output)
        self._write_rejected_debug_output(rejected_output)
        self._write_ai_debug_output(ai_debug_output)
        self._write_run_history_entry(output)
        return output

    async def _collect_job_summaries(
        self,
        query: str,
        location: str,
        max_pages: int | None,
        start_page: int = 1,
        page_scanned_callback=None,
        fresh_policy: FreshScoutPolicy | None = None,
    ) -> tuple[list[dict], int]:
        all_jobs = []
        pages_scanned = 0
        async for page_jobs, pages_scanned, _page_number in self._collect_job_summary_pages(
            query=query,
            location=location,
            max_pages=max_pages,
            start_page=start_page,
            page_scanned_callback=page_scanned_callback,
            fresh_policy=fresh_policy,
        ):
            all_jobs.extend(page_jobs)
        return all_jobs, pages_scanned

    async def _collect_job_summary_pages(
        self,
        query: str,
        location: str,
        max_pages: int | None,
        start_page: int = 1,
        page_scanned_callback=None,
        fresh_policy: FreshScoutPolicy | None = None,
    ):
        seen_urls = set()
        first_search_url = self._build_search_url(query, location, start=0)
        pages_scanned = 0
        total_jobs_collected = 0
        page_number = max(1, int(start_page or 1))
        fresh_policy = fresh_policy if fresh_policy and fresh_policy.enabled else None
        duplicate_heavy_streak = 0

        while True:
            if max_pages is not None and page_number > max_pages:
                break

            total_label = str(max_pages) if max_pages is not None else "all"
            if page_number == 1:
                search_url = first_search_url
                self._search_urls_used.append(search_url)
                self._report(
                    "PAGE",
                    f"Scanning LinkedIn page {page_number}/{total_label} for '{self._safe_console_text(query)}' in '{self._safe_console_text(location)}'",
                    style="bright_blue",
                )
                await self.browser.goto(search_url)
                await self._wait_for_search_state_stable(query, location, search_url)
                await self._human_pause_after_page_navigation()
            elif pages_scanned == 0:
                search_url = self._build_search_url(
                    query,
                    location,
                    start=(page_number - 1) * self.RESULTS_PER_PAGE,
                )
                self._search_urls_used.append(search_url)
                self._report(
                    "PAGE",
                    f"Scanning LinkedIn page {page_number}/{total_label} for '{self._safe_console_text(query)}' in '{self._safe_console_text(location)}'",
                    style="bright_blue",
                )
                await self.browser.goto(search_url)
                await self._wait_for_search_state_stable(query, location, search_url)
                await self._human_pause_after_page_navigation()
            else:
                self._report(
                    "PAGE",
                    f"Scanning LinkedIn page {page_number}/{total_label} for '{self._safe_console_text(query)}' in '{self._safe_console_text(location)}'",
                    style="bright_blue",
                )
                await self._human_pause_before_page_navigation()
                navigated = await self._navigate_to_results_page(
                    page_number=page_number,
                    query=query,
                    location=location,
                )
                if not navigated:
                    start = (page_number - 1) * self.RESULTS_PER_PAGE
                    search_url = self._build_search_url(query, location, start=start)
                    self._search_urls_used.append(search_url)
                    await self.browser.goto(search_url)
                    await self._wait_for_search_state_stable(query, location, search_url)
                    await self._human_pause_after_page_navigation()

            pages_scanned += 1
            layout = await self._ensure_full_results_list_ready(
                query=query,
                location=location,
                search_url=self.browser.page.url,
                page_number=page_number,
            )
            for _ in range(self.linkedin.SEARCH_SCROLL_ROUNDS):
                await self.linkedin._scroll_search_results(700)
                await self._human_pause_between_scroll_rounds()
                if not self.human_mode:
                    await asyncio.sleep(1)

            page_jobs = await self.linkedin._extract_job_cards()
            layout = await self._inspect_results_layout(page_number=page_number)
            self._log_results_layout(layout, page_number=page_number)
            if not page_jobs and page_number > 1:
                yield [], pages_scanned, page_number
                break
            if layout.get("layout_type") == "condensed_results_rail":
                self._report(
                    "STATE",
                    "LinkedIn remained in a condensed results rail after inspection; stopping here instead of assuming numbered pagination.",
                    style="bright_cyan",
                )

            if len(page_jobs) < self.RESULTS_PER_PAGE and not layout.get("has_additional_pages", False):
                self._report(
                    "STATE",
                    "Current LinkedIn view behaves like a single-page result set; stopping pagination instead of forcing a synthetic next page.",
                    style="bright_cyan",
                )

            cards_seen = len(page_jobs)
            unique_jobs_added = 0
            known_jobs_on_page = 0
            duplicate_cards_on_page = 0
            invalid_cards_on_page = 0
            page_unique_jobs = []
            for job in page_jobs:
                job = dict(job)
                url_analysis = self._analyze_linkedin_job_url(
                    job.get("_raw_url") or job.get("url", "")
                )
                if not url_analysis["valid"]:
                    invalid_cards_on_page += 1
                    self._log_invalid_job_url(
                        analysis=url_analysis,
                        source="fresh extraction",
                        title=job.get("title", ""),
                    )
                    continue
                url = url_analysis["canonical_url"]
                if not url or url in seen_urls:
                    duplicate_cards_on_page += 1
                    continue
                seen_urls.add(url)
                job["url"] = url
                job["_url_validation"] = url_analysis
                known_analyzed, known_source = self._is_globally_analyzed(job)
                if known_analyzed:
                    known_jobs_on_page += 1
                    self._touch_known_job_seen(job, query)
                    self._record_previously_analyzed_skip(stage="card_stage")
                    if (
                        self._known_job_counters["previously_analyzed_jobs_skipped_at_card_stage"] % 25
                        == 0
                    ):
                        self._report(
                            "STATE",
                            (
                                "Previously analyzed jobs skipped at card stage: "
                                f"{self._known_job_counters['previously_analyzed_jobs_skipped_at_card_stage']} "
                                f"(latest source: {known_source})"
                            ),
                            style="yellow",
                        )
                    continue
                job["page_number"] = page_number
                page_unique_jobs.append(job)
                unique_jobs_added += 1
                total_jobs_collected += 1

            valid_unique_cards = known_jobs_on_page + unique_jobs_added
            known_ratio = (
                known_jobs_on_page / valid_unique_cards
                if valid_unique_cards
                else 0.0
            )
            page_quality = {
                "query": query,
                "page_number": page_number,
                "cards_seen": cards_seen,
                "valid_unique_cards": valid_unique_cards,
                "known_jobs": known_jobs_on_page,
                "new_jobs": unique_jobs_added,
                "known_ratio": round(known_ratio, 4),
                "duplicate_cards": duplicate_cards_on_page,
                "invalid_cards": invalid_cards_on_page,
                "total_new_jobs_collected": total_jobs_collected,
                "results_layout_type": layout.get("layout_type", ""),
                "has_additional_pages": bool(layout.get("has_additional_pages", False)),
            }
            self._page_quality_records.append(page_quality)

            self.reporter.record_page_scan(
                page_number=page_number,
                new_cards=unique_jobs_added,
                cards_seen=cards_seen,
                known_cards=known_jobs_on_page,
                known_ratio=known_ratio,
                total_collected=total_jobs_collected,
                results_layout_type=layout.get("layout_type", ""),
            )

            if page_scanned_callback:
                page_scanned_callback(
                    query=query,
                    page_number=page_number,
                    pages_scanned=pages_scanned,
                    total_jobs_collected=total_jobs_collected,
                    page_quality=page_quality,
                )

            yield page_unique_jobs, pages_scanned, page_number

            if layout.get("layout_type") == "condensed_results_rail":
                break

            if not layout.get("has_additional_pages", False):
                break

            if fresh_policy:
                duplicate_heavy_streak = self._fresh_duplicate_heavy_streak(
                    page_quality,
                    duplicate_heavy_streak,
                    fresh_policy,
                )
                if self._should_stop_fresh_query(
                    page_quality=page_quality,
                    duplicate_heavy_streak=duplicate_heavy_streak,
                    policy=fresh_policy,
                ):
                    break

            self._human_pages_since_break += 1
            page_number += 1

    def _fresh_duplicate_heavy_streak(
        self,
        page_quality: dict,
        current_streak: int,
        policy: FreshScoutPolicy,
    ) -> int:
        valid_unique_cards = int(page_quality.get("valid_unique_cards", 0) or 0)
        known_ratio = float(page_quality.get("known_ratio", 0) or 0)
        if valid_unique_cards and known_ratio >= policy.duplicate_heavy_stop_threshold:
            return current_streak + 1
        return 0

    def _should_stop_fresh_query(
        self,
        *,
        page_quality: dict,
        duplicate_heavy_streak: int,
        policy: FreshScoutPolicy,
    ) -> bool:
        page_number = int(page_quality.get("page_number", 0) or 0)
        total_new_jobs = int(page_quality.get("total_new_jobs_collected", 0) or 0)
        new_jobs = int(page_quality.get("new_jobs", 0) or 0)
        known_ratio = float(page_quality.get("known_ratio", 0) or 0)

        if total_new_jobs >= policy.min_new_jobs_per_useful_query:
            self._report(
                "FRESH",
                (
                    f"Stopping query after finding {total_new_jobs} new job(s); "
                    f"fresh target per useful query is {policy.min_new_jobs_per_useful_query}."
                ),
                style="bright_green",
            )
            return True

        if duplicate_heavy_streak >= policy.stop_after_duplicate_heavy_pages:
            self._report(
                "FRESH",
                (
                    "Stopping query after "
                    f"{duplicate_heavy_streak} duplicate-heavy page(s) "
                    f"with fewer than {policy.min_new_jobs_per_useful_query} new jobs."
                ),
                style="yellow",
            )
            return True

        if page_number >= policy.max_pages_per_query:
            self._report(
                "FRESH",
                f"Stopping query at fresh page cap ({policy.max_pages_per_query}).",
                style="yellow",
            )
            return True

        if known_ratio >= policy.known_ratio_continue_threshold:
            self._report(
                "FRESH",
                (
                    f"Trying next page because page {page_number} was "
                    f"{round(known_ratio * 100)}% known and found {new_jobs} new job(s)."
                ),
                style="bright_blue",
            )
            return False

        self._report(
            "FRESH",
            (
                f"Trying next page because only {total_new_jobs}/"
                f"{policy.min_new_jobs_per_useful_query} fresh job(s) were found for this query."
            ),
            style="bright_blue",
        )
        return False

    async def _navigate_to_results_page(self, page_number: int, query: str, location: str) -> bool:
        page = self.browser.page
        target_names = [f"Page {page_number}"]
        if page_number > 1:
            target_names.append("View next page")

        for name in target_names:
            try:
                button = page.get_by_role("button", name=name).first
                if not await button.is_visible(timeout=1500):
                    continue
                await button.click(timeout=3000)
                await asyncio.sleep(2)
                current_url = page.url
                self._search_urls_used.append(current_url)
                await self._wait_for_search_state_stable(query, location, current_url)
                await self._human_pause_after_page_navigation()
                self._report(
                    "PAGE",
                    f"Navigated via LinkedIn pagination control: {self._safe_console_text(name)}",
                    style="bright_blue",
                )
                return True
            except Exception:
                continue
        return False

    async def _ensure_full_results_list_ready(
        self,
        query: str,
        location: str,
        search_url: str,
        page_number: int,
    ) -> dict:
        last_layout = {}
        for _ in range(2):
            layout = await self._inspect_results_layout(page_number=page_number)
            last_layout = layout
            if layout.get("layout_type") != "condensed_results_rail":
                return layout
            if not layout.get("show_all_control_found", False):
                return layout

            clicked = await self._click_results_show_all()
            if not clicked:
                return layout

            self._report(
                "PAGE",
                "Condensed LinkedIn results rail detected; clicked 'Show all' before attempting pagination.",
                style="bright_blue",
            )
            await asyncio.sleep(2)
            await self._wait_for_search_state_stable(query, location, search_url)

        return last_layout

    async def _inspect_results_layout(self, page_number: int) -> dict:
        page = self.browser.page
        layout = await page.evaluate(
            """(pageNumber) => {
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== "hidden" &&
                        style.display !== "none" &&
                        rect.width > 0 &&
                        rect.height > 0;
                };

                const cardSelector = ".job-card-container, .jobs-search-results__list-item, li.scaffold-layout__list-item";
                const railSelectors = [
                    ".jobs-search-results-list",
                    ".jobs-search-two-pane__results",
                    ".scaffold-layout__list",
                    ".scaffold-layout__list-container",
                ];

                let rail = null;
                for (const selector of railSelectors) {
                    const candidates = Array.from(document.querySelectorAll(selector)).filter(visible);
                    const matched = candidates.find((node) => node.querySelector(cardSelector));
                    if (matched) {
                        rail = matched;
                        break;
                    }
                }

                if (!rail) {
                    rail = Array.from(document.querySelectorAll("main, body")).find(
                        (node) => node && node.querySelector && node.querySelector(cardSelector)
                    ) || null;
                }

                const railText = normalize(rail?.innerText || "");
                const railTail = railText.slice(-1200);
                const controls = Array.from((rail || document).querySelectorAll("a, button"))
                    .filter(visible)
                    .map((el) => {
                        const text = normalize(el.innerText || el.textContent || "");
                        const aria = normalize(el.getAttribute("aria-label") || "");
                        const href = normalize(el.getAttribute("href") || "");
                        const current = normalize(el.getAttribute("aria-current") || "");
                        return { text, aria, href, current };
                    });

                const paginationControls = controls.filter((control) => {
                    return /^\\d+$/.test(control.text)
                        || /^page \\d+$/i.test(control.aria)
                        || /^next$/i.test(control.text)
                        || /view next page/i.test(control.aria);
                });

                const numberedPages = [];
                let hasNextPage = false;
                for (const control of paginationControls) {
                    if (/^\\d+$/.test(control.text)) {
                        numberedPages.push(parseInt(control.text, 10));
                    } else {
                        const match = control.aria.match(/page\\s+(\\d+)/i);
                        if (match) {
                            numberedPages.push(parseInt(match[1], 10));
                        }
                    }
                    if (/^next$/i.test(control.text) || /view next page/i.test(control.aria)) {
                        hasNextPage = true;
                    }
                }

                const showAllControls = controls.filter((control) => {
                    const combined = `${control.text} ${control.aria}`.toLowerCase();
                    return combined.includes("show all")
                        && !combined.includes("filters")
                        && !combined.includes("top job picks")
                        && !combined.includes("jobs where you’d be a top applicant")
                        && !combined.includes("jobs where you'd be a top applicant")
                        && !combined.includes("remote opportunities")
                        && !combined.includes("similar to a job you applied");
                });

                const showAllNearEnd = /show all/i.test(railTail);
                const maxPageNumber = numberedPages.length ? Math.max(...numberedPages) : 1;
                const hasNumberedPagination = numberedPages.length > 1;
                const hasAdditionalPages = hasNextPage || maxPageNumber > pageNumber;

                let layoutType = "single_page_results";
                if (hasNumberedPagination || hasNextPage) {
                    layoutType = "full_paginated_results";
                } else if (showAllControls.length && showAllNearEnd) {
                    layoutType = "condensed_results_rail";
                }

                const bodyText = normalize(document.body?.innerText || "");
                const resultCountMatch =
                    bodyText.match(/(\\d+[\\+]?)\\s+results/i)
                    || document.title.match(/^\\((\\d+[\\+]?)\\)/);

                return {
                    layout_type: layoutType,
                    rail_found: !!rail,
                    rail_tail: railTail,
                    rail_show_all_near_end: showAllNearEnd,
                    show_all_control_found: showAllControls.length > 0,
                    pagination_controls: paginationControls.slice(0, 12),
                    has_numbered_pagination: hasNumberedPagination,
                    has_next_page: hasNextPage,
                    has_additional_pages: hasAdditionalPages || layoutType === "condensed_results_rail",
                    max_page_number: maxPageNumber,
                    visible_card_count: Array.from((rail || document).querySelectorAll(cardSelector)).length,
                    result_count_hint: resultCountMatch ? resultCountMatch[1] : "",
                };
            }""",
            page_number,
        )
        return layout

    async def _click_results_show_all(self) -> bool:
        return bool(
            await self.browser.page.evaluate(
                """() => {
                    const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.visibility !== "hidden" &&
                            style.display !== "none" &&
                            rect.width > 0 &&
                            rect.height > 0;
                    };

                    const cardSelector = ".job-card-container, .jobs-search-results__list-item, li.scaffold-layout__list-item";
                    const railSelectors = [
                        ".jobs-search-results-list",
                        ".jobs-search-two-pane__results",
                        ".scaffold-layout__list",
                        ".scaffold-layout__list-container",
                    ];

                    let rail = null;
                    for (const selector of railSelectors) {
                        const candidates = Array.from(document.querySelectorAll(selector)).filter(visible);
                        const matched = candidates.find((node) => node.querySelector(cardSelector));
                        if (matched) {
                            rail = matched;
                            break;
                        }
                    }
                    if (!rail) return false;

                    const candidates = Array.from(rail.querySelectorAll("a, button")).filter(visible);
                    const target = candidates.find((el) => {
                        const text = normalize(el.innerText || el.textContent || "").toLowerCase();
                        const aria = normalize(el.getAttribute("aria-label") || "").toLowerCase();
                        const combined = `${text} ${aria}`;
                        return combined.includes("show all")
                            && !combined.includes("filters")
                            && !combined.includes("top job picks")
                            && !combined.includes("jobs where you’d be a top applicant")
                            && !combined.includes("jobs where you'd be a top applicant")
                            && !combined.includes("remote opportunities")
                            && !combined.includes("similar to a job you applied");
                    });

                    if (!target) return false;
                    target.click();
                    return true;
                }"""
            )
        )

    def _log_results_layout(self, layout: dict, page_number: int) -> None:
        self._record_results_layout_type(layout)
        controls = []
        for control in layout.get("pagination_controls", []) or []:
            label = control.get("text") or control.get("aria") or ""
            label = self._safe_console_text(label)
            if label:
                controls.append(label)
        self._report(
            "STATE",
            (
                f"Results layout | page={page_number} "
                f"type={layout.get('layout_type', 'unknown')} "
                f"cards={layout.get('visible_card_count', 0)} "
                f"result_hint={self._safe_console_text(layout.get('result_count_hint', '')) or 'unknown'} "
                f"show_all_in_rail={layout.get('show_all_control_found', False)} "
                f"pagination={controls[:6]}"
            ),
            style="bright_cyan",
        )

    def _record_results_layout_type(self, layout: dict) -> None:
        layout_type = (layout.get("layout_type") or "").strip()
        if not layout_type:
            return
        if layout_type in self._results_layout_types_encountered:
            return
        self._results_layout_types_encountered.append(layout_type)

    async def _get_full_job_details(self, job: dict) -> dict:
        details = dict(job)
        url_analysis = self._analyze_linkedin_job_url(details.get("url", ""))
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
        await self.browser.goto(details["url"])
        if self.human_mode:
            await self._human_pause_after_job_navigation()
        else:
            await asyncio.sleep(2)

        try:
            await self.browser.wait_for_navigation(5000)
        except Exception:
            pass

        try:
            await self.linkedin._wait_for_apply_state(attempts=4, delay_seconds=0.75)
        except Exception:
            pass

        details.update(await self._detect_linkedin_apply_method(details))

        extraction = await self._extract_linkedin_job_description()
        if not extraction.get("text"):
            await asyncio.sleep(1.2)
            retry_extraction = await self._extract_linkedin_job_description()
            if len(retry_extraction.get("text", "")) > len(extraction.get("text", "")):
                retry_extraction["notes"] = retry_extraction.get("notes", []) + ["retry_used"]
                extraction = retry_extraction

        details["description"] = (extraction.get("text") or "").strip()
        details["description_debug"] = {
            key: value
            for key, value in extraction.items()
            if key != "text"
        }
        self.reporter.record_description_extracted(
            length=int(details["description_debug"].get("text_length", 0) or 0),
            extracted=bool(details.get("description")),
        )
        return details

    async def _detect_linkedin_apply_method(self, job: dict) -> dict:
        """Inspect visible LinkedIn apply controls without clicking anything."""
        fallback_method = "easy_apply" if bool(job.get("easy_apply")) else self._normalize_apply_method(job.get("apply_method"))
        if fallback_method not in {"easy_apply", "external_apply"}:
            fallback_method = "unknown"

        try:
            state = await self.browser.page.evaluate(
                """() => {
                    const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.visibility !== "hidden" &&
                            style.display !== "none" &&
                            rect.width > 0 &&
                            rect.height > 0;
                    };
                    const selectors = [
                        ".jobs-apply-button--top-card",
                        "button.jobs-apply-button",
                        "a.jobs-apply-button",
                        "button[aria-label*='Easy Apply']",
                        "button[aria-label*='easy apply']",
                        "button[aria-label*='Apply']",
                        "a[aria-label*='Apply']",
                        "a[href*='offsite-apply']"
                    ];
                    const controls = Array.from(document.querySelectorAll(selectors.join(",")))
                        .filter(visible)
                        .map((el) => ({
                            text: normalize(el.innerText || el.textContent || ""),
                            aria: normalize(el.getAttribute("aria-label") || ""),
                            href: normalize(el.getAttribute("href") || ""),
                            className: normalize(el.className || ""),
                        }));
                    return { controls };
                }"""
            )
        except Exception:
            return self._apply_method_payload(fallback_method, "card_or_existing_data")

        controls = state.get("controls", []) if isinstance(state, dict) else []
        for control in controls:
            combined = self._apply_control_text(control)
            if "easy apply" in combined:
                return self._apply_method_payload("easy_apply", "detail_apply_button")

        for control in controls:
            combined = self._apply_control_text(control)
            href = (control.get("href") or "").strip().lower() if isinstance(control, dict) else ""
            if "apply" not in combined and "offsite-apply" not in href:
                continue
            return self._apply_method_payload("external_apply", "detail_apply_button")

        return self._apply_method_payload(fallback_method, "card_or_existing_data")

    def _apply_control_text(self, control: dict) -> str:
        if not isinstance(control, dict):
            return ""
        return " ".join(
            str(control.get(key, "") or "").strip().lower()
            for key in ("text", "aria", "href", "className")
        )

    def _normalize_apply_method(self, value: str | None) -> str:
        method = re.sub(r"\s+", "_", (value or "").strip().lower().replace("-", "_"))
        if method in {"easy", "easy_apply", "linkedin_easy_apply"}:
            return "easy_apply"
        if method in {"external", "external_apply", "company_site", "company_website"}:
            return "external_apply"
        return "unknown"

    def _apply_method_payload(self, method: str, source: str = "") -> dict:
        normalized = self._normalize_apply_method(method)
        return {
            "easy_apply": normalized == "easy_apply",
            "apply_method": normalized,
            "apply_method_detection_source": source,
        }

    def _reset_human_mode_state(self, enabled: bool) -> None:
        self.human_mode = bool(enabled)
        self._human_jobs_since_break = 0
        self._human_pages_since_break = 0
        self._human_next_job_break_after = random.randint(5, 9)
        self._human_next_page_break_after = random.randint(2, 4)

    async def _human_pause(
        self,
        min_sec: float,
        max_sec: float,
        *,
        long_pause_chance: float = 0.0,
        long_min_sec: float = 5.0,
        long_max_sec: float = 10.0,
        reason: str = "",
        log_long_pause: bool = False,
    ) -> None:
        if not self.human_mode:
            return

        duration = random.uniform(min_sec, max_sec)
        took_long_pause = False
        if random.random() < long_pause_chance:
            duration = random.uniform(long_min_sec, long_max_sec)
            took_long_pause = True

        if took_long_pause and log_long_pause:
            label = f" for {reason}" if reason else ""
            self._report("HUMAN", f"Taking a longer pause of {duration:.1f}s{label}", style="magenta")

        await asyncio.sleep(duration)

    async def _human_take_session_break(self, trigger: str) -> None:
        if not self.human_mode:
            return

        duration = random.uniform(20, 60)
        self._report(
            "HUMAN",
            f"Taking a session break after {trigger} activity: {duration:.1f}s",
            style="magenta",
        )
        await asyncio.sleep(duration)

    async def _human_pause_before_opening_job(self) -> None:
        if not self.human_mode:
            return
        if self._human_jobs_since_break >= self._human_next_job_break_after:
            await self._human_take_session_break("job-opening")
            self._human_jobs_since_break = 0
            self._human_next_job_break_after = random.randint(5, 9)
        await self._human_pause(
            2.0,
            5.0,
            long_pause_chance=0.18,
            long_min_sec=5.0,
            long_max_sec=10.0,
            reason="before opening the next job",
            log_long_pause=True,
        )

    async def _human_pause_before_page_navigation(self) -> None:
        if not self.human_mode:
            return
        if self._human_pages_since_break >= self._human_next_page_break_after:
            await self._human_take_session_break("page-scanning")
            self._human_pages_since_break = 0
            self._human_next_page_break_after = random.randint(2, 4)
        await self._human_pause(
            2.0,
            5.0,
            long_pause_chance=0.12,
            long_min_sec=5.0,
            long_max_sec=10.0,
            reason="before navigating pages",
            log_long_pause=True,
        )

    async def _human_pause_after_page_navigation(self) -> None:
        await self._human_pause(
            2.0,
            5.0,
            long_pause_chance=0.12,
            long_min_sec=5.0,
            long_max_sec=10.0,
            reason="after loading a results page",
            log_long_pause=True,
        )

    async def _human_pause_between_scroll_rounds(self) -> None:
        await self._human_pause(
            2.0,
            4.5,
            long_pause_chance=0.08,
            long_min_sec=5.0,
            long_max_sec=8.0,
            reason="between scroll actions",
            log_long_pause=False,
        )

    async def _human_pause_after_job_navigation(self) -> None:
        await self._human_pause(
            2.0,
            5.0,
            long_pause_chance=0.15,
            long_min_sec=5.0,
            long_max_sec=10.0,
            reason="after opening a job page",
            log_long_pause=True,
        )

    async def _extract_linkedin_job_description(self) -> dict:
        try:
            await self.browser.page.wait_for_selector("main", timeout=8000)
        except Exception:
            pass

        payload = {
            "textSelectors": [
                "[componentkey^='JobDetails_AboutTheJob_'] [data-testid='expandable-text-box']",
                "[data-sdui-component*='aboutTheJob'] [data-testid='expandable-text-box']",
                "[data-testid='expandable-text-box']",
                "[componentkey^='JobDetails_AboutTheJob_']",
                "[data-sdui-component*='aboutTheJob']",
            ],
            "containerSelectors": [
                "[componentkey^='JobDetails_AboutTheJob_']",
                "[data-sdui-component*='aboutTheJob']",
            ],
            "aboutHeadings": [
                "About the job",
                "About this job",
                "Job description",
                "Over de functie",
                "Over deze functie",
                "Functieomschrijving",
            ],
            "expandLabels": [
                "show more",
                "see more",
                "read more",
                "more",
                "meer weergeven",
                "meer lezen",
                "meer",
            ],
            "stopMarkers": [
                "People you can reach out to",
                "Meet the hiring team",
                "Applicants for this job",
                "Applicant seniority level",
                "Employment type",
                "Job function",
                "Industries",
                "About the company",
                "About us",
                "Get job alerts",
                "Similar jobs",
                "See more jobs like this",
                "Recommended for you",
                "Skills",
                "Seniority level",
                "Company size",
                "Followers",
                "Show all",
                "Report this job",
            ],
            "maxScrollRounds": 8,
        }

        extraction = await self.browser.page.evaluate(
            """async (payload) => {
                const result = {
                    text: "",
                    selector_matched: "",
                    source: "",
                    container_found: false,
                    expand_clicked: false,
                    scrolled: false,
                    text_length: 0,
                    notes: [],
                };

                const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== "hidden" &&
                        style.display !== "none" &&
                        rect.width > 0 &&
                        rect.height > 0;
                };
                const textOf = (el) => normalize(el?.innerText || el?.textContent || "");
                const aboutTerms = payload.aboutHeadings.map((term) => normalize(term).toLowerCase());
                const expandTerms = payload.expandLabels.map((term) => normalize(term).toLowerCase());
                const stopTerms = payload.stopMarkers.map((term) => normalize(term));

                const normalizeDescription = (text) => {
                    let output = normalize(text);
                    for (const heading of payload.aboutHeadings) {
                        const escaped = heading.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");
                        output = output.replace(new RegExp("^" + escaped + "\\\\s*", "i"), "");
                    }
                    return normalize(output);
                };

                const trimBodyFallback = (text) => {
                    let output = normalizeDescription(text);
                    let cutIndex = -1;
                    for (const marker of stopTerms) {
                        const index = output.toLowerCase().indexOf(marker.toLowerCase());
                        if (index > 120 && (cutIndex === -1 || index < cutIndex)) {
                            cutIndex = index;
                        }
                    }
                    if (cutIndex > -1) {
                        output = output.slice(0, cutIndex);
                    }
                    return normalize(output);
                };

                const findBySelectors = (selectors) => {
                    for (const selector of selectors) {
                        const nodes = Array.from(document.querySelectorAll(selector)).filter(visible);
                        for (const node of nodes) {
                            const text = normalizeDescription(textOf(node));
                            if (text) {
                                return { element: node, selector };
                            }
                        }
                    }
                    return null;
                };

                const expandHeadingContainer = (heading) => {
                    let current = heading?.parentElement || null;
                    while (current && current !== document.body) {
                        if (!visible(current)) {
                            current = current.parentElement;
                            continue;
                        }
                        if (current.querySelector("[data-testid='expandable-text-box']")) {
                            return current;
                        }
                        const text = textOf(current);
                        if (text.length >= 160) {
                            return current;
                        }
                        current = current.parentElement;
                    }
                    return heading?.parentElement || null;
                };

                const findAboutHeadingContainer = () => {
                    const headings = Array.from(document.querySelectorAll("h1, h2, h3, h4, h5"));
                    for (const heading of headings) {
                        if (!visible(heading)) continue;
                        const headingText = textOf(heading).toLowerCase();
                        if (!headingText) continue;
                        if (!aboutTerms.some((term) => headingText === term || headingText.startsWith(term + " "))) {
                            continue;
                        }
                        const container =
                            heading.closest("[componentkey^='JobDetails_AboutTheJob_'], [data-sdui-component*='aboutTheJob']") ||
                            expandHeadingContainer(heading);
                        if (container && visible(container)) {
                            return {
                                element: container,
                                selector: "heading:" + textOf(heading),
                            };
                        }
                    }
                    return null;
                };

                const findScrollableAncestor = (el) => {
                    let current = el;
                    while (current && current !== document.body) {
                        const style = window.getComputedStyle(current);
                        const overflowY = style.overflowY || "";
                        const canScroll = /(auto|scroll)/i.test(overflowY);
                        if (canScroll && current.scrollHeight > current.clientHeight + 20) {
                            return current;
                        }
                        current = current.parentElement;
                    }
                    return null;
                };

                const scrollWindow = async () => {
                    window.scrollBy(0, Math.max(450, Math.floor(window.innerHeight * 0.8)));
                    result.scrolled = true;
                    await sleep(250);
                };

                const scrollIntoJobArea = async (element) => {
                    if (!element) return;
                    try {
                        element.scrollIntoView({ block: "start", inline: "nearest" });
                        result.scrolled = true;
                        await sleep(250);
                    } catch (error) {
                        result.notes.push("scrollIntoView_failed");
                    }

                    const scroller = findScrollableAncestor(element);
                    if (!scroller) {
                        return;
                    }

                    const maxSteps = 4;
                    for (let step = 0; step < maxSteps; step += 1) {
                        const previousTop = scroller.scrollTop;
                        scroller.scrollTop = Math.min(
                            scroller.scrollHeight,
                            scroller.scrollTop + Math.max(250, Math.floor(scroller.clientHeight * 0.7))
                        );
                        if (scroller.scrollTop !== previousTop) {
                            result.scrolled = true;
                        }
                        await sleep(180);
                    }
                };

                const findExpandButtons = (scope) => {
                    const roots = [];
                    if (scope) {
                        roots.push(scope);
                        if (scope.parentElement) roots.push(scope.parentElement);
                        if (scope.parentElement?.parentElement) roots.push(scope.parentElement.parentElement);
                    }
                    roots.push(document);

                    for (const root of roots) {
                        const buttons = Array.from(
                            root.querySelectorAll("button, a, span[role='button'], div[role='button']")
                        ).filter(visible);
                        const matches = buttons.filter((button) => {
                            const label = normalize(
                                [
                                    textOf(button),
                                    button.getAttribute("aria-label") || "",
                                    button.getAttribute("title") || "",
                                ].join(" ")
                            ).toLowerCase();
                            return expandTerms.some((term) => label.includes(term));
                        });
                        if (matches.length) {
                            return matches;
                        }
                    }
                    return [];
                };

                let match = findBySelectors(payload.textSelectors);
                let containerMatch = match || findBySelectors(payload.containerSelectors) || findAboutHeadingContainer();

                for (let round = 0; round < payload.maxScrollRounds && !containerMatch; round += 1) {
                    await scrollWindow();
                    match = findBySelectors(payload.textSelectors);
                    containerMatch = match || findBySelectors(payload.containerSelectors) || findAboutHeadingContainer();
                }

                if (containerMatch) {
                    result.container_found = true;
                    result.selector_matched = containerMatch.selector;
                    await scrollIntoJobArea(containerMatch.element);
                } else {
                    result.notes.push("description_container_not_found");
                }

                const expandButtons = findExpandButtons(containerMatch?.element || null);
                if (expandButtons.length) {
                    try {
                        expandButtons[0].click();
                        result.expand_clicked = true;
                        await sleep(500);
                    } catch (error) {
                        result.notes.push("expand_click_failed");
                    }
                } else {
                    result.notes.push("expand_button_not_found");
                }

                match = findBySelectors(payload.textSelectors);
                if (match) {
                    result.container_found = true;
                    result.selector_matched = match.selector;
                    result.source = "linkedin_description_container";
                    result.text = normalizeDescription(textOf(match.element));
                } else if (containerMatch?.element) {
                    result.source = "linkedin_about_container";
                    result.text = normalizeDescription(textOf(containerMatch.element));
                }

                if (!result.text) {
                    const bodyText = normalize(document.body?.innerText || "");
                    const lowerBody = bodyText.toLowerCase();
                    let startIndex = -1;
                    let usedMarker = "";
                    for (const marker of payload.aboutHeadings) {
                        const index = lowerBody.indexOf(marker.toLowerCase());
                        if (index !== -1 && (startIndex === -1 || index < startIndex)) {
                            startIndex = index;
                            usedMarker = marker;
                        }
                    }
                    if (startIndex !== -1) {
                        result.source = "body_about_fallback";
                        result.selector_matched = usedMarker ? "body-marker:" + usedMarker : result.selector_matched;
                        result.text = trimBodyFallback(bodyText.slice(startIndex + usedMarker.length));
                    } else {
                        result.notes.push("body_fallback_not_found");
                    }
                }

                result.text = normalizeDescription(result.text);
                result.text_length = result.text.length;
                return result;
            }""",
            payload,
        )

        description = self._clean_extracted_description(extraction.get("text", ""))
        extraction["text"] = description
        extraction["text_length"] = len(description)
        extraction["preview"] = self._description_preview(description, max_chars=280)
        return extraction

    def _clean_extracted_description(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        cleaned = re.sub(r"^(About the job|About this job|Job description)\s*", "", cleaned, flags=re.I)
        return cleaned

    def _evaluate_job(self, query: str, job: dict) -> dict:
        job["url"] = self._canonicalize_linkedin_job_url(job.get("url", ""))
        combined_text = self._combined_job_text(job)
        title = (job.get("title") or "").strip()
        company = (job.get("company") or "").strip()

        workplace_types = self.search_scope.get("workplace_types") or []
        if workplace_types:
            inferred = self.brain._infer_workplace_type(job)
            if inferred and inferred not in workplace_types:
                return {
                    "status": "rejected_excluded",
                    "language": "unknown",
                    "matched_terms": [],
                    "reasons": [
                        f"Workplace type '{inferred}' does not match run scope filters: {', '.join(workplace_types)}"
                    ],
                }

        if self._is_blacklisted_company(company):
            return {
                "status": "rejected_excluded",
                "language": "unknown",
                "matched_terms": [],
                "reasons": ["Company is blacklisted"],
            }

        internship_reason = self._internship_reason(job, preopen=False)
        if internship_reason:
            return {
                "status": "rejected_internship",
                "language": "unknown",
                "matched_terms": [],
                "reasons": [internship_reason],
            }

        location_reason = self._location_scope_reason(job, preopen=False)
        if location_reason:
            return {
                "status": "rejected_outside_search_market",
                "language": "unknown",
                "matched_terms": [],
                "reasons": [location_reason],
            }

        language = self._detect_description_language(job)
        incompatible_language = self._incompatible_language_requirement(job)
        if incompatible_language:
            return {
                "status": "rejected_dutch",
                "language": language,
                "matched_terms": [],
                "reasons": [incompatible_language],
            }
        market_verdict = market_eligibility(job, self.search_scope)
        if not market_verdict["eligible"]:
            return {
                "status": "rejected_market_eligibility",
                "language": language,
                "matched_terms": [],
                "reasons": list(market_verdict["reasons"]),
            }
        employment = infer_employment_metadata(job)
        employment_verdict = evaluate_employment_policy(
            employment.get("employment_types"),
            bool(employment.get("flexible_hours")),
            self.search_scope,
        )
        if not employment_verdict["employment_eligible"]:
            return {
                "status": "rejected_employment_type",
                "language": language,
                "matched_terms": [],
                "reasons": [employment_verdict["employment_adjustment_reason"]],
            }

        qualification_reason = self._mandatory_qualification_reason(job, preopen=False)
        if qualification_reason:
            return {
                "status": "rejected_excluded",
                "language": language,
                "matched_terms": [],
                "reasons": [qualification_reason],
            }

        entry_level = self._passes_entry_level_filter(job)
        if not entry_level["pass"]:
            return {
                "status": "rejected_entry_level",
                "language": language,
                "matched_terms": [],
                "reasons": entry_level["reasons"],
            }

        hard_viability_reason = self._hard_viability_marker_reason(job)
        if hard_viability_reason:
            return {
                "status": "rejected_excluded",
                "language": language,
                "matched_terms": [],
                "reasons": [hard_viability_reason],
            }

        false_positive_reason = self._obvious_false_positive_reason(query, job)
        if false_positive_reason:
            return {
                "status": "rejected_excluded",
                "language": language,
                "matched_terms": [],
                "reasons": [false_positive_reason],
            }

        soft_negative_hits = self._contains_excluded_terms(title, combined_text)
        fallback_hits = self._contains_fallback_terms(title, combined_text)
        internship_review_notes = self._internship_review_notes(job)
        dutch_risk_notes = self._dutch_risk_notes(job)
        relevance = self._passes_query_relevance(query, job)
        reasons = list(relevance["reasons"]) + list(entry_level["reasons"])
        if soft_negative_hits:
            reasons.append(
                f"Soft negative signal kept for AI review: {', '.join(soft_negative_hits[:4])}"
            )
        if fallback_hits:
            reasons.append(
                f"Fallback/income role signal kept for AI review: {', '.join(fallback_hits[:4])}"
            )
        reasons.extend(internship_review_notes)
        reasons.extend(dutch_risk_notes)
        reasons.extend(market_verdict["concerns"])
        return {
            "status": "accepted",
            "language": language,
            "matched_terms": relevance["matched_terms"],
            "reasons": reasons,
        }

    async def _wait_for_search_state_stable(
        self,
        query: str,
        location: str,
        search_url: str,
    ) -> None:
        expected_geo_id = self._search_geo_id(location)
        expected_location = self._location_display_text(location)
        expected_query = (query or "").strip().lower()
        expected_distance = str(self._linkedin_distance_miles())
        stable_rounds = 0
        last_signature = ""

        for attempt in range(12):
            try:
                await self.browser.page.wait_for_selector(
                    ", ".join(self.linkedin.CARD_SELECTORS),
                    timeout=5000,
                )
            except Exception:
                await asyncio.sleep(1)
                continue

            page_state = await self.browser.page.evaluate(
                """() => {
                    const readValue = (selectors) => {
                        for (const selector of selectors) {
                            const element = document.querySelector(selector);
                            if (element && typeof element.value === "string") {
                                return element.value.trim();
                            }
                        }
                        return "";
                    };
                    const cards = [...document.querySelectorAll(
                        ".job-card-container, .jobs-search-results__list-item, li.scaffold-layout__list-item"
                    )]
                        .slice(0, 8)
                        .map((card) => {
                            const title = card.querySelector(
                                "a.job-card-list__title, .job-card-list__title, a.job-card-container__link, a[href*='/jobs/view/']"
                            )?.innerText || "";
                            const location = card.querySelector(
                                ".job-card-container__metadata-item, .artdeco-entity-lockup__caption, .job-card-container__metadata-wrapper li"
                            )?.innerText || "";
                            return `${title.trim()}|${location.trim()}`;
                        })
                        .filter(Boolean);
                    const bodyText = (document.body?.innerText || "");
                    const lowerBody = bodyText.toLowerCase();
                    return {
                        url: window.location.href,
                        titleInput: readValue([
                            "input[aria-label*='Search by title']",
                            "input[placeholder='Search by title, skill, or company']",
                            "input[placeholder='Title, skill, or company']",
                            "input[placeholder='Title, skill or Company']",
                        ]),
                        locationInput: readValue([
                            "input[aria-label*='City, state, or zip code']",
                            "input[placeholder='City, state, or zip code']",
                        ]),
                        cards,
                        noResults: lowerBody.includes("no matching jobs found"),
                        loadingError: lowerBody.includes("things arent loading")
                            || lowerBody.includes("things aren't loading")
                            || lowerBody.includes("issue is usually resolved by reloading the page"),
                    };
                }"""
            )

            current_url = page_state.get("url", "")
            location_input = (page_state.get("locationInput") or "").strip().lower()
            title_input = (page_state.get("titleInput") or "").strip().lower()
            card_signature = "||".join(page_state.get("cards") or [])
            url_location_ready = (
                f"geoId={expected_geo_id}" in current_url
                if expected_geo_id
                else "location=" in current_url
            )
            expected_exp_codes = self._linkedin_experience_level_codes()
            if expected_exp_codes:
                expected_exp_param = urllib.parse.quote(",".join(expected_exp_codes))
                expected_exp_param_alt = ",".join(expected_exp_codes)
                experience_in_url = (f"f_E={expected_exp_param}" in current_url or f"f_E={expected_exp_param_alt}" in current_url)
            else:
                experience_in_url = "f_E=" not in current_url

            url_ready = (
                url_location_ready
                and f"distance={expected_distance}" in current_url
                and experience_in_url
            )
            inputs_ready = expected_query in title_input and expected_location in location_input
            no_results = bool(page_state.get("noResults"))
            loading_error = bool(page_state.get("loadingError"))

            if loading_error:
                self._report(
                    "PAGE",
                    "LinkedIn search page reported a transient loading error; reloading once before continuing.",
                    style="yellow",
                )
                await self.browser.page.reload(wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                continue

            if no_results:
                self._report(
                    "PAGE",
                    "LinkedIn search page reports no matching jobs for this page/filter state.",
                    style="yellow",
                )
                return

            if url_ready and inputs_ready and card_signature:
                if card_signature == last_signature:
                    stable_rounds += 1
                else:
                    stable_rounds = 1
                    last_signature = card_signature
                if stable_rounds >= 2:
                    self._report(
                        "STATE",
                        (
                            f"Search state stable | "
                            f"url={self._safe_console_text(current_url)} "
                            f"location={self._safe_console_text(page_state.get('locationInput', ''))}"
                        ),
                        style="bright_cyan",
                    )
                    return

            await asyncio.sleep(1)

        self._report(
            "STATE",
            f"Search state timed out; continuing with latest visible results: {self._safe_console_text(search_url)}",
            style="yellow",
        )

    def _build_search_url(self, query: str, location: str, start: int = 0) -> str:
        params = {
            "keywords": query,
            "distance": str(self._linkedin_distance_miles()),
            "origin": self.DEFAULT_SEARCH_ORIGIN,
            "refresh": "true",
        }
        exp_codes = self._linkedin_experience_level_codes()
        if exp_codes:
            params["f_E"] = ",".join(exp_codes)

        employment_codes = linkedin_employment_codes(self.search_scope)
        if employment_codes:
            params["f_JT"] = ",".join(employment_codes)

        wt_codes = linkedin_workplace_type_codes(self.search_scope)
        if wt_codes:
            params["f_WT"] = ",".join(wt_codes)

        location_key = self._normalize_text(location)
        geo_id = self.LINKEDIN_GEO_IDS.get(location_key)
        if geo_id:
            params["geoId"] = geo_id
        else:
            params["location"] = location
        if start > 0:
            params["start"] = str(start)
        return f"{LinkedInScraper.JOBS_URL}?{urllib.parse.urlencode(params)}"

    def _linkedin_experience_level_codes(self) -> list[str]:
        levels = self.search_scope.get("experience_levels")
        if levels is None:
            return list(self.DEFAULT_EXPERIENCE_LEVELS)
        codes = []
        mapping = {
            "internship": "1",
            "entry": "2",
            "entry_level": "2",
            "associate": "3",
            "mid-senior": "4",
            "mid_senior": "4",
            "director": "5",
            "executive": "6",
        }
        for lvl in levels:
            code = mapping.get(str(lvl).lower())
            if code and code not in codes:
                codes.append(code)
        return codes

    def _linkedin_distance_miles(self) -> int:
        scope_distance = self.search_scope.get("radius_miles")
        if scope_distance is not None:
            try:
                return max(0, int(scope_distance))
            except (TypeError, ValueError):
                pass
        linkedin_prefs = self.preferences.get("job_boards", {}).get("linkedin", {})
        raw_distance = linkedin_prefs.get("distance_miles", self.DEFAULT_DISTANCE_MILES)
        try:
            return max(0, int(raw_distance))
        except (TypeError, ValueError):
            return self.DEFAULT_DISTANCE_MILES

    def _search_geo_id(self, location: str) -> str:
        return self.LINKEDIN_GEO_IDS.get(self._normalize_text(location), "")

    def _location_display_text(self, location: str) -> str:
        normalized = self._normalize_text(location)
        if normalized == "amstelveen":
            return "amstelveen, north holland, netherlands"
        if normalized == "amsterdam":
            return "amsterdam, north holland, netherlands"
        return normalized

    def _write_output(self, output: dict) -> None:
        self.output_path.write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        new_count = sum(len(items) for items in output.get("new_recommendations", {}).values())
        cached_count = sum(
            len(items) for items in output.get("cached_previous_recommendations", {}).values()
        )
        self._report(
            "FILE",
            f"Wrote {new_count} new and {cached_count} cached valid recommendations to {self.output_path}",
            style="green",
        )

    def _write_rejected_debug_output(self, output: dict) -> None:
        self.rejected_debug_path.write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._report(
            "FILE",
            f"Wrote {len(output.get('rejected_jobs', []))} rejected jobs to {self.rejected_debug_path}",
            style="green",
        )

    def _write_ai_debug_output(self, output: dict) -> None:
        self.ai_debug_path.write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._report(
            "FILE",
            f"Wrote {len(output.get('processed_jobs', []))} AI debug entries to {self.ai_debug_path}",
            style="green",
        )

    def _write_run_history_entry(self, output: dict) -> None:
        stats = output.get("stats", {})
        self.run_history.append_run(
            {
                "timestamp": output.get("generated_at", ""),
                "started_at": output.get("started_at", ""),
                "completed_at": output.get("completed_at", output.get("generated_at", "")),
                "query": output.get("query", ""),
                "location": output.get("location", ""),
                "total_scanned": stats.get("job_cards_collected", 0),
                "new_recommendations": stats.get("new_recommendations", 0),
                "cached_previous_recommendations": stats.get(
                    "cached_previous_recommendations", 0
                ),
                "rejected_or_below_threshold": stats.get(
                    "rejected_or_below_threshold", 0
                ),
                "results_layout_types": stats.get("results_layout_types", []),
                "search_scope": dict(output.get("search_scope") or self.search_scope),
                "ai_queries": output.get("query_plan", {}).get("ai_queries", []) if isinstance(output.get("query_plan"), dict) else [],
            }
        )
        self._report(
            "FILE",
            f"Appended scout run history to {self.run_history_path}",
            style="green",
        )

    def _resolve_perfect_job_profile_path(self) -> Path:
        for candidate in self.PERFECT_JOB_PROFILE_CANDIDATES:
            if candidate.exists():
                return candidate
        raise RuntimeError(
            "Could not find the Perfect Suitable Job profile file. "
            "Expected one of: "
            + ", ".join(str(path) for path in self.PERFECT_JOB_PROFILE_CANDIDATES)
        )

    def _load_perfect_job_profile_text(self) -> str:
        text = self.perfect_job_profile_path.read_text(encoding="utf-8", errors="ignore")
        normalized = re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()
        if not normalized:
            raise RuntimeError(
                f"The Perfect Suitable Job profile is empty: {self.perfect_job_profile_path}"
            )
        return normalized

    def _load_score_cache(self) -> dict[str, dict]:
        if not self.score_cache_path.exists():
            return {}

        try:
            raw = json.loads(self.score_cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if isinstance(raw, dict):
            jobs = raw.get("jobs", [])
        elif isinstance(raw, list):
            jobs = raw
        else:
            jobs = []

        cache = {}
        for entry in jobs:
            if not isinstance(entry, dict):
                continue
            key = (entry.get("cache_key") or "").strip()
            if not key:
                key = self._cache_key_from_parts(entry.get("job_id", ""), entry.get("url", ""))
            if key:
                cache[key] = entry
        return cache

    def _load_historical_analyzed_identity_sources(self) -> dict[str, str]:
        sources: dict[str, str] = {}
        candidate_files = [
            (self.ai_debug_path, "scout_ai_debug"),
            (self.rejected_debug_path, "rejected_jobs_debug"),
            (self.output_path, "single_query_output"),
            (Path("high_success_probability_jobs_multi.json"), "multi_query_output"),
            (Path("review_latest_jobs.json"), "review_latest"),
        ]
        for path, label in candidate_files:
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for job in self._iter_historical_job_records(payload):
                if not self._historical_record_counts_as_analyzed(job):
                    continue
                for key in self._same_run_job_identity_keys(job):
                    sources.setdefault(key, label)
        return sources

    def _historical_record_counts_as_analyzed(self, job: dict) -> bool:
        status_values = [
            job.get("analysis_status", ""),
            job.get("output_status", ""),
            job.get("ai_status", ""),
            job.get("status", ""),
            job.get("decision", ""),
        ]
        normalized_statuses = {
            re.sub(r"\s+", "_", str(value or "").strip().lower())
            for value in status_values
            if str(value or "").strip()
        }
        if "ai_error" in normalized_statuses:
            return False

        combined_reasoning = " ".join(
            [
                str(job.get("analysis_reason", "") or ""),
                str(job.get("interview_probability_reason", "") or ""),
                str(job.get("short_ai_reasoning", "") or ""),
            ]
        ).lower()
        if "ai scoring failed:" in combined_reasoning:
            return False
        return True

    def _iter_historical_job_records(self, payload) -> list[dict]:
        records: list[dict] = []
        if not isinstance(payload, dict):
            return records

        if isinstance(payload.get("processed_jobs"), list):
            records.extend(job for job in payload.get("processed_jobs", []) if isinstance(job, dict))
        if isinstance(payload.get("rejected_jobs"), list):
            records.extend(job for job in payload.get("rejected_jobs", []) if isinstance(job, dict))
        if isinstance(payload.get("go_jobs"), list):
            records.extend(job for job in payload.get("go_jobs", []) if isinstance(job, dict))
        if isinstance(payload.get("consider_jobs"), list):
            records.extend(job for job in payload.get("consider_jobs", []) if isinstance(job, dict))

        for bucket_name in ("new_recommendations", "cached_previous_recommendations"):
            grouped = payload.get(bucket_name, {})
            if not isinstance(grouped, dict):
                continue
            for jobs in grouped.values():
                if isinstance(jobs, list):
                    records.extend(job for job in jobs if isinstance(job, dict))

        trailing = payload.get("rejected_or_below_threshold", [])
        if isinstance(trailing, list):
            records.extend(job for job in trailing if isinstance(job, dict))

        return records

    def _write_score_cache(self) -> None:
        payload = {
            "updated_at": datetime.now().astimezone().isoformat(),
            "jobs": sorted(
                self.score_cache.values(),
                key=lambda item: (
                    item.get("last_recommended_at") or "",
                    item.get("scored_at") or "",
                    item.get("title") or "",
                ),
                reverse=True,
            ),
        }
        self.score_cache_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._report(
            "FILE",
            f"Wrote {len(payload['jobs'])} cached AI scoring records to {self.score_cache_path}",
            style="green",
        )

    def _score_surviving_job(self, query: str, job: dict, verdict: dict) -> dict:
        now = datetime.now().astimezone().isoformat()
        found_at = (job.get("_found_at") or now).strip() if isinstance(job.get("_found_at"), str) else now
        url = self._canonicalize_linkedin_job_url(job.get("url", ""))
        job_id = self._linkedin_job_id(url)
        description = (job.get("description") or "").strip()
        description_fingerprint = self._fingerprint_text(description)
        cache_key = self._cache_key_from_parts(job_id, url)
        cached_entry = self.score_cache.get(cache_key)
        cache_scope_matches = bool(
            self.search_scope.get("legacy_mode")
            or (
                cached_entry
                and cached_entry.get("search_scope_fingerprint")
                == self.search_scope_fingerprint
            )
        )
        cache_status = "new"
        cache_dirty = False
        second_stage_used = False

        if (
            cached_entry
            and cached_entry.get("description_fingerprint") == description_fingerprint
            and cached_entry.get("perfect_job_profile_fingerprint") == self.perfect_job_profile_fingerprint
            and cached_entry.get("ai_scoring_version") == self.AI_SCORING_VERSION
            and cached_entry.get("ai_model") in self.brain.scoring_model_labels_for_cache()
            and cache_scope_matches
        ):
            cache_status = "reused_unchanged"
            base_score = int(
                cached_entry.get(
                    "base_interview_probability_score",
                    cached_entry.get("interview_probability_score", 0),
                )
                or 0
            )
            ai_payload = {
                "interview_probability_score": base_score,
                "base_interview_probability_score": base_score,
                "reason": cached_entry.get("short_ai_reasoning", ""),
                "model": cached_entry.get("ai_model", self.brain.scoring_model_label),
                "used_cv": bool(cached_entry.get("used_cv_second_stage")),
                "career_lane": cached_entry.get("career_lane", ""),
                "employment_types": cached_entry.get("employment_types", []),
                "weekly_hours": cached_entry.get("weekly_hours", ""),
                "flexible_hours": bool(cached_entry.get("flexible_hours")),
                "sponsorship_status": cached_entry.get("sponsorship_status", ""),
                "relocation_support": cached_entry.get("relocation_support", "unknown"),
                "housing_support": cached_entry.get("housing_support", "unknown"),
                "health_insurance": cached_entry.get("health_insurance", "unknown"),
                "annual_flight_support": cached_entry.get("annual_flight_support", "unknown"),
                "compensation_text": cached_entry.get("compensation_text", ""),
                "contract_type": cached_entry.get("contract_type", "unknown"),
                "market_concerns": cached_entry.get("market_concerns", []),
            }
            second_stage_used = bool(cached_entry.get("used_cv_second_stage"))
            cached_entry["last_seen_at"] = now
            cached_entry["title"] = job.get("title", "")
            cached_entry["company"] = job.get("company", "")
            cached_entry["location"] = job.get("location", "")
            cached_entry["url"] = url
            cached_entry["last_query"] = query
            cached_entry["search_queries"] = self._append_unique_query(
                cached_entry.get("search_queries", []),
                query,
            )
            cache_dirty = True
            self._report(
                "REUSE",
                f"Reused cached AI score for {self._safe_console_text(job.get('title', 'Untitled job'))}",
                style="magenta",
            )
        else:
            try:
                ai_payload = self.brain.score_interview_probability(
                    job=job,
                    query=query,
                    ideal_job_profile=self.perfect_job_profile_text,
                    include_cv=False,
                )
                if ai_payload["interview_probability_score"] > self.AI_THRESHOLD:
                    ai_payload = self.brain.score_interview_probability(
                        job=job,
                        query=query,
                        ideal_job_profile=self.perfect_job_profile_text,
                        include_cv=True,
                        prior_assessment=ai_payload,
                    )
                    second_stage_used = True
                cache_status = "rescored_changed" if cached_entry else "new"
            except Exception as exc:
                reason = f"AI scoring could not complete for the current job: {str(exc).strip()}"
                self._report("AI", reason, style="red")
                return {
                    "status": "ai_error",
                    "job_id": job_id,
                    "interview_probability_score": 0,
                    "reason": reason,
                    "model": self.brain.scoring_model_label,
                    "cache_status": cache_status,
                    "second_stage_used": False,
                    "cache_dirty": False,
                    "found_at": found_at,
                    "first_seen_at": (cached_entry or {}).get("first_seen_at", now),
                    "last_seen_at": (cached_entry or {}).get("last_seen_at", now),
                    "debug_record": self._build_ai_debug_record(
                        job=job,
                        verdict=verdict,
                        query=query,
                        description_fingerprint=description_fingerprint,
                        cache_status=cache_status,
                        ai_payload={
                            "interview_probability_score": 0,
                            "reason": reason,
                            "model": self.brain.scoring_model_label,
                            "used_cv": False,
                        },
                        output_status="ai_error",
                        duplicate_suppressed=False,
                        previous_recommended_at=(cached_entry or {}).get("last_recommended_at", ""),
                        found_at=found_at,
                        first_seen_at=(cached_entry or {}).get("first_seen_at", now),
                        last_seen_at=(cached_entry or {}).get("last_seen_at", now),
                    ),
                }

            base_score = int(ai_payload.get("interview_probability_score", 0) or 0)
            ai_payload["base_interview_probability_score"] = base_score
            scope_metadata = enrich_job_scope_metadata(
                job,
                self.search_scope,
                ai_result=ai_payload,
                user_country=self.profile.get("personal", {}).get("location", {}).get("country", ""),
            )
            adjusted_score = max(
                0,
                min(
                    100,
                    base_score + int(scope_metadata.get("employment_score_adjustment", 0) or 0),
                ),
            )
            capped_score, cap_reason = cap_score_for_scope(
                adjusted_score,
                scope_metadata,
            )
            ai_payload["interview_probability_score"] = capped_score
            if cap_reason:
                ai_payload["reason"] = " ".join(
                    value
                    for value in (ai_payload.get("reason", ""), cap_reason)
                    if value
                ).strip()
            ai_payload.update(scope_metadata)
            self.score_cache[cache_key] = {
                "cache_key": cache_key,
                "job_id": job_id,
                "url": url,
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "easy_apply": bool(job.get("easy_apply")),
                "apply_method": job.get("apply_method", "unknown"),
                "apply_method_detection_source": job.get("apply_method_detection_source", ""),
                "base_interview_probability_score": base_score,
                "interview_probability_score": ai_payload["interview_probability_score"],
                "short_ai_reasoning": ai_payload["reason"],
                "scored_at": now,
                "timestamp": now,
                "first_seen_at": (cached_entry or {}).get("first_seen_at", now),
                "last_seen_at": now,
                "last_query": query,
                "search_queries": self._append_unique_query(
                    (cached_entry or {}).get("search_queries", []),
                    query,
                ),
                "description_fingerprint": description_fingerprint,
                "perfect_job_profile_fingerprint": self.perfect_job_profile_fingerprint,
                "ai_scoring_version": self.AI_SCORING_VERSION,
                "ai_model": ai_payload.get("model", self.brain.scoring_model_label),
                "used_cv_second_stage": second_stage_used,
                "last_recommended_at": (cached_entry or {}).get("last_recommended_at", ""),
                "search_scope_fingerprint": self.search_scope_fingerprint,
                "search_scope": dict(self.search_scope),
                "career_lane": ai_payload.get("career_lane", ""),
                "employment_types": ai_payload.get("employment_types", []),
                "weekly_hours": ai_payload.get("weekly_hours", ""),
                "flexible_hours": bool(ai_payload.get("flexible_hours")),
                "employment_match": ai_payload.get("employment_match", "unknown"),
                "employment_eligible": bool(ai_payload.get("employment_eligible", True)),
                "employment_score_adjustment": int(
                    ai_payload.get("employment_score_adjustment", 0) or 0
                ),
                "employment_adjustment_reason": ai_payload.get(
                    "employment_adjustment_reason",
                    "",
                ),
                "sponsorship_status": ai_payload.get("sponsorship_status", ""),
                "relocation_support": ai_payload.get("relocation_support", "unknown"),
                "housing_support": ai_payload.get("housing_support", "unknown"),
                "health_insurance": ai_payload.get("health_insurance", "unknown"),
                "annual_flight_support": ai_payload.get("annual_flight_support", "unknown"),
                "compensation_text": ai_payload.get("compensation_text", ""),
                "contract_type": ai_payload.get("contract_type", "unknown"),
                "market_concerns": ai_payload.get("market_concerns", []),
            }
            cached_entry = self.score_cache[cache_key]
            cache_dirty = True
            self._report(
                "AI",
                (
                    f"AI scored {self._safe_console_text(job.get('title', 'Untitled job'))} "
                    f"-> {ai_payload['interview_probability_score']}"
                ),
                style="green" if int(ai_payload["interview_probability_score"] or 0) >= self.AI_STRONG_MATCH_THRESHOLD else "yellow",
            )

        if cache_status == "reused_unchanged":
            base_score = int(
                (cached_entry or {}).get(
                    "base_interview_probability_score",
                    ai_payload.get("interview_probability_score", 0),
                )
                or 0
            )
            ai_payload["interview_probability_score"] = base_score
            ai_payload["base_interview_probability_score"] = base_score
            scope_metadata = enrich_job_scope_metadata(
                job,
                self.search_scope,
                ai_result=ai_payload,
                user_country=self.profile.get("personal", {}).get("location", {}).get("country", ""),
            )
            adjusted_score = max(
                0,
                min(
                    100,
                    base_score + int(scope_metadata.get("employment_score_adjustment", 0) or 0),
                ),
            )
            capped_score, cap_reason = cap_score_for_scope(
                adjusted_score,
                scope_metadata,
            )
            ai_payload["interview_probability_score"] = capped_score
            if cap_reason and cap_reason not in ai_payload.get("reason", ""):
                ai_payload["reason"] = " ".join(
                    value
                    for value in (ai_payload.get("reason", ""), cap_reason)
                    if value
                ).strip()
            ai_payload.update(scope_metadata)
            cached_entry.update(
                {
                    "base_interview_probability_score": base_score,
                    "interview_probability_score": capped_score,
                    "short_ai_reasoning": ai_payload.get("reason", ""),
                    "career_lane": ai_payload.get("career_lane", ""),
                    "employment_types": ai_payload.get("employment_types", []),
                    "weekly_hours": ai_payload.get("weekly_hours", ""),
                    "flexible_hours": bool(ai_payload.get("flexible_hours")),
                    "employment_match": ai_payload.get("employment_match", "unknown"),
                    "employment_eligible": bool(ai_payload.get("employment_eligible", True)),
                    "employment_score_adjustment": int(
                        ai_payload.get("employment_score_adjustment", 0) or 0
                    ),
                    "employment_adjustment_reason": ai_payload.get(
                        "employment_adjustment_reason",
                        "",
                    ),
                    "sponsorship_status": ai_payload.get("sponsorship_status", ""),
                    "relocation_support": ai_payload.get("relocation_support", "unknown"),
                    "housing_support": ai_payload.get("housing_support", "unknown"),
                    "health_insurance": ai_payload.get("health_insurance", "unknown"),
                    "annual_flight_support": ai_payload.get("annual_flight_support", "unknown"),
                    "compensation_text": ai_payload.get("compensation_text", ""),
                    "contract_type": ai_payload.get("contract_type", "unknown"),
                    "market_concerns": ai_payload.get("market_concerns", []),
                }
            )
            cache_dirty = True

        employment_eligible = bool(ai_payload.get("employment_eligible", True))
        market_eligible = bool(ai_payload.get("market_eligible", True))
        passed_threshold = (
            employment_eligible
            and market_eligible
            and ai_payload["interview_probability_score"] >= self.AI_THRESHOLD
        )
        match_tier = self._match_tier(ai_payload["interview_probability_score"])
        previous_recommended_at = (cached_entry or {}).get("last_recommended_at", "")
        duplicate_suppressed = bool(
            cache_status == "reused_unchanged"
            and passed_threshold
            and previous_recommended_at
        )

        output_status = (
            "below_threshold"
            if employment_eligible and market_eligible
            else "rejected_market_eligibility"
            if employment_eligible
            else "rejected_employment_type"
        )
        if passed_threshold and duplicate_suppressed:
            output_status = "duplicate_suppressed"
        elif passed_threshold:
            output_status = "accepted"

        if passed_threshold and not duplicate_suppressed:
            cached_entry["last_recommended_at"] = now
            cache_dirty = True

        # Cover letters are no longer generated during the background sweep.
        # They are now generated on-demand via the dashboard to save tokens.

        ai_result = {
            "status": output_status,
            "job_id": job_id,
            "interview_probability_score": ai_payload["interview_probability_score"],
            "reason": ai_payload["reason"],
            "match_tier": match_tier,
            "model": ai_payload.get("model", self.brain.scoring_model_label),
            "cache_status": cache_status,
            "second_stage_used": second_stage_used,
            "cache_dirty": cache_dirty,
            "found_at": found_at,
            "first_seen_at": (cached_entry or {}).get("first_seen_at", now),
            "last_seen_at": (cached_entry or {}).get("last_seen_at", now),
            "career_lane": ai_payload.get("career_lane", ""),
            "search_market": ai_payload.get("search_market", ""),
            "country": ai_payload.get("country", ""),
            "employment_types": ai_payload.get("employment_types", []),
            "weekly_hours": ai_payload.get("weekly_hours", ""),
            "flexible_hours": bool(ai_payload.get("flexible_hours")),
            "employment_match": ai_payload.get("employment_match", "unknown"),
            "employment_eligible": employment_eligible,
            "employment_score_adjustment": int(
                ai_payload.get("employment_score_adjustment", 0) or 0
            ),
            "employment_adjustment_reason": ai_payload.get(
                "employment_adjustment_reason",
                "",
            ),
            "sponsorship_status": ai_payload.get("sponsorship_status", ""),
            "relocation_required": bool(ai_payload.get("relocation_required")),
            "relocation_support": ai_payload.get("relocation_support", "unknown"),
            "housing_support": ai_payload.get("housing_support", "unknown"),
            "health_insurance": ai_payload.get("health_insurance", "unknown"),
            "annual_flight_support": ai_payload.get("annual_flight_support", "unknown"),
            "compensation_text": ai_payload.get("compensation_text", ""),
            "contract_type": ai_payload.get("contract_type", "unknown"),
            "market_eligible": market_eligible,
            "market_rejection_reasons": ai_payload.get("market_rejection_reasons", []),
            "market_concerns": ai_payload.get("market_concerns", []),
            "cover_letter": ai_payload.get("cover_letter", ""),
            "debug_record": self._build_ai_debug_record(
                job=job,
                verdict=verdict,
                query=query,
                description_fingerprint=description_fingerprint,
                cache_status=cache_status,
                ai_payload=ai_payload,
                output_status=output_status,
                duplicate_suppressed=duplicate_suppressed,
                previous_recommended_at=previous_recommended_at,
                found_at=found_at,
                first_seen_at=(cached_entry or {}).get("first_seen_at", now),
                last_seen_at=(cached_entry or {}).get("last_seen_at", now),
            ),
        }
        self._maybe_record_ai_payload_audit(
            query=query,
            job=job,
            ai_result=ai_result,
            cache_status=cache_status,
        )

        return ai_result

    def _build_ai_debug_record(
        self,
        job: dict,
        verdict: dict,
        query: str,
        description_fingerprint: str,
        cache_status: str,
        ai_payload: dict,
        output_status: str,
        duplicate_suppressed: bool,
        previous_recommended_at: str,
        found_at: str = "",
        first_seen_at: str = "",
        last_seen_at: str = "",
    ) -> dict:
        return {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": self._canonicalize_linkedin_job_url(job.get("url", "")),
            "job_id": self._linkedin_job_id(job.get("url", "")),
            "found_at": found_at or job.get("_found_at", ""),
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
            "query": query,
            "non_ai_language": verdict.get("language", ""),
            "non_ai_matched_query_terms": verdict.get("matched_terms", []),
            "non_ai_filter_notes": verdict.get("reasons", []),
            "description_fingerprint": description_fingerprint,
            "description_length": len((job.get("description") or "").strip()),
            "description_preview": self._description_preview(job.get("description", ""), max_chars=260),
            "easy_apply": bool(job.get("easy_apply")),
            "apply_method": job.get("apply_method", "unknown"),
            "apply_method_detection_source": job.get("apply_method_detection_source", ""),
            "cache_status": cache_status,
            "interview_probability_score": ai_payload.get("interview_probability_score", 0),
            "base_interview_probability_score": ai_payload.get(
                "base_interview_probability_score",
                ai_payload.get("interview_probability_score", 0),
            ),
            "short_ai_reasoning": ai_payload.get("reason", ""),
            "ai_model": ai_payload.get("model", self.brain.scoring_model_label),
            "ai_scoring_version": self.AI_SCORING_VERSION,
            "used_cv_second_stage": bool(ai_payload.get("used_cv")),
            "ai_match_tier": self._match_tier(ai_payload.get("interview_probability_score", 0)),
            "passed_ai_threshold": ai_payload.get("interview_probability_score", 0) >= self.AI_THRESHOLD,
            "output_status": output_status,
            "duplicate_suppressed": duplicate_suppressed,
            "previously_recommended_at": previous_recommended_at,
            "employment_match": ai_payload.get("employment_match", "unknown"),
            "employment_eligible": bool(ai_payload.get("employment_eligible", True)),
            "employment_score_adjustment": int(
                ai_payload.get("employment_score_adjustment", 0) or 0
            ),
            "employment_adjustment_reason": ai_payload.get(
                "employment_adjustment_reason",
                "",
            ),
            "search_market": ai_payload.get("search_market", ""),
            "sponsorship_status": ai_payload.get("sponsorship_status", ""),
            "relocation_support": ai_payload.get("relocation_support", "unknown"),
            "housing_support": ai_payload.get("housing_support", "unknown"),
            "health_insurance": ai_payload.get("health_insurance", "unknown"),
            "annual_flight_support": ai_payload.get("annual_flight_support", "unknown"),
            "compensation_text": ai_payload.get("compensation_text", ""),
            "contract_type": ai_payload.get("contract_type", "unknown"),
            "market_eligible": bool(ai_payload.get("market_eligible", True)),
            "market_rejection_reasons": ai_payload.get("market_rejection_reasons", []),
            "market_concerns": ai_payload.get("market_concerns", []),
        }

    def _build_ai_output_job_record(self, job: dict, verdict: dict, ai_result: dict) -> dict:
        output_status = ai_result.get("status", "")
        record = {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": self._canonicalize_linkedin_job_url(job.get("url", "")),
            "job_id": ai_result.get("job_id", self._linkedin_job_id(job.get("url", ""))),
            "found_at": ai_result.get("found_at", job.get("_found_at", "")),
            "first_seen_at": ai_result.get("first_seen_at", ""),
            "last_seen_at": ai_result.get("last_seen_at", ""),
            "language": verdict.get("language", ""),
            "matched_query_terms": verdict.get("matched_terms", []),
            "filter_notes": verdict.get("reasons", []),
            "easy_apply": bool(job.get("easy_apply")),
            "apply_method": job.get("apply_method", "unknown"),
            "apply_method_detection_source": job.get("apply_method_detection_source", ""),
            "interview_probability_score": ai_result.get("interview_probability_score", 0),
            "interview_probability_reason": ai_result.get("reason", ""),
            "ai_match_tier": ai_result.get("match_tier", "weak_match"),
            "ai_cache_status": ai_result.get("cache_status", ""),
            "ai_model": ai_result.get("model", self.brain.scoring_model_label),
            "ai_used_cv_second_stage": bool(ai_result.get("second_stage_used")),
            "output_status": output_status,
            "ai_status": output_status,
            "search_scope": dict(self.search_scope),
            "career_lane": ai_result.get("career_lane", ""),
            "search_market": ai_result.get("search_market", ""),
            "country": ai_result.get("country", ""),
            "employment_types": ai_result.get("employment_types", []),
            "weekly_hours": ai_result.get("weekly_hours", ""),
            "flexible_hours": bool(ai_result.get("flexible_hours")),
            "employment_match": ai_result.get("employment_match", "unknown"),
            "employment_eligible": bool(ai_result.get("employment_eligible", True)),
            "employment_score_adjustment": int(
                ai_result.get("employment_score_adjustment", 0) or 0
            ),
            "employment_adjustment_reason": ai_result.get(
                "employment_adjustment_reason",
                "",
            ),
            "sponsorship_status": ai_result.get("sponsorship_status", ""),
            "relocation_required": bool(ai_result.get("relocation_required")),
            "relocation_support": ai_result.get("relocation_support", "unknown"),
            "housing_support": ai_result.get("housing_support", "unknown"),
            "health_insurance": ai_result.get("health_insurance", "unknown"),
            "annual_flight_support": ai_result.get("annual_flight_support", "unknown"),
            "compensation_text": ai_result.get("compensation_text", ""),
            "contract_type": ai_result.get("contract_type", "unknown"),
            "market_eligible": bool(ai_result.get("market_eligible", True)),
            "market_rejection_reasons": ai_result.get("market_rejection_reasons", []),
            "market_concerns": ai_result.get("market_concerns", []),
            "cover_letter": ai_result.get("cover_letter", ""),
        }
        tracking_entry = self.job_tracking.get(
            job_id=record.get("job_id", ""),
            url=record.get("url", ""),
        )
        tracking_status = tracking_entry.get("tracking_status", "")
        if tracking_status:
            record["tracking_status"] = tracking_status
            record["tracking_updated_at"] = tracking_entry.get("tracking_updated_at", "")
        return record

    def _group_recommendations_by_tier(self, jobs: list[dict]) -> dict:
        grouped = {
            "strong_match": [],
            "possible_match": [],
        }
        for job in jobs:
            tier = job.get("ai_match_tier")
            if tier == "strong_match":
                grouped["strong_match"].append(job)
            elif tier == "possible_match":
                grouped["possible_match"].append(job)
        return grouped

    def _append_unique_query(self, queries: list, query: str) -> list[str]:
        cleaned = []
        seen = set()
        for value in list(queries or []) + [query]:
            normalized = re.sub(r"\s+", " ", (value or "").strip())
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(normalized)
        return cleaned

    def _cache_key_from_parts(self, job_id: str, url: str) -> str:
        if job_id:
            return f"linkedin_job_id:{job_id}"
        canonical_url = self._canonicalize_linkedin_job_url(url)
        if canonical_url:
            return f"url:{canonical_url}"
        return ""

    def _linkedin_job_id(self, url: str) -> str:
        normalized_url = self._canonicalize_linkedin_job_url(url)
        match = re.search(r"/jobs/view/(\d+)/?$", normalized_url)
        return match.group(1) if match else ""

    def _is_globally_analyzed(self, job: dict) -> tuple[bool, str]:
        identity_keys = self._same_run_job_identity_keys(job)
        if not identity_keys:
            return False, ""

        collected_entry = self.collected_jobs.get_by_identity_keys(identity_keys)
        if collected_entry and (
            (collected_entry.get("analyzed_at") or "").strip()
            or (collected_entry.get("analysis_status") or "").strip()
        ):
            return True, "collected_jobs_store"

        cache_key = self._cache_key_from_parts(
            (job.get("job_id") or self._linkedin_job_id(job.get("url", ""))).strip(),
            job.get("url", ""),
        )
        if cache_key and cache_key in self.score_cache:
            return True, "score_cache"

        for key in identity_keys:
            if key in self._historical_analyzed_identity_sources:
                return True, self._historical_analyzed_identity_sources.get(key, "historical_outputs")

        return False, ""

    def _same_run_job_identity_keys(self, job: dict) -> list[str]:
        keys = []
        seen = set()

        job_id = (job.get("job_id") or self._linkedin_job_id(job.get("url", ""))).strip()
        canonical_url = self._canonicalize_linkedin_job_url(job.get("url", ""))
        title = self._normalize_text(job.get("title", ""))
        company = self._normalize_text(job.get("company", ""))

        candidates = [
            f"linkedin_job_id:{job_id}" if job_id else "",
            f"url:{canonical_url}" if canonical_url else "",
            f"title_company:{title}::{company}" if title and company else "",
        ]
        for key in candidates:
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    def _find_same_run_job_entry(
        self,
        registry: dict[str, dict] | None,
        job: dict,
    ) -> dict | None:
        if not registry:
            return None
        for key in self._same_run_job_identity_keys(job):
            entry = registry.get(key)
            if entry:
                return entry
        return None

    def _store_same_run_job_entry(
        self,
        registry: dict[str, dict] | None,
        job: dict,
        query: str,
    ) -> None:
        if registry is None:
            return

        identity_keys = self._same_run_job_identity_keys(job)
        if not identity_keys:
            return

        entry = self._find_same_run_job_entry(registry, job)
        if entry is None:
            entry = {
                "details": copy.deepcopy(job),
                "first_query": query,
                "last_query": query,
            }
        else:
            entry["details"] = copy.deepcopy(job)
            entry["last_query"] = query

        for key in identity_keys:
            registry[key] = entry

    def _find_persistent_collected_job(self, job: dict) -> dict | None:
        identity_keys = self._same_run_job_identity_keys(job)
        if not identity_keys:
            return None
        return self.collected_jobs.get_by_identity_keys(identity_keys)

    def _mark_job_as_analyzed(
        self,
        job: dict,
        *,
        query: str,
        analysis_status: str,
        analysis_reason: str = "",
    ) -> dict | None:
        identity_keys = self._same_run_job_identity_keys(job)
        if not identity_keys:
            return None

        now = datetime.now().astimezone().isoformat()
        existing = self.collected_jobs.get_by_identity_keys(identity_keys)
        if existing and ((existing.get("analyzed_at") or "").strip() or (existing.get("analysis_status") or "").strip()):
            return existing

        record = {
            "query": query,
            "queries_seen": [query],
            "page_number": int(job.get("page_number", 0) or 0),
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": self._canonicalize_linkedin_job_url(job.get("url", "")),
            "job_id": (job.get("job_id") or self._linkedin_job_id(job.get("url", ""))).strip(),
            "description": (job.get("description") or "").strip(),
            "description_debug": dict(job.get("description_debug", {}) or {}),
            "easy_apply": bool(job.get("easy_apply")),
            "apply_method": job.get("apply_method", "unknown"),
            "apply_method_detection_source": job.get("apply_method_detection_source", ""),
            "collected_at": (existing or {}).get("collected_at", "") or now,
            "last_seen_at": now,
            "analyzed_at": now,
            "analysis_status": analysis_status,
            "analysis_reason": analysis_reason,
            "identity_keys": identity_keys,
        }
        return self.collected_jobs.upsert_job(record)

    def _record_terminal_job_analysis(
        self,
        *,
        job: dict,
        query: str,
        status: str,
        reason: str = "",
    ) -> None:
        self._mark_job_as_analyzed(
            job,
            query=query,
            analysis_status=status,
            analysis_reason=reason,
        )

    def _upsert_collected_job(self, job: dict, query: str) -> dict | None:
        if not self._description_extracted(job):
            return None

        identity_keys = self._same_run_job_identity_keys(job)
        if not identity_keys:
            return None

        record = {
            "query": query,
            "queries_seen": [query],
            "page_number": int(job.get("page_number", 0) or 0),
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": self._canonicalize_linkedin_job_url(job.get("url", "")),
            "job_id": self._linkedin_job_id(job.get("url", "")),
            "description": (job.get("description") or "").strip(),
            "description_debug": dict(job.get("description_debug", {}) or {}),
            "easy_apply": bool(job.get("easy_apply")),
            "apply_method": job.get("apply_method", "unknown"),
            "apply_method_detection_source": job.get("apply_method_detection_source", ""),
            "collected_at": datetime.now().astimezone().isoformat(),
            "last_seen_at": datetime.now().astimezone().isoformat(),
            "identity_keys": identity_keys,
        }
        return self.collected_jobs.upsert_job(record)

    def _load_collected_job_summaries(self, query: str, max_pages: int | None = None) -> list[dict]:
        summaries = []
        for job in self.collected_jobs.find_for_query(query=query, max_pages=max_pages):
            already_analyzed, _ = self._is_globally_analyzed(job)
            if already_analyzed:
                self._touch_known_job_seen(job, query)
                self._record_previously_analyzed_skip(stage="process_only")
                continue
            summary = dict(job)
            summary["preview_text"] = self._description_preview(summary.get("description", ""), max_chars=240)
            summaries.append(summary)
        return summaries

    def _fingerprint_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _match_tier(self, score: int) -> str:
        try:
            numeric = int(score)
        except (TypeError, ValueError):
            numeric = 0
        if numeric >= self.AI_STRONG_MATCH_THRESHOLD:
            return "strong_match"
        if numeric >= self.AI_THRESHOLD:
            return "possible_match"
        return "weak_match"

    def _build_rejected_job_record(self, job: dict, verdict: dict) -> dict:
        reasons = verdict.get("reasons") or []
        description = (job.get("description") or "").strip()
        extraction_debug = job.get("description_debug") or {}
        return {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": self._canonicalize_linkedin_job_url(job.get("url", "")),
            "found_at": job.get("_found_at", datetime.now().astimezone().isoformat()),
            "easy_apply": bool(job.get("easy_apply")),
            "apply_method": job.get("apply_method", "unknown"),
            "apply_method_detection_source": job.get("apply_method_detection_source", ""),
            "rejection_category": self._rejection_category_label(verdict.get("status", "")),
            "rejection_reason": reasons[0] if reasons else "Rejected by non-AI filter",
            "description_extracted": self._description_extracted(job),
            "description_length": len(description),
            "description_preview": self._description_preview(description),
            "description_selector_matched": extraction_debug.get("selector_matched", ""),
            "description_extraction_source": extraction_debug.get("source", ""),
            "description_container_found": extraction_debug.get("container_found", False),
            "description_expand_clicked": extraction_debug.get("expand_clicked", False),
            "description_scrolled": extraction_debug.get("scrolled", False),
            "description_extraction_notes": extraction_debug.get("notes", []),
        }

    def _rejection_category_label(self, status: str) -> str:
        return {
            "skipped_preopen_outside_netherlands": "Pre-open outside Netherlands",
            "skipped_preopen_internship": "Pre-open internship",
            "skipped_preopen_seniority": "Pre-open seniority",
            "skipped_preopen_language": "Pre-open language requirement",
            "skipped_preopen_irrelevant": "Pre-open irrelevant",
            "rejected_outside_netherlands": "Outside Netherlands",
            "rejected_internship": "Internship",
            "rejected_dutch": "Language requirement",
            "rejected_entry_level": "Seniority / non-entry-level",
            "rejected_irrelevant": "Irrelevant to search query",
            "rejected_excluded": "Excluded unrelated field",
            "rejected_market_eligibility": "Market eligibility",
            "rejected_employment_type": "Employment type",
        }.get(status, "Rejected by filter")

    def _detect_description_language(self, job: dict) -> str:
        title = (job.get("title") or "").strip().lower()
        description = (
            job.get("description")
            or job.get("preview_text")
            or ""
        )[:6000].strip().lower()

        if not title and not description:
            return "unknown"

        if any(marker in title for marker in JobBrain.DUTCH_TITLE_MARKERS):
            return "dutch"

        title_tokens = self._language_tokens(title)
        description_tokens = self._language_tokens(description)
        combined_tokens = title_tokens + description_tokens
        if not combined_tokens:
            return "unknown"

        dutch_hits = self._marker_hits(combined_tokens, JobBrain.DUTCH_LANGUAGE_MARKERS)
        english_hits = self._marker_hits(combined_tokens, JobBrain.ENGLISH_LANGUAGE_MARKERS)

        if len(description_tokens) >= 30 and dutch_hits >= 8 and dutch_hits > english_hits * 1.5:
            return "dutch"
        if len(description_tokens) >= 18 and dutch_hits >= 6 and english_hits <= 3:
            return "dutch"
        if len(title_tokens) >= 3 and dutch_hits >= 3 and english_hits == 0:
            return "dutch"
        if english_hits >= max(3, dutch_hits):
            return "english"
        return "english_friendly"

    def _passes_query_relevance(self, query: str, job: dict) -> dict:
        title = (job.get("title") or "").lower()
        combined_text = self._combined_job_text(job)
        normalized_query = self._normalize_text(query)
        expanded_terms = self._expanded_query_terms(query)
        family = self._query_family(query)

        matched_terms = [
            term for term in expanded_terms
            if self._contains_term(combined_text, term)
        ]
        title_matches = [
            term for term in expanded_terms
            if self._contains_term(title, term)
        ]

        if normalized_query and self._contains_term(title, normalized_query):
            return {
                "pass": True,
                "matched_terms": sorted(set([normalized_query] + matched_terms))[:10],
                "reasons": [f"Title directly matches query '{query}'"],
            }

        if normalized_query and self._contains_term(combined_text, normalized_query):
            return {
                "pass": True,
                "matched_terms": sorted(set([normalized_query] + matched_terms))[:10],
                "reasons": [f"Description matches query phrase '{query}'"],
            }

        if family == "creative_brand":
            creative_brand = self._passes_creative_brand_relevance(query, title, combined_text, matched_terms)
            if creative_brand["pass"]:
                return creative_brand

        if family == "ux_product":
            ux_product = self._passes_grouped_relevance(
                title=title,
                combined_text=combined_text,
                groups=self.UX_PRODUCT_GROUPS,
                matched_terms=matched_terms,
                minimum_text_groups=2,
                minimum_title_groups=1,
                reason_prefix="UX/product role-family match",
            )
            if ux_product["pass"]:
                return ux_product

        if family == "analysis":
            analysis = self._passes_grouped_relevance(
                title=title,
                combined_text=combined_text,
                groups=self.ANALYSIS_GROUPS,
                matched_terms=matched_terms,
                minimum_text_groups=2,
                minimum_title_groups=1,
                reason_prefix="Analysis/consulting role-family match",
            )
            if analysis["pass"]:
                return analysis

        if family == "support":
            support = self._passes_grouped_relevance(
                title=title,
                combined_text=combined_text,
                groups=self.SUPPORT_GROUPS,
                matched_terms=matched_terms,
                minimum_text_groups=2,
                minimum_title_groups=1,
                reason_prefix="Support role-family match",
            )
            if support["pass"]:
                return support

        if len(title_matches) >= 2:
            return {
                "pass": True,
                "matched_terms": sorted(set(title_matches))[:10],
                "reasons": [f"Title overlaps with search domain: {', '.join(sorted(set(title_matches))[:4])}"],
            }

        if len(title_matches) >= 1 and len(matched_terms) >= 2:
            return {
                "pass": True,
                "matched_terms": sorted(set(matched_terms))[:10],
                "reasons": [f"Relevant title and description terms found: {', '.join(sorted(set(matched_terms))[:4])}"],
            }

        if len(matched_terms) >= 3:
            return {
                "pass": True,
                "matched_terms": sorted(set(matched_terms))[:10],
                "reasons": [f"Description contains multiple query-related terms: {', '.join(sorted(set(matched_terms))[:4])}"],
            }

        return {
            "pass": True,
            "matched_terms": sorted(set(matched_terms))[:10],
            "reasons": [
                "Broad entry-level or graduate-friendly role kept for AI interview-probability scoring despite limited direct query overlap"
            ],
        }

    def _passes_entry_level_filter(self, job: dict) -> dict:
        title = (job.get("title") or "").lower()
        description = (job.get("description") or "").lower()
        combined_text = f"{title}\n{description}"
        entry_markers = [
            marker for marker in self.ENTRY_LEVEL_MARKERS
            if self._contains_term(combined_text, marker)
        ]

        title_hits = self._seniority_title_hits(title)
        if title_hits:
            return {
                "pass": False,
                "reasons": [f"Title suggests non-entry-level seniority: {', '.join(title_hits[:3])}"],
            }

        years_requirement = self._required_experience_years(combined_text)
        if years_requirement["reject"]:
            return {
                "pass": False,
                "reasons": [years_requirement["reason"]],
            }

        hard_seniority_hits = self._hard_seniority_responsibility_hits(combined_text)
        if hard_seniority_hits and not entry_markers:
            return {
                "pass": False,
                "reasons": [
                    "Description shows unmistakable non-junior line-management responsibility: "
                    + ", ".join(hard_seniority_hits[:3])
                ],
            }

        soft_seniority_hits = self._soft_seniority_signal_hits(combined_text)

        reasons = []
        if entry_markers:
            reasons.append(f"Entry-level signal found: {', '.join(entry_markers[:3])}")
        else:
            reasons.append("No clear seniority blockers found for entry-level screening")
        if re.search(r"\bmanager\b", self._normalize_text(title)):
            reasons.append("Manager title alone is not treated as a hard blocker and is kept for AI review")
        if soft_seniority_hits:
            reasons.append(
                "Soft seniority/ownership language kept for AI review: "
                + ", ".join(soft_seniority_hits[:4])
            )
        return {"pass": True, "reasons": reasons}

    def _required_experience_years(self, text: str) -> dict:
        matches = []

        range_patterns = [
            re.compile(r"\b(\d+)\s*(?:-|to|–|—)\s*(\d+)\s*(?:years?|yrs?|jaar)\b", re.IGNORECASE),
        ]
        single_patterns = [
            re.compile(r"\b(\d+)\s*\+\s*(?:years?|yrs?|jaar)\b", re.IGNORECASE),
            re.compile(r"\bat least\s+(\d+)\s*(?:years?|yrs?|jaar)\b", re.IGNORECASE),
            re.compile(r"\bminimum(?: of)?\s+(\d+)\s*(?:years?|yrs?|jaar)\b", re.IGNORECASE),
            re.compile(r"\bmin\.?\s*(\d+)\s*(?:years?|yrs?|jaar)\b", re.IGNORECASE),
            re.compile(r"\b(\d+)\s*(?:years?|yrs?|jaar)\s+of\s+(?:relevant\s+)?experience\b", re.IGNORECASE),
            re.compile(r"\b(\d+)\s*(?:years?|yrs?|jaar)\s+experience\b", re.IGNORECASE),
        ]

        for pattern in range_patterns:
            for match in pattern.finditer(text):
                lower = int(match.group(1))
                upper = int(match.group(2))
                matches.append((lower, upper, match.group(0), match.start(), match.end()))

        for pattern in single_patterns:
            for match in pattern.finditer(text):
                value = int(match.group(1))
                matches.append((value, value, match.group(0), match.start(), match.end()))

        if not matches:
            return {"reject": False, "reason": ""}

        optional_markers = {
            "preferred",
            "nice to have",
            "nice-to-have",
            "plus",
            "bonus",
            "ideal",
            "ideally",
            "preferred but not required",
        }
        strict_markers = {"must have", "required", "requires", "mandatory", "essential", "minimum", "at least"}
        senior_or_domain_heavy_context = any(
            marker in text
            for marker in [
                "senior",
                "lead",
                "principal",
                "specialist",
                "standalone",
                "own the",
                "ownership",
                "direct reports",
                "performance reviews",
                "p&l",
                "product ux experience",
                "product design experience",
                "design system ownership",
                "platform migration",
                "hands-on sql",
                "hands-on python",
                "dbt",
                "snowflake",
                "production data",
                "machine learning engineering",
                "advanced statistical",
                "proven track record",
                "extensive experience",
            ]
        )

        for lower, upper, phrase, start, end in matches:
            context_window = text[max(0, start - 90): min(len(text), end + 90)]
            if any(marker in context_window for marker in optional_markers):
                continue

            strict_context = any(marker in context_window for marker in strict_markers)

            if lower >= 5:
                return {
                    "reject": True,
                    "reason": f"Role requires {phrase}, which is above Omar's early-career range",
                }
            if lower >= 4 and (strict_context or senior_or_domain_heavy_context):
                return {
                    "reject": True,
                    "reason": f"Role requires {phrase} in a senior/specialist context, which is above entry-level range",
                }
            if lower >= 3 and strict_context and (senior_or_domain_heavy_context or upper >= 6):
                return {
                    "reject": True,
                    "reason": (
                        f"Role requires {phrase} in a strict senior/specialist context; "
                        "kept out before AI scoring"
                    ),
                }

        return {"reject": False, "reason": ""}

    def _expanded_query_terms(self, query: str) -> set[str]:
        normalized_query = self._normalize_text(query)
        tokens = [
            token for token in normalized_query.split()
            if (len(token) > 2 or token in self.SHORT_QUERY_TOKENS)
            and token not in self.QUERY_STOPWORDS
        ]

        expanded = set(tokens)
        if normalized_query:
            expanded.add(normalized_query)

        for token in tokens:
            expanded.update(self.QUERY_EXPANSIONS.get(token, set()))

        if "brand strategy" in normalized_query:
            expanded.update({"brand strategy", "brand strategist", "branding", "positioning", "creative strategy"})
        if "business analyst" in normalized_query:
            expanded.update({"business analysis", "requirements", "stakeholder", "process improvement"})
        if "ux" in normalized_query or "user experience" in normalized_query:
            expanded.update({"ux", "user experience", "ui ux", "product design", "user research"})

        return {term.strip() for term in expanded if term and term.strip()}

    def _is_blacklisted_company(self, company: str) -> bool:
        lowered = (company or "").lower()
        for value in self.preferences.get("companies_blacklist", []):
            if value and value.lower() in lowered:
                return True
        return False

    def _contains_excluded_terms(self, title: str, combined_text: str) -> list[str]:
        excluded = self._preference_exclusion_terms()
        hits = self._matching_values(title, excluded)
        hits.extend(self._matching_values(combined_text, excluded))
        return sorted(set(hits), key=lambda value: (-len(value), value.lower()))

    def _contains_fallback_terms(self, title: str, combined_text: str) -> list[str]:
        fallback_terms = self.preferences.get("fallback_keywords", [])
        hits = self._matching_values(title, fallback_terms)
        hits.extend(self._matching_values(combined_text, fallback_terms))
        return sorted(set(hits), key=lambda value: (-len(value), value.lower()))

    def _preference_exclusion_terms(self) -> list[str]:
        configured = self.preferences.get("soft_negative_keywords")
        if configured is None:
            configured = list(self.SOFT_PREFERENCE_EXCLUDE_MARKERS)

        excluded = []
        for value in configured:
            lowered = (value or "").strip().lower()
            if not lowered:
                continue
            if lowered in self._preference_seniority_terms():
                continue
            excluded.append(value)
        return excluded

    def _preference_seniority_terms(self) -> set[str]:
        return {
            "senior",
            "lead",
            "principal",
            "mid-senior",
            "mid senior",
            "medior",
            "10+ years",
            "8+ years",
        }

    def _combined_job_text(self, job: dict) -> str:
        parts = [
            job.get("title", ""),
            job.get("company", ""),
            job.get("location", ""),
            job.get("preview_text", ""),
            job.get("description", ""),
        ]
        return " ".join(part for part in parts if part).lower()

    def _listing_text(self, job: dict) -> str:
        parts = [
            job.get("title", ""),
            job.get("company", ""),
            job.get("location", ""),
            job.get("preview_text", ""),
        ]
        return " ".join(part for part in parts if part).lower()

    def _matching_values(self, haystack: str, values: list) -> list:
        lowered = (haystack or "").lower()
        matches = []
        for value in values:
            if not value:
                continue
            pattern = rf"(?<!\w){re.escape(value.lower())}(?!\w)"
            if re.search(pattern, lowered):
                matches.append(value)
        return matches

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+/#-]+", " ", (text or "").lower())).strip()

    def _language_tokens(self, text: str) -> list[str]:
        return re.findall(r"[a-zA-ZÀ-ÿ]+", (text or "").lower())

    def _marker_hits(self, tokens: list[str], markers: set[str]) -> int:
        return sum(1 for token in tokens if token in markers)

    def _contains_term(self, haystack: str, term: str) -> bool:
        normalized_haystack = self._normalize_text(haystack)
        normalized_term = self._normalize_text(term)
        if not normalized_term:
            return False
        pattern = rf"(?<!\w){re.escape(normalized_term)}(?!\w)"
        return bool(re.search(pattern, normalized_haystack))

    def _query_family(self, query: str) -> str:
        tokens = set(self._normalize_text(query).split())
        if {"brand", "branding", "strategy", "creative", "designer", "design", "marketing"} & tokens:
            return "creative_brand"
        if {"ux", "ui", "product", "designer", "design", "research"} & tokens:
            return "ux_product"
        if {"business", "analyst", "analysis", "data", "consultant", "implementation"} & tokens:
            return "analysis"
        if {"support", "technical", "it", "help", "desk", "service"} & tokens:
            return "support"
        return "generic"

    def _passes_creative_brand_relevance(
        self,
        query: str,
        title: str,
        combined_text: str,
        matched_terms: list[str],
    ) -> dict:
        title_group_hits = self._group_hits(title, self.CREATIVE_BRAND_GROUPS)
        text_group_hits = self._group_hits(combined_text, self.CREATIVE_BRAND_GROUPS)
        adjacent_title_hits = [
            marker for marker in self.CREATIVE_BRAND_ADJACENT_TITLE_MARKERS
            if self._contains_term(title, marker)
        ]
        title_matches = self._group_hits(title, self.CREATIVE_BRAND_GROUPS)
        ux_adjacent_title = any(
            self._contains_term(title, marker)
            for marker in ["ux", "ui", "product designer", "ux designer", "ui designer"]
        )

        if len(title_group_hits) >= 2:
            return {
                "pass": True,
                "matched_terms": sorted(set(matched_terms + title_group_hits))[:10],
                "reasons": [f"Creative/brand title overlap: {', '.join(title_group_hits[:3])}"],
            }

        if adjacent_title_hits and len(text_group_hits) >= 2:
            return {
                "pass": True,
                "matched_terms": sorted(set(matched_terms + adjacent_title_hits + text_group_hits))[:10],
                "reasons": [f"Adjacent creative role with strong brand/strategy signals: {', '.join(adjacent_title_hits[:2])}"],
            }

        if "brand" in text_group_hits and ("strategy" in text_group_hits or "creative" in text_group_hits):
            if "marketing" in title or "content" in title or "designer" in title or "creative" in title:
                return {
                    "pass": True,
                    "matched_terms": sorted(set(matched_terms + text_group_hits))[:10],
                    "reasons": ["Returned role is adjacent but meaningfully brand/creative/strategic"],
                }

        if ux_adjacent_title and "brand" in text_group_hits and ("strategy" in text_group_hits or "creative" in text_group_hits):
            return {
                "pass": True,
                "matched_terms": sorted(set(matched_terms + text_group_hits))[:10],
                "reasons": ["UX/product role kept because branding/creative strategy is meaningfully present"],
            }

        if len(text_group_hits) >= 3 and (title_group_hits or adjacent_title_hits or title_matches):
            return {
                "pass": True,
                "matched_terms": sorted(set(matched_terms + text_group_hits))[:10],
                "reasons": [f"Strong creative/brand signal in description: {', '.join(text_group_hits[:3])}"],
            }

        return {
            "pass": False,
            "matched_terms": sorted(set(matched_terms + text_group_hits + title_group_hits))[:10],
            "reasons": [f"Insufficient non-AI relevance to search query '{query}'"],
        }

    def _passes_grouped_relevance(
        self,
        title: str,
        combined_text: str,
        groups: dict[str, set[str]],
        matched_terms: list[str],
        minimum_text_groups: int,
        minimum_title_groups: int,
        reason_prefix: str,
    ) -> dict:
        title_group_hits = self._group_hits(title, groups)
        text_group_hits = self._group_hits(combined_text, groups)
        if len(title_group_hits) >= minimum_title_groups and len(text_group_hits) >= minimum_text_groups:
            return {
                "pass": True,
                "matched_terms": sorted(set(matched_terms + title_group_hits + text_group_hits))[:10],
                "reasons": [f"{reason_prefix}: {', '.join(text_group_hits[:3])}"],
            }
        if len(title_group_hits) >= max(2, minimum_title_groups):
            return {
                "pass": True,
                "matched_terms": sorted(set(matched_terms + title_group_hits))[:10],
                "reasons": [f"{reason_prefix}: title strongly matches"],
            }
        return {
            "pass": False,
            "matched_terms": sorted(set(matched_terms + title_group_hits + text_group_hits))[:10],
            "reasons": [],
        }

    def _group_hits(self, haystack: str, groups: dict[str, set[str]]) -> list[str]:
        hits = []
        for group_name, terms in groups.items():
            if any(self._contains_term(haystack, term) for term in terms):
                hits.append(group_name)
        return hits

    def _canonicalize_linkedin_job_url(self, url: str) -> str:
        return self._analyze_linkedin_job_url(url).get("canonical_url", "")

    def _resolve_preferred_linkedin_job_url(self, primary_url: str, fallback_url: str = "") -> str:
        primary = self._canonicalize_linkedin_job_url(primary_url)
        if primary:
            return primary
        return self._canonicalize_linkedin_job_url(fallback_url)

    def _is_linkedin_host(self, host: str) -> bool:
        normalized = (host or "").strip().lower()
        return normalized == "linkedin.com" or normalized.endswith(".linkedin.com")

    def _analyze_linkedin_job_url(self, url: str) -> dict:
        raw_url = (url or "").strip()
        analysis = {
            "raw_url": raw_url,
            "absolute_url": "",
            "canonical_url": "",
            "valid": False,
            "result": "invalid_empty_url",
        }
        if not raw_url:
            return analysis

        absolute_url = urllib.parse.urljoin("https://www.linkedin.com", raw_url)
        analysis["absolute_url"] = absolute_url
        parsed = urllib.parse.urlparse(absolute_url)
        scheme = (parsed.scheme or "").strip().lower()
        host = (parsed.netloc or "").strip().lower()
        if scheme and scheme not in {"http", "https"}:
            analysis["result"] = "invalid_scheme"
            return analysis
        if not self._is_linkedin_host(host):
            analysis["result"] = "invalid_non_linkedin_domain"
            return analysis

        job_id = ""
        for pattern in (
            r"/jobs/view/(\d+)",
            r"[?&]currentJobId=(\d+)",
            r"[?&]referenceJobId=(\d+)",
        ):
            match = re.search(pattern, absolute_url)
            if match:
                job_id = match.group(1)
                break

        if not job_id:
            analysis["result"] = "invalid_non_job_linkedin_page"
            return analysis

        analysis["canonical_url"] = f"https://www.linkedin.com/jobs/view/{job_id}/"
        analysis["valid"] = True
        analysis["result"] = "valid_job_detail_url"
        return analysis

    def _short_url_for_log(self, url: str, max_chars: int = 120) -> str:
        safe = self._safe_console_text(url or "")
        if not safe:
            return "<empty>"
        if len(safe) <= max_chars:
            return safe
        return safe[: max_chars - 3].rstrip() + "..."

    def _log_invalid_job_url(self, *, analysis: dict, source: str, title: str = "") -> None:
        title_label = self._safe_console_text(title or "")
        title_part = f"title={title_label} | " if title_label else ""
        self._report(
            "STATE",
            (
                f"Blocked invalid job URL | {title_part}"
                f"source={source} | "
                f"raw={self._short_url_for_log(analysis.get('raw_url', ''))} | "
                f"canon={self._short_url_for_log(analysis.get('canonical_url', ''))} | "
                f"result={analysis.get('result', 'invalid_unknown')}"
            ),
            style="yellow",
        )

    def _invalid_url_verdict(self, *, source: str, analysis: dict) -> dict:
        result = (analysis.get("result") or "invalid_unknown").replace("_", " ")
        return {
            "status": "skipped_preopen_irrelevant",
            "language": "unknown",
            "matched_terms": [],
            "reasons": [f"Invalid non-job URL blocked before navigation ({source}; {result})"],
        }

    def _skip_invalid_job_url(
        self,
        *,
        job: dict,
        analysis: dict,
        source: str,
        stats: dict,
        rejected_jobs: list[dict],
        query: str,
        index: int,
        job_processed_callback=None,
        live_result_callback=None,
    ) -> None:
        self._log_invalid_job_url(
            analysis=analysis,
            source=source,
            title=job.get("title", ""),
        )
        verdict = self._invalid_url_verdict(source=source, analysis=analysis)
        stats["preopen_skipped_total"] += 1
        stats["skipped_preopen_irrelevant"] += 1
        rejected_record = self._build_rejected_job_record(job, verdict)
        rejected_jobs.append(rejected_record)
        self._emit_live_result(
            live_result_callback,
            self._build_live_result_event(
                query=query,
                index=index,
                job=job,
                terminal_status=verdict["status"],
                source_stage="invalid_url",
                reason=verdict["reasons"][0],
                verdict=verdict,
                flags=["invalid_url"],
            ),
        )
        self.reporter.record_preopen_skip(reason=verdict["reasons"][0])
        self._record_summary_processed(
            query=query,
            index=index,
            page_number=job.get("page_number", 0),
            callback=job_processed_callback,
        )
        self.reporter.end_job()

    def _evaluate_preopen_job(self, query: str, job: dict) -> dict:
        internship_reason = self._internship_reason(job, preopen=True)
        if internship_reason:
            return {
                "status": "skipped_preopen_internship",
                "language": "unknown",
                "matched_terms": [],
                "reasons": [internship_reason],
            }

        location_reason = self._location_scope_reason(job, preopen=True)
        if location_reason:
            return {
                "status": "skipped_preopen_outside_search_market",
                "language": "unknown",
                "matched_terms": [],
                "reasons": [location_reason],
            }

        language_reason = self._preopen_language_reason(job)
        if language_reason:
            return {
                "status": "skipped_preopen_language",
                "language": "unknown",
                "matched_terms": [],
                "reasons": [language_reason],
            }

        title_hits = self._seniority_title_hits(job.get("title", ""))
        if title_hits:
            return {
                "status": "skipped_preopen_seniority",
                "language": "unknown",
                "matched_terms": [],
                "reasons": [f"Title suggests non-entry-level seniority: {', '.join(title_hits[:3])}"],
            }

        irrelevant_reason = self._preopen_irrelevant_reason(query, job)
        if irrelevant_reason:
            return {
                "status": "skipped_preopen_irrelevant",
                "language": "unknown",
                "matched_terms": [],
                "reasons": [irrelevant_reason],
            }

        return {
            "status": "open",
            "language": "unknown",
            "matched_terms": [],
            "reasons": [],
        }

    def _preopen_language_reason(self, job: dict) -> str:
        title = (job.get("title") or "").strip()
        lowered_title = title.lower()
        listing_text = self._combined_job_text(job)

        title_marker = self._first_matching_marker(lowered_title, self.PREOPEN_LANGUAGE_MARKERS)
        if title_marker:
            return f"Title signals incompatible language requirement: {title_marker}"

        listing_marker = self._first_matching_marker(listing_text, self.DUTCH_REQUIREMENT_MARKERS)
        if listing_marker:
            return f"Listing signals Dutch language requirement: {listing_marker}"

        contextual_dutch = self._contextual_fluent_dutch_requirement(job)
        if contextual_dutch:
            return contextual_dutch

        return ""

    def _location_scope_reason(self, job: dict, preopen: bool) -> str:
        if self.search_scope.get("legacy_mode"):
            return self._legacy_netherlands_location_scope_reason(job, preopen)

        location = (job.get("location") or "").strip()
        normalized_location = self._normalize_text(location)
        combined_text = self._combined_job_text(job)
        market = self.search_scope.get("search_market", "netherlands")
        profile = MARKET_PROFILES.get(market, MARKET_PROFILES["netherlands"])
        target_markers = {
            self._normalize_text(profile.get("country", "")),
            *(
                self._normalize_text(value)
                for value in profile.get("locations", [])
                if self._normalize_text(value) != "remote"
            ),
        }
        target_markers.discard("")

        if any(self._contains_term(normalized_location, marker) for marker in target_markers):
            return ""

        if not normalized_location:
            return "" if preopen else (
                f"Job location is missing and the description does not show "
                f"{profile['label']} compatibility"
            )

        has_remote_marker = any(
            self._contains_term(normalized_location, marker)
            for marker in self.REMOTE_LOCATION_MARKERS
        )
        remaining_location = normalized_location
        for marker in self.REMOTE_LOCATION_MARKERS:
            remaining_location = re.sub(
                rf"(?<!\w){re.escape(self._normalize_text(marker))}(?!\w)",
                " ",
                remaining_location,
            )
        remaining_location = re.sub(r"\s+", " ", remaining_location).strip()

        if has_remote_marker and not remaining_location:
            return ""

        if has_remote_marker and remaining_location and not any(
            self._contains_term(remaining_location, marker) for marker in target_markers
        ):
            return f"Location is outside the {profile['label']} scope: {location}"

        if not any(
            self._contains_term(normalized_location, marker) for marker in target_markers
        ):
            return f"Location is outside the {profile['label']} scope: {location}"

        return ""

    def _legacy_netherlands_location_scope_reason(self, job: dict, preopen: bool) -> str:
        location = (job.get("location") or "").strip()
        normalized_location = self._normalize_text(location)
        combined_text = self._combined_job_text(job)
        if self._contains_netherlands_marker(normalized_location):
            return ""
        if not normalized_location:
            if preopen or self._contains_netherlands_compatibility(combined_text):
                return ""
            return "Job location is missing and the description does not show Netherlands compatibility"
        has_remote_marker = any(
            self._contains_term(normalized_location, marker)
            for marker in self.REMOTE_LOCATION_MARKERS
        )
        remaining_location = normalized_location
        for marker in self.REMOTE_LOCATION_MARKERS:
            remaining_location = re.sub(
                rf"(?<!\w){re.escape(self._normalize_text(marker))}(?!\w)",
                " ",
                remaining_location,
            )
        remaining_location = re.sub(r"\s+", " ", remaining_location).strip()
        if has_remote_marker and not remaining_location:
            if preopen or self._contains_netherlands_compatibility(combined_text):
                return ""
            return "Remote role does not clearly indicate Netherlands compatibility"
        if has_remote_marker and remaining_location and not self._contains_netherlands_marker(remaining_location):
            return f"Location is outside the Netherlands scope: {location}"
        if not self._contains_netherlands_marker(normalized_location):
            return f"Location is outside the Netherlands scope: {location}"
        return ""

    def _internship_reason(self, job: dict, preopen: bool) -> str:
        title = (job.get("title") or "").strip().lower()
        combined_text = self._combined_job_text(job)
        if not self._is_internship_like(job):
            return ""

        student_requirement = self._first_matching_marker(
            combined_text,
            self.CURRENT_STUDENT_REQUIRED_MARKERS,
        )
        if student_requirement:
            return f"Internship requires current student/enrollment status: {student_requirement}"

        if preopen:
            return ""

        if self._first_matching_marker(combined_text, self.INTERNSHIP_ALLOW_MARKERS):
            return ""

        if self._first_matching_marker(combined_text, self.STRATEGIC_INTERNSHIP_MARKERS):
            return ""

        return ""

    def _is_internship_like(self, job: dict) -> bool:
        title = (job.get("title") or "").strip().lower()
        combined_text = self._combined_job_text(job)
        return bool(
            self._first_matching_marker(title, self.INTERNSHIP_TITLE_MARKERS)
            or self._first_matching_marker(combined_text, self.INTERNSHIP_DESCRIPTION_MARKERS)
        )

    def _internship_review_notes(self, job: dict) -> list[str]:
        if not self._is_internship_like(job):
            return []

        notes = [
            "Internship-style role allowed because no explicit current-student requirement was found"
        ]
        combined_text = self._combined_job_text(job)
        if re.search(r"€?\s?[0-7]\d{2}\s*(?:per month|monthly|/month|p/m|month)", combined_text, flags=re.I):
            notes.append("Low internship allowance risk; keep for human review")
        elif "allowance" in combined_text or "stagevergoeding" in combined_text:
            notes.append("Internship allowance mentioned; verify pay before applying")
        return notes

    def _preopen_irrelevant_reason(self, query: str, job: dict) -> str:
        hard_viability_reason = self._hard_viability_marker_reason(job)
        if hard_viability_reason:
            return hard_viability_reason

        qualification_reason = self._mandatory_qualification_reason(job, preopen=True)
        if qualification_reason:
            return qualification_reason

        return ""

    def _seniority_title_hits(self, title: str) -> list[str]:
        normalized_title = self._normalize_text(title)
        hits = []

        pattern_map = {
            "senior": r"\bsenior\b",
            "sr": r"\bsr\.?\b",
            "principal": r"\bprincipal\b",
            "staff": r"\bstaff\b",
            "head": r"\bhead\b",
            "director": r"\bdirector\b",
            "chief": r"\bchief\b",
        }
        for label, pattern in pattern_map.items():
            if re.search(pattern, normalized_title):
                hits.append(label)

        if re.search(r"\blead\b", normalized_title) and "lead generation" not in normalized_title:
            hits.append("lead")

        return sorted(set(hits))

    def _soft_seniority_signal_hits(self, combined_text: str) -> list[str]:
        hits = [
            marker
            for marker in sorted(self.SOFT_SENIORITY_SIGNAL_MARKERS, key=len, reverse=True)
            if self._contains_term(combined_text, marker)
        ]
        return sorted(set(hits), key=lambda value: (-len(value), value.lower()))

    def _hard_seniority_responsibility_hits(self, combined_text: str) -> list[str]:
        hits = [
            marker
            for marker in sorted(self.HARD_SENIOR_RESPONSIBILITY_MARKERS, key=len, reverse=True)
            if self._contains_term(combined_text, marker)
        ]
        return sorted(set(hits), key=lambda value: (-len(value), value.lower()))

    def _is_clearly_dutch_title(self, title: str) -> bool:
        lowered = (title or "").strip().lower()
        if not lowered:
            return False
        if any(marker in lowered for marker in JobBrain.DUTCH_TITLE_MARKERS):
            return True

        title_tokens = self._language_tokens(lowered)
        dutch_hits = self._marker_hits(title_tokens, JobBrain.DUTCH_LANGUAGE_MARKERS)
        english_hits = self._marker_hits(title_tokens, JobBrain.ENGLISH_LANGUAGE_MARKERS)
        return len(title_tokens) >= 2 and dutch_hits >= 2 and english_hits == 0

    def _first_matching_marker(self, haystack: str, markers: set[str]) -> str:
        for marker in sorted(markers, key=len, reverse=True):
            if self._contains_term(haystack, marker):
                return marker
        return ""

    def _contextual_fluent_dutch_requirement(self, job: dict) -> str:
        combined_text = self._combined_job_text(job)
        fluent_marker = self._first_matching_marker(combined_text, self.FLUENT_DUTCH_MARKERS)
        if not fluent_marker:
            return ""

        context_marker = self._first_matching_marker(
            combined_text,
            self.DUTCH_COMMUNICATION_CONTEXT_MARKERS,
        )
        if context_marker:
            return (
                "Fluent Dutch appears in a Dutch-heavy communication context "
                f"({fluent_marker} + {context_marker})"
            )
        return ""

    def _dutch_risk_notes(self, job: dict) -> list[str]:
        combined_text = self._combined_job_text(job)
        fluent_marker = self._first_matching_marker(combined_text, self.FLUENT_DUTCH_MARKERS)
        if fluent_marker:
            return [f"Dutch risk kept for AI review: {fluent_marker}"]
        if self._contains_term(combined_text, "dutch and english"):
            return ["Dutch and English mentioned; Omar is English-fluent and B1/intermediate Dutch"]
        return []

    def _contains_netherlands_marker(self, text: str) -> bool:
        return any(
            self._contains_term(text, marker)
            for marker in self.NETHERLANDS_LOCATION_MARKERS
        )

    def _contains_netherlands_compatibility(self, text: str) -> bool:
        return any(
            self._contains_term(text, marker)
            for marker in self.NETHERLANDS_REMOTE_COMPATIBILITY_MARKERS
        )

    def _hard_viability_marker_reason(self, job: dict) -> str:
        title = (job.get("title") or "").strip().lower()
        listing_text = self._listing_text(job)

        marker = self._first_matching_marker(title, self.PREOPEN_UNRELATED_TITLE_MARKERS)
        if not marker:
            marker = self._first_matching_marker(listing_text, self.PREOPEN_UNRELATED_TITLE_MARKERS)

        if marker:
            return f"Role is clearly incompatible with the graduate-level opportunity funnel: {marker}"

        non_role_marker = self._first_matching_marker(title, self.NON_ROLE_LISTING_MARKERS)
        if non_role_marker:
            return f"Listing appears to be a community or talent-pool page rather than a normal job: {non_role_marker}"

        return ""

    def _mandatory_qualification_reason(self, job: dict, preopen: bool = False) -> str:
        combined_text = self._combined_job_text(job)
        text = combined_text if not preopen else combined_text[:2500]

        def requirement_pattern(subject_pattern: str) -> str:
            return (
                rf"(?:{subject_pattern}).{{0,40}}(?:required|mandatory|must have|must hold|essential)"
                rf"|(?:required|mandatory|must have|must hold|essential).{{0,40}}(?:{subject_pattern})"
            )

        subject_patterns = {
            "healthcare license or medical qualification": (
                r"big registration|big-registratie|registered nurse|rn license|nursing license|"
                r"medical license|physician license|medical degree|doctor of medicine|"
                r"pharmacist license|dentistry degree|dentist license"
            ),
            "legal qualification": (
                r"law degree|llb|llm|bar admission|admitted to the bar|"
                r"solicitor qualification|attorney qualification|advocaat"
            ),
            "specialized engineering qualification": (
                r"civil engineering degree|mechanical engineering degree|electrical engineering degree|"
                r"chemical engineering degree|structural engineering degree|"
                r"professional engineer license|pe license|chartered engineer"
            ),
            "specialized accounting certification": (
                r"cpa|acca|chartered accountant|ra certification|registeraccountant"
            ),
            "driver's license": (
                r"driver'?s license|driving license|rijbewijs"
            ),
        }

        for label, subject_pattern in subject_patterns.items():
            if re.search(requirement_pattern(subject_pattern), text, flags=re.IGNORECASE | re.DOTALL):
                return f"Role has a mandatory hard qualification requirement: {label}"

        return ""

    def _incompatible_language_requirement(self, job: dict) -> str:
        combined_text = self._combined_job_text(job)
        dutch_marker = self._first_matching_marker(combined_text, self.DUTCH_REQUIREMENT_MARKERS)
        if dutch_marker:
            return f"Job explicitly requires high Dutch fluency: {dutch_marker}"

        contextual_dutch = self._contextual_fluent_dutch_requirement(job)
        if contextual_dutch:
            return contextual_dutch

        other_markers = self.PREOPEN_LANGUAGE_MARKERS - self.DUTCH_REQUIREMENT_MARKERS
        other_marker = self._first_matching_marker(combined_text, other_markers)
        if other_marker:
            return f"Job requires an incompatible language signal: {other_marker}"

        return ""

    def _obvious_false_positive_reason(self, query: str, job: dict) -> str:
        family = self._query_family(query)
        if family not in {"creative_brand", "ux_product"}:
            return ""

        listing_text = self._listing_text(job)
        marker = self._first_matching_marker(listing_text, self.CREATIVE_FALSE_POSITIVE_MARKERS)
        if marker:
            return f"Obvious false-positive for {query}: {marker}"
        return ""

    def _safe_console_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        return normalized.encode("ascii", errors="ignore").decode("ascii")

    def _description_extracted(self, job: dict) -> bool:
        return bool((job.get("description") or "").strip())

    def _description_preview(self, description: str, max_chars: int = 220) -> str:
        normalized = re.sub(r"\s+", " ", (description or "").strip())
        if len(normalized) <= max_chars:
            return normalized
        return normalized[: max_chars - 3].rstrip() + "..."
