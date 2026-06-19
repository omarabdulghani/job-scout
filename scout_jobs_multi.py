import argparse
import asyncio
from datetime import datetime
import json
import os
import re
import sys
from pathlib import Path
from agent.env_loader import load_workspace_env
from rich.console import Console
from rich.panel import Panel

from agent.browser import BrowserController
from agent.fresh_scout_policy import FreshScoutPolicy
from agent.indeed_job_scout import IndeedJobScout
from agent.job_scout import LinkedInJobScout
from agent.scout_cli_modes import (
    add_board_mode_arguments,
    board_display_name,
    default_browser_profile_dir,
    requires_description_only,
    resolve_board_mode,
    supported_browser_executable,
)
from agent.scout_console_reporter import ScoutConsoleReporter
from agent.scout_progress import ScoutProgressStore
from agent.live_recommended_jobs_dashboard import LiveRecommendedJobsDashboard
from agent.query_learning import order_queries_with_learning
from agent.search_query_plan import (
    SEARCH_GOAL_LABELS,
    build_search_query_plan,
    query_plan_metadata,
)
from agent.search_scope import (
    EMPLOYMENT_PREFERENCES,
    SEARCH_MARKETS,
    build_search_scope,
    normalize_search_scope,
    search_scope_summary,
)
from agent.safe_file_io import DEFAULT_RETRY_DELAYS, PersistenceError
from agent.scout_review_latest import ScoutReviewLatestWriter
from agent.job_tracking import JobTrackingStore
from agent.scout_run_logger import ScoutRunLogger
from agent.scout_stop import clear_stop_request, stop_reason, stop_requested
from agent.user_workspace import UserWorkspace, active_search_queries_path, load_user_config

load_workspace_env()
console = Console()
ACTIVE_RUN_LOGGER: ScoutRunLogger | None = None

DEFAULT_QUERY_FILE = Path("search_queries.txt")
OUTPUT_PATH = Path("data/high_success_probability_jobs_multi.json")
PROGRESS_MODE = "multi_query_scout"
FRESH_COUNT_KEYS = ("apply_first", "good_or_better", "new_jobs_seen", "ai_calls")
FINAL_PERSISTENCE_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.0, 1.0, 1.0, 1.0, 1.0)


def load_config() -> tuple[dict, dict]:
    try:
        return load_user_config()
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


def _parse_max_pages(value: str | int | None) -> tuple[int | None, str]:
    raw = str(value or "2").strip().lower()
    if raw == "all":
        return None, "all"

    try:
        parsed = max(1, int(raw))
    except ValueError as exc:
        raise SystemExit("--max-pages must be a positive integer or 'all'.") from exc

    return parsed, str(parsed)


def _load_queries(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(f"Query file not found at {path}")

    queries: list[str] = []
    seen = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        normalized = re.sub(r"\s+", " ", stripped)
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(normalized)

    if not queries:
        raise SystemExit(f"No usable queries found in {path}")

    return queries


def _legacy_query_plan(queries: list[str], *, search_goal: str = "legacy") -> dict:
    return {
        "schema_version": "legacy_flat_queries.v1",
        "search_goal": search_goal,
        "search_goal_label": SEARCH_GOAL_LABELS.get(search_goal, search_goal),
        "selected_groups": [],
        "phase_order": [],
        "initial_coverage_count": 0,
        "ai_budget_eligible_after_index": -1,
        "entries": [
            {
                "query": query,
                "search_group": "",
                "matched_search_groups": [],
                "phase": "",
                "initial_coverage": False,
            }
            for query in queries
        ],
        "queries": list(queries),
        "query_learning": {},
    }


def _parse_search_groups(value: str | None) -> list[str]:
    groups: list[str] = []
    for raw in str(value or "").split(","):
        group = raw.strip().lower()
        if not group:
            continue
        if group not in {"primary", "bridge", "fallback"}:
            raise SystemExit("--search-groups may contain only primary, bridge, and fallback.")
        if group not in groups:
            groups.append(group)
    return groups


def _expected_query_file(
    query_source_path: Path,
    *,
    progress: dict,
    resume: bool,
) -> str:
    if resume and progress.get("query_file"):
        return str(progress.get("query_file"))
    return str(query_source_path.resolve())


def _annotate_report_search_metadata(
    report: dict,
    metadata: dict,
    search_goal: str,
    search_scope: dict | None = None,
) -> None:
    report["search_goal"] = search_goal
    report["search_group"] = metadata.get("search_group", "")
    report["matched_search_groups"] = list(metadata.get("matched_search_groups", []))
    report["search_phase"] = metadata.get("phase", "")
    report["search_scope"] = dict(search_scope or {})
    for _, job in _iter_report_jobs(report):
        job["search_goal"] = search_goal
        job["search_group"] = metadata.get("search_group", "")
        job["matched_search_groups"] = list(metadata.get("matched_search_groups", []))
        job["search_scope"] = dict(search_scope or {})
        job["search_market"] = str((search_scope or {}).get("search_market") or "")


def _query_learning_summary(query_learning: dict) -> str:
    if not query_learning:
        return "disabled"
    if "enabled" in query_learning:
        if query_learning.get("enabled"):
            label = (
                "enabled"
                + (
                    "; reordered queries"
                    if query_learning.get("reordered")
                    else "; kept query-file order"
                )
            )
            top_queries = [
                item.get("query", "")
                for item in query_learning.get("top_queries", [])[:3]
                if item.get("query")
            ]
            return label + (f"; top: {', '.join(top_queries)}" if top_queries else "")
        return str(query_learning.get("reason") or "disabled")

    summaries = []
    for group in ("primary", "bridge", "fallback"):
        metadata = query_learning.get(group)
        if not isinstance(metadata, dict):
            continue
        if metadata.get("enabled"):
            summaries.append(
                f"{group}: {'reordered' if metadata.get('reordered') else 'learned order'}"
            )
        else:
            summaries.append(f"{group}: {metadata.get('reason') or 'disabled'}")
    return "; ".join(summaries) or "disabled"


def _normalize_query(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def _ai_backend_label(scout: LinkedInJobScout) -> str:
    backend = (scout.brain.scoring_backend or "claude").strip().lower()
    if backend == "auto":
        labels = [
            scout.brain._hosted_model_label(item)
            for item in scout.brain._configured_auto_backends()
        ]
        return "Auto (" + " -> ".join(labels) + ")" if labels else "Auto (no configured providers)"
    if backend == "cerebras":
        return f"Cerebras ({scout.brain.cerebras_model or '<unset>'})"
    if backend == "ollama_cloud":
        return f"Ollama Cloud ({scout.brain.ollama_model or '<unset>'})"
    if backend == "openai_compatible":
        return f"OpenAI-compatible ({scout.brain.openai_compatible_model or '<unset>'})"
    if backend == "gemini":
        return f"Gemini ({scout.brain.gemini_model or '<unset>'})"
    if backend == "lmstudio":
        return f"LM Studio ({scout.brain.lmstudio_model or '<unset>'})"
    return f"Claude ({scout.brain.model})"


def _iter_report_jobs(report: dict):
    for bucket_name in ("new_recommendations", "cached_previous_recommendations"):
        grouped = report.get(bucket_name, {})
        if not isinstance(grouped, dict):
            continue
        for jobs in grouped.values():
            if not isinstance(jobs, list):
                continue
            for job in jobs:
                if isinstance(job, dict):
                    yield bucket_name, job

    for job in report.get("rejected_or_below_threshold", []):
        if isinstance(job, dict):
            yield "rejected_or_below_threshold", job


def _status_rank(status: str) -> int:
    normalized = (status or "").strip().lower()
    if normalized == "accepted":
        return 3
    if normalized == "duplicate_suppressed":
        return 2
    if normalized == "below_threshold":
        return 1
    return 0


def _match_tier(score: int, scout: LinkedInJobScout) -> str:
    if score >= scout.AI_STRONG_MATCH_THRESHOLD:
        return "strong_match"
    if score >= scout.AI_THRESHOLD:
        return "possible_match"
    return "weak_match"


def _dedupe_key(job: dict, tracker: JobTrackingStore) -> str:
    return tracker.cache_key_from_parts(job.get("job_id", ""), job.get("url", ""))


def _pick_best_occurrence(occurrences: list[dict], query_order: dict[str, int]) -> dict:
    def sort_key(item: dict):
        return (
            int(item.get("interview_probability_score", 0) or 0),
            _status_rank(item.get("output_status", "")),
            -query_order.get(item.get("query", ""), 10**6),
        )

    return max(occurrences, key=sort_key)


def _final_bucket_for_occurrences(occurrences: list[dict]) -> str:
    statuses = {(item.get("output_status") or "").strip().lower() for item in occurrences}
    if "accepted" in statuses:
        return "new_recommendations"
    if "duplicate_suppressed" in statuses:
        return "cached_previous_recommendations"
    return "rejected_or_below_threshold"


def _final_status_for_occurrences(occurrences: list[dict], final_bucket: str) -> str:
    if final_bucket == "new_recommendations":
        return "accepted"
    if final_bucket == "cached_previous_recommendations":
        return "duplicate_suppressed"
    statuses = {(item.get("output_status") or "").strip().lower() for item in occurrences}
    if "below_threshold" in statuses:
        return "below_threshold"
    return "ai_error"


def _merge_tracking(occurrences: list[dict]) -> tuple[str, str]:
    best_status = ""
    best_updated_at = ""
    for item in occurrences:
        status = (item.get("tracking_status") or "").strip()
        updated_at = (item.get("tracking_updated_at") or "").strip()
        if not status:
            continue
        if not best_status or updated_at > best_updated_at:
            best_status = status
            best_updated_at = updated_at
    return best_status, best_updated_at


def _build_query_hits(occurrences: list[dict], query_order: dict[str, int]) -> list[dict]:
    hits = []
    for item in sorted(
        occurrences,
        key=lambda entry: (
            -(int(entry.get("interview_probability_score", 0) or 0)),
            -_status_rank(entry.get("output_status", "")),
            query_order.get(entry.get("query", ""), 10**6),
        ),
    ):
        hits.append(
            {
                "query": item.get("query", ""),
                "interview_probability_score": int(item.get("interview_probability_score", 0) or 0),
                "ai_match_tier": item.get("ai_match_tier", "weak_match"),
                "output_status": item.get("output_status", ""),
                "ai_status": item.get("ai_status", item.get("output_status", "")),
                "search_group": item.get("search_group", ""),
                "matched_search_groups": list(
                    item.get("matched_search_groups", [])
                ),
            }
        )
    return hits


def _fresh_recommendation_counts(reports: list[dict], scout: LinkedInJobScout) -> dict[str, int]:
    tracker = JobTrackingStore()
    seen_keys: set[str] = set()
    apply_first = 0
    good_or_better = 0
    new_jobs_seen = 0
    ai_calls = 0

    for report in reports:
        stats = report.get("stats", {}) or {}
        new_jobs_seen += int(stats.get("job_cards_collected", 0) or 0)
        ai_calls += _fresh_ai_calls_from_stats(stats)
        for bucket_name, job in _iter_report_jobs(report):
            if bucket_name not in {"new_recommendations", "cached_previous_recommendations"}:
                continue
            status = str(job.get("output_status", "") or "").strip().lower()
            if status not in {"accepted", "duplicate_suppressed"}:
                continue
            key = _dedupe_key(job, tracker)
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            score = int(job.get("interview_probability_score", 0) or 0)
            if score < scout.AI_THRESHOLD:
                continue
            good_or_better += 1
            if score >= scout.AI_STRONG_MATCH_THRESHOLD:
                apply_first += 1

    return {
        "apply_first": apply_first,
        "good_or_better": good_or_better,
        "new_jobs_seen": new_jobs_seen,
        "ai_calls": ai_calls,
    }


def _normalize_fresh_counts(value: dict | None) -> dict[str, int]:
    counts = {}
    source = value if isinstance(value, dict) else {}
    for key in FRESH_COUNT_KEYS:
        try:
            counts[key] = max(0, int(source.get(key, 0) or 0))
        except (TypeError, ValueError):
            counts[key] = 0
    return counts


def _combine_fresh_counts(*count_sets: dict | None) -> dict[str, int]:
    combined = _normalize_fresh_counts({})
    for count_set in count_sets:
        normalized = _normalize_fresh_counts(count_set)
        for key in FRESH_COUNT_KEYS:
            combined[key] += normalized[key]
    return combined


def _fresh_ai_calls_from_stats(stats: dict) -> int:
    explicit_keys = {"ai_scored_new", "ai_cache_refreshed", "ai_cache_reused", "ai_errors"}
    if any(key in stats for key in explicit_keys):
        return sum(
            int(stats.get(key, 0) or 0)
            for key in ("ai_scored_new", "ai_cache_refreshed", "ai_errors")
        )
    return int(stats.get("survived_non_ai", 0) or 0)


def _fresh_ai_budget_stop_reason(counts: dict[str, int], policy: FreshScoutPolicy) -> str:
    if not policy.ai_budget_guard_enabled:
        return ""

    ai_calls = int(counts.get("ai_calls", 0) or 0)
    apply_first = int(counts.get("apply_first", 0) or 0)
    good_or_better = int(counts.get("good_or_better", 0) or 0)
    budget_mode = getattr(policy, "ai_budget_mode", "smart")

    if (
        budget_mode == "smart"
        and policy.ai_calls_quality_check
        and ai_calls >= policy.ai_calls_quality_check
        and apply_first < policy.min_apply_first_after_ai_quality_check
        and good_or_better < policy.min_good_or_better_after_ai_quality_check
    ):
        return (
            "AI budget guard: "
            f"{ai_calls} model call(s) produced only {apply_first} APPLY FIRST / "
            f"{good_or_better} GOOD+ jobs "
            f"(minimum {policy.min_apply_first_after_ai_quality_check} APPLY FIRST or "
            f"{policy.min_good_or_better_after_ai_quality_check} GOOD+ after "
            f"{policy.ai_calls_quality_check} calls)"
        )

    if (
        policy.ai_calls_strict_check
        and ai_calls >= policy.ai_calls_strict_check
        and apply_first < policy.min_apply_first_after_ai_strict_check
        and good_or_better < policy.min_good_or_better_after_ai_strict_check
    ):
        return (
            "AI budget guard: "
            f"{ai_calls} model call(s) produced only {apply_first} APPLY FIRST / "
            f"{good_or_better} GOOD+ jobs "
            f"(minimum {policy.min_apply_first_after_ai_strict_check} APPLY FIRST or "
            f"{policy.min_good_or_better_after_ai_strict_check} GOOD+ after "
            f"{policy.ai_calls_strict_check} calls)"
        )

    if policy.ai_calls_soft_cap and ai_calls >= policy.ai_calls_soft_cap:
        return (
            "AI budget guard: "
            f"processed {ai_calls} model call(s) before reaching fresh quality targets "
            f"(soft cap {policy.ai_calls_soft_cap})"
        )

    return ""


def _fresh_global_stop_reason(
    reports: list[dict],
    scout: LinkedInJobScout,
    policy: FreshScoutPolicy,
    base_counts: dict | None = None,
    *,
    allow_ai_budget_guard: bool = True,
) -> tuple[str, dict[str, int]]:
    counts = _combine_fresh_counts(base_counts, _fresh_recommendation_counts(reports, scout))
    if counts["apply_first"] >= policy.target_apply_first_jobs:
        return (
            f"found {counts['apply_first']} APPLY FIRST jobs "
            f"(target {policy.target_apply_first_jobs})",
            counts,
        )
    if counts["good_or_better"] >= policy.target_good_or_better_jobs:
        return (
            f"found {counts['good_or_better']} APPLY FIRST/GOOD OPTIONS jobs "
            f"(target {policy.target_good_or_better_jobs})",
            counts,
        )
    budget_reason = (
        _fresh_ai_budget_stop_reason(counts, policy)
        if allow_ai_budget_guard
        else ""
    )
    if budget_reason:
        return budget_reason, counts
    if counts["new_jobs_seen"] >= policy.global_new_jobs_soft_cap:
        return (
            f"processed {counts['new_jobs_seen']} fresh job cards "
            f"(soft cap {policy.global_new_jobs_soft_cap})",
            counts,
        )
    return "", counts


def _min_timestamp(values: list[str]) -> str:
    cleaned = sorted(value for value in values if isinstance(value, str) and value.strip())
    return cleaned[0] if cleaned else ""


def _max_timestamp(values: list[str]) -> str:
    cleaned = sorted(value for value in values if isinstance(value, str) and value.strip())
    return cleaned[-1] if cleaned else ""


def _build_merged_output(
    reports: list[dict],
    queries: list[str],
    query_file: Path,
    location: str,
    max_pages_label: str,
    scout: LinkedInJobScout,
    started_at: str = "",
    query_plan: dict | None = None,
) -> dict:
    tracker = JobTrackingStore()
    query_plan = query_plan or _legacy_query_plan(queries)
    query_order = {query: index for index, query in enumerate(queries)}
    per_query_summary = []
    merged: dict[str, dict] = {}
    total_occurrences = 0

    for report in reports:
        stats = report.get("stats", {})
        query = report.get("query", "")
        per_query_summary.append(
            {
                "query": query,
                "search_group": report.get("search_group", ""),
                "matched_search_groups": list(
                    report.get("matched_search_groups", [])
                ),
                "pages_scanned": stats.get("pages_scanned", report.get("pages_scanned", 0)),
                "total_scanned": stats.get("job_cards_collected", 0),
                "same_run_cross_query_reused": stats.get("same_run_cross_query_reused", 0),
                "previously_analyzed_jobs_skipped": stats.get("previously_analyzed_jobs_skipped", 0),
                "previously_analyzed_jobs_skipped_at_card_stage": stats.get(
                    "previously_analyzed_jobs_skipped_at_card_stage",
                    0,
                ),
                "duplicate_job_records_prevented": stats.get("duplicate_job_records_prevented", 0),
                "page_quality": stats.get("page_quality", []),
                "new_recommendations": stats.get("new_recommendations", 0),
                "cached_previous_recommendations": stats.get("cached_previous_recommendations", 0),
                "rejected_or_below_threshold": stats.get("rejected_or_below_threshold", 0),
                "results_layout_types": stats.get("results_layout_types", []),
            }
        )

        for _, job in _iter_report_jobs(report):
            total_occurrences += 1
            key = _dedupe_key(job, tracker)
            if not key:
                continue
            occurrence = {
                "query": query,
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "url": tracker.canonicalize_linkedin_job_url(job.get("url", "")),
                "job_id": (job.get("job_id", "") or tracker.linkedin_job_id(job.get("url", ""))).strip(),
                "found_at": job.get("found_at", ""),
                "first_seen_at": job.get("first_seen_at", ""),
                "last_seen_at": job.get("last_seen_at", ""),
                "interview_probability_score": int(job.get("interview_probability_score", 0) or 0),
                "interview_probability_reason": job.get("interview_probability_reason", ""),
                "ai_match_tier": job.get("ai_match_tier", "weak_match"),
                "output_status": job.get("output_status", ""),
                "ai_status": job.get("ai_status", job.get("output_status", "")),
                "tracking_status": job.get("tracking_status", ""),
                "tracking_updated_at": job.get("tracking_updated_at", ""),
                "search_goal": job.get(
                    "search_goal",
                    query_plan.get("search_goal", "legacy"),
                ),
                "search_group": job.get(
                    "search_group",
                    report.get("search_group", ""),
                ),
                "matched_search_groups": list(
                    job.get(
                        "matched_search_groups",
                        report.get("matched_search_groups", []),
                    )
                ),
            }
            entry = merged.setdefault(key, {"occurrences": []})
            entry["occurrences"].append(occurrence)

    new_recommendations = {"strong_match": [], "possible_match": []}
    cached_previous_recommendations = {"strong_match": [], "possible_match": []}
    rejected_or_below_threshold = []

    for key, entry in merged.items():
        occurrences = entry["occurrences"]
        best = _pick_best_occurrence(occurrences, query_order)
        final_bucket = _final_bucket_for_occurrences(occurrences)
        final_status = _final_status_for_occurrences(occurrences, final_bucket)
        final_score = int(best.get("interview_probability_score", 0) or 0)
        final_tier = _match_tier(final_score, scout)
        matched_queries = []
        seen_queries = set()
        for item in sorted(occurrences, key=lambda occ: query_order.get(occ.get("query", ""), 10**6)):
            query = item.get("query", "")
            if query and query not in seen_queries:
                seen_queries.add(query)
                matched_queries.append(query)
        tracking_status, tracking_updated_at = _merge_tracking(occurrences)
        matched_search_groups = []
        for item in occurrences:
            for group in item.get("matched_search_groups", []):
                if group and group not in matched_search_groups:
                    matched_search_groups.append(group)

        merged_job = {
            "title": best.get("title", ""),
            "company": best.get("company", ""),
            "location": best.get("location", ""),
            "url": best.get("url", ""),
            "job_id": best.get("job_id", ""),
            "found_at": _min_timestamp([item.get("found_at", "") for item in occurrences]),
            "first_seen_at": _min_timestamp([item.get("first_seen_at", "") for item in occurrences]),
            "last_seen_at": _max_timestamp([item.get("last_seen_at", "") for item in occurrences]),
            "interview_probability_score": final_score,
            "interview_probability_reason": best.get("interview_probability_reason", ""),
            "ai_match_tier": final_tier,
            "output_status": final_status,
            "ai_status": final_status,
            "matched_queries": matched_queries,
            "best_matching_query": best.get("query", ""),
            "query_match_count": len(matched_queries),
            "query_hits": _build_query_hits(occurrences, query_order),
            "search_goal": query_plan.get("search_goal", "legacy"),
            "search_group": best.get("search_group", ""),
            "matched_search_groups": matched_search_groups,
        }
        if tracking_status:
            merged_job["tracking_status"] = tracking_status
            merged_job["tracking_updated_at"] = tracking_updated_at

        if final_bucket == "new_recommendations":
            if final_tier == "strong_match":
                new_recommendations["strong_match"].append(merged_job)
            else:
                new_recommendations["possible_match"].append(merged_job)
        elif final_bucket == "cached_previous_recommendations":
            if final_tier == "strong_match":
                cached_previous_recommendations["strong_match"].append(merged_job)
            else:
                cached_previous_recommendations["possible_match"].append(merged_job)
        else:
            rejected_or_below_threshold.append(merged_job)

    def _sort_jobs(jobs: list[dict]) -> list[dict]:
        return sorted(
            jobs,
            key=lambda job: (
                -int(job.get("interview_probability_score", 0) or 0),
                job.get("title", ""),
                job.get("company", ""),
            ),
        )

    new_recommendations = {
        "strong_match": _sort_jobs(new_recommendations["strong_match"]),
        "possible_match": _sort_jobs(new_recommendations["possible_match"]),
    }
    cached_previous_recommendations = {
        "strong_match": _sort_jobs(cached_previous_recommendations["strong_match"]),
        "possible_match": _sort_jobs(cached_previous_recommendations["possible_match"]),
    }
    rejected_or_below_threshold = _sort_jobs(rejected_or_below_threshold)

    stats = {
        "queries_requested": len(queries),
        "queries_run": len(reports),
        "total_unique_jobs_seen": len(merged),
        "duplicate_jobs_collapsed": max(0, total_occurrences - len(merged)),
        "same_run_cross_query_reused": sum(
            int((report.get("stats", {}) or {}).get("same_run_cross_query_reused", 0) or 0)
            for report in reports
        ),
        "previously_analyzed_jobs_skipped": sum(
            int((report.get("stats", {}) or {}).get("previously_analyzed_jobs_skipped", 0) or 0)
            for report in reports
        ),
        "previously_analyzed_jobs_skipped_at_card_stage": sum(
            int(
                (report.get("stats", {}) or {}).get(
                    "previously_analyzed_jobs_skipped_at_card_stage",
                    0,
                )
                or 0
            )
            for report in reports
        ),
        "duplicate_job_records_prevented": sum(
            int((report.get("stats", {}) or {}).get("duplicate_job_records_prevented", 0) or 0)
            for report in reports
        ),
        "new_recommendations": sum(len(items) for items in new_recommendations.values()),
        "cached_previous_recommendations": sum(
            len(items) for items in cached_previous_recommendations.values()
        ),
        "rejected_or_below_threshold": len(rejected_or_below_threshold),
    }

    latest_generated_at = max(
        (report.get("generated_at", "") for report in reports),
        default="",
    )
    earliest_started_at = started_at or _min_timestamp([report.get("started_at", "") for report in reports])
    apply_first_jobs = (
        new_recommendations["strong_match"]
        + cached_previous_recommendations["strong_match"]
    )
    consider_jobs = (
        new_recommendations["possible_match"]
        + cached_previous_recommendations["possible_match"]
    )
    return {
        "started_at": earliest_started_at,
        "generated_at": latest_generated_at,
        "completed_at": latest_generated_at,
        "mode": "linkedin_scout_multi",
        "query_file": str(query_file),
        "queries_run": queries,
        "search_goal": query_plan.get("search_goal", "legacy"),
        "search_goal_label": query_plan.get("search_goal_label", ""),
        "selected_search_groups": query_plan.get("selected_groups", []),
        "query_plan": query_plan,
        "location": location,
        "max_pages": max_pages_label,
        "ai_threshold": scout.AI_THRESHOLD,
        "ai_strong_match_threshold": scout.AI_STRONG_MATCH_THRESHOLD,
        "ai_scoring_version": scout.AI_SCORING_VERSION,
        "perfect_job_profile_path": str(scout.perfect_job_profile_path),
        "stats": stats,
        "per_query_summary": per_query_summary,
        "new_recommendations": new_recommendations,
        "cached_previous_recommendations": cached_previous_recommendations,
        "apply_first": apply_first_jobs,
        "consider_human_review": consider_jobs,
        "rejected": rejected_or_below_threshold,
        "rejected_or_below_threshold": rejected_or_below_threshold,
    }


def _write_output(output: dict) -> None:
    OUTPUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _recover_reports_from_live_dashboard(
    progress: dict,
    *,
    data_path: Path = Path("data/recommended_jobs_dashboard_data.json"),
) -> tuple[list[dict], dict]:
    """Rebuild final merge inputs when every query finished before finalization failed."""
    if not data_path.exists():
        return [], {}
    try:
        payload = json.loads(data_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return [], {}
    if not isinstance(payload, dict):
        return [], {}

    expected_queries = [
        _normalize_query(query)
        for query in progress.get("queries", [])
        if isinstance(query, str) and _normalize_query(query)
    ]
    expected_location = str(progress.get("location") or "").strip()
    candidates = []
    for run in payload.get("runs", []):
        if not isinstance(run, dict):
            continue
        run_queries = [
            _normalize_query(query)
            for query in run.get("queries", [])
            if isinstance(query, str) and _normalize_query(query)
        ]
        if run_queries != expected_queries:
            continue
        if str(run.get("location") or "").strip() != expected_location:
            continue
        if run.get("status") not in {"running", "failed", "stopped", "interrupted"}:
            continue
        candidates.append(run)
    if not candidates:
        return [], {}

    run = max(candidates, key=lambda item: str(item.get("started_at") or ""))
    run_id = str(run.get("run_id") or "")
    jobs = [
        job
        for job in payload.get("jobs", [])
        if isinstance(job, dict) and str(job.get("run_id") or "") == run_id
    ]
    if not jobs and int(progress.get("total_jobs_processed", 0) or 0) > 0:
        return [], {}

    jobs_by_query: dict[str, list[dict]] = {query: [] for query in progress.get("queries", [])}
    query_lookup = {_normalize_query(query): query for query in jobs_by_query}
    for event in jobs:
        query = query_lookup.get(_normalize_query(event.get("query", "")))
        if not query:
            continue
        score = int(event.get("score", 0) or 0)
        accepted = str(event.get("terminal_status") or "").strip().lower() in {
            "accepted",
            "duplicate_suppressed",
        }
        jobs_by_query[query].append(
            {
                "title": event.get("title", ""),
                "company": event.get("company", ""),
                "location": event.get("location", ""),
                "url": event.get("url", ""),
                "job_id": event.get("job_id", ""),
                "found_at": event.get("processed_at", ""),
                "first_seen_at": event.get("processed_at", ""),
                "last_seen_at": event.get("processed_at", ""),
                "interview_probability_score": score,
                "interview_probability_reason": event.get("reason", ""),
                "ai_match_tier": (event.get("ai") or {}).get("match_tier", ""),
                "output_status": "accepted" if accepted else "below_threshold",
                "ai_status": "accepted" if accepted else "below_threshold",
                "tracking_status": event.get("tracking_status", ""),
                "tracking_updated_at": event.get("tracking_updated_at", ""),
                "search_goal": event.get(
                    "search_goal",
                    progress.get("search_goal", "legacy"),
                ),
                "search_group": event.get("search_group", ""),
                "matched_search_groups": list(
                    event.get("matched_search_groups", [])
                ),
            }
        )

    latest_event_at = max(
        (str(job.get("processed_at") or "") for job in jobs),
        default=str(run.get("completed_at") or run.get("started_at") or ""),
    )
    reports = []
    for query in progress.get("queries", []):
        query_jobs = jobs_by_query.get(query, [])
        accepted_jobs = [job for job in query_jobs if job["output_status"] == "accepted"]
        rejected_jobs = [job for job in query_jobs if job["output_status"] != "accepted"]
        reports.append(
            {
                "query": query,
                "search_goal": progress.get("search_goal", "legacy"),
                "search_group": query_plan_metadata(
                    progress.get("query_plan", {}),
                    query,
                ).get("search_group", ""),
                "matched_search_groups": query_plan_metadata(
                    progress.get("query_plan", {}),
                    query,
                ).get("matched_search_groups", []),
                "started_at": run.get("started_at", ""),
                "generated_at": latest_event_at,
                "pages_scanned": 0,
                "stats": {
                    "pages_scanned": 0,
                    "job_cards_collected": len(query_jobs),
                    "new_recommendations": len(accepted_jobs),
                    "cached_previous_recommendations": 0,
                    "rejected_or_below_threshold": len(rejected_jobs),
                },
                "new_recommendations": {
                    "strong_match": [
                        job for job in accepted_jobs if int(job["interview_probability_score"]) >= 70
                    ],
                    "possible_match": [
                        job for job in accepted_jobs if int(job["interview_probability_score"]) < 70
                    ],
                },
                "cached_previous_recommendations": {
                    "strong_match": [],
                    "possible_match": [],
                },
                "rejected_or_below_threshold": rejected_jobs,
            }
        )
    return reports, dict(run)


def _first_description_log_path(reports: list[dict]) -> str:
    for report in reports:
        path = (report.get("description_log_path") or "").strip()
        if path:
            return path
    return ""


def _merge_description_only_stats(reports: list[dict]) -> dict:
    merged: dict[str, int] = {}
    passthrough = {
        "ai_threshold",
        "ai_strong_match_threshold",
        "ai_scoring_version",
        "perfect_job_profile_path",
    }
    for report in reports:
        for key, value in (report.get("stats", {}) or {}).items():
            if key in passthrough:
                merged.setdefault(key, value)
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                merged[key] = int(merged.get(key, 0) or 0) + value
    merged["description_log_path"] = _first_description_log_path(reports)
    return merged


async def main():
    global console, ACTIVE_RUN_LOGGER
    parser = argparse.ArgumentParser(
        description="Run the trusted job scout across a curated list of queries and merge overlaps."
    )
    add_board_mode_arguments(parser)
    parser.add_argument(
        "--query-file",
        default=None,
        help="Text file with one curated search query per line. Defaults to search_queries.txt.",
    )
    parser.add_argument(
        "--search-goal",
        choices=["career-growth", "career-focus", "broad", "income", "custom"],
        default=None,
        help="Use structured Primary, Bridge, and Fallback query groups.",
    )
    parser.add_argument(
        "--search-groups",
        default="",
        help="Comma-separated groups for --search-goal custom: primary,bridge,fallback.",
    )
    parser.add_argument(
        "--location",
        default=None,
        help="Search location. Defaults to 'Amstelveen'.",
    )
    parser.add_argument(
        "--search-market",
        choices=list(SEARCH_MARKETS),
        default=None,
        help="Search market. Existing commands default to the Netherlands.",
    )
    parser.add_argument(
        "--radius-km",
        choices=[0, 8, 16, 40, 80, 160],
        type=int,
        default=None,
        help="LinkedIn-native search radius in kilometres.",
    )
    parser.add_argument(
        "--employment",
        choices=list(EMPLOYMENT_PREFERENCES),
        default=None,
        help="Employment preference for discovery and scoring.",
    )
    parser.add_argument(
        "--sponsorship-policy",
        choices=["required", "not_required"],
        default=None,
        help="Sponsorship policy for the run. Overrides market defaults.",
    )
    parser.add_argument(
        "--experience-levels",
        default=None,
        help="Comma-separated list of LinkedIn experience level names to filter.",
    )
    parser.add_argument(
        "--max-pages",
        default="2",
        help="How many result pages to scan per query: 1, 2, or 'all'.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Enable Smart Fresh Scout mode. Dynamic fresh-run behavior is added in follow-up steps.",
    )
    parser.add_argument(
        "--ai-budget-mode",
        choices=["smart", "deep", "off"],
        default=None,
        help=(
            "Fresh-mode AI budget behavior: smart keeps the normal early guard, "
            "deep skips the first low-yield stop but keeps later caps, off disables budget guard stops."
        ),
    )
    parser.add_argument(
        "--no-query-learning",
        action="store_true",
        help="Keep query-file order instead of prioritizing queries using previous fresh-scout results.",
    )
    parser.add_argument(
        "--human-mode",
        action="store_true",
        help="Use slower, randomized human-like pacing to reduce bot-like behavior.",
    )
    parser.add_argument(
        "--description-only",
        "--extract-descriptions-only",
        dest="description_only",
        action="store_true",
        help="Extract and save job descriptions without AI scoring.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from saved multi-query scout progress when possible.",
    )
    parser.add_argument(
        "--process-only",
        action="store_true",
        help="Skip scraping and process already collected jobs only.",
    )
    parser.add_argument(
        "--browser",
        choices=["chromium", "firefox"],
        default="chromium",
        help="Browser engine to use for the scout. Defaults to chromium.",
    )
    parser.add_argument(
        "--browser-profile-dir",
        default=None,
        help=(
            "Dedicated browser profile directory. Defaults to data/browser_profile "
            "for LinkedIn and data/indeed_browser_profile for Indeed."
        ),
    )
    parser.add_argument(
        "--browser-executable",
        default=None,
        help="Optional path to an installed browser executable, such as Firefox.",
    )
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Clear scout_progress.json before continuing.",
    )
    parser.add_argument(
        "--test-run",
        action="store_true",
        help="Run without saving any collected jobs or progress.",
    )
    parser.add_argument("--headless", action="store_true", help="Run browser headlessly")
    args = parser.parse_args()
    ACTIVE_RUN_LOGGER = ScoutRunLogger()
    ACTIVE_RUN_LOGGER.install()
    console = Console()
    if os.getenv("DASHBOARD_STARTED_SCOUT") != "1":
        clear_stop_request()
    board_mode = resolve_board_mode(args)
    board_name = board_display_name(board_mode)
    if requires_description_only(board_mode):
        args.description_only = True
    browser_executable, executable_warning = supported_browser_executable(
        args.browser,
        args.browser_executable,
    )
    if executable_warning:
        console.print(f"[yellow]Warning:[/yellow] {executable_warning}")

    workspace = UserWorkspace().ensure_initialized()
    explicit_query_file = bool(args.query_file)
    query_file = Path(args.query_file) if explicit_query_file else active_search_queries_path()
    base_queries = _load_queries(query_file)
    effective_pages, page_label = _parse_max_pages(args.max_pages)
    profile, preferences = load_config()
    explicit_scope_requested = any(
        value is not None
        for value in (args.search_market, args.radius_km, args.employment)
    )
    fresh_policy = FreshScoutPolicy.from_preferences(
        preferences,
        enabled=args.fresh,
        ai_budget_mode=args.ai_budget_mode,
    )
    if fresh_policy.enabled:
        effective_pages = fresh_policy.max_pages_per_query
        page_label = f"smart up to {fresh_policy.max_pages_per_query}"
    run_started_at = datetime.now().astimezone().isoformat()
    progress_store = ScoutProgressStore()
    if args.reset_progress:
        progress_store.clear()
        console.print("[yellow]Cleared scout progress.[/yellow]")

    progress = progress_store.load() if args.resume else {}
    selected_search_groups = _parse_search_groups(args.search_groups)
    requested_search_goal = args.search_goal or ("custom" if selected_search_groups else "")
    structured_search = bool(requested_search_goal) and not explicit_query_file
    query_source_path = workspace.search_query_groups_path if structured_search else query_file
    expected_query_file = _expected_query_file(
        query_source_path,
        progress=progress,
        resume=args.resume,
    )
    progress_mode = PROGRESS_MODE if board_mode == "linkedin" else f"{board_mode}_{PROGRESS_MODE}"
    progress_queries = [
        query
        for query in progress.get("queries", [])
        if isinstance(query, str) and _normalize_query(query)
    ]
    resume_active = bool(
        progress
        and progress.get("mode") == progress_mode
        and progress.get("status") != "completed"
        and str(progress.get("max_pages", "")) == page_label
        and str(progress.get("query_file", "")) == expected_query_file
    )
    if resume_active:
        queries = progress_queries
        query_plan = progress.get("query_plan")
        if not isinstance(query_plan, dict) or not query_plan.get("entries"):
            query_plan = _legacy_query_plan(
                queries,
                search_goal=str(progress.get("search_goal") or "legacy"),
            )
        query_learning = query_plan.get("query_learning", {})
    else:
        learning_enabled = (
            board_mode == "linkedin"
            and fresh_policy.enabled
            and not args.description_only
            and not args.process_only
            and not args.no_query_learning
        )
        if structured_search:
            query_plan = build_search_query_plan(
                workspace.load_search_query_groups(),
                search_goal=requested_search_goal,
                selected_groups=selected_search_groups,
                preferences=preferences,
                learning_enabled=learning_enabled,
                learning_scope={
                    "platform": board_mode,
                    "search_market": args.search_market or "netherlands",
                    "employment": args.employment or "full-time-preferred",
                },
            )
            queries = list(query_plan["queries"])
            query_learning = query_plan.get("query_learning", {})
        else:
            queries, query_learning = order_queries_with_learning(
                base_queries,
                preferences=preferences,
                enabled=learning_enabled,
                learning_context=(
                    {
                        "platform": board_mode,
                        "search_market": args.search_market or "netherlands",
                        "employment": args.employment or "full-time-preferred",
                    }
                    if explicit_scope_requested
                    else None
                ),
            )
            query_plan = _legacy_query_plan(
                queries,
                search_goal="custom-file" if explicit_query_file else "legacy",
            )
            query_plan["query_learning"] = query_learning
    if resume_active:
        search_scope = normalize_search_scope(
            progress.get("search_scope"),
            platform=board_mode,
            location=progress.get("location") or args.location,
            legacy_distance_miles=int(
                (preferences.get("linkedin") or {}).get("distance_miles", 25) or 25
            ),
        )
    else:
        # Parse experience levels
        exp_levels = None
        if getattr(args, "experience_levels", None):
            exp_levels = [lvl.strip().lower() for lvl in args.experience_levels.split(",") if lvl.strip()]
        search_scope = build_search_scope(
            platform=board_mode,
            search_market=args.search_market or "netherlands",
            location=args.location,
            radius_km=args.radius_km if args.radius_km is not None else 40,
            employment=args.employment or "full-time-preferred",
            search_goal=query_plan.get("search_goal", "legacy"),
            search_groups=query_plan.get("selected_groups", []),
            legacy_mode=not explicit_scope_requested,
            legacy_distance_miles=int(
                (preferences.get("linkedin") or {}).get("distance_miles", 25) or 25
            ),
            experience_levels=exp_levels,
            sponsorship_policy=getattr(args, "sponsorship_policy", None),
        )
    args.location = search_scope["location"]
    preferences["_runtime_search_scope"] = dict(search_scope)
    expected_queries = [_normalize_query(query) for query in queries]
    start_query_index = int(progress.get("current_query_index", 0) or 0) if resume_active else 0
    resume_finalization_only = bool(
        resume_active
        and queries
        and start_query_index >= len(queries)
        and int(progress.get("last_completed_query_index", -1) or -1) >= len(queries) - 1
    )
    stable_pages = int(progress.get("stable_total_pages_processed", 0) or 0) if resume_active else 0
    stable_jobs = int(progress.get("stable_total_jobs_processed", 0) or 0) if resume_active else 0
    base_fresh_counts = (
        _normalize_fresh_counts(progress.get("fresh_progress_counts"))
        if resume_active and fresh_policy.enabled
        else _normalize_fresh_counts({})
    )

    profile_dir = args.browser_profile_dir or default_browser_profile_dir(board_mode, args.browser)
    browser = None if args.process_only or resume_finalization_only else BrowserController(
        headless=args.headless,
        profile_dir=profile_dir,
        use_automation_overrides=(board_mode == "linkedin" and args.browser == "chromium"),
        browser_type=args.browser,
        executable_path=browser_executable,
        start_new_page=(board_mode == "indeed"),
    )
    if browser:
        browser.set_human_delays(args.human_mode or board_mode == "indeed")
    reporter = ScoutConsoleReporter(console=console)
    review_writer = ScoutReviewLatestWriter()
    scout_cls = IndeedJobScout if board_mode == "indeed" else LinkedInJobScout
    scout = scout_cls(profile, preferences, browser, reporter=reporter, test_run=args.test_run)
    live_dashboard = None
    live_run = None
    live_run_completed = False
    live_completion_status = "failed"
    persistence_warning_count = int(progress.get("persistence_warning_count", 0) or 0)
    latest_persistence_warning = str(progress.get("latest_persistence_warning") or "")
    recovered_reports: list[dict] = []
    recovered_live_run: dict = {}
    current_query_metadata: dict = {}

    def record_persistence_warning(component: str, exc: BaseException) -> None:
        nonlocal persistence_warning_count, latest_persistence_warning
        persistence_warning_count += 1
        source = exc.original_error if isinstance(exc, PersistenceError) else exc
        latest_persistence_warning = f"{component}: {source}"
        console.print(
            "[yellow][PERSISTENCE WARNING][/yellow] "
            f"{latest_persistence_warning}"
        )
    if resume_finalization_only and not args.description_only:
        recovered_reports, recovered_live_run = _recover_reports_from_live_dashboard(progress)
        if not recovered_reports:
            raise RuntimeError(
                "All queries are marked complete, but saved live results could not be recovered for finalization."
            )

    if not args.description_only:
        try:
            live_dashboard = LiveRecommendedJobsDashboard()
            if recovered_live_run:
                live_run = live_dashboard.resume_run(recovered_live_run["run_id"])
                run_started_at = str(live_run.get("started_at") or run_started_at)
            else:
                live_run = live_dashboard.start_run(
                    mode=f"{board_mode}_multi_query_scout",
                    board=board_mode,
                    location=args.location,
                    max_pages=page_label,
                    queries=queries,
                    started_at=run_started_at,
                    fresh_policy=fresh_policy.as_dict() if fresh_policy.enabled else None,
                    search_goal=query_plan.get("search_goal", "legacy"),
                    selected_search_groups=query_plan.get("selected_groups", []),
                    query_plan=query_plan,
                    search_scope=search_scope,
                )
            console.print(
                "[green]Live dashboard:[/green] "
                "recommended_jobs_dashboard.html"
            )
        except Exception as exc:
            if isinstance(exc, PersistenceError):
                record_persistence_warning("Live dashboard startup", exc)
                active_run_id = str(
                    (live_dashboard.data if live_dashboard else {}).get("active_run_id") or ""
                )
                live_run = next(
                    (
                        dict(run)
                        for run in (live_dashboard.data.get("runs", []) if live_dashboard else [])
                        if str(run.get("run_id") or "") == active_run_id
                    ),
                    None,
                )
                if live_run:
                    console.print(
                        "[yellow]Live dashboard will continue from its recoverable "
                        "temporary state.[/yellow]"
                    )
                else:
                    live_dashboard = None
            else:
                live_dashboard = None
                live_run = None
            if not live_dashboard or not live_run:
                console.print(f"[yellow]Live dashboard disabled:[/yellow] {exc}")

    def on_live_result(event: dict):
        if not live_dashboard or not live_run:
            return
        event = dict(event)
        event["run_id"] = live_run["run_id"]
        event["search_goal"] = query_plan.get("search_goal", "legacy")
        event["search_group"] = current_query_metadata.get("search_group", "")
        event["matched_search_groups"] = current_query_metadata.get(
            "matched_search_groups",
            [],
        )
        event["search_scope"] = dict(search_scope)
        event["search_market"] = search_scope.get("search_market", "")
        try:
            live_dashboard.record_job(event)
        except PersistenceError as exc:
            record_persistence_warning("Live dashboard job update", exc)

    def update_live_progress(**updates):
        if not live_dashboard or not live_run or not fresh_policy.enabled:
            return
        updates.setdefault("persistence_warning_count", persistence_warning_count)
        updates.setdefault("latest_persistence_warning", latest_persistence_warning)
        try:
            live_dashboard.update_run_progress(live_run["run_id"], **updates)
        except PersistenceError as exc:
            record_persistence_warning("Live dashboard progress update", exc)
        except Exception as exc:
            console.print(f"[yellow]Live dashboard progress update skipped:[/yellow] {exc}")

    if fresh_policy.enabled and any(base_fresh_counts.values()):
        resumed_metadata = (
            query_plan_metadata(query_plan, queries[start_query_index])
            if queries and start_query_index < len(queries)
            else {}
        )
        update_live_progress(
            phase="resumed",
            current_query_index=start_query_index + 1,
            total_queries=len(queries),
            current_query=queries[start_query_index] if queries and start_query_index < len(queries) else "",
            current_search_group=resumed_metadata.get("search_group", ""),
            current_search_phase=resumed_metadata.get("phase", ""),
            pages_scanned=stable_pages,
            fresh_jobs_seen=base_fresh_counts["new_jobs_seen"],
            ai_scored=base_fresh_counts["ai_calls"],
            apply_first=base_fresh_counts["apply_first"],
            good_or_better=base_fresh_counts["good_or_better"],
        )

    query_learning_label = _query_learning_summary(query_learning)

    mode_label = (
        f"Curated {board_name} description extraction only (no AI scoring)"
        if args.description_only
        else ("Curated process-only orchestration" if args.process_only else "Curated multi-query orchestration")
    )
    ai_backend_label = "disabled (description-only)" if args.description_only else _ai_backend_label(scout)
    console.print(
        Panel(
            f"[bold green]{board_name} Multi Scout[/bold green]\n"
            f"Query file: {query_file}\n"
            f"Search goal: {query_plan.get('search_goal_label', 'Legacy query list')}\n"
            f"Search groups: {', '.join(query_plan.get('selected_groups', [])) or 'flat query list'}\n"
            f"Queries: {len(queries)}\n"
            f"Search scope: {search_scope_summary(search_scope)}\n"
            f"Pages per query: {page_label}\n"
            f"Fresh mode: {fresh_policy.panel_label()}\n"
            f"Query learning: {query_learning_label}\n"
            f"Browser: {args.browser}\n"
            f"Interaction: {'human-like' if args.human_mode or board_mode == 'indeed' else 'fast'}\n"
            f"AI Backend: {ai_backend_label}\n"
            f"Started: {run_started_at}\n"
            f"Mode: {mode_label}",
            title="Multi-Scouting Configuration",
        )
    )
    reports: list[dict] = list(recovered_reports)
    same_run_job_registry: dict[str, dict] = {}
    fresh_stop_reason = ""
    fresh_stop_counts: dict[str, int] = {}
    progress_state = {
        "run_id": str((live_run or {}).get("run_id") or progress.get("run_id") or ""),
        "started_at": run_started_at,
        "mode": progress_mode,
        "status": "in_progress",
        "phase": "idle",
        "location": args.location,
        "search_scope": dict(search_scope),
        "max_pages": page_label,
        "query_file": expected_query_file,
        "queries": queries,
        "query_plan": query_plan,
        "search_goal": query_plan.get("search_goal", "legacy"),
        "selected_search_groups": query_plan.get("selected_groups", []),
        "phase_order": query_plan.get("phase_order", []),
        "current_search_group": (
            query_plan_metadata(query_plan, queries[start_query_index]).get("search_group", "")
            if queries and start_query_index < len(queries)
            else ""
        ),
        "current_query_index": start_query_index,
        "current_query": queries[start_query_index] if queries and start_query_index < len(queries) else "",
        "current_page_number": 0,
        "total_pages_processed": stable_pages,
        "total_jobs_processed": stable_jobs,
        "stable_total_pages_processed": stable_pages,
        "stable_total_jobs_processed": stable_jobs,
        "last_completed_query_index": int(progress.get("last_completed_query_index", -1) or -1)
        if resume_active
        else -1,
        "last_completed_query": progress.get("last_completed_query", "") if resume_active else "",
        "last_completed_page_number": int(progress.get("last_completed_page_number", 0) or 0)
        if resume_active
        else 0,
        "fresh_policy": fresh_policy.as_dict() if fresh_policy.enabled else {},
        "fresh_progress_counts": base_fresh_counts if fresh_policy.enabled else {},
        "query_learning": query_learning,
        "persistence_warning_count": persistence_warning_count,
        "latest_persistence_warning": latest_persistence_warning,
    }

    def save_progress(*, final: bool = False, **updates):
        if args.test_run:
            return
        if args.process_only:
            return
        progress_state.update(updates)
        progress_state["persistence_warning_count"] = persistence_warning_count
        progress_state["latest_persistence_warning"] = latest_persistence_warning
        try:
            progress_store.save(
                progress_state,
                retry_delays=(
                    FINAL_PERSISTENCE_RETRY_DELAYS
                    if final
                    else DEFAULT_RETRY_DELAYS
                ),
            )
        except PersistenceError as exc:
            record_persistence_warning("Scout progress checkpoint", exc)

    def fresh_counts_so_far(extra_new_jobs_seen: int = 0) -> dict[str, int]:
        if resume_finalization_only:
            return dict(base_fresh_counts)
        current_counts = _fresh_recommendation_counts(reports, scout)
        if extra_new_jobs_seen:
            current_counts = dict(current_counts)
            current_counts["new_jobs_seen"] += max(0, int(extra_new_jobs_seen or 0))
        return _combine_fresh_counts(base_fresh_counts, current_counts)

    try:
        if browser:
            await browser.start()
        if resume_finalization_only:
            console.print(
                "[yellow]Resuming finalization only.[/yellow] "
                "All saved queries are complete, so LinkedIn will not be reopened."
            )
        elif resume_active:
            console.print(
                "[yellow]Resuming from the unfinished query in safe restart mode.[/yellow] "
                f"Last seen query index {start_query_index + 1}, "
                f"last seen page {int(progress.get('current_page_number', 0) or 0)}."
            )
        cumulative_pages = stable_pages
        cumulative_jobs = stable_jobs
        index = max(-1, start_query_index - 1)
        for index, query in enumerate(queries):
            if index < start_query_index:
                continue
            current_query_metadata = query_plan_metadata(query_plan, query)
            search_group = current_query_metadata.get("search_group", "")
            if search_group:
                console.print(
                    "[cyan][SEARCH PATH][/cyan] "
                    f"{search_group.replace('_', ' ').title()} phase"
                )

            reporter.start_query(
                query_index=index + 1,
                total_queries=len(queries),
                query_name=query,
                max_pages=effective_pages,
                process_only=args.process_only,
            )

            query_pages_seen = {"value": 0}

            def on_page_scanned(
                query: str,
                page_number: int,
                pages_scanned: int,
                total_jobs_collected: int,
                page_quality: dict | None = None,
            ):
                query_pages_seen["value"] = pages_scanned
                save_progress(
                    status="in_progress",
                    phase="collecting_pages",
                    current_query_index=index,
                    current_query=query,
                    current_search_group=search_group,
                    current_page_number=page_number,
                    last_completed_page_number=page_number,
                    last_page_quality=page_quality or {},
                    total_pages_processed=cumulative_pages + pages_scanned,
                    total_jobs_processed=cumulative_jobs,
                    fresh_progress_counts=fresh_counts_so_far(),
                )
                live_fresh_counts = fresh_counts_so_far(extra_new_jobs_seen=int(total_jobs_collected or 0))
                update_live_progress(
                    phase="collecting_pages",
                    current_query_index=index + 1,
                    total_queries=len(queries),
                    current_query=query,
                    current_search_group=search_group,
                    current_search_phase=current_query_metadata.get("phase", search_group),
                    current_page_number=page_number,
                    pages_scanned=cumulative_pages + pages_scanned,
                    fresh_jobs_seen=live_fresh_counts["new_jobs_seen"],
                    ai_scored=live_fresh_counts["ai_calls"],
                    apply_first=live_fresh_counts["apply_first"],
                    good_or_better=live_fresh_counts["good_or_better"],
                    page_quality=page_quality or {},
                )

            def on_job_processed(query: str, processed_jobs: int, page_number: int):
                save_progress(
                    status="in_progress",
                    phase="processing_jobs",
                    current_query_index=index,
                    current_query=query,
                    current_search_group=search_group,
                    current_page_number=int(page_number or 0),
                    last_completed_page_number=query_pages_seen["value"],
                    total_pages_processed=cumulative_pages + query_pages_seen["value"],
                    total_jobs_processed=cumulative_jobs + int(processed_jobs or 0),
                    fresh_progress_counts=fresh_counts_so_far(),
                )
                live_fresh_counts = fresh_counts_so_far()
                update_live_progress(
                    phase="processing_jobs",
                    current_query_index=index + 1,
                    total_queries=len(queries),
                    current_query=query,
                    current_search_group=search_group,
                    current_search_phase=current_query_metadata.get("phase", search_group),
                    current_page_number=int(page_number or 0),
                    pages_scanned=cumulative_pages + query_pages_seen["value"],
                    processed_jobs=cumulative_jobs + int(processed_jobs or 0),
                    ai_scored=live_fresh_counts["ai_calls"],
                    apply_first=live_fresh_counts["apply_first"],
                    good_or_better=live_fresh_counts["good_or_better"],
                )

            if args.process_only:
                if args.resume:
                    console.print("[yellow]Process-only mode ignores --resume and uses collected jobs directly.[/yellow]")
                report = await scout.process_collected_jobs(
                    query=query,
                    location=args.location,
                    max_pages=effective_pages,
                    same_run_job_registry=same_run_job_registry,
                    run_started_at=run_started_at,
                    description_only=args.description_only,
                    live_result_callback=on_live_result if live_dashboard else None,
                )
            else:
                save_progress(
                    status="in_progress",
                    phase="collecting_pages",
                    current_query_index=index,
                    current_query=query,
                    current_search_group=search_group,
                    fresh_progress_counts=fresh_counts_so_far(),
                )
                report = await scout.run(
                    query=query,
                    location=args.location,
                    max_pages=effective_pages,
                    human_mode=args.human_mode,
                    same_run_job_registry=same_run_job_registry,
                    start_page=1,
                    page_scanned_callback=on_page_scanned,
                    job_processed_callback=on_job_processed,
                    live_result_callback=on_live_result if live_dashboard else None,
                    run_started_at=run_started_at,
                    description_only=args.description_only,
                    fresh_policy=fresh_policy,
                )
            _annotate_report_search_metadata(
                report,
                current_query_metadata,
                query_plan.get("search_goal", "legacy"),
                search_scope,
            )
            reports.append(report)
            reporter.finish_query(report.get("stats", {}))
            cumulative_pages += int(report.get("pages_scanned", 0) or 0)
            cumulative_jobs += int((report.get("stats", {}) or {}).get("job_cards_collected", 0) or 0)
            completed_fresh_counts = fresh_counts_so_far()
            save_progress(
                status="in_progress",
                phase="query_completed",
                current_query_index=index + 1,
                current_query=queries[index + 1] if index + 1 < len(queries) else "",
                current_search_group=(
                    query_plan_metadata(query_plan, queries[index + 1]).get("search_group", "")
                    if index + 1 < len(queries)
                    else ""
                ),
                current_page_number=0,
                last_completed_query_index=index,
                last_completed_query=query,
                last_completed_page_number=int(report.get("pages_scanned", 0) or 0),
                total_pages_processed=cumulative_pages,
                total_jobs_processed=cumulative_jobs,
                stable_total_pages_processed=cumulative_pages,
                stable_total_jobs_processed=cumulative_jobs,
                fresh_progress_counts=completed_fresh_counts if fresh_policy.enabled else {},
            )
            update_live_progress(
                phase="query_completed",
                current_query_index=index + 1,
                total_queries=len(queries),
                current_query=query,
                current_search_group=search_group,
                current_search_phase=current_query_metadata.get("phase", search_group),
                current_page_number=0,
                pages_scanned=cumulative_pages,
                fresh_jobs_seen=completed_fresh_counts["new_jobs_seen"],
                ai_scored=completed_fresh_counts["ai_calls"],
                apply_first=completed_fresh_counts["apply_first"],
                good_or_better=completed_fresh_counts["good_or_better"],
            )
            if fresh_policy.enabled and not args.description_only and not args.process_only:
                fresh_stop_reason, fresh_stop_counts = _fresh_global_stop_reason(
                    reports,
                    scout,
                    fresh_policy,
                    base_counts=base_fresh_counts,
                    allow_ai_budget_guard=(
                        int(query_plan.get("ai_budget_eligible_after_index", -1) or -1) < 0
                        or index
                        >= int(query_plan.get("ai_budget_eligible_after_index", -1) or -1)
                    ),
                )
                if fresh_stop_reason:
                    console.print(
                        "[green][FRESH][/green] "
                        f"Stopping multi-query run early: {fresh_stop_reason}."
                    )
                    update_live_progress(
                        phase="fresh_stopped",
                        current_query_index=index + 1,
                        total_queries=len(queries),
                        current_query=query,
                        pages_scanned=cumulative_pages,
                        fresh_jobs_seen=int(fresh_stop_counts.get("new_jobs_seen", 0) or cumulative_jobs),
                        ai_scored=int(fresh_stop_counts.get("ai_calls", 0) or 0),
                        apply_first=int(fresh_stop_counts.get("apply_first", 0) or 0),
                        good_or_better=int(fresh_stop_counts.get("good_or_better", 0) or 0),
                        stopped_early=True,
                        stop_reason=fresh_stop_reason,
                    )
                    break
            if stop_requested():
                fresh_stop_reason = stop_reason() or "Dashboard stop requested."
                fresh_stop_counts = fresh_counts_so_far()
                live_completion_status = "stopped"
                console.print(f"[yellow][STOP][/yellow] {fresh_stop_reason}")
                update_live_progress(
                    phase="dashboard_stopped",
                    current_query_index=index + 1,
                    total_queries=len(queries),
                    current_query=query,
                    pages_scanned=cumulative_pages,
                    fresh_jobs_seen=int(fresh_stop_counts.get("new_jobs_seen", 0) or cumulative_jobs),
                    ai_scored=int(fresh_stop_counts.get("ai_calls", 0) or 0),
                    apply_first=int(fresh_stop_counts.get("apply_first", 0) or 0),
                    good_or_better=int(fresh_stop_counts.get("good_or_better", 0) or 0),
                    stopped_early=True,
                    stop_reason=fresh_stop_reason,
                )
                break

        if args.description_only:
            completed_at = datetime.now().astimezone().isoformat()
            final_stats = _merge_description_only_stats(reports)
            description_log_path = _first_description_log_path(reports)
            if description_log_path:
                console.print(f"[green]Description log:[/green] {description_log_path}")
            reporter.finish_run(
                output_path=description_log_path,
                final_stats=final_stats,
                completed_at=completed_at,
            )
            save_progress(
                status="completed",
                phase="completed",
                current_query_index=len(queries),
                current_query="",
                current_page_number=0,
                last_completed_query_index=len(queries) - 1 if queries else -1,
                last_completed_query=queries[-1] if queries else "",
                total_pages_processed=cumulative_pages,
                total_jobs_processed=cumulative_jobs,
                stable_total_pages_processed=cumulative_pages,
                stable_total_jobs_processed=cumulative_jobs,
            )
            return

        merged_output = _build_merged_output(
            reports=reports,
            queries=queries,
            query_file=query_file,
            location=args.location,
            max_pages_label=page_label,
            scout=scout,
            started_at=run_started_at,
            query_plan=query_plan,
        )
        merged_output["search_scope"] = dict(search_scope)
        if fresh_policy.enabled:
            fresh_counts = fresh_stop_counts or fresh_counts_so_far()
            merged_output["fresh_scout"] = {
                "policy": fresh_policy.as_dict(),
                "stopped_early": bool(fresh_stop_reason),
                "stop_reason": fresh_stop_reason,
                "counts": fresh_counts,
            }
            merged_output["query_learning"] = query_learning
            merged_output.setdefault("stats", {})["fresh_stopped_early"] = bool(fresh_stop_reason)
            merged_output.setdefault("stats", {})["fresh_stop_reason"] = fresh_stop_reason
            merged_output.setdefault("stats", {})["fresh_apply_first_jobs"] = int(
                fresh_counts.get("apply_first", 0) or 0
            )
            merged_output.setdefault("stats", {})["fresh_good_or_better_jobs"] = int(
                fresh_counts.get("good_or_better", 0) or 0
            )
            merged_output.setdefault("stats", {})["fresh_new_jobs_seen"] = int(
                fresh_counts.get("new_jobs_seen", 0) or 0
            )
            merged_output.setdefault("stats", {})["fresh_ai_calls"] = int(
                fresh_counts.get("ai_calls", 0) or 0
            )
        _write_output(merged_output)
        review_writer.write(merged_output, reports=reports)

        stats = merged_output.get("stats", {})
        reporter.finish_run(
            output_path=OUTPUT_PATH,
            final_stats=stats,
            completed_at=merged_output.get("completed_at", merged_output.get("generated_at", "")),
        )
        save_progress(
            final=True,
            status="completed",
            phase="completed",
            current_query_index=len(queries) if not fresh_stop_reason else min(len(queries), index + 1),
            current_query="",
            current_page_number=0,
            last_completed_query_index=(
                len(queries) - 1 if queries and not fresh_stop_reason else min(len(queries) - 1, index)
            ),
            last_completed_query=(
                queries[-1] if queries and not fresh_stop_reason else (queries[index] if queries else "")
            ),
            total_pages_processed=cumulative_pages,
            total_jobs_processed=cumulative_jobs,
            stable_total_pages_processed=cumulative_pages,
            stable_total_jobs_processed=cumulative_jobs,
            fresh_stop_reason=fresh_stop_reason,
            fresh_progress_counts=fresh_counts if fresh_policy.enabled else {},
        )
        if live_dashboard and live_run:
            live_fresh_counts = fresh_counts if fresh_policy.enabled else {}
            update_live_progress(
                phase="completed",
                total_queries=len(queries),
                ai_scored=int(live_fresh_counts.get("ai_calls", 0) or 0),
                apply_first=int(live_fresh_counts.get("apply_first", 0) or 0),
                good_or_better=int(live_fresh_counts.get("good_or_better", 0) or 0),
                fresh_jobs_seen=int(live_fresh_counts.get("new_jobs_seen", 0) or 0),
                stopped_early=bool(fresh_stop_reason),
                stop_reason=fresh_stop_reason,
            )
            try:
                live_dashboard.complete_run(
                    live_run["run_id"],
                    status=live_completion_status if live_completion_status == "stopped" else "completed",
                    retry_delays=FINAL_PERSISTENCE_RETRY_DELAYS,
                )
            except PersistenceError as exc:
                record_persistence_warning("Live dashboard completion", exc)
            live_run_completed = True
    except KeyboardInterrupt:
        live_completion_status = "stopped"
        save_progress(final=True, status="stopped", phase="stopped")
        console.print("\n[yellow]Multi-scout stopped by user.[/yellow]")
    except Exception as exc:
        live_completion_status = "failed"
        try:
            save_progress(
                final=True,
                status="failed",
                phase="failed",
                last_error=str(exc),
            )
        except Exception as persistence_exc:
            record_persistence_warning("Failed-run progress update", persistence_exc)
        try:
            update_live_progress(phase="failed", stop_reason=str(exc))
        except Exception as persistence_exc:
            record_persistence_warning("Failed-run dashboard update", persistence_exc)
        raise
    finally:
        if live_dashboard and live_run and not live_run_completed:
            try:
                live_dashboard.complete_run(
                    live_run["run_id"],
                    status=live_completion_status,
                    retry_delays=FINAL_PERSISTENCE_RETRY_DELAYS,
                )
            except PersistenceError as exc:
                record_persistence_warning("Live dashboard finalization", exc)
            except Exception as exc:
                console.print(f"[yellow]Could not complete live dashboard run:[/yellow] {exc}")
        if browser:
            await browser.close()
            console.print("Browser closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[red]Fatal error:[/red] {exc}")
        sys.exit(1)
    finally:
        if ACTIVE_RUN_LOGGER is not None:
            ACTIVE_RUN_LOGGER.close()
