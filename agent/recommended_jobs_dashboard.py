"""Update the persistent human-facing recommended jobs HTML dashboard.

This module intentionally touches only the embedded JSON data block in
recommended_jobs.html. Layout, styling, and checkbox/localStorage behavior stay
owned by the HTML file.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any


SINGLE_OUTPUT_PATH = Path("high_success_probability_jobs.json")
MULTI_OUTPUT_PATH = Path("high_success_probability_jobs_multi.json")
HTML_DASHBOARD_PATH = Path("recommended_jobs.html")
EMBEDDED_SCRIPT_OPEN_RE = re.compile(
    r'(<script\s+type="application/json"\s+id="embeddedRecommendations"\s*>\s*)',
    re.IGNORECASE,
)
EMBEDDED_SCRIPT_CLOSE = "</script>"


def update_recommended_jobs_html(project_root: Path | str | None = None) -> dict[str, Any]:
    """Merge current scout outputs into recommended_jobs.html.

    The updater reads only high_success_probability_jobs.json and
    high_success_probability_jobs_multi.json as new recommendation sources.
    It reads the existing embedded dashboard data only to preserve jobs that
    were already visible, so applying/checking jobs remains a stable workflow.
    """

    root = Path(project_root or ".").resolve()
    html_path = root / HTML_DASHBOARD_PATH
    if not html_path.exists():
        return {
            "updated": False,
            "reason": f"{HTML_DASHBOARD_PATH} not found",
            "html_path": str(html_path),
        }

    existing_data = _read_embedded_dashboard_data(html_path)
    source_data = _read_source_recommendations(root)
    merged_data = _merge_dashboard_data(existing_data, source_data, root)
    _write_embedded_dashboard_data(html_path, merged_data)

    return {
        "updated": True,
        "html_path": str(html_path),
        "go_jobs": len(merged_data.get("go_jobs_apply_first", [])),
        "consider_jobs": len(merged_data.get("consider_jobs_apply_selectively", [])),
        "new_go_jobs_added": merged_data.get("update_summary", {}).get("new_go_jobs_added", 0),
        "new_consider_jobs_added": merged_data.get("update_summary", {}).get(
            "new_consider_jobs_added", 0
        ),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_embedded_dashboard_data(html_path: Path) -> dict[str, Any]:
    html = html_path.read_text(encoding="utf-8")
    match = EMBEDDED_SCRIPT_OPEN_RE.search(html)
    if not match:
        return {}
    close_index = html.find(EMBEDDED_SCRIPT_CLOSE, match.end())
    if close_index == -1:
        return {}
    raw_json = html[match.end() : close_index].strip()
    if not raw_json:
        return {}
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_embedded_dashboard_data(html_path: Path, data: dict[str, Any]) -> None:
    html = html_path.read_text(encoding="utf-8")
    match = EMBEDDED_SCRIPT_OPEN_RE.search(html)
    if not match:
        raise ValueError("recommended_jobs.html is missing embeddedRecommendations script")
    close_index = html.find(EMBEDDED_SCRIPT_CLOSE, match.end())
    if close_index == -1:
        raise ValueError("recommended_jobs.html has an unterminated embeddedRecommendations script")

    new_json = json.dumps(data, indent=2, ensure_ascii=False)
    updated = html[: match.end()] + "\n" + new_json + "\n  " + html[close_index:]
    html_path.write_text(updated, encoding="utf-8")


def _read_source_recommendations(root: Path) -> dict[str, Any]:
    source_paths = [root / SINGLE_OUTPUT_PATH, root / MULTI_OUTPUT_PATH]
    go_jobs: list[dict[str, Any]] = []
    consider_jobs: list[dict[str, Any]] = []
    source_summaries: dict[str, dict[str, int]] = {}

    for path in source_paths:
        payload = _read_json(path)
        if not payload:
            source_summaries[path.name] = {"strong_match": 0, "possible_match": 0}
            continue

        strong = _extract_recommendation_bucket(payload, "strong_match")
        possible = _extract_recommendation_bucket(payload, "possible_match")
        source_summaries[path.name] = {
            "strong_match": len(strong),
            "possible_match": len(possible),
        }
        for item in strong:
            go_jobs.append(_normalize_job(item, decision="GO", source_file=path.name))
        for item in possible:
            consider_jobs.append(
                _normalize_job(item, decision="CONSIDER", source_file=path.name)
            )

    return {
        "go_jobs": go_jobs,
        "consider_jobs": consider_jobs,
        "source_files": [str(path) for path in source_paths],
        "source_summaries": source_summaries,
    }


def _extract_recommendation_bucket(payload: dict[str, Any], bucket: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for group_name in ("new_recommendations", "cached_previous_recommendations"):
        group = payload.get(group_name) or {}
        if not isinstance(group, dict):
            continue
        group_items = group.get(bucket) or []
        if isinstance(group_items, list):
            items.extend(item for item in group_items if isinstance(item, dict))
    return items


def _merge_dashboard_data(
    existing_data: dict[str, Any],
    source_data: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    existing_go = [
        _normalize_job(item, decision="GO", source_file="existing_dashboard")
        for item in existing_data.get("go_jobs_apply_first", [])
        if isinstance(item, dict)
    ]
    existing_consider = [
        _normalize_job(item, decision="CONSIDER", source_file="existing_dashboard")
        for item in existing_data.get("consider_jobs_apply_selectively", [])
        if isinstance(item, dict)
    ]

    go_jobs, new_go = _merge_job_lists(
        existing_jobs=existing_go,
        source_jobs=source_data.get("go_jobs", []),
    )
    consider_jobs, new_consider = _merge_job_lists(
        existing_jobs=existing_consider,
        source_jobs=source_data.get("consider_jobs", []),
    )

    _renumber(go_jobs)
    _renumber(consider_jobs)

    now = datetime.now().astimezone().isoformat()
    source_files = [
        str(Path(path).resolve()) if not Path(path).is_absolute() else str(Path(path))
        for path in source_data.get("source_files", [])
    ]

    return {
        "generated_at": now,
        "dashboard_updated_at": now,
        "source_files": source_files,
        "summary": {
            "unique_go_jobs_after_merging_all_sources": len(go_jobs),
            "unique_consider_jobs_after_merging_all_sources": len(consider_jobs),
            "unique_recommended_jobs_total": len(go_jobs) + len(consider_jobs),
            "deduplication_rule": (
                "Deduplicated by LinkedIn job ID first, then canonical LinkedIn URL, "
                "then title/company fallback."
            ),
        },
        "update_summary": {
            "new_go_jobs_added": new_go,
            "new_consider_jobs_added": new_consider,
            "source_summaries": source_data.get("source_summaries", {}),
            "existing_go_jobs_preserved": len(existing_go),
            "existing_consider_jobs_preserved": len(existing_consider),
            "project_root": str(root),
        },
        "go_jobs_apply_first": go_jobs,
        "consider_jobs_apply_selectively": consider_jobs,
    }


def _merge_job_lists(
    *,
    existing_jobs: list[dict[str, Any]],
    source_jobs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    existing_by_id = {_job_identity(job): job for job in existing_jobs if _job_identity(job)}
    new_jobs: list[dict[str, Any]] = []

    for source_job in _sort_newest_first(source_jobs):
        identity = _job_identity(source_job)
        if not identity:
            continue
        if identity in existing_by_id:
            existing_by_id[identity] = _merge_existing_with_source(existing_by_id[identity], source_job)
        else:
            new_jobs.append(source_job)
            existing_by_id[identity] = source_job

    existing_identities = {_job_identity(job) for job in existing_jobs}
    existing_identities.discard("")
    existing_updated = [
        existing_by_id[_job_identity(job)]
        for job in existing_jobs
        if _job_identity(job) in existing_by_id
    ]
    return new_jobs + existing_updated, len(new_jobs)


def _normalize_job(item: dict[str, Any], *, decision: str, source_file: str) -> dict[str, Any]:
    score = _safe_int(item.get("score") or item.get("interview_probability_score"))
    link = _canonical_job_url(item.get("link") or item.get("url") or "")
    job_id = _clean_text(item.get("job_id")) or _extract_job_id(link)
    queries = item.get("matched_queries") or item.get("seen_as_queries") or []
    if not isinstance(queries, list):
        queries = []

    normalized = {
        "application_order": _safe_int(item.get("application_order")),
        "title": _clean_title(item.get("title")),
        "company": _clean_text(item.get("company")),
        "location": _clean_text(item.get("location")),
        "score": score,
        "decision": decision,
        "match_tier": item.get("match_tier") or item.get("ai_match_tier") or (
            "strong_match" if decision == "GO" else "possible_match"
        ),
        "why": _clean_text(
            item.get("why")
            or item.get("interview_probability_reason")
            or item.get("short_ai_reasoning")
            or item.get("reason")
        ),
        "link": link,
        "job_id": job_id,
        "query": _clean_text(item.get("query") or item.get("best_matching_query")),
        "seen_as_queries": [_clean_text(query) for query in queries if _clean_text(query)],
        "matched_queries": [_clean_text(query) for query in queries if _clean_text(query)],
        "seen_in_sources": _merge_unique_strings(item.get("seen_in_sources", []), [source_file]),
    }

    for field in (
        "found_at",
        "first_seen_at",
        "last_seen_at",
        "tracking_status",
        "tracking_updated_at",
    ):
        value = item.get(field)
        if value:
            normalized[field] = value

    return normalized


def _merge_existing_with_source(
    existing: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    for field in (
        "title",
        "company",
        "location",
        "score",
        "decision",
        "match_tier",
        "why",
        "link",
        "job_id",
        "query",
        "found_at",
        "first_seen_at",
        "last_seen_at",
        "tracking_status",
        "tracking_updated_at",
    ):
        if source.get(field) not in ("", None, [], {}):
            merged[field] = source[field]

    merged["seen_as_queries"] = _merge_unique_strings(
        existing.get("seen_as_queries", []),
        source.get("seen_as_queries", []),
    )
    merged["matched_queries"] = _merge_unique_strings(
        existing.get("matched_queries", []),
        source.get("matched_queries", []),
    )
    merged["seen_in_sources"] = _merge_unique_strings(
        existing.get("seen_in_sources", []),
        source.get("seen_in_sources", []),
    )
    return merged


def _sort_newest_first(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(job: dict[str, Any]) -> tuple[str, int, str]:
        timestamp = (
            job.get("found_at")
            or job.get("last_seen_at")
            or job.get("first_seen_at")
            or ""
        )
        return (str(timestamp), _safe_int(job.get("score")), job.get("title", ""))

    return sorted(jobs, key=key, reverse=True)


def _renumber(jobs: list[dict[str, Any]]) -> None:
    for index, job in enumerate(jobs, start=1):
        job["application_order"] = index


def _job_identity(job: dict[str, Any]) -> str:
    job_id = _clean_text(job.get("job_id")) or _extract_job_id(job.get("link", ""))
    if job_id:
        return f"id:{job_id}"
    link = _canonical_job_url(job.get("link", ""))
    if link:
        return f"url:{link.lower()}"
    title = _clean_text(job.get("title")).lower()
    company = _clean_text(job.get("company")).lower()
    if title or company:
        return f"title_company:{title}::{company}"
    return ""


def _canonical_job_url(value: Any) -> str:
    text = _clean_text(value)
    job_id = _extract_job_id(text)
    if job_id:
        return f"https://www.linkedin.com/jobs/view/{job_id}/"
    return text


def _extract_job_id(value: Any) -> str:
    match = re.search(r"/jobs/view/(\d+)", str(value or ""))
    return match.group(1) if match else ""


def _clean_title(value: Any) -> str:
    text = _clean_text(value)
    text = re.sub(r"\s+with verification\b", "", text, flags=re.IGNORECASE).strip()
    words = text.split()
    if len(words) >= 4 and len(words) % 2 == 0:
        half = len(words) // 2
        if " ".join(words[:half]).lower() == " ".join(words[half:]).lower():
            text = " ".join(words[:half])
    return text


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _merge_unique_strings(*groups: Any) -> list[str]:
    values: list[str] = []
    for group in groups:
        if isinstance(group, str):
            candidates = [group]
        elif isinstance(group, list):
            candidates = group
        else:
            candidates = []
        for candidate in candidates:
            cleaned = _clean_text(candidate)
            if cleaned and cleaned not in values:
                values.append(cleaned)
    return values
