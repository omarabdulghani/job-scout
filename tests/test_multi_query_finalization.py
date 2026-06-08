import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.live_recommended_jobs_dashboard import LiveRecommendedJobsDashboard
from scout_jobs_multi import _recover_reports_from_live_dashboard, _write_output


class MultiQueryFinalizationTests(unittest.TestCase):
    def test_real_output_writer_emits_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "multi.json"
            payload = {"mode": "linkedin_scout_multi", "queries_run": ["ux designer"]}
            with patch("scout_jobs_multi.OUTPUT_PATH", output_path):
                _write_output(payload)

            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), payload)

    def test_completed_query_checkpoint_recovers_reports_without_rescanning(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "dashboard.json"
            writer = LiveRecommendedJobsDashboard(data_path)
            run = writer.start_run(
                mode="linkedin_multi_query_scout",
                board="linkedin",
                location="Amstelveen",
                max_pages="smart up to 4",
                queries=["junior ux designer", "product coordinator"],
                started_at="2026-06-08T01:00:00+02:00",
            )
            writer.record_job(
                {
                    "run_id": run["run_id"],
                    "query": "junior ux designer",
                    "title": "Junior UX Designer",
                    "company": "Example",
                    "url": "https://www.linkedin.com/jobs/view/123/",
                    "score": 82,
                    "terminal_status": "accepted",
                    "source_stage": "ai_scored",
                    "reason": "Strong fit",
                }
            )
            writer.complete_run(run["run_id"], status="failed")
            progress = {
                "location": "Amstelveen",
                "queries": ["junior ux designer", "product coordinator"],
                "current_query_index": 2,
                "last_completed_query_index": 1,
                "total_jobs_processed": 1,
            }

            reports, recovered_run = _recover_reports_from_live_dashboard(
                progress,
                data_path=data_path,
            )

            self.assertEqual(recovered_run["run_id"], run["run_id"])
            self.assertEqual(len(reports), 2)
            self.assertEqual(
                reports[0]["new_recommendations"]["strong_match"][0]["title"],
                "Junior UX Designer",
            )
            self.assertEqual(reports[1]["stats"]["job_cards_collected"], 0)

    def test_resume_run_reuses_existing_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "dashboard.json"
            writer = LiveRecommendedJobsDashboard(data_path)
            run = writer.start_run(
                mode="linkedin_multi_query_scout",
                board="linkedin",
                location="Amstelveen",
                max_pages="1",
                queries=["ux"],
            )
            writer.complete_run(run["run_id"], status="failed")

            resumed = writer.resume_run(run["run_id"])

            self.assertEqual(resumed["run_id"], run["run_id"])
            self.assertEqual(resumed["status"], "running")
            self.assertEqual(writer.data["active_run_id"], run["run_id"])
            self.assertEqual(len(writer.data["runs"]), 1)


if __name__ == "__main__":
    unittest.main()
