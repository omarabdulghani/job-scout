import tempfile
from pathlib import Path
import unittest

from agent.operational_store import OperationalStore


class OperationalStoreTests(unittest.TestCase):
    def test_sync_indexes_jobs_runs_and_applications(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = OperationalStore(Path(temporary) / "job_scout.db")
            dashboard = {
                "jobs": [
                    {
                        "board": "linkedin",
                        "job_id": "123",
                        "title": "Product Designer",
                        "company": "Example",
                        "score": 82,
                    }
                ],
                "runs": [{"run_id": "run_1", "run_label": "Run 1"}],
            }
            state = {
                "jobs": {
                    "linkedin:job_id:123": {
                        "status": "applied",
                        "title": "Product Designer",
                        "company": "Example",
                        "application_stage": "interview",
                        "notes": "Interview booked",
                        "updated_at": "2026-06-07T12:00:00+02:00",
                    }
                }
            }

            counts = store.sync(dashboard, state)
            records = store.application_records(search="designer")

            self.assertEqual(counts, {"jobs": 1, "runs": 1, "applications": 1})
            self.assertEqual(records[0]["application_stage"], "interview")
            self.assertEqual(records[0]["score"], 82)
            self.assertEqual(store.stage_counts()["interview"], 1)

            store.sync(dashboard, {"jobs": {}})
            self.assertEqual(store.counts()["applications"], 0)


if __name__ == "__main__":
    unittest.main()
