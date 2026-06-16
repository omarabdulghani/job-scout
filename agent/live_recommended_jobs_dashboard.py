"""Live JSON writer for the recommended jobs dashboard.

This module owns only the live dashboard data file. It does not touch the
existing final scout outputs.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Callable

from agent.job_metadata import APPLY_METHOD_LABELS, normalize_apply_method
from agent.job_scope_metadata import (
    classify_historical_career_lane,
    enrich_job_scope_metadata,
)
from agent.safe_file_io import (
    DEFAULT_RETRY_DELAYS,
    atomic_write_json,
    load_json_with_recovery,
)


SCHEMA_VERSION = "live_dashboard.v1"
CAREER_LANE_BACKFILL_VERSION = 1
SCOPE_METADATA_BACKFILL_VERSION = 1
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
        self._migration_applied = False
        self.data = self._load_or_create()
        if self._migration_applied:
            self._refresh_metadata()
            self.write()

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
        fresh_policy: dict[str, Any] | None = None,
        search_goal: str = "",
        selected_search_groups: list[str] | None = None,
        query_plan: dict[str, Any] | None = None,
        search_scope: dict[str, Any] | None = None,
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
            "search_goal": _clean_text(search_goal),
            "selected_search_groups": _clean_string_list(selected_search_groups or []),
            "query_plan": dict(query_plan or {}),
            "search_scope": dict(search_scope or {}),
            "stats": self._empty_run_stats(),
            "fresh_scout": self._empty_fresh_scout(fresh_policy),
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

    def update_run_progress(
        self,
        run_id: str | None = None,
        **progress: Any,
    ) -> dict[str, Any]:
        resolved_run_id = _clean_text(run_id or self.data.get("active_run_id"))
        if not resolved_run_id:
            raise ValueError("run_id is required to update live dashboard progress")

        run = self._find_run(resolved_run_id)
        if not run:
            raise ValueError(f"Unknown live dashboard run_id: {resolved_run_id}")

        fresh_policy = progress.pop("fresh_policy", None)
        fresh = run.setdefault("fresh_scout", self._empty_fresh_scout(fresh_policy))
        if not isinstance(fresh, dict):
            fresh = self._empty_fresh_scout(fresh_policy)
            run["fresh_scout"] = fresh
        if isinstance(fresh_policy, dict) and fresh_policy:
            fresh["enabled"] = bool(fresh_policy.get("enabled", True))
            fresh["policy"] = dict(fresh_policy)
        elif "fresh_enabled" in progress:
            fresh["enabled"] = bool(progress.get("fresh_enabled"))

        page_quality = progress.pop("page_quality", None)
        if isinstance(page_quality, dict) and page_quality:
            self._upsert_fresh_page(fresh, page_quality)

        target = fresh.setdefault("progress", self._empty_fresh_progress())
        allowed_text = {
            "phase",
            "current_query",
            "current_search_group",
            "current_search_phase",
            "stop_reason",
            "latest_persistence_warning",
        }
        allowed_int = {
            "current_query_index",
            "total_queries",
            "current_page_number",
            "pages_scanned",
            "fresh_jobs_seen",
            "processed_jobs",
            "opened_jobs",
            "survived_to_ai",
            "ai_scored",
            "apply_first",
            "good_or_better",
            "persistence_warning_count",
        }
        for key in allowed_text:
            if key in progress:
                target[key] = _clean_text(progress.get(key))
        for key in allowed_int:
            if key in progress:
                target[key] = _safe_int(progress.get(key))
        if "stopped_early" in progress:
            target["stopped_early"] = bool(progress.get("stopped_early"))
        target["updated_at"] = self._now_iso()

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
        reason: str = "",
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    ) -> dict[str, Any]:
        return self.transition_run(
            run_id,
            status=status,
            transitioned_at=completed_at,
            reason=reason,
            retry_delays=retry_delays,
        )

    def transition_run(
        self,
        run_id: str | None = None,
        *,
        status: str,
        transitioned_at: str | None = None,
        reason: str = "",
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    ) -> dict[str, Any]:
        """Apply one terminal lifecycle state and clear stale active-run metadata."""
        resolved_run_id = _clean_text(run_id or self.data.get("active_run_id"))
        if not resolved_run_id:
            raise ValueError("run_id is required to complete a live dashboard run")

        run = self._find_run(resolved_run_id)
        if not run:
            raise ValueError(f"Unknown live dashboard run_id: {resolved_run_id}")

        allowed_statuses = {"completed", "stopped", "interrupted", "failed"}
        resolved_status = status if status in allowed_statuses else "completed"
        event_at = transitioned_at or self._now_iso()
        run["status"] = resolved_status
        run["completed_at"] = event_at
        if resolved_status == "interrupted":
            run["interrupted_at"] = event_at
            run["interruption_reason"] = _clean_text(reason)
        elif resolved_status == "failed":
            run["failure_reason"] = _clean_text(reason)
        fresh = run.get("fresh_scout")
        if isinstance(fresh, dict):
            progress = fresh.setdefault("progress", self._empty_fresh_progress())
            progress["phase"] = resolved_status
            if reason:
                progress["stop_reason"] = _clean_text(reason)
            progress["updated_at"] = event_at
        if self.data.get("active_run_id") == resolved_run_id:
            self.data["active_run_id"] = ""
        self._refresh_metadata()
        self.write(retry_delays=retry_delays)
        return dict(run)

    def resume_run(self, run_id: str) -> dict[str, Any]:
        """Reopen a saved interrupted/failed/stopped run without duplicating it."""
        resolved_run_id = _clean_text(run_id)
        run = self._find_run(resolved_run_id)
        if not run:
            raise ValueError(f"Unknown live dashboard run_id: {resolved_run_id}")
        if run.get("status") == "completed":
            raise ValueError(f"Completed live dashboard run cannot be resumed: {resolved_run_id}")
        run["status"] = "running"
        run["completed_at"] = ""
        run["interrupted_at"] = ""
        run["interruption_reason"] = ""
        run["failure_reason"] = ""
        fresh = run.get("fresh_scout")
        if isinstance(fresh, dict):
            progress = fresh.setdefault("progress", self._empty_fresh_progress())
            progress["phase"] = "resumed"
            progress["stop_reason"] = ""
            progress["updated_at"] = self._now_iso()
        self.data["active_run_id"] = resolved_run_id
        self._refresh_metadata()
        self.write()
        return dict(run)

    def trim_historical_runs(self, keep_latest_runs: int = 10) -> None:
        """Keep only the N most recent runs and their associated jobs."""
        runs = self.data.get("runs", [])
        if not isinstance(runs, list) or len(runs) <= max(1, keep_latest_runs):
            return
            
        runs.sort(key=lambda r: str(r.get("started_at") or ""))
        kept_runs = runs[-max(1, keep_latest_runs):]
        kept_run_ids = {str(r.get("run_id") or "") for r in kept_runs if r.get("run_id")}
        
        active_run_id = self.data.get("active_run_id")
        if active_run_id and active_run_id not in kept_run_ids:
            active_run = self._find_run(active_run_id)
            if active_run:
                kept_runs.append(active_run)
                kept_run_ids.add(active_run_id)
                
        jobs = self.data.get("jobs", [])
        if isinstance(jobs, list):
            kept_jobs = [
                job for job in jobs
                if isinstance(job, dict) and str(job.get("run_id") or "") in kept_run_ids
            ]
            self.data["jobs"] = kept_jobs
            
        self.data["runs"] = kept_runs
        self._refresh_metadata()
        self.write()

    def write(
        self,
        *,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
    ) -> None:
        atomic_write_json(self.data_path, self.data, retry_delays=retry_delays)

    def _load_or_create(self) -> dict[str, Any]:
        payload = load_json_with_recovery(self.data_path)
        if payload.get("schema_version") == SCHEMA_VERSION:
            payload.setdefault("runs", [])
            payload.setdefault("jobs", [])
            payload.setdefault("summary", {})
            payload.setdefault("filter_options", {})
            run_scopes = {
                str(run.get("run_id") or ""): dict(run.get("search_scope") or {})
                for run in payload["runs"]
                if isinstance(run, dict) and run.get("run_id")
            }
            migration = payload.setdefault("migrations", {})
            backfill = migration.get("career_lane_backfill", {})
            backfill_version = _safe_int(
                backfill.get("version") if isinstance(backfill, dict) else 0
            )
            scope_backfill = migration.get("scope_metadata_backfill", {})
            scope_backfill_version = _safe_int(
                scope_backfill.get("version") if isinstance(scope_backfill, dict) else 0
            )
            scope_backfill_fields = (
                "career_lane",
                "search_market",
                "country",
                "employment_types",
                "weekly_hours",
                "flexible_hours",
                "sponsorship_status",
                "relocation_required",
                "relocation_support",
                "housing_support",
                "health_insurance",
                "annual_flight_support",
                "compensation_text",
                "contract_type",
                "market_concerns",
            )
            before_counts = self._career_lane_counts(payload["jobs"])
            changed_samples: list[dict[str, str]] = []
            changed_count = 0
            scope_changed_count = 0
            scope_changed_samples: list[dict[str, str]] = []
            for job in payload["jobs"]:
                if not isinstance(job, dict):
                    continue
                existing_lane = _clean_text(job.get("career_lane")).lower()
                metadata = enrich_job_scope_metadata(
                    job,
                    job.get("search_scope")
                    or run_scopes.get(str(job.get("run_id") or ""), {}),
                    ai_result=job,
                )
                if (
                    backfill_version < CAREER_LANE_BACKFILL_VERSION
                    and existing_lane in {"", "other"}
                ):
                    historical_lane = classify_historical_career_lane(job)
                    metadata["career_lane"] = historical_lane
                    if historical_lane != "other":
                        job["career_lane_source"] = (
                            f"historical_backfill_v{CAREER_LANE_BACKFILL_VERSION}"
                        )
                        changed_count += 1
                        if len(changed_samples) < 20:
                            changed_samples.append(
                                {
                                    "job_id": _clean_text(job.get("job_id")),
                                    "title": _clean_text(job.get("title")),
                                    "company": _clean_text(job.get("company")),
                                    "from": existing_lane or "missing",
                                    "to": historical_lane,
                                }
                            )
                scope_changed = (
                    scope_backfill_version < SCOPE_METADATA_BACKFILL_VERSION
                    and any(job.get(key) in (None, "", [], {}) for key in scope_backfill_fields)
                )
                for key, value in metadata.items():
                    if key == "career_lane" and existing_lane in {"", "other"}:
                        job[key] = value
                    elif job.get(key) in (None, "", [], {}):
                        job[key] = value
                if scope_changed:
                    scope_changed_count += 1
                    if len(scope_changed_samples) < 20:
                        scope_changed_samples.append(
                            {
                                "job_id": _clean_text(job.get("job_id")),
                                "title": _clean_text(job.get("title")),
                                "company": _clean_text(job.get("company")),
                            }
                        )
            if backfill_version < CAREER_LANE_BACKFILL_VERSION:
                migration["career_lane_backfill"] = {
                    "version": CAREER_LANE_BACKFILL_VERSION,
                    "applied_at": self._now_iso(),
                    "changed_count": changed_count,
                    "before_counts": before_counts,
                    "after_counts": self._career_lane_counts(payload["jobs"]),
                    "sample_changes": changed_samples,
                }
                self._migration_applied = True
            if scope_backfill_version < SCOPE_METADATA_BACKFILL_VERSION:
                migration["scope_metadata_backfill"] = {
                    "version": SCOPE_METADATA_BACKFILL_VERSION,
                    "applied_at": self._now_iso(),
                    "changed_count": scope_changed_count,
                    "sample_changes": scope_changed_samples,
                }
                self._migration_applied = True
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
            "migrations": {
                "career_lane_backfill": {
                    "version": CAREER_LANE_BACKFILL_VERSION,
                    "applied_at": self._now_iso(),
                    "changed_count": 0,
                    "before_counts": {},
                    "after_counts": {},
                    "sample_changes": [],
                },
                "scope_metadata_backfill": {
                    "version": SCOPE_METADATA_BACKFILL_VERSION,
                    "applied_at": self._now_iso(),
                    "changed_count": 0,
                    "sample_changes": [],
                }
            },
        }

    def _career_lane_counts(self, jobs: list[Any]) -> dict[str, int]:
        counts = {lane: 0 for lane in ("primary", "bridge", "fallback", "other")}
        for job in jobs:
            if not isinstance(job, dict):
                continue
            lane = _clean_text(job.get("career_lane")).lower()
            counts[lane if lane in counts else "other"] += 1
        return counts

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

        apply_method = normalize_apply_method(event)
        apply_method_flags = []
        if apply_method == "easy_apply":
            apply_method_flags.append("easy_apply")
        elif apply_method == "external_apply":
            apply_method_flags.append("external_apply")
        inferred_flags = infer_flags(event, score=score, decision_category=decision_category)
        flags = _merge_unique_strings(
            event.get("flags", []),
            apply_method_flags,
            inferred_flags,
        )
        normalized_flags = {flag.lower() for flag in flags}
        if apply_method == "unknown" and "easy_apply" in normalized_flags:
            apply_method = "easy_apply"
        elif apply_method == "unknown" and "external_apply" in normalized_flags:
            apply_method = "external_apply"
        scope_metadata = enrich_job_scope_metadata(
            {
                **event,
                "title": title,
                "company": company,
                "location": location,
                "query": query,
                "domain": DOMAIN_LABELS.get(domain_category, ""),
            },
            event.get("search_scope") or run.get("search_scope"),
            ai_result=event,
        )

        normalized = {
            "event_id": _clean_text(event.get("event_id")) or identity,
            "run_id": run["run_id"],
            "run_label": run.get("run_label", ""),
            "processed_at": _clean_text(event.get("processed_at")) or self._now_iso(),
            "board": _clean_text(event.get("board") or run.get("board")),
            "query": query,
            "search_goal": _clean_text(event.get("search_goal") or run.get("search_goal")),
            "search_group": _clean_text(event.get("search_group")),
            "search_group_label": _search_group_label(event.get("search_group")),
            "matched_search_groups": _clean_string_list(
                event.get("matched_search_groups", [])
            ),
            "search_scope": dict(event.get("search_scope") or run.get("search_scope") or {}),
            "career_lane": scope_metadata["career_lane"],
            "search_market": scope_metadata["search_market"],
            "country": scope_metadata["country"],
            "employment_types": scope_metadata["employment_types"],
            "weekly_hours": scope_metadata["weekly_hours"],
            "flexible_hours": scope_metadata["flexible_hours"],
            "sponsorship_status": scope_metadata["sponsorship_status"],
            "relocation_required": scope_metadata["relocation_required"],
            "relocation_support": scope_metadata["relocation_support"],
            "housing_support": scope_metadata["housing_support"],
            "health_insurance": scope_metadata["health_insurance"],
            "annual_flight_support": scope_metadata["annual_flight_support"],
            "compensation_text": scope_metadata["compensation_text"],
            "contract_type": scope_metadata["contract_type"],
            "market_concerns": scope_metadata["market_concerns"],
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
            "easy_apply": apply_method == "easy_apply",
            "apply_method": apply_method,
            "apply_method_label": APPLY_METHOD_LABELS[apply_method],
            "apply_method_detection_source": _clean_text(event.get("apply_method_detection_source")),
            "flags": flags,
            "source_stage": source_stage,
            "terminal_status": terminal_status,
            "filter_notes": _clean_string_list(event.get("filter_notes", [])),
            "ai_model": _clean_text(event.get("ai_model") or event.get("model")),
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
            if key in {
                "seen_queries",
                "seen_pages",
                "flags",
                "filter_notes",
                "matched_search_groups",
                "employment_types",
                "market_concerns",
            }:
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
        merged["matched_search_groups"] = _merge_unique_strings(
            existing.get("matched_search_groups", []),
            incoming.get("matched_search_groups", []),
        )
        merged["employment_types"] = _merge_unique_strings(
            existing.get("employment_types", []),
            incoming.get("employment_types", []),
        )
        merged["market_concerns"] = _merge_unique_strings(
            existing.get("market_concerns", []),
            incoming.get("market_concerns", []),
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
            self._refresh_fresh_progress(run)

    def _build_summary(self) -> dict[str, Any]:
        jobs = [job for job in self.data.get("jobs", []) if isinstance(job, dict)]
        by_decision = {key: 0 for key in DECISION_LABELS}
        by_domain = {key: 0 for key in DOMAIN_LABELS}
        by_apply_method = {key: 0 for key in APPLY_METHOD_LABELS}
        by_career_lane = {key: 0 for key in ("primary", "bridge", "fallback", "other")}
        by_search_market: dict[str, int] = {}
        for job in jobs:
            decision = job.get("decision_category")
            domain = job.get("domain_category")
            apply_method = normalize_apply_method(job)
            if decision in by_decision:
                by_decision[decision] += 1
            if domain in by_domain:
                by_domain[domain] += 1
            if apply_method in by_apply_method:
                by_apply_method[apply_method] += 1
            lane = str(job.get("career_lane") or "other")
            by_career_lane[lane if lane in by_career_lane else "other"] += 1
            market = str(job.get("search_market") or "netherlands")
            by_search_market[market] = by_search_market.get(market, 0) + 1
        active_run_id = self.data.get("active_run_id", "")
        return {
            "total_runs": len(self.data.get("runs", [])),
            "total_jobs": len(jobs),
            "active_run_jobs": len([job for job in jobs if job.get("run_id") == active_run_id]),
            "by_decision": by_decision,
            "by_domain": by_domain,
            "by_apply_method": by_apply_method,
            "by_career_lane": by_career_lane,
            "by_search_market": by_search_market,
            "last_event_at": max((job.get("processed_at", "") for job in jobs), default=""),
        }

    def _build_run_stats(self, run_id: str) -> dict[str, Any]:
        stats = self._empty_run_stats()
        stats["by_search_group"] = {}
        stats["by_career_lane"] = {}
        stats["by_search_market"] = {}
        for job in self.data.get("jobs", []):
            if not isinstance(job, dict) or job.get("run_id") != run_id:
                continue
            decision = job.get("decision_category")
            self._increment_decision_stats(stats, decision)
            lane = _clean_text(job.get("career_lane") or "other").lower()
            lane_key = lane if lane in {"primary", "bridge", "fallback", "other"} else "other"
            self._increment_decision_stats(
                stats["by_career_lane"].setdefault(lane_key, self._empty_run_stats()),
                decision,
            )
            market = _clean_text(job.get("search_market") or "netherlands").lower()
            self._increment_decision_stats(
                stats["by_search_market"].setdefault(market, self._empty_run_stats()),
                decision,
            )
            search_group = _clean_text(job.get("search_group"))
            if search_group:
                group_stats = stats["by_search_group"].setdefault(
                    search_group,
                    self._empty_run_stats(),
                )
                self._increment_decision_stats(group_stats, decision)
        return stats

    def _increment_decision_stats(self, stats: dict[str, Any], decision: str) -> None:
        stats["processed_jobs"] = _safe_int(stats.get("processed_jobs")) + 1
        if decision == "APPLY_FIRST":
            stats["apply_first"] = _safe_int(stats.get("apply_first")) + 1
        elif decision == "GOOD_OPTIONS":
            stats["good_options"] = _safe_int(stats.get("good_options")) + 1
        elif decision == "LOW_PROBABILITY":
            stats["low_probability"] = _safe_int(stats.get("low_probability")) + 1
        elif decision == "REJECTED":
            stats["rejected"] = _safe_int(stats.get("rejected")) + 1

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
            "apply_methods": list(APPLY_METHOD_LABELS),
            "search_groups": sorted(
                {
                    group
                    for job in jobs
                    for group in _merge_unique_strings(
                        [job.get("search_group")],
                        job.get("matched_search_groups", []),
                    )
                    if group
                }
            ),
            "career_lanes": sorted(
                {str(job.get("career_lane") or "other") for job in jobs}
            ),
            "search_markets": sorted(
                {str(job.get("search_market") or "netherlands") for job in jobs}
            ),
            "employment_types": sorted(
                {
                    str(value)
                    for job in jobs
                    for value in job.get("employment_types", [])
                    if str(value)
                }
            ),
            "sponsorship_statuses": sorted(
                {
                    str(job.get("sponsorship_status") or "not_required")
                    for job in jobs
                }
            ),
            "platforms": sorted(
                {str(job.get("board") or "linkedin") for job in jobs}
            ),
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

    def _empty_fresh_scout(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        policy = policy if isinstance(policy, dict) else {}
        return {
            "enabled": bool(policy.get("enabled")),
            "policy": dict(policy),
            "progress": self._empty_fresh_progress(),
            "page_history": [],
        }

    def _empty_fresh_progress(self) -> dict[str, Any]:
        return {
            "phase": "",
            "current_query": "",
            "current_query_index": 0,
            "total_queries": 0,
            "current_page_number": 0,
            "pages_scanned": 0,
            "fresh_jobs_seen": 0,
            "known_jobs_skipped": 0,
            "processed_jobs": 0,
            "opened_jobs": 0,
            "survived_to_ai": 0,
            "ai_scored": 0,
            "apply_first": 0,
            "good_or_better": 0,
            "stopped_early": False,
            "stop_reason": "",
            "persistence_warning_count": 0,
            "latest_persistence_warning": "",
            "updated_at": "",
        }

    def _upsert_fresh_page(self, fresh: dict[str, Any], page_quality: dict[str, Any]) -> None:
        page = {
            "query": _clean_text(page_quality.get("query")),
            "page_number": _safe_int(page_quality.get("page_number")),
            "cards_seen": _safe_int(page_quality.get("cards_seen")),
            "valid_unique_cards": _safe_int(page_quality.get("valid_unique_cards")),
            "known_jobs": _safe_int(page_quality.get("known_jobs")),
            "new_jobs": _safe_int(page_quality.get("new_jobs")),
            "known_ratio": _safe_float(page_quality.get("known_ratio")),
            "duplicate_cards": _safe_int(page_quality.get("duplicate_cards")),
            "invalid_cards": _safe_int(page_quality.get("invalid_cards")),
            "total_new_jobs_collected": _safe_int(page_quality.get("total_new_jobs_collected")),
            "results_layout_type": _clean_text(page_quality.get("results_layout_type")),
            "has_additional_pages": bool(page_quality.get("has_additional_pages")),
            "scanned_at": self._now_iso(),
        }
        if not page["query"] or not page["page_number"]:
            return

        history = fresh.setdefault("page_history", [])
        if not isinstance(history, list):
            history = []
            fresh["page_history"] = history
        identity = (page["query"].lower(), page["page_number"])
        for index, existing in enumerate(history):
            if not isinstance(existing, dict):
                continue
            existing_identity = (
                _clean_text(existing.get("query")).lower(),
                _safe_int(existing.get("page_number")),
            )
            if existing_identity == identity:
                history[index] = page
                return
        history.append(page)

    def _refresh_fresh_progress(self, run: dict[str, Any]) -> None:
        fresh = run.get("fresh_scout")
        if not isinstance(fresh, dict) or not fresh.get("enabled"):
            return
        progress = fresh.setdefault("progress", self._empty_fresh_progress())
        if not isinstance(progress, dict):
            progress = self._empty_fresh_progress()
            fresh["progress"] = progress

        stats = run.get("stats", {}) if isinstance(run.get("stats"), dict) else {}
        page_history = [
            page for page in fresh.get("page_history", [])
            if isinstance(page, dict)
        ]
        progress["apply_first"] = _safe_int(stats.get("apply_first"))
        progress["good_or_better"] = _safe_int(stats.get("apply_first")) + _safe_int(stats.get("good_options"))
        progress["processed_jobs"] = max(
            _safe_int(progress.get("processed_jobs")),
            _safe_int(stats.get("processed_jobs")),
        )
        progress["known_jobs_skipped"] = sum(_safe_int(page.get("known_jobs")) for page in page_history)
        progress["fresh_jobs_seen"] = max(
            _safe_int(progress.get("fresh_jobs_seen")),
            sum(_safe_int(page.get("new_jobs")) for page in page_history),
        )
        progress["pages_scanned"] = max(
            _safe_int(progress.get("pages_scanned")),
            len(page_history),
        )
        progress["search_group_counts"] = dict(
            (run.get("stats", {}) or {}).get("by_search_group", {})
        )

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


def _safe_float(value: Any) -> float:
    try:
        return float(str(value or 0).strip())
    except (TypeError, ValueError):
        return 0.0


def _normalize_identity_text(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+/#-]+", " ", str(value or "").lower())).strip()


def _date_part(value: str) -> str:
    return _clean_text(value)[:10]


def _human_datetime(value: str) -> str:
    cleaned = _clean_text(value)
    if len(cleaned) >= 16:
        return cleaned[:16].replace("T", " ")
    return cleaned


def _search_group_label(value: Any) -> str:
    return {
        "primary": "Primary Path",
        "bridge": "Bridge Opportunity",
        "fallback": "Fallback Income",
    }.get(_clean_text(value).lower(), "")
