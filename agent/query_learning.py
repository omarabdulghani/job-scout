from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class QueryLearningPolicy:
    """Runtime query ordering based on previous scout yield."""

    enabled: bool = True
    history_run_limit: int = 80
    exploration_interval: int = 5
    top_query_preview_count: int = 8

    @classmethod
    def from_preferences(cls, preferences: dict[str, Any] | None, *, enabled: bool = True) -> "QueryLearningPolicy":
        raw: dict[str, Any] = {}
        preferences = preferences or {}
        if isinstance(preferences.get("query_learning"), dict):
            raw.update(preferences["query_learning"])
        linkedin = preferences.get("job_boards", {}).get("linkedin", {})
        if isinstance(linkedin.get("query_learning"), dict):
            raw.update(linkedin["query_learning"])
        return cls(
            enabled=enabled and _bool_setting(raw, "enabled", cls.enabled),
            history_run_limit=_int_setting(raw, "history_run_limit", cls.history_run_limit),
            exploration_interval=_int_setting(raw, "exploration_interval", cls.exploration_interval),
            top_query_preview_count=_int_setting(raw, "top_query_preview_count", cls.top_query_preview_count),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "history_run_limit": self.history_run_limit,
            "exploration_interval": self.exploration_interval,
            "top_query_preview_count": self.top_query_preview_count,
        }


def order_queries_with_learning(
    queries: list[str],
    *,
    preferences: dict[str, Any] | None = None,
    enabled: bool = True,
    multi_output_path: Path | str = Path("data/high_success_probability_jobs_multi.json"),
    run_history_path: Path | str = Path("data/scout_run_history.json"),
    learning_context: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    policy = QueryLearningPolicy.from_preferences(preferences, enabled=enabled)
    cleaned_queries = _dedupe_queries(queries)
    if not policy.enabled or len(cleaned_queries) <= 1:
        return cleaned_queries, _metadata(policy, cleaned_queries, {}, reordered=False, reason="disabled")

    query_index = {_normalize_query(query): index for index, query in enumerate(cleaned_queries)}
    scores = {
        _normalize_query(query): {
            "query": query,
            "score": 0.0,
            "apply_first": 0,
            "good_options": 0,
            "new_jobs": 0,
            "known_jobs": 0,
            "accepted": 0,
            "rejected": 0,
            "runs_seen": 0,
        }
        for query in cleaned_queries
    }
    sources_used: list[str] = []

    if _apply_multi_output_scores(
        scores,
        Path(multi_output_path),
        query_index,
        learning_context=learning_context,
    ):
        sources_used.append(str(multi_output_path))
    if _apply_run_history_scores(
        scores,
        Path(run_history_path),
        query_index,
        policy.history_run_limit,
        learning_context=learning_context,
    ):
        sources_used.append(str(run_history_path))

    if not sources_used:
        return cleaned_queries, _metadata(policy, cleaned_queries, scores, reordered=False, reason="no learning data")

    ordered = _interleaved_order(cleaned_queries, scores, query_index, policy.exploration_interval)
    reordered = [_normalize_query(query) for query in ordered] != [_normalize_query(query) for query in cleaned_queries]
    return ordered, _metadata(
        policy,
        ordered,
        scores,
        reordered=reordered,
        reason="learned from previous query yield" if reordered else "learned order matched file order",
        sources_used=sources_used,
    )


def _apply_multi_output_scores(
    scores: dict[str, dict[str, Any]],
    path: Path,
    query_index: dict[str, int],
    *,
    learning_context: dict[str, Any] | None = None,
) -> bool:
    payload = _load_json(path)
    if not payload or not _scope_matches(payload.get("search_scope"), learning_context):
        return False

    used = False
    for summary in payload.get("per_query_summary", []) if isinstance(payload.get("per_query_summary"), list) else []:
        query_key = _normalize_query(summary.get("query", ""))
        if query_key not in scores:
            continue
        stat = scores[query_key]
        new_jobs = _safe_int(summary.get("total_scanned"))
        accepted = _safe_int(summary.get("new_recommendations")) + _safe_int(summary.get("cached_previous_recommendations"))
        rejected = _safe_int(summary.get("rejected_or_below_threshold"))
        known = _safe_int(summary.get("previously_analyzed_jobs_skipped_at_card_stage"))
        stat["new_jobs"] += new_jobs
        stat["accepted"] += accepted
        stat["rejected"] += rejected
        stat["known_jobs"] += known
        stat["runs_seen"] += 1
        stat["score"] += accepted * 28 + new_jobs * 2 - rejected * 1.5
        if new_jobs == 0 and accepted == 0 and known >= 8:
            stat["score"] -= 12
        used = True

    for bucket, weight, field in (
        ("apply_first", 90, "apply_first"),
        ("consider_human_review", 34, "good_options"),
    ):
        for job in payload.get(bucket, []) if isinstance(payload.get(bucket), list) else []:
            for query_key in _job_query_keys(job, query_index):
                stat = scores[query_key]
                stat[field] += 1
                stat["score"] += weight
                used = True

    return used


def _apply_run_history_scores(
    scores: dict[str, dict[str, Any]],
    path: Path,
    query_index: dict[str, int],
    limit: int,
    *,
    learning_context: dict[str, Any] | None = None,
) -> bool:
    payload = _load_json(path)
    runs = payload.get("runs", []) if isinstance(payload, dict) else []
    if not isinstance(runs, list):
        return False

    used = False
    for entry in runs[: max(1, limit)]:
        if not isinstance(entry, dict):
            continue
        if not _scope_matches(entry.get("search_scope"), learning_context):
            continue
        query_key = _normalize_query(entry.get("query", ""))
        if query_key not in scores:
            continue
        accepted = _safe_int(entry.get("new_recommendations")) + _safe_int(entry.get("cached_previous_recommendations"))
        scanned = _safe_int(entry.get("total_scanned"))
        rejected = _safe_int(entry.get("rejected_or_below_threshold"))
        stat = scores[query_key]
        stat["accepted"] += accepted
        stat["new_jobs"] += scanned
        stat["rejected"] += rejected
        stat["runs_seen"] += 1
        stat["score"] += accepted * 14 + scanned * 0.6 - rejected * 0.8
        if scanned == 0 and accepted == 0:
            stat["score"] -= 3
        used = True
    return used


def _scope_matches(
    candidate: Any,
    expected: dict[str, Any] | None,
) -> bool:
    if not expected:
        return True
    if not isinstance(candidate, dict):
        return False
    for key in ("platform", "search_market", "employment"):
        expected_value = str(expected.get(key) or "").strip().lower()
        if not expected_value:
            continue
        candidate_value = str(candidate.get(key) or "").strip().lower()
        if candidate_value != expected_value:
            return False
    expected_group = str(expected.get("search_group") or "").strip().lower()
    if expected_group:
        candidate_group = str(
            candidate.get("search_group")
            or candidate.get("current_search_group")
            or ""
        ).strip().lower()
        if candidate_group and candidate_group != expected_group:
            return False
    return True


def _interleaved_order(
    queries: list[str],
    scores: dict[str, dict[str, Any]],
    query_index: dict[str, int],
    exploration_interval: int,
) -> list[str]:
    sorted_by_score = sorted(
        queries,
        key=lambda query: (
            -float(scores[_normalize_query(query)]["score"]),
            query_index[_normalize_query(query)],
        ),
    )
    productive = [query for query in sorted_by_score if float(scores[_normalize_query(query)]["score"]) > 0]
    exploration = [query for query in queries if query not in productive]
    if not productive:
        return queries

    interval = max(1, exploration_interval)
    ordered: list[str] = []
    exploration_index = 0
    for index, query in enumerate(productive, start=1):
        ordered.append(query)
        if index % interval == 0 and exploration_index < len(exploration):
            ordered.append(exploration[exploration_index])
            exploration_index += 1
    ordered.extend(exploration[exploration_index:])
    return ordered


def _metadata(
    policy: QueryLearningPolicy,
    ordered_queries: list[str],
    scores: dict[str, dict[str, Any]],
    *,
    reordered: bool,
    reason: str,
    sources_used: list[str] | None = None,
) -> dict[str, Any]:
    top = sorted(
        scores.values(),
        key=lambda item: (-float(item.get("score", 0)), ordered_queries.index(item["query"]) if item["query"] in ordered_queries else 10**6),
    )[: max(1, policy.top_query_preview_count)] if scores else []
    return {
        "enabled": policy.enabled,
        "reordered": bool(reordered),
        "reason": reason,
        "policy": policy.as_dict(),
        "sources_used": sources_used or [],
        "top_queries": [
            {
                "query": item["query"],
                "score": round(float(item.get("score", 0)), 2),
                "apply_first": _safe_int(item.get("apply_first")),
                "good_options": _safe_int(item.get("good_options")),
                "new_jobs": _safe_int(item.get("new_jobs")),
                "known_jobs": _safe_int(item.get("known_jobs")),
            }
            for item in top
        ],
    }


def _job_query_keys(job: dict[str, Any], query_index: dict[str, int]) -> list[str]:
    candidates: list[str] = []
    for key in ("best_matching_query", "query"):
        if job.get(key):
            candidates.append(str(job.get(key)))
    for key in ("matched_queries", "seen_as_queries"):
        values = job.get(key, [])
        if isinstance(values, list):
            candidates.extend(str(value) for value in values)
    if isinstance(job.get("query_hits"), list):
        candidates.extend(str(hit.get("query", "")) for hit in job["query_hits"] if isinstance(hit, dict))
    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        query_key = _normalize_query(candidate)
        if query_key in query_index and query_key not in seen:
            seen.add(query_key)
            normalized.append(query_key)
    return normalized


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dedupe_queries(queries: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for query in queries:
        cleaned = " ".join(str(query or "").split())
        key = _normalize_query(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _normalize_query(value: str) -> str:
    return " ".join(str(value or "").split()).lower()


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value or 0).strip()))
    except (TypeError, ValueError):
        return 0


def _int_setting(settings: dict[str, Any], key: str, default: int) -> int:
    try:
        return max(1, int(settings.get(key, default)))
    except (TypeError, ValueError):
        return default


def _bool_setting(settings: dict[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)
