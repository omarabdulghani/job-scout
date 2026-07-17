import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from agent.safe_file_io import atomic_write_json, load_json_with_recovery

if TYPE_CHECKING:
    from agent.operational_store import OperationalStore


class ScoutCollectedJobsStore:
    COLLECTED_JOBS_PATH = Path("data/scout_collected_jobs.json")

    def __init__(
        self,
        path: Path | None = None,
        *,
        operational_store: "OperationalStore | None" = None,
    ):
        self.path = Path(path) if path else self.COLLECTED_JOBS_PATH
        self.operational_store = operational_store
        self.jobs = self._load()
        self.index = self._build_index()

    def get_by_identity_keys(self, identity_keys: list[str]) -> dict | None:
        for key in identity_keys or []:
            entry = self.index.get(key)
            if entry:
                return dict(entry)
                
        if getattr(self, "operational_store", None) and identity_keys:
            fallback = self.operational_store.get_collected_job(identity_keys)
            if fallback:
                return fallback
        return None

    def is_analyzed(self, identity_keys: list[str]) -> bool:
        entry = self.get_by_identity_keys(identity_keys)
        if not entry:
            return False
        return bool((entry.get("analyzed_at") or "").strip() or (entry.get("analysis_status") or "").strip())

    def upsert_job(self, record: dict) -> dict:
        normalized = self._normalize_record(record)
        if not normalized.get("identity_keys"):
            return normalized

        existing = self.get_by_identity_keys(normalized.get("identity_keys", []))
        if existing:
            existing_identity_keys = list(existing.get("identity_keys", []) or [])
            normalized["queries_seen"] = self._merge_unique_strings(
                existing.get("queries_seen", []),
                normalized.get("queries_seen", []),
            )
            normalized["identity_keys"] = self._merge_unique_strings(
                existing_identity_keys,
                normalized.get("identity_keys", []),
            )
            normalized["collected_at"] = existing.get("collected_at") or normalized.get("collected_at", "")
            normalized["title"] = self._prefer_non_empty(normalized.get("title", ""), existing.get("title", ""))
            normalized["company"] = self._prefer_non_empty(normalized.get("company", ""), existing.get("company", ""))
            normalized["location"] = self._prefer_non_empty(normalized.get("location", ""), existing.get("location", ""))
            normalized["url"] = self._prefer_non_empty(normalized.get("url", ""), existing.get("url", ""))
            normalized["job_id"] = self._prefer_non_empty(normalized.get("job_id", ""), existing.get("job_id", ""))
            normalized["description"] = self._prefer_non_empty(
                normalized.get("description", ""),
                existing.get("description", ""),
            )
            normalized["description_debug"] = self._merge_description_debug(
                existing.get("description_debug", {}) or {},
                normalized.get("description_debug", {}) or {},
            )
            normalized["analyzed_at"] = existing.get("analyzed_at") or normalized.get("analyzed_at", "")
            normalized["analysis_status"] = self._prefer_non_empty(
                normalized.get("analysis_status", ""),
                existing.get("analysis_status", ""),
            )
            normalized["analysis_reason"] = self._prefer_non_empty(
                normalized.get("analysis_reason", ""),
                existing.get("analysis_reason", ""),
            )
            normalized["easy_apply"] = bool(existing.get("easy_apply")) or bool(normalized.get("easy_apply"))
            normalized["apply_method"] = self._prefer_apply_method(
                normalized.get("apply_method", ""),
                existing.get("apply_method", ""),
                normalized.get("easy_apply", False),
            )
            normalized["apply_method_detection_source"] = self._prefer_non_empty(
                normalized.get("apply_method_detection_source", ""),
                existing.get("apply_method_detection_source", ""),
            )
            self.jobs = [
                normalized
                if self._same_record(existing, job)
                else job
                for job in self.jobs
            ]
        else:
            self.jobs.append(normalized)

        self.index = self._build_index()
        self._write()
        return dict(normalized)

    def find_for_query(self, query: str, max_pages: int | None = None) -> list[dict]:
        return self.find_for_query_with_options(query=query, max_pages=max_pages, include_analyzed=True)

    def find_for_query_with_options(
        self,
        *,
        query: str,
        max_pages: int | None = None,
        include_analyzed: bool = True,
    ) -> list[dict]:
        normalized_query = self._normalize_query(query)
        if not normalized_query:
            return []

        matched = []
        for job in self.jobs:
            queries_seen = [self._normalize_query(value) for value in job.get("queries_seen", [])]
            primary_query = self._normalize_query(job.get("query", ""))
            if normalized_query not in queries_seen and normalized_query != primary_query:
                continue
            if max_pages is not None:
                page_number = int(job.get("page_number", 0) or 0)
                if page_number and page_number > max_pages:
                    continue
            if not include_analyzed and (
                (job.get("analyzed_at") or "").strip() or (job.get("analysis_status") or "").strip()
            ):
                continue
            matched.append(dict(job))

        matched.sort(
            key=lambda item: (
                int(item.get("page_number", 0) or 0),
                item.get("collected_at", ""),
                item.get("title", ""),
            )
        )
        return matched

    def trim_old_records(self, keep_days: int = 14) -> None:
        cutoff = datetime.now().astimezone() - timedelta(days=max(1, keep_days))
        cutoff_iso = cutoff.isoformat()
        
        trimmed_jobs = []
        for job in self.jobs:
            collected_at = str(job.get("collected_at") or "")
            if not collected_at or collected_at >= cutoff_iso:
                trimmed_jobs.append(job)
                
        if len(trimmed_jobs) < len(self.jobs):
            self.jobs = trimmed_jobs
            self.index = self._build_index()
            self._write()

    def clear(self) -> None:
        self.jobs = []
        self.index = {}
        self._write()

    def _same_record(self, left: dict, right: dict) -> bool:
        left_keys = set(left.get("identity_keys", []) or [])
        right_keys = set(right.get("identity_keys", []) or [])
        return bool(left_keys and right_keys and left_keys.intersection(right_keys))

    def _build_index(self) -> dict[str, dict]:
        index: dict[str, dict] = {}
        for job in self.jobs:
            if not isinstance(job, dict):
                continue
            normalized = self._normalize_record(job)
            for key in normalized.get("identity_keys", []):
                index[key] = normalized
        return index

    def _load(self) -> list[dict]:
        raw = load_json_with_recovery(self.path)

        jobs = raw.get("jobs", []) if isinstance(raw, dict) else []
        if not isinstance(jobs, list):
            return []
        return [self._normalize_record(job) for job in jobs if isinstance(job, dict)]

    def _write(self) -> None:
        payload = {
            "updated_at": datetime.now().astimezone().isoformat(),
            "jobs": sorted(
                self.jobs,
                key=lambda item: (
                    item.get("query", ""),
                    int(item.get("page_number", 0) or 0),
                    item.get("title", ""),
                    item.get("company", ""),
                ),
            ),
        }
        atomic_write_json(self.path, payload, trailing_newline=False)

    def _normalize_record(self, record: dict) -> dict:
        now = datetime.now().astimezone().isoformat()
        identity_keys = self._merge_unique_strings([], record.get("identity_keys", []))
        query = self._clean_string(record.get("query", ""))
        query_list = [query] if query else []
        queries_seen = self._merge_unique_strings(query_list, record.get("queries_seen", []))
        page_number = self._safe_int(record.get("page_number", 0))
        analyzed_at = self._clean_string(record.get("analyzed_at", ""))
        analysis_status = self._clean_string(record.get("analysis_status", ""))
        analysis_reason = self._clean_string(record.get("analysis_reason", ""))
        if analysis_status.strip().lower() == "ai_error" or "ai scoring failed:" in analysis_reason.lower():
            analyzed_at = ""
            analysis_status = ""
            analysis_reason = ""
        apply_method = self._normalize_apply_method(record.get("apply_method", ""))
        easy_apply = bool(record.get("easy_apply")) or apply_method == "easy_apply"
        if easy_apply:
            apply_method = "easy_apply"

        return {
            "query": query,
            "queries_seen": queries_seen,
            "page_number": page_number,
            "title": self._clean_string(record.get("title", "")),
            "company": self._clean_string(record.get("company", "")),
            "location": self._clean_string(record.get("location", "")),
            "url": self._clean_string(record.get("url", "")),
            "job_id": self._clean_string(record.get("job_id", "")),
            "description": self._clean_string(record.get("description", "")),
            "description_debug": dict(record.get("description_debug", {}) or {}),
            "easy_apply": easy_apply,
            "apply_method": apply_method,
            "apply_method_detection_source": self._clean_string(
                record.get("apply_method_detection_source", "")
            ),
            "collected_at": self._clean_string(record.get("collected_at", "")) or now,
            "last_seen_at": self._clean_string(record.get("last_seen_at", "")) or now,
            "analyzed_at": analyzed_at,
            "analysis_status": analysis_status,
            "analysis_reason": analysis_reason,
            "identity_keys": identity_keys,
        }

    def _normalize_query(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip()).lower()

    def _clean_string(self, value) -> str:
        return str(value or "").strip()

    def _safe_int(self, value) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def _normalize_apply_method(self, value) -> str:
        method = re.sub(r"\s+", "_", self._clean_string(value).lower().replace("-", "_"))
        if method in {"easy", "easy_apply", "linkedin_easy_apply"}:
            return "easy_apply"
        if method in {"external", "external_apply", "company_site", "company_website"}:
            return "external_apply"
        return "unknown"

    def _prefer_apply_method(self, new_value, existing_value, easy_apply=False) -> str:
        new_method = self._normalize_apply_method(new_value)
        existing_method = self._normalize_apply_method(existing_value)
        if easy_apply or "easy_apply" in {new_method, existing_method}:
            return "easy_apply"
        if new_method != "unknown":
            return new_method
        if existing_method != "unknown":
            return existing_method
        return "unknown"

    def _merge_unique_strings(self, left: list, right: list) -> list[str]:
        merged = []
        seen = set()
        for value in list(left or []) + list(right or []):
            cleaned = self._clean_string(value)
            normalized = self._normalize_query(cleaned)
            if not cleaned or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(cleaned)
        return merged

    def _prefer_non_empty(self, new_value, existing_value):
        if isinstance(new_value, str):
            return new_value if new_value.strip() else existing_value
        if isinstance(new_value, dict):
            return new_value if new_value else existing_value
        if new_value not in (None, "", [], ()):
            return new_value
        return existing_value

    def _merge_description_debug(self, existing: dict, new: dict) -> dict:
        if not existing:
            return dict(new or {})
        if not new:
            return dict(existing or {})
        merged = dict(existing)
        merged.update(new)
        return merged
