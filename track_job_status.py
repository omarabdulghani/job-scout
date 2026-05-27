import argparse
import json
from pathlib import Path

from agent.job_tracking import JobTrackingStore


OUTPUT_PATH = Path("high_success_probability_jobs.json")
SCORE_CACHE_PATH = Path("scored_jobs_cache.json")


def _iter_output_jobs(payload: dict) -> list[dict]:
    jobs: list[dict] = []
    for bucket in ("new_recommendations", "cached_previous_recommendations"):
        grouped = payload.get(bucket, {})
        if not isinstance(grouped, dict):
            continue
        for tier_jobs in grouped.values():
            if isinstance(tier_jobs, list):
                jobs.extend(job for job in tier_jobs if isinstance(job, dict))
    for job in payload.get("rejected_or_below_threshold", []):
        if isinstance(job, dict):
            jobs.append(job)
    return jobs


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_known_metadata(store: JobTrackingStore, reference: str) -> dict:
    resolved = store.resolve_reference(reference)
    cache_key = resolved.get("cache_key", "")
    if not cache_key:
        return {
            "job_id": resolved.get("job_id", ""),
            "url": resolved.get("url", ""),
        }

    candidates: list[dict] = []

    output_payload = _load_json(OUTPUT_PATH)
    candidates.extend(_iter_output_jobs(output_payload))

    score_cache_payload = _load_json(SCORE_CACHE_PATH)
    for job in score_cache_payload.get("jobs", []):
        if isinstance(job, dict):
            candidates.append(job)

    for candidate in candidates:
        url = store.canonicalize_linkedin_job_url(candidate.get("url", ""))
        job_id = candidate.get("job_id", "") or store.linkedin_job_id(url)
        candidate_key = store.cache_key_from_parts(job_id, url)
        if candidate_key != cache_key:
            continue
        return {
            "job_id": job_id,
            "url": url,
            "title": candidate.get("title", ""),
            "company": candidate.get("company", ""),
            "location": candidate.get("location", ""),
        }

    return {
        "job_id": resolved.get("job_id", ""),
        "url": resolved.get("url", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Track a recommended LinkedIn job with a lightweight manual status.",
    )
    parser.add_argument("job_reference", help="LinkedIn job URL or numeric LinkedIn job ID")
    parser.add_argument(
        "status",
        choices=sorted(JobTrackingStore.ALLOWED_STATUSES),
        help="Manual tracking status to save",
    )
    args = parser.parse_args()

    store = JobTrackingStore()
    metadata = _find_known_metadata(store, args.job_reference)
    entry = store.set_status(
        status=args.status,
        job_id=metadata.get("job_id", ""),
        url=metadata.get("url", ""),
        title=metadata.get("title", ""),
        company=metadata.get("company", ""),
        location=metadata.get("location", ""),
    )

    print("Tracking status updated.")
    print(f"File: {store.path}")
    print(f"Status: {entry.get('tracking_status', '')}")
    print(f"Updated: {entry.get('tracking_updated_at', '')}")
    print(f"Job ID: {entry.get('job_id', '')}")
    print(f"URL: {entry.get('url', '')}")
    if entry.get("title"):
        print(f"Title: {entry.get('title', '')}")
    if entry.get("company"):
        print(f"Company: {entry.get('company', '')}")
    if entry.get("location"):
        print(f"Location: {entry.get('location', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
