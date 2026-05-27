"""Live JSON writer for the recommended jobs dashboard.

This module owns only the live dashboard data file. It does not touch the
existing final scout outputs or the older recommended_jobs.html updater.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Callable


SCHEMA_VERSION = "live_dashboard.v1"
DEFAULT_DATA_PATH = Path("recommended_jobs_dashboard_data.json")

DECISION_LABELS = {
    "APPLY_FIRST": "APPLY FIRST",
    "GOOD_OPTIONS": "GOOD OPTIONS",
    "LOW_PROBABILITY": "LOW PROBABILITY",
    "REJECTED": "REJECTED",
}

DOMAIN_LABELS = {
    "UX_UI_PRODUCT_DESIGN": "UX/UI/Product Design",
    "BRAND_CREATIVE_CONTENT": "Brand/Creative/Content",
    "ECOMMERCE_WEB_DIGITAL_OPS": "E-commerce/Web/Digital Ops",
    "DATA_ANALYTICS_BUSINESS": "Data/Analytics/Business Analyst",
    "CUSTOMER_SUCCESS_OPS_SUPPORT": "Customer Success/Ops/Support",
    "PRODUCT_PROJECT_OPERATIONS": "Product/Project/Operations",
    "PROCUREMENT_SUPPLY_CHAIN": "Procurement/Supply Chain",
    "RESEARCH_ADMIN": "Research/Admin",
    "MARKETING_COMMUNICATIONS": "Marketing/Communications",
    "FINANCE_LEGAL_COMPLIANCE": "Finance/Legal/Compliance",
    "FALLBACK_INCOME": "Fallback/Income",
    "OTHER": "Other",
}


class LiveRecommendedJobsDashboard:
    """Maintain the live dashboard JSON state with atomic writes."""

    def __init__(
        self,
        data_path: Path | str | None = None,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.data_path = Path(data_path or DEFAULT_DATA_PATH)
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())
        self.data = self._load_or_create()

    def start_run(
        self,
        *,
        mode: str,
        board: str,
        location: str,
        max_pages: str | int | None,
        queries: list[str],
        started_at: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        started_at = started_at or self._now_iso()
        run_id = run_id or self._unique_run_id(started_at)
        run_number = self._next_run_number()
        run = {
            "run_id": run_id,
            "run_number": run_number,
            "run_label": self._run_label(run_number, started_at),
            "started_at": started_at,
            "completed_at": "",
            "status": "running",
            "mode": _clean_text(mode),
            "board": _clean_text(board),
            "location": _clean_text(location),
            "max_pages": "" if max_pages is None else str(max_pages),
            "queries": [_clean_text(query) for query in queries if _clean_text(query)],
            "stats": self._empty_run_stats(),
        }

        existing_index = self._run_index(run_id)
        if existing_index is None:
            self.data["runs"].append(run)
        else:
            self.data["runs"][existing_index].update(run)
            run = self.data["runs"][existing_index]

        self.data["active_run_id"] = run_id
        self._refresh_metadata()
        self.write()
        return dict(run)

    def record_job(self, job_event: dict[str, Any]) -> dict[str, Any]:
        run_id = _clean_text(job_event.get("run_id") or self.data.get("active_run_id"))
        if not run_id:
            raise ValueError("run_id is required before recording a live dashboard job")

        run = self._find_run(run_id)
        if not run:
            raise ValueError(f"Unknown live dashboard run_id: {run_id}")

        normalized = self._normalize_job_event(job_event, run)
        existing_index = self._job_index(normalized)
        if existing_index is None:
            self.data["jobs"].append(normalized)
            stored = normalized
        else:
            stored = self._merge_job_event(self.data["jobs"][existing_index], normalized)
            self.data["jobs"][existing_index] = stored

        self._refresh_metadata()
        self.write()
        return dict(stored)

    def complete_run(
        self,
        run_id: str | None = None,
        *,
        status: str = "completed",
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        resolved_run_id = _clean_text(run_id or self.data.get("active_run_id"))
        if not resolved_run_id:
            raise ValueError("run_id is required to complete a live dashboard run")

        run = self._find_run(resolved_run_id)
        if not run:
            raise ValueError(f"Unknown live dashboard run_id: {resolved_run_id}")

        run["status"] = status if status in {"completed", "stopped", "failed"} else "completed"
        run["completed_at"] = completed_at or self._now_iso()
        if self.data.get("active_run_id") == resolved_run_id:
            self.data["active_run_id"] = ""
        self._refresh_metadata()
        self.write()
        return dict(run)

    def write(self) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.data_path.with_name(f".{self.data_path.name}.tmp")
        temporary_path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, self.data_path)

    def _load_or_create(self) -> dict[str, Any]:
        if self.data_path.exists():
            try:
                payload = json.loads(self.data_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION:
                payload.setdefault("runs", [])
                payload.setdefault("jobs", [])
                payload.setdefault("summary", {})
                payload.setdefault("filter_options", {})
                return payload
        return {
            "schema_version": SCHEMA_VERSION,
            "dashboard_generated_at": self._now_iso(),
            "dashboard_updated_at": self._now_iso(),
            "active_run_id": "",
            "runs": [],
            "jobs": [],
            "summary": {},
            "filter_options": {},
        }

    def _normalize_job_event(self, event: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        score = _safe_int(event.get("score") or event.get("interview_probability_score"))
        terminal_status = _clean_text(event.get("terminal_status") or event.get("status"))
        source_stage = _clean_text(event.get("source_stage"))
        decision_category = _clean_text(event.get("decision_category")).upper()
        if decision_category not in DECISION_LABELS:
            decision_category = self._decision_category(score, terminal_status, source_stage)

        title = _clean_text(event.get("title"))
        company = _clean_text(event.get("company"))
        location = _clean_text(event.get("location"))
        query = _clean_text(event.get("query"))
        url = _canonical_job_url(event.get("url") or event.get("link"))
        job_id = _clean_text(event.get("job_id")) or _extract_job_id(url)
        identity = self._job_identity(
            run_id=run["run_id"],
            job_id=job_id,
            url=url,
            title=title,
            company=company,
            location=location,
        )
        domain_category = _clean_text(event.get("domain_category")).upper()
        if domain_category not in DOMAIN_LABELS:
            domain_category = classify_domain(
                title=title,
                query=query,
                description=event.get("description") or event.get("description_preview") or "",
            )

        flags = _merge_unique_strings(
            event.get("flags", []),
            infer_flags(event, score=score, decision_category=decision_category),
        )

        normalized = {
            "event_id": _clean_text(event.get("event_id")) or identity,
            "run_id": run["run_id"],
            "run_label": run.get("run_label", ""),
            "processed_at": _clean_text(event.get("processed_at")) or self._now_iso(),
            "board": _clean_text(event.get("board") or run.get("board")),
            "query": query,
            "page_number": _safe_int(event.get("page_number")),
            "job_index": _safe_int(event.get("job_index")),
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "job_id": job_id,
            "decision_category": decision_category,
            "decision_label": DECISION_LABELS[decision_category],
            "score": score,
            "domain_category": domain_category,
            "domain_label": DOMAIN_LABELS[domain_category],
            "reason": _clean_text(
                event.get("reason")
                or event.get("interview_probability_reason")
                or event.get("short_ai_reasoning")
                or event.get("why")
            ),
            "flags": flags,
            "source_stage": source_stage,
            "terminal_status": terminal_status,
            "filter_notes": _clean_string_list(event.get("filter_notes", [])),
            "ai": {
                "model": _clean_text(event.get("ai_model") or event.get("model")),
                "match_tier": _clean_text(event.get("match_tier") or event.get("ai_match_tier")),
                "cache_status": _clean_text(event.get("cache_status") or event.get("ai_cache_status")),
                "used_cv_second_stage": bool(event.get("used_cv_second_stage") or event.get("ai_used_cv_second_stage")),
            },
            "seen_queries": _merge_unique_strings(event.get("seen_queries", []), [query]),
            "seen_pages": _merge_unique_ints(event.get("seen_pages", []), [event.get("page_number")]),
            "duplicate_count": _safe_int(event.get("duplicate_count")),
        }

        for field in (
            "salary_text",
            "employment_type",
            "workplace_type",
            "description_preview",
            "company_application_count_14_days",
            "tracking_status",
            "tracking_updated_at",
        ):
            value = event.get(field)
            if value not in ("", None, [], {}):
                normalized[field] = value

        return normalized

    def _merge_job_event(self, existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = dict(existing)
        for key, value in incoming.items():
            if key in {"seen_queries", "seen_pages", "flags", "filter_notes"}:
                continue
            if value not in ("", None, [], {}):
                merged[key] = value

        merged["seen_queries"] = _merge_unique_strings(
            existing.get("seen_queries", []),
            incoming.get("seen_queries", []),
        )
        merged["seen_pages"] = _merge_unique_ints(
            existing.get("seen_pages", []),
            incoming.get("seen_pages", []),
        )
        merged["flags"] = _merge_unique_strings(existing.get("flags", []), incoming.get("flags", []))
        merged["filter_notes"] = _merge_unique_strings(
            existing.get("filter_notes", []),
            incoming.get("filter_notes", []),
        )
        merged["duplicate_count"] = _safe_int(existing.get("duplicate_count")) + 1
        return merged

    def _refresh_metadata(self) -> None:
        now = self._now_iso()
        self.data["dashboard_updated_at"] = now
        self.data["summary"] = self._build_summary()
        self.data["filter_options"] = self._build_filter_options()
        for run in self.data["runs"]:
            run["stats"] = self._build_run_stats(run.get("run_id", ""))

    def _build_summary(self) -> dict[str, Any]:
        jobs = [job for job in self.data.get("jobs", []) if isinstance(job, dict)]
        by_decision = {key: 0 for key in DECISION_LABELS}
        by_domain = {key: 0 for key in DOMAIN_LABELS}
        for job in jobs:
            decision = job.get("decision_category")
            domain = job.get("domain_category")
            if decision in by_decision:
                by_decision[decision] += 1
            if domain in by_domain:
                by_domain[domain] += 1
        active_run_id = self.data.get("active_run_id", "")
        return {
            "total_runs": len(self.data.get("runs", [])),
            "total_jobs": len(jobs),
            "active_run_jobs": len([job for job in jobs if job.get("run_id") == active_run_id]),
            "by_decision": by_decision,
            "by_domain": by_domain,
            "last_event_at": max((job.get("processed_at", "") for job in jobs), default=""),
        }

    def _build_run_stats(self, run_id: str) -> dict[str, int]:
        stats = self._empty_run_stats()
        for job in self.data.get("jobs", []):
            if not isinstance(job, dict) or job.get("run_id") != run_id:
                continue
            stats["processed_jobs"] += 1
            decision = job.get("decision_category")
            if decision == "APPLY_FIRST":
                stats["apply_first"] += 1
            elif decision == "GOOD_OPTIONS":
                stats["good_options"] += 1
            elif decision == "LOW_PROBABILITY":
                stats["low_probability"] += 1
            elif decision == "REJECTED":
                stats["rejected"] += 1
        return stats

    def _build_filter_options(self) -> dict[str, Any]:
        jobs = [job for job in self.data.get("jobs", []) if isinstance(job, dict)]
        return {
            "runs": [
                {
                    "run_id": run.get("run_id", ""),
                    "label": run.get("run_label", ""),
                    "date": _date_part(run.get("started_at", "")),
                }
                for run in self.data.get("runs", [])
                if isinstance(run, dict)
            ],
            "decisions": list(DECISION_LABELS),
            "domains": sorted({job.get("domain_category", "OTHER") for job in jobs if job.get("domain_category")}),
            "flags": sorted({flag for job in jobs for flag in job.get("flags", []) if flag}),
        }

    def _decision_category(self, score: int, terminal_status: str, source_stage: str) -> str:
        terminal = terminal_status.lower()
        stage = source_stage.lower()
        if terminal.startswith("rejected") or terminal.startswith("skipped") or "invalid" in stage:
            return "REJECTED"
        if terminal == "ai_error":
            return "LOW_PROBABILITY"
        if score >= 70:
            return "APPLY_FIRST"
        if score >= 50:
            return "GOOD_OPTIONS"
        return "LOW_PROBABILITY"

    def _job_index(self, incoming: dict[str, Any]) -> int | None:
        incoming_identity = self._job_identity(
            run_id=incoming.get("run_id", ""),
            job_id=incoming.get("job_id", ""),
            url=incoming.get("url", ""),
            title=incoming.get("title", ""),
            company=incoming.get("company", ""),
            location=incoming.get("location", ""),
        )
        for index, job in enumerate(self.data.get("jobs", [])):
            if not isinstance(job, dict):
                continue
            current_identity = self._job_identity(
                run_id=job.get("run_id", ""),
                job_id=job.get("job_id", ""),
                url=job.get("url", ""),
                title=job.get("title", ""),
                company=job.get("company", ""),
                location=job.get("location", ""),
            )
            if current_identity == incoming_identity:
                return index
        return None

    def _job_identity(
        self,
        *,
        run_id: str,
        job_id: str,
        url: str,
        title: str,
        company: str,
        location: str,
    ) -> str:
        run_part = _clean_text(run_id)
        if job_id:
            return f"{run_part}:job_id:{job_id}"
        canonical_url = _canonical_job_url(url)
        if canonical_url:
            return f"{run_part}:url:{canonical_url.lower()}"
        normalized_title = _normalize_identity_text(title)
        normalized_company = _normalize_identity_text(company)
        normalized_location = _normalize_identity_text(location)
        return f"{run_part}:title_company_location:{normalized_title}::{normalized_company}::{normalized_location}"

    def _find_run(self, run_id: str) -> dict[str, Any] | None:
        index = self._run_index(run_id)
        if index is None:
            return None
        return self.data["runs"][index]

    def _run_index(self, run_id: str) -> int | None:
        for index, run in enumerate(self.data.get("runs", [])):
            if isinstance(run, dict) and run.get("run_id") == run_id:
                return index
        return None

    def _unique_run_id(self, started_at: str) -> str:
        base = "run_" + re.sub(r"[^0-9]", "", started_at[:19])[:14]
        if len(base) <= 4:
            base = "run_" + self._now_compact()
        candidate = base
        suffix = 2
        existing = {run.get("run_id") for run in self.data.get("runs", []) if isinstance(run, dict)}
        while candidate in existing:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def _next_run_number(self) -> int:
        numbers = [
            _safe_int(run.get("run_number"))
            for run in self.data.get("runs", [])
            if isinstance(run, dict)
        ]
        return max(numbers, default=0) + 1

    def _run_label(self, run_number: int, started_at: str) -> str:
        return f"Run {run_number} - {_human_datetime(started_at)}"

    def _empty_run_stats(self) -> dict[str, int]:
        return {
            "processed_jobs": 0,
            "apply_first": 0,
            "good_options": 0,
            "low_probability": 0,
            "rejected": 0,
        }

    def _now_iso(self) -> str:
        return self.now_provider().isoformat()

    def _now_compact(self) -> str:
        return self.now_provider().strftime("%Y%m%d%H%M%S")


def classify_domain(*, title: str, query: str = "", description: str = "") -> str:
    text = _normalize_identity_text(f"{title} {query} {description}")
    groups = [
        ("UX_UI_PRODUCT_DESIGN", ["ux", "ui", "product design", "product designer", "figma", "prototype", "user research"]),
        ("BRAND_CREATIVE_CONTENT", ["brand", "creative", "content", "ugc", "social media", "storytelling", "visual"]),
        ("ECOMMERCE_WEB_DIGITAL_OPS", ["ecommerce", "e commerce", "e-commerce", "shopify", "cms", "web content", "merchandising", "digital merchandiser"]),
        ("DATA_ANALYTICS_BUSINESS", ["data analyst", "analytics", "reporting", "insights", "business analyst", "power bi", "sql", "dashboard"]),
        ("CUSTOMER_SUCCESS_OPS_SUPPORT", ["customer success", "customer operations", "customer support", "case investigation", "support operations", "partner experience"]),
        ("PRODUCT_PROJECT_OPERATIONS", ["product coordinator", "project coordinator", "operations coordinator", "product operations", "digital operations", "project assistant"]),
        ("PROCUREMENT_SUPPLY_CHAIN", ["procurement", "supply chain", "supplier", "purchasing"]),
        ("RESEARCH_ADMIN", ["research assistant", "clinical study", "research admin", "study assistant", "administrative"]),
        ("MARKETING_COMMUNICATIONS", ["marketing communications", "campaign", "influencer", "communications", "product marketing"]),
        ("FINANCE_LEGAL_COMPLIANCE", ["finance", "accounting", "legal", "compliance"]),
        ("FALLBACK_INCOME", ["receptionist", "office assistant", "retail", "hospitality", "order processing", "travel consultant"]),
    ]
    for domain, markers in groups:
        if any(marker in text for marker in markers):
            return domain
    return "OTHER"


def infer_flags(event: dict[str, Any], *, score: int, decision_category: str) -> list[str]:
    text = _normalize_identity_text(
        " ".join(
            str(event.get(field, ""))
            for field in (
                "title",
                "query",
                "location",
                "reason",
                "description",
                "description_preview",
                "salary_text",
                "employment_type",
            )
        )
    )
    flags: list[str] = []
    marker_flags = {
        "dutch_risk": ["fluent dutch", "b2 dutch", "dutch preferred", "local language", "vloeiend nederlands"],
        "high_dutch_blocker": ["native dutch", "professional dutch", "excellent dutch", "c1 dutch", "c2 dutch", "moedertaal"],
        "commute_risk": ["utrecht", "rotterdam", "the hague", "den haag", "leiden", "hilversum", "almere"],
        "low_pay": ["low pay", "allowance", "500 per month", "600 per month", "700 per month"],
        "internship": ["internship", "intern ", "stagiaire", "stagevergoeding"],
        "current_student_required": ["current student", "currently enrolled", "student status", "thesis internship", "afstudeerstage"],
        "training_based": ["training", "trainee", "traineeship", "graduate programme", "graduate program"],
        "graduate_friendly": ["recent graduate", "graduates welcome", "graduate-friendly"],
        "english_friendly": ["english-friendly", "english friendly"],
        "seniority_risk": ["3-6 years", "3+ years", "4+ years"],
        "hard_seniority_blocker": ["5+ years", "senior", "lead", "principal", "director"],
        "heavy_technical_requirement": ["snowflake", "dbt", "production data", "machine learning engineering"],
        "sales_cold_calling": ["cold calling", "outbound sales", "sales targets"],
        "recruitment_pressure": ["recruitment", "recruiter", "talent acquisition"],
        "fallback_income": ["customer support", "receptionist", "office assistant", "retail", "hospitality"],
        "strong_bridge_role": ["customer success", "business analyst", "data analyst", "operations", "implementation consultant"],
        "creative_fit": ["creative", "brand", "ux", "ui", "figma", "visual storytelling"],
        "data_training_opportunity": ["data analyst", "power bi", "sql", "analytics trainee", "bi trainee"],
        "ai_error": ["ai error", "ai scoring failed"],
        "cached_score": ["cached", "reused"],
        "duplicate_suppressed": ["duplicate"],
        "external_apply": ["external apply"],
        "easy_apply": ["easy apply"],
    }
    for flag, markers in marker_flags.items():
        if any(marker in text for marker in markers):
            flags.append(flag)
    if decision_category == "GOOD_OPTIONS":
        flags.append("manual_review_needed")
    if score and score < 50:
        flags.append("manual_review_needed")
    return flags


def _canonical_job_url(value: Any) -> str:
    text = _clean_text(value)
    job_id = _extract_job_id(text)
    if job_id and "linkedin.com" in text.lower():
        return f"https://www.linkedin.com/jobs/view/{job_id}/"
    return text


def _extract_job_id(value: Any) -> str:
    text = str(value or "")
    for pattern in (r"/jobs/view/(\d+)", r"[?&]currentJobId=(\d+)", r"[?&]jk=([A-Za-z0-9_-]+)"):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []
    return [_clean_text(item) for item in candidates if _clean_text(item)]


def _merge_unique_strings(*groups: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for group in groups:
        candidates = [group] if isinstance(group, str) else group if isinstance(group, list) else []
        for candidate in candidates:
            cleaned = _clean_text(candidate)
            lowered = cleaned.lower()
            if cleaned and lowered not in seen:
                seen.add(lowered)
                values.append(cleaned)
    return values


def _merge_unique_ints(*groups: Any) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()
    for group in groups:
        candidates = group if isinstance(group, list) else [group]
        for candidate in candidates:
            value = _safe_int(candidate)
            if value and value not in seen:
                seen.add(value)
                values.append(value)
    return values


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value or 0).strip()))
    except (TypeError, ValueError):
        return 0


def _normalize_identity_text(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+/#-]+", " ", str(value or "").lower())).strip()


def _date_part(value: str) -> str:
    return _clean_text(value)[:10]


def _human_datetime(value: str) -> str:
    cleaned = _clean_text(value)
    if len(cleaned) >= 16:
        return cleaned[:16].replace("T", " ")
    return cleaned
