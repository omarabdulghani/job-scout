import tempfile
import unittest
from pathlib import Path

from agent.scout_collected_jobs import ScoutCollectedJobsStore


class ScoutCollectedJobsStoreApplyMethodTests(unittest.TestCase):
    def test_preserves_easy_apply_fields_on_insert_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scout_collected_jobs.json"
            store = ScoutCollectedJobsStore(path)

            stored = store.upsert_job(
                {
                    "query": "ux designer",
                    "title": "Junior UX Designer",
                    "company": "Example",
                    "url": "https://www.linkedin.com/jobs/view/123/",
                    "easy_apply": True,
                    "apply_method": "easy_apply",
                    "apply_method_detection_source": "detail_apply_button",
                    "identity_keys": ["linkedin_job_id:123"],
                }
            )

            self.assertTrue(stored["easy_apply"])
            self.assertEqual(stored["apply_method"], "easy_apply")
            self.assertEqual(stored["apply_method_detection_source"], "detail_apply_button")

            reloaded = ScoutCollectedJobsStore(path).get_by_identity_keys(["linkedin_job_id:123"])
            self.assertIsNotNone(reloaded)
            self.assertTrue(reloaded["easy_apply"])
            self.assertEqual(reloaded["apply_method"], "easy_apply")
            self.assertEqual(reloaded["apply_method_detection_source"], "detail_apply_button")

    def test_merge_does_not_downgrade_known_easy_apply_to_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scout_collected_jobs.json"
            store = ScoutCollectedJobsStore(path)

            store.upsert_job(
                {
                    "query": "ux designer",
                    "title": "Junior UX Designer",
                    "company": "Example",
                    "url": "https://www.linkedin.com/jobs/view/123/",
                    "easy_apply": True,
                    "apply_method": "easy_apply",
                    "apply_method_detection_source": "detail_apply_button",
                    "identity_keys": ["linkedin_job_id:123"],
                }
            )
            merged = store.upsert_job(
                {
                    "query": "product designer",
                    "title": "Junior UX Designer",
                    "company": "Example",
                    "url": "https://www.linkedin.com/jobs/view/123/",
                    "easy_apply": False,
                    "apply_method": "unknown",
                    "apply_method_detection_source": "",
                    "identity_keys": ["linkedin_job_id:123"],
                }
            )

            self.assertTrue(merged["easy_apply"])
            self.assertEqual(merged["apply_method"], "easy_apply")
            self.assertEqual(merged["apply_method_detection_source"], "detail_apply_button")
            self.assertIn("ux designer", merged["queries_seen"])
            self.assertIn("product designer", merged["queries_seen"])

    def test_merge_upgrades_unknown_apply_method_when_new_scan_knows_more(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scout_collected_jobs.json"
            store = ScoutCollectedJobsStore(path)

            store.upsert_job(
                {
                    "query": "ux designer",
                    "title": "Junior UX Designer",
                    "company": "Example",
                    "url": "https://www.linkedin.com/jobs/view/123/",
                    "apply_method": "unknown",
                    "identity_keys": ["linkedin_job_id:123"],
                }
            )
            merged = store.upsert_job(
                {
                    "query": "ux designer",
                    "title": "Junior UX Designer",
                    "company": "Example",
                    "url": "https://www.linkedin.com/jobs/view/123/",
                    "easy_apply": True,
                    "apply_method_detection_source": "card_or_existing_data",
                    "identity_keys": ["linkedin_job_id:123"],
                }
            )

            self.assertTrue(merged["easy_apply"])
            self.assertEqual(merged["apply_method"], "easy_apply")
            self.assertEqual(merged["apply_method_detection_source"], "card_or_existing_data")


if __name__ == "__main__":
    unittest.main()
