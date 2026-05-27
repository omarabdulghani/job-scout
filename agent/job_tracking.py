import json
import re
from datetime import datetime
from pathlib import Path


class JobTrackingStore:
    STATUS_PATH = Path("job_tracking_status.json")
    ALLOWED_STATUSES = {
        "applied",
        "skipped",
        "saved_for_later",
    }

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else self.STATUS_PATH
        self.entries = self._load()

    def get(self, *, job_id: str = "", url: str = "") -> dict:
        key = self.cache_key_from_parts(job_id, url)
        if not key:
            return {}
        entry = self.entries.get(key, {})
        return dict(entry) if entry else {}

    def set_status(
        self,
        *,
        status: str,
        job_id: str = "",
        url: str = "",
        title: str = "",
        company: str = "",
        location: str = "",
    ) -> dict:
        normalized_status = (status or "").strip().lower()
        if normalized_status not in self.ALLOWED_STATUSES:
            allowed = ", ".join(sorted(self.ALLOWED_STATUSES))
            raise ValueError(f"Unsupported tracking status '{status}'. Allowed values: {allowed}")

        canonical_url = self.canonicalize_linkedin_job_url(url)
        resolved_job_id = (job_id or self.linkedin_job_id(canonical_url)).strip()
        cache_key = self.cache_key_from_parts(resolved_job_id, canonical_url)
        if not cache_key:
            raise ValueError("A LinkedIn job URL or job ID is required.")

        now = datetime.now().astimezone().isoformat()
        entry = self.entries.get(cache_key, {})
        entry.update(
            {
                "cache_key": cache_key,
                "job_id": resolved_job_id,
                "url": canonical_url,
                "tracking_status": normalized_status,
                "tracking_updated_at": now,
            }
        )
        if title:
            entry["title"] = title
        if company:
            entry["company"] = company
        if location:
            entry["location"] = location

        self.entries[cache_key] = entry
        self._write()
        return dict(entry)

    def resolve_reference(self, reference: str) -> dict:
        raw_reference = (reference or "").strip()
        if not raw_reference:
            return {
                "job_id": "",
                "url": "",
                "cache_key": "",
            }

        if raw_reference.isdigit():
            job_id = raw_reference
            url = f"https://www.linkedin.com/jobs/view/{job_id}/"
        else:
            url = self.canonicalize_linkedin_job_url(raw_reference)
            job_id = self.linkedin_job_id(url)

        return {
            "job_id": job_id,
            "url": url,
            "cache_key": self.cache_key_from_parts(job_id, url),
        }

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        jobs = raw.get("jobs", []) if isinstance(raw, dict) else []
        entries: dict[str, dict] = {}
        for entry in jobs:
            if not isinstance(entry, dict):
                continue
            url = self.canonicalize_linkedin_job_url(entry.get("url", ""))
            job_id = (entry.get("job_id", "") or self.linkedin_job_id(url)).strip()
            cache_key = (entry.get("cache_key", "") or self.cache_key_from_parts(job_id, url)).strip()
            if not cache_key:
                continue
            normalized_entry = dict(entry)
            normalized_entry["url"] = url
            normalized_entry["job_id"] = job_id
            normalized_entry["cache_key"] = cache_key
            entries[cache_key] = normalized_entry
        return entries

    def _write(self) -> None:
        payload = {
            "updated_at": datetime.now().astimezone().isoformat(),
            "jobs": sorted(
                self.entries.values(),
                key=lambda item: (
                    item.get("tracking_updated_at") or "",
                    item.get("title") or "",
                    item.get("company") or "",
                ),
                reverse=True,
            ),
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def cache_key_from_parts(self, job_id: str, url: str) -> str:
        normalized_job_id = (job_id or "").strip()
        if normalized_job_id:
            return f"linkedin_job_id:{normalized_job_id}"
        canonical_url = self.canonicalize_linkedin_job_url(url)
        if canonical_url:
            return f"url:{canonical_url}"
        return ""

    def linkedin_job_id(self, url: str) -> str:
        normalized_url = self.canonicalize_linkedin_job_url(url)
        match = re.search(r"/jobs/view/(\d+)/?$", normalized_url)
        return match.group(1) if match else ""

    def canonicalize_linkedin_job_url(self, url: str) -> str:
        raw_url = (url or "").strip()
        if not raw_url:
            return ""

        absolute_url = raw_url
        if raw_url.startswith("/"):
            absolute_url = f"https://www.linkedin.com{raw_url}"

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

        if job_id:
            return f"https://www.linkedin.com/jobs/view/{job_id}/"

        return absolute_url
