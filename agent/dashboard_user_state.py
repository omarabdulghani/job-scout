"""Persistent manual status storage for the live jobs dashboard."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


SCHEMA_VERSION = "dashboard_user_state.v1"
DEFAULT_USER_STATE_PATH = Path("recommended_jobs_dashboard_user_state.json")

STATUS_UNREVIEWED = "unreviewed"
STATUS_APPLIED = "applied"
STATUS_IRRELEVANT = "irrelevant"
VALID_STATUSES = {STATUS_UNREVIEWED, STATUS_APPLIED, STATUS_IRRELEVANT}
STATUS_LABELS = {
    STATUS_UNREVIEWED: "Unreviewed",
    STATUS_APPLIED: "Applied",
    STATUS_IRRELEVANT: "Irrelevant",
}


class DashboardUserStateStore:
    """Save user review decisions separately from live scout output."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or DEFAULT_USER_STATE_PATH)
        self.data = self._load_or_create()

    def set_status(
        self,
        job: dict[str, Any],
        status: str,
        *,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_status = normalize_status(status)
        job_key = build_job_key(job)
        if not job_key:
            raise ValueError("Could not build a stable dashboard job key")

        if normalized_status == STATUS_UNREVIEWED:
            self.data["jobs"].pop(job_key, None)
            self._refresh_updated_at(updated_at)
            self.write()
            return {
                "job_key": job_key,
                "status": STATUS_UNREVIEWED,
                "status_label": STATUS_LABELS[STATUS_UNREVIEWED],
                "updated_at": self.data["updated_at"],
            }

        record = {
            "job_key": job_key,
            "status": normalized_status,
            "status_label": STATUS_LABELS[normalized_status],
            "updated_at": updated_at or now_iso(),
            "board": clean_text(job.get("board")) or "linkedin",
            "job_id": clean_text(job.get("job_id")),
            "url": canonical_job_url(job.get("url")),
            "title": clean_text(job.get("title")),
            "company": clean_text(job.get("company")),
            "location": clean_text(job.get("location")),
            "last_run_id": clean_text(job.get("run_id")),
            "last_run_label": clean_text(job.get("run_label")),
        }
        self.data["jobs"][job_key] = record
        self._refresh_updated_at(record["updated_at"])
        self.write()
        return dict(record)

    def get_record(self, job: dict[str, Any]) -> dict[str, Any] | None:
        job_key = build_job_key(job)
        if not job_key:
            return None
        record = self.data.get("jobs", {}).get(job_key)
        return dict(record) if isinstance(record, dict) else None

    def apply_to_dashboard_data(self, dashboard_data: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(dashboard_data) if isinstance(dashboard_data, dict) else {}
        jobs = merged.get("jobs")
        if not isinstance(jobs, list):
            merged["jobs"] = []
            jobs = merged["jobs"]

        for job in jobs:
            if not isinstance(job, dict):
                continue
            job_key = build_job_key(job)
            record = self.data.get("jobs", {}).get(job_key, {}) if job_key else {}
            status = normalize_status(record.get("status")) if record else STATUS_UNREVIEWED
            job["job_key"] = job_key
            job["manual_status"] = status
            job["manual_status_label"] = STATUS_LABELS[status]
            job["manual_updated_at"] = clean_text(record.get("updated_at")) if record else ""

        summary = merged.setdefault("summary", {})
        if isinstance(summary, dict):
            summary["by_manual_status"] = manual_status_counts(jobs)

        filter_options = merged.setdefault("filter_options", {})
        if isinstance(filter_options, dict):
            filter_options["manual_statuses"] = [
                {"value": key, "label": label}
                for key, label in STATUS_LABELS.items()
            ]
        return merged

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        temporary_path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, self.path)

    def _load_or_create(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION:
                payload.setdefault("updated_at", "")
                payload.setdefault("jobs", {})
                if not isinstance(payload["jobs"], dict):
                    payload["jobs"] = {}
                return payload
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": "",
            "jobs": {},
        }

    def _refresh_updated_at(self, updated_at: str | None = None) -> None:
        self.data["updated_at"] = updated_at or now_iso()


def merge_dashboard_user_state(
    dashboard_data: dict[str, Any],
    state_path: Path | str | None = None,
) -> dict[str, Any]:
    return DashboardUserStateStore(state_path).apply_to_dashboard_data(dashboard_data)


def manual_status_counts(jobs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in STATUS_LABELS}
    for job in jobs:
        if not isinstance(job, dict):
            continue
        status = normalize_status(job.get("manual_status"))
        counts[status] += 1
    return counts


def normalize_status(status: Any) -> str:
    value = clean_text(status).lower().replace("-", "_")
    return value if value in VALID_STATUSES else STATUS_UNREVIEWED


def build_job_key(job: dict[str, Any]) -> str:
    board = clean_text(job.get("board")) or "linkedin"
    job_id = clean_text(job.get("job_id"))
    if job_id:
        return f"{board}:job_id:{job_id}"

    canonical_url = canonical_job_url(job.get("url"))
    if canonical_url:
        return f"{board}:url:{canonical_url.lower()}"

    title = normalize_identity_text(job.get("title"))
    company = normalize_identity_text(job.get("company"))
    if title and company:
        return f"{board}:title_company:{title}::{company}"
    return ""


def canonical_job_url(value: Any) -> str:
    url = clean_text(value)
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_identity_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()
