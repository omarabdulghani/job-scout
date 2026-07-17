"""Structured search-query groups and adaptive multi-query planning."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.query_learning import order_queries_with_learning


SCHEMA_VERSION = "search_query_groups.v1"
SEARCH_GROUPS = ("primary", "bridge", "fallback")
SEARCH_GROUP_LABELS = {
    "primary": "Primary Path",
    "bridge": "Bridge Opportunity",
    "fallback": "Fallback Income",
}
SEARCH_GOAL_GROUPS = {
    "career-growth": ("primary", "bridge"),
    "career-focus": ("primary",),
    "broad": ("primary", "bridge", "fallback"),
    "income": ("fallback",),
}
SEARCH_GOAL_LABELS = {
    "career-growth": "Career + Growth",
    "career-focus": "Career Focus",
    "broad": "Broaden Opportunities",
    "income": "Income Priority",
    "custom": "Custom",
    "custom-file": "Custom query file",
    "legacy": "Legacy query list",
    "ai-generated": "AI Generated Queries",
}
INITIAL_COVERAGE_LIMITS = {
    "primary": 10,
    "bridge": 8,
    "fallback": 6,
}
DEFAULT_FALLBACK_QUERIES = [
    "customer support",
    "back office",
    "order processing",
    "office assistant",
    "administrative assistant",
    "receptionist",
    "retail sales assistant",
    "travel consultant",
    "operations assistant",
]

_PRIMARY_MARKERS = (
    "designer",
    "design",
    "creative",
    "brand",
    "content",
    "social media",
    "community",
    "ugc",
    "influencer",
    "marketing communications",
    "campaign",
    "ecommerce",
    "merchand",
    "product coordinator",
    "product specialist",
    "product manager",
    "product marketing",
    "product operations",
    "digital operations",
    "ai product operations",
)
_BRIDGE_MARKERS = (
    "customer success",
    "customer experience",
    "partner experience",
    "partner operations",
    "customer operations",
    "project coordinator",
    "project assistant",
    "operations coordinator",
    "business operations",
    "implementation consultant",
    "ai implementation",
    "ai customer success",
    "ai product support",
    "ai operations",
    "ai content quality",
    "prompt evaluator",
    "model evaluator",
    "ai evaluator",
    "business analyst",
    "data analyst",
    "reporting analyst",
    "insights analyst",
    "bi trainee",
    "analytics trainee",
    "graduate program",
    "graduate programme",
    "traineeship",
    "procurement trainee",
    "supply chain trainee",
    "research assistant",
    "clinical study assistant",
)


def empty_query_groups() -> dict[str, list[str]]:
    return {group: [] for group in SEARCH_GROUPS}


def normalize_query_groups(payload: Any) -> dict[str, list[str]]:
    raw_groups = payload.get("groups", payload) if isinstance(payload, dict) else {}
    groups = empty_query_groups()
    for group in SEARCH_GROUPS:
        groups[group] = _dedupe_queries(raw_groups.get(group, []))
    return groups


def query_groups_payload(groups: dict[str, list[str]]) -> dict[str, Any]:
    normalized = normalize_query_groups(groups)
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now().astimezone().isoformat(),
        "groups": normalized,
    }


def migrate_flat_queries(queries: list[str], *, seed_fallback: bool = True) -> dict[str, list[str]]:
    groups = empty_query_groups()
    for query in _dedupe_queries(queries):
        groups[classify_query_group(query)].append(query)
    if seed_fallback:
        groups["fallback"] = _dedupe_queries(
            [*groups["fallback"], *DEFAULT_FALLBACK_QUERIES]
        )
    return groups


def merge_legacy_queries(
    queries: list[str],
    existing_groups: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Preserve known memberships while assigning unknown legacy entries to Primary."""
    normalized_existing = normalize_query_groups(existing_groups)
    memberships: dict[str, list[str]] = {}
    for group in SEARCH_GROUPS:
        for query in normalized_existing[group]:
            memberships.setdefault(_normalize_query(query), []).append(group)

    merged = empty_query_groups()
    for query in _dedupe_queries(queries):
        known_groups = memberships.get(_normalize_query(query), ["primary"])
        for group in known_groups:
            merged[group].append(query)
    return {group: _dedupe_queries(values) for group, values in merged.items()}


def flatten_query_groups(groups: dict[str, list[str]]) -> list[str]:
    flattened: list[str] = []
    for group in SEARCH_GROUPS:
        flattened.extend(normalize_query_groups(groups)[group])
    return _dedupe_queries(flattened)


def classify_query_group(query: str) -> str:
    normalized = _normalize_query(query)
    if any(marker in normalized for marker in _BRIDGE_MARKERS):
        return "bridge"
    if any(marker in normalized for marker in _PRIMARY_MARKERS):
        return "primary"
    return "primary"


def resolve_search_groups(
    search_goal: str,
    selected_groups: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    goal = str(search_goal or "").strip().lower()
    if goal == "custom":
        groups = [
            group
            for group in SEARCH_GROUPS
            if group in {str(value or "").strip().lower() for value in selected_groups or []}
        ]
        if not groups:
            raise ValueError("Custom search goal requires at least one search group")
        return groups
    if goal not in SEARCH_GOAL_GROUPS:
        raise ValueError(f"Unsupported search goal: {search_goal}")
    return list(SEARCH_GOAL_GROUPS[goal])


def build_search_query_plan(
    query_groups: dict[str, list[str]],
    *,
    search_goal: str,
    selected_groups: list[str] | tuple[str, ...] | None = None,
    preferences: dict[str, Any] | None = None,
    learning_enabled: bool = True,
    multi_output_path: Path | str = Path("data/high_success_probability_jobs_multi.json"),
    run_history_path: Path | str = Path("data/scout_run_history.json"),
    learning_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    groups = normalize_query_groups(query_groups)
    selected = resolve_search_groups(search_goal, selected_groups)
    ordered_by_group: dict[str, list[str]] = {}
    learning: dict[str, dict[str, Any]] = {}
    for group in selected:
        ordered, metadata = order_queries_with_learning(
            groups[group],
            preferences=preferences,
            enabled=learning_enabled,
            multi_output_path=multi_output_path,
            run_history_path=run_history_path,
            learning_context={
                **dict(learning_scope or {}),
                "search_group": group,
            },
        )
        ordered_by_group[group] = ordered
        learning[group] = metadata

    memberships: dict[str, list[str]] = {}
    original_values: dict[str, str] = {}
    for group in selected:
        for query in ordered_by_group[group]:
            key = _normalize_query(query)
            original_values.setdefault(key, query)
            memberships.setdefault(key, [])
            if group not in memberships[key]:
                memberships[key].append(group)

    entries: list[dict[str, Any]] = []
    emitted: set[str] = set()
    multi_group = len(selected) > 1

    def emit(group: str, queries: list[str], *, initial: bool) -> None:
        for query in queries:
            key = _normalize_query(query)
            if key in emitted:
                continue
            emitted.add(key)
            entries.append(
                {
                    "query": original_values.get(key, query),
                    "search_group": group,
                    "matched_search_groups": list(memberships.get(key, [group])),
                    "phase": group,
                    "initial_coverage": bool(initial),
                }
            )

    if multi_group:
        for group in selected:
            limit = INITIAL_COVERAGE_LIMITS[group]
            emit(group, ordered_by_group[group][:limit], initial=True)
        initial_coverage_count = len(entries)
        for group in selected:
            limit = INITIAL_COVERAGE_LIMITS[group]
            emit(group, ordered_by_group[group][limit:], initial=False)
    else:
        group = selected[0]
        emit(group, ordered_by_group[group], initial=False)
        initial_coverage_count = 0

    if not entries:
        raise ValueError("The selected search groups do not contain any queries")

    return {
        "schema_version": SCHEMA_VERSION,
        "search_goal": search_goal,
        "search_goal_label": SEARCH_GOAL_LABELS.get(search_goal, search_goal),
        "selected_groups": selected,
        "phase_order": list(selected),
        "initial_coverage_count": initial_coverage_count,
        "ai_budget_eligible_after_index": initial_coverage_count - 1 if multi_group else -1,
        "entries": entries,
        "queries": [entry["query"] for entry in entries],
        "query_learning": learning,
    }


def query_plan_metadata(plan: dict[str, Any], query: str) -> dict[str, Any]:
    key = _normalize_query(query)
    for entry in plan.get("entries", []):
        if _normalize_query(entry.get("query", "")) == key:
            return deepcopy(entry)
    return {
        "query": query,
        "search_group": "",
        "matched_search_groups": [],
        "phase": "",
        "initial_coverage": False,
    }


def _dedupe_queries(values: Any) -> list[str]:
    if isinstance(values, str):
        values = values.splitlines()
    output: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        cleaned = " ".join(str(value or "").split())
        key = _normalize_query(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _normalize_query(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()
