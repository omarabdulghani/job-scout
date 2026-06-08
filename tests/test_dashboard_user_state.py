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
from agent.operational_store import OperationalStore
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

    def test_paginated_jobs_and_applications_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "recommended_jobs_dashboard_data.json"
            state_path = root / "recommended_jobs_dashboard_user_state.json"
            jobs = [
                {
                    "board": "linkedin",
                    "job_id": str(index),
                    "title": f"Product Role {index}",
                    "company": "Example",
                    "decision_category": "APPLY_FIRST" if index < 2 else "GOOD_OPTIONS",
                    "score": 90 - index,
                    "processed_at": f"2026-06-0{index + 1}T12:00:00+02:00",
                    "domain_category": "PRODUCT_PROJECT_OPERATIONS",
                    "flags": ["easy_apply"] if index == 0 else [],
                    "apply_method": "easy_apply" if index == 0 else "external_apply",
                }
                for index in range(4)
            ]
            dashboard = {
                "schema_version": "live_dashboard.v1",
                "runs": [],
                "jobs": jobs,
                "summary": {
                    "total_jobs": len(jobs),
                    "by_decision": {"APPLY_FIRST": 2, "GOOD_OPTIONS": 2},
                },
                "filter_options": {},
            }
            data_path.write_text(json.dumps(dashboard), encoding="utf-8")
            state_store = DashboardUserStateStore(state_path)
            state_store.update_application(
                jobs[0],
                stage="interview",
                notes="Interview booked",
            )
            operational_store = OperationalStore(root / "job_scout.db")
            operational_store.sync(dashboard, state_store.data)

            handler = make_handler(
                directory=root,
                dashboard_data_path=data_path,
                user_state_path=state_path,
                operational_store=operational_store,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base_url = f"http://127.0.0.1:{server.server_address[1]}"
                with urlopen(
                    base_url + "/api/dashboard-data?include_jobs=false",
                    timeout=5,
                ) as response:
                    metadata = json.loads(response.read().decode("utf-8"))
                self.assertEqual(metadata["jobs"], [])
                self.assertEqual(metadata["summary"]["actionable_jobs"], 3)

                with urlopen(
                    base_url + "/api/jobs?decision=APPLY_FIRST&limit=1&offset=0",
                    timeout=5,
                ) as response:
                    first = json.loads(response.read().decode("utf-8"))
                self.assertEqual(first["total"], 2)
                self.assertEqual(len(first["jobs"]), 1)
                self.assertTrue(first["has_more"])

                with urlopen(
                    base_url + "/api/jobs?apply_method=easy_apply&status=applied",
                    timeout=5,
                ) as response:
                    applied = json.loads(response.read().decode("utf-8"))
                self.assertEqual(applied["total"], 1)

                with urlopen(
                    base_url + "/api/applications?stage=interview&limit=1",
                    timeout=5,
                ) as response:
                    applications = json.loads(response.read().decode("utf-8"))
                self.assertEqual(applications["total"], 1)
                self.assertEqual(
                    applications["applications"][0]["application_stage"],
                    "interview",
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_compact_status_api_omits_full_dashboard_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "recommended_jobs_dashboard_data.json"
            state_path = root / "recommended_jobs_dashboard_user_state.json"
            job = {
                "board": "linkedin",
                "job_id": "compact",
                "title": "Compact response role",
            }
            data_path.write_text(
                json.dumps({
                    "schema_version": "live_dashboard.v1",
                    "runs": [],
                    "jobs": [job],
                    "summary": {"total_jobs": 1},
                    "filter_options": {},
                }),
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
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/api/job-status",
                    data=json.dumps({
                        "status": "irrelevant",
                        "job": job,
                        "compact": True,
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertNotIn("data", payload)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
