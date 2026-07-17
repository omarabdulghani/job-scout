"""Persistent manual status storage for the live jobs dashboard."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agent.safe_file_io import atomic_write_json, load_json_with_recovery


SCHEMA_VERSION = "dashboard_user_state.v1"
DEFAULT_USER_STATE_PATH = Path("data/recommended_jobs_dashboard_user_state.json")

STATUS_UNREVIEWED = "unreviewed"
STATUS_APPLIED = "applied"
STATUS_IRRELEVANT = "irrelevant"
STATUS_EXPIRED = "expired"
VALID_STATUSES = {STATUS_UNREVIEWED, STATUS_APPLIED, STATUS_IRRELEVANT, STATUS_EXPIRED}
STATUS_LABELS = {
    STATUS_UNREVIEWED: "Unreviewed",
    STATUS_APPLIED: "Applied",
    STATUS_IRRELEVANT: "Irrelevant",
    STATUS_EXPIRED: "Expired"
}
APPLICATION_STAGE_NONE = ""
APPLICATION_STAGE_PREPARING = "preparing"
APPLICATION_STAGE_APPLIED = "applied"
APPLICATION_STAGE_INTERVIEW = "interview"
APPLICATION_STAGE_OFFER = "offer"
APPLICATION_STAGE_REJECTED = "rejected"
APPLICATION_STAGE_WITHDRAWN = "withdrawn"
APPLICATION_STAGE_LABELS = {
    APPLICATION_STAGE_NONE: "Not started",
    APPLICATION_STAGE_PREPARING: "Preparing",
    APPLICATION_STAGE_APPLIED: "Applied",
    APPLICATION_STAGE_INTERVIEW: "Interview",
    APPLICATION_STAGE_OFFER: "Offer",
    APPLICATION_STAGE_REJECTED: "Rejected",
    APPLICATION_STAGE_WITHDRAWN: "Withdrawn",
}
VALID_APPLICATION_STAGES = set(APPLICATION_STAGE_LABELS)


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
        existing = self.data.get("jobs", {}).get(job_key, {})
        if isinstance(existing, dict):
            for field in (
                "application_stage",
                "application_stage_label",
                "application_updated_at",
                "applied_at",
                "follow_up_at",
                "notes",
            ):
                if field in existing:
                    record[field] = existing[field]
        if normalized_status == STATUS_APPLIED and not record.get("application_stage"):
            record["application_stage"] = APPLICATION_STAGE_APPLIED
            record["application_stage_label"] = APPLICATION_STAGE_LABELS[APPLICATION_STAGE_APPLIED]
            record["application_updated_at"] = record["updated_at"]
            record["applied_at"] = record["updated_at"]
        self.data["jobs"][job_key] = record
        self._refresh_updated_at(record["updated_at"])
        self.write()
        return dict(record)

    def update_application(
        self,
        job: dict[str, Any],
        *,
        stage: str,
        notes: str = "",
        applied_at: str = "",
        follow_up_at: str = "",
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_stage = normalize_application_stage(stage)
        job_key = build_job_key(job)
        if not job_key:
            raise ValueError("Could not build a stable dashboard job key")
        timestamp = updated_at or now_iso()
        existing = self.data.get("jobs", {}).get(job_key, {})
        record = dict(existing) if isinstance(existing, dict) else {}
        record.update(
            {
                "job_key": job_key,
                "status": (
                    STATUS_UNREVIEWED
                    if normalized_stage in {APPLICATION_STAGE_NONE, APPLICATION_STAGE_PREPARING}
                    else STATUS_APPLIED
                ),
                "status_label": (
                    STATUS_LABELS[STATUS_UNREVIEWED]
                    if normalized_stage in {APPLICATION_STAGE_NONE, APPLICATION_STAGE_PREPARING}
                    else STATUS_LABELS[STATUS_APPLIED]
                ),
                "updated_at": timestamp,
                "board": clean_text(job.get("board")) or record.get("board") or "linkedin",
                "job_id": clean_text(job.get("job_id")) or record.get("job_id", ""),
                "url": canonical_job_url(job.get("url")) or record.get("url", ""),
                "title": clean_text(job.get("title")) or record.get("title", ""),
                "company": clean_text(job.get("company")) or record.get("company", ""),
                "location": clean_text(job.get("location")) or record.get("location", ""),
                "last_run_id": clean_text(job.get("run_id")) or record.get("last_run_id", ""),
                "last_run_label": clean_text(job.get("run_label")) or record.get("last_run_label", ""),
                "application_stage": normalized_stage,
                "application_stage_label": APPLICATION_STAGE_LABELS[normalized_stage],
                "application_updated_at": timestamp,
                "notes": str(notes or "").strip()[:5000],
                "applied_at": clean_text(applied_at),
                "follow_up_at": clean_text(follow_up_at),
            }
        )
        if normalized_stage == APPLICATION_STAGE_APPLIED and not record["applied_at"]:
            record["applied_at"] = timestamp
        if normalized_stage == APPLICATION_STAGE_NONE and not record["notes"] and not record["follow_up_at"]:
            self.data["jobs"].pop(job_key, None)
            self._refresh_updated_at(timestamp)
            self.write()
            return {
                "job_key": job_key,
                "status": STATUS_UNREVIEWED,
                "status_label": STATUS_LABELS[STATUS_UNREVIEWED],
                "application_stage": APPLICATION_STAGE_NONE,
                "application_stage_label": APPLICATION_STAGE_LABELS[APPLICATION_STAGE_NONE],
                "updated_at": timestamp,
            }
        self.data["jobs"][job_key] = record
        self._refresh_updated_at(timestamp)
        self.write()
        return dict(record)

    def application_records(
        self,
        dashboard_data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        live_jobs: dict[str, dict[str, Any]] = {}
        if isinstance(dashboard_data, dict):
            for job in dashboard_data.get("jobs", []):
                if isinstance(job, dict):
                    job_key = build_job_key(job)
                    if job_key:
                        live_jobs[job_key] = job
        records: list[dict[str, Any]] = []
        for job_key, saved in self.data.get("jobs", {}).items():
            if not isinstance(saved, dict):
                continue
            stage = normalize_application_stage(saved.get("application_stage"))
            if not stage and normalize_status(saved.get("status")) != STATUS_APPLIED:
                continue
            if not stage:
                stage = APPLICATION_STAGE_APPLIED
            merged = dict(live_jobs.get(job_key, {}))
            merged.update(saved)
            merged["job_key"] = job_key
            merged["application_stage"] = stage
            merged["application_stage_label"] = APPLICATION_STAGE_LABELS[stage]
            records.append(merged)
        return sorted(
            records,
            key=lambda item: (
                clean_text(item.get("application_updated_at") or item.get("updated_at")),
                clean_text(item.get("title")),
            ),
            reverse=True,
        )

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
            stage = normalize_application_stage(record.get("application_stage")) if record else ""
            if not stage and status == STATUS_APPLIED:
                stage = APPLICATION_STAGE_APPLIED
            job["application_stage"] = stage
            job["application_stage_label"] = APPLICATION_STAGE_LABELS[stage]
            job["application_updated_at"] = clean_text(record.get("application_updated_at")) if record else ""
            job["applied_at"] = clean_text(record.get("applied_at")) if record else ""
            job["follow_up_at"] = clean_text(record.get("follow_up_at")) if record else ""
            job["application_notes"] = str(record.get("notes") or "") if record else ""

        summary = merged.setdefault("summary", {})
        if isinstance(summary, dict):
            summary["by_manual_status"] = manual_status_counts(jobs)
            
            # Live Inbox dynamic subtraction
            if "by_decision" in summary:
                by_decision = dict(summary["by_decision"])
                for job in jobs:
                    if job.get("manual_status") != STATUS_UNREVIEWED:
                        decision = job.get("decision_category")
                        if decision and decision in by_decision:
                            by_decision[decision] = max(0, by_decision[decision] - 1)
                summary["by_decision"] = by_decision
                
            summary["total_jobs"] = summary["by_manual_status"].get(STATUS_UNREVIEWED, 0)

        filter_options = merged.setdefault("filter_options", {})
        if isinstance(filter_options, dict):
            filter_options["manual_statuses"] = [
                {"value": key, "label": label}
                for key, label in STATUS_LABELS.items()
            ]
        return merged

    def write(self) -> None:
        atomic_write_json(self.path, self.data)

    def _load_or_create(self) -> dict[str, Any]:
        payload = load_json_with_recovery(self.path)
        if payload.get("schema_version") == SCHEMA_VERSION:
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


def normalize_application_stage(stage: Any) -> str:
    value = clean_text(stage).lower().replace("-", "_")
    return value if value in VALID_APPLICATION_STAGES else APPLICATION_STAGE_NONE


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
