from __future__ import annotations

import json
from pathlib import Path


class ScoutReviewLatestWriter:
    REVIEW_PATH = Path("review_latest_jobs.json")
    POSTOPEN_REJECTION_KEYS = (
        "rejected_outside_netherlands",
        "rejected_internship",
        "rejected_dutch",
        "rejected_irrelevant",
        "rejected_entry_level",
        "rejected_excluded",
    )

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else self.REVIEW_PATH

    def write(self, output: dict, reports: list[dict] | None = None) -> dict:
        payload = self.build(output, reports=reports)
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return payload

    def build(self, output: dict, reports: list[dict] | None = None) -> dict:
        is_multi = (output.get("mode") or "").strip() == "linkedin_scout_multi"
        go_jobs = self._collect_review_jobs(output, tier="strong_match", decision="GO", is_multi=is_multi)
        consider_jobs = self._collect_review_jobs(
            output,
            tier="possible_match",
            decision="CONSIDER",
            is_multi=is_multi,
        )

        return {
            "run_metadata": self._build_run_metadata(output, is_multi=is_multi),
            "run_summary": self._build_run_summary(
                output,
                reports=reports,
                go_count=len(go_jobs),
                consider_count=len(consider_jobs),
                is_multi=is_multi,
            ),
            "go_jobs": go_jobs,
            "consider_jobs": consider_jobs,
        }

    def _build_run_metadata(self, output: dict, *, is_multi: bool) -> dict:
        metadata = {
            "mode": "multi-query" if is_multi else "single-query",
            "location": output.get("location", ""),
            "started_at": output.get("started_at", ""),
            "completed_at": output.get("completed_at", output.get("generated_at", "")),
            "generated_at": output.get("generated_at", ""),
        }
        if is_multi:
            metadata["queries"] = list(output.get("queries_run", []) or [])
        else:
            metadata["query"] = output.get("query", "")
        return metadata

    def _build_run_summary(
        self,
        output: dict,
        *,
        reports: list[dict] | None,
        go_count: int,
        consider_count: int,
        is_multi: bool,
    ) -> dict:
        if is_multi and reports:
            total_jobs_collected = sum(
                int(((report.get("stats") or {}).get("job_cards_collected", 0)) or 0)
                for report in reports
            )
            total_jobs_skipped_pre_open = sum(
                int(((report.get("stats") or {}).get("preopen_skipped_total", 0)) or 0)
                for report in reports
            )
            total_jobs_rejected_post_open = sum(
                self._postopen_rejected_count(report.get("stats", {}) or {})
                for report in reports
            )
            total_survivors_to_ai = sum(
                int(((report.get("stats") or {}).get("survived_non_ai", 0)) or 0)
                for report in reports
            )
        else:
            stats = output.get("stats", {}) or {}
            total_jobs_collected = int(
                stats.get("job_cards_collected", stats.get("total_unique_jobs_seen", 0)) or 0
            )
            total_jobs_skipped_pre_open = int(stats.get("preopen_skipped_total", 0) or 0)
            total_jobs_rejected_post_open = self._postopen_rejected_count(stats)
            total_survivors_to_ai = int(stats.get("survived_non_ai", 0) or 0)

        return {
            "total_jobs_collected": total_jobs_collected,
            "total_jobs_skipped_pre_open": total_jobs_skipped_pre_open,
            "total_jobs_rejected_post_open": total_jobs_rejected_post_open,
            "total_survivors_to_ai": total_survivors_to_ai,
            "total_go_jobs": go_count,
            "total_consider_jobs": consider_count,
        }

    def _postopen_rejected_count(self, stats: dict) -> int:
        return sum(int(stats.get(key, 0) or 0) for key in self.POSTOPEN_REJECTION_KEYS)

    def _collect_review_jobs(self, output: dict, *, tier: str, decision: str, is_multi: bool) -> list[dict]:
        jobs: list[dict] = []
        for bucket_name in ("new_recommendations", "cached_previous_recommendations"):
            grouped = output.get(bucket_name, {}) or {}
            for job in grouped.get(tier, []) or []:
                if isinstance(job, dict):
                    jobs.append(self._build_review_job(job, decision=decision, is_multi=is_multi))
        return jobs

    def _build_review_job(self, job: dict, *, decision: str, is_multi: bool) -> dict:
        record = {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": job.get("url", ""),
            "job_id": job.get("job_id", ""),
            "interview_probability_score": int(job.get("interview_probability_score", 0) or 0),
            "ai_match_tier": job.get("ai_match_tier", ""),
            "decision": decision,
            "interview_probability_reason": job.get("interview_probability_reason", ""),
            "found_at": job.get("found_at", ""),
            "first_seen_at": job.get("first_seen_at", ""),
            "last_seen_at": job.get("last_seen_at", ""),
        }
        if is_multi:
            if "best_matching_query" in job:
                record["best_matching_query"] = job.get("best_matching_query", "")
            if "matched_queries" in job:
                record["matched_queries"] = list(job.get("matched_queries", []) or [])
        tracking_status = (job.get("tracking_status") or "").strip()
        if tracking_status:
            record["tracking_status"] = tracking_status
            record["tracking_updated_at"] = job.get("tracking_updated_at", "")
        return record
