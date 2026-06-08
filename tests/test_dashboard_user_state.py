import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from agent.dashboard_user_state import (
    DashboardUserStateStore,
    build_job_key,
)
from serve_dashboard import make_handler


class DashboardUserStateTests(unittest.TestCase):
    def test_manual_status_persists_across_runs_for_same_job_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "recommended_jobs_dashboard_user_state.json"
            store = DashboardUserStateStore(state_path)
            original_job = {
                "board": "linkedin",
                "run_id": "run_1",
                "run_label": "Run 1",
                "job_id": "4419175235",
                "url": "https://www.linkedin.com/jobs/view/4419175235/",
                "title": "Junior UX Designer",
                "company": "Deloitte",
            }
            later_job = {
                **original_job,
                "run_id": "run_2",
                "run_label": "Run 2",
            }

            store.set_status(original_job, "applied", updated_at="2026-05-27T16:30:00+02:00")
            merged = store.apply_to_dashboard_data(
                {
                    "schema_version": "live_dashboard.v1",
                    "jobs": [later_job],
                    "summary": {},
                    "filter_options": {},
                }
            )

            self.assertEqual(build_job_key(original_job), build_job_key(later_job))
            self.assertEqual(merged["jobs"][0]["manual_status"], "applied")
            self.assertEqual(merged["summary"]["by_manual_status"]["applied"], 1)

    def test_unreviewed_clears_saved_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "recommended_jobs_dashboard_user_state.json"
            store = DashboardUserStateStore(state_path)
            job = {
                "board": "linkedin",
                "job_id": "123",
                "title": "Product Designer",
                "company": "Example",
            }

            store.set_status(job, "irrelevant", updated_at="2026-05-27T16:30:00+02:00")
            store.set_status(job, "unreviewed", updated_at="2026-05-27T16:31:00+02:00")

            self.assertEqual(store.data["jobs"], {})

    def test_application_stage_persists_and_enriches_live_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "recommended_jobs_dashboard_user_state.json"
            store = DashboardUserStateStore(state_path)
            job = {
                "board": "linkedin",
                "job_id": "321",
                "title": "Product Coordinator",
                "company": "Example",
                "url": "https://www.linkedin.com/jobs/view/321/",
            }

            store.update_application(
                job,
                stage="interview",
                notes="First interview scheduled",
                follow_up_at="2026-06-10",
            )
            merged = store.apply_to_dashboard_data(
                {
                    "schema_version": "live_dashboard.v1",
                    "jobs": [job],
                    "summary": {},
                    "filter_options": {},
                }
            )

            self.assertEqual(merged["jobs"][0]["manual_status"], "applied")
            self.assertEqual(merged["jobs"][0]["application_stage"], "interview")
            self.assertEqual(merged["jobs"][0]["application_notes"], "First interview scheduled")
            self.assertEqual(store.application_records()[0]["application_stage"], "interview")

    def test_api_saves_status_and_returns_merged_dashboard_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "recommended_jobs_dashboard_data.json"
            state_path = root / "recommended_jobs_dashboard_user_state.json"
            job = {
                "board": "linkedin",
                "run_id": "run_1",
                "run_label": "Run 1",
                "job_id": "555",
                "url": "https://www.linkedin.com/jobs/view/555/",
                "title": "Graduate Visual UI Designer",
                "company": "Canonical",
                "decision_category": "APPLY_FIRST",
            }
            data_path.write_text(
                json.dumps(
                    {
                        "schema_version": "live_dashboard.v1",
                        "runs": [],
                        "jobs": [job],
                        "summary": {},
                        "filter_options": {},
                    }
                ),
                encoding="utf-8",
            )

            handler = make_handler(
                directory=root,
                dashboard_data_path=data_path,
                user_state_path=state_path,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_address[1]}"
                request = Request(
                    base_url + "/api/job-status",
                    data=json.dumps({"status": "applied", "job": job}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["record"]["status"], "applied")

                with urlopen(base_url + "/api/dashboard-data", timeout=5) as response:
                    merged = json.loads(response.read().decode("utf-8"))
                self.assertEqual(merged["jobs"][0]["manual_status"], "applied")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
