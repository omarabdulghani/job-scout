import json
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

            self.assertEqual(counts, {"jobs": 1, "runs": 1, "applications": 1, "collected_jobs": 0})
            self.assertEqual(records[0]["application_stage"], "interview")
            self.assertEqual(records[0]["score"], 82)
            self.assertEqual(store.stage_counts()["interview"], 1)

            store.sync(dashboard, {"jobs": {}})
            self.assertEqual(store.counts()["applications"], 0)

    def test_job_records_support_server_filters_sorting_and_pagination(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = OperationalStore(Path(temporary) / "job_scout.db")
            dashboard = {
                "jobs": [
                    {
                        "board": "linkedin",
                        "job_id": str(index),
                        "title": f"Role {index}",
                        "company": "Alpha" if index % 2 else "Beta",
                        "location": "Amsterdam (Hybrid)" if index < 3 else "Utrecht",
                        "decision_category": "APPLY_FIRST" if index < 2 else "GOOD_OPTIONS",
                        "score": 90 - index,
                        "run_id": "run_1" if index < 3 else "run_2",
                        "processed_at": f"2026-06-0{index + 1}T12:00:00+02:00",
                        "domain_category": "UX_UI_PRODUCT_DESIGN",
                        "search_group": "primary" if index < 3 else "bridge",
                        "matched_search_groups": (
                            ["primary", "bridge"] if index == 0
                            else ["primary"] if index < 3
                            else ["bridge"]
                        ),
                        "flags": ["easy_apply", "dutch_risk"] if index == 0 else [],
                        "apply_method": "easy_apply" if index == 0 else "external_apply",
                    }
                    for index in range(5)
                ],
                "runs": [],
            }
            state = {
                "jobs": {
                    "linkedin:job_id:1": {"status": "applied"},
                }
            }

            store.sync(dashboard, state)
            first_page = store.job_records(
                decision="APPLY_FIRST,GOOD_OPTIONS",
                status="unreviewed",
                sort="score",
                limit=2,
            )
            second_page = store.job_records(
                decision="APPLY_FIRST,GOOD_OPTIONS",
                status="unreviewed",
                sort="score",
                limit=2,
                offset=2,
            )
            easy_apply = store.job_records(
                apply_method="easy_apply",
                preset="dutch_risk",
            )
            hybrid = store.job_records(preset="remote_hybrid")
            bridge = store.job_records(search_group="bridge")

            self.assertEqual(first_page["total"], 4)
            self.assertEqual(len(first_page["jobs"]), 2)
            self.assertTrue(first_page["has_more"])
            self.assertEqual(len(second_page["jobs"]), 2)
            self.assertFalse(second_page["has_more"])
            keys = {
                job["job_key"]
                for job in [*first_page["jobs"], *second_page["jobs"]]
            }
            self.assertEqual(len(keys), 4)
            self.assertEqual(easy_apply["total"], 1)
            self.assertEqual(hybrid["total"], 3)
            self.assertEqual(bridge["total"], 3)
            self.assertTrue(
                all(
                    "bridge" in job.get("matched_search_groups", [])
                    for job in bridge["jobs"]
                )
            )
            self.assertEqual(first_page["by_decision"], {
                "APPLY_FIRST": 1,
                "GOOD_OPTIONS": 3,
            })

    def test_sync_if_changed_only_rebuilds_after_source_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dashboard_path = root / "dashboard.json"
            state_path = root / "state.json"
            store = OperationalStore(root / "job_scout.db")
            dashboard_path.write_text(
                json.dumps({
                    "jobs": [{
                        "board": "linkedin",
                        "job_id": "1",
                        "title": "Designer",
                    }],
                    "runs": [],
                }),
                encoding="utf-8",
            )
            state_path.write_text(json.dumps({"jobs": {}}), encoding="utf-8")

            first = store.sync_if_changed(dashboard_path, state_path)
            unchanged = store.sync_if_changed(dashboard_path, state_path)
            state_path.write_text(
                json.dumps({
                    "jobs": {
                        "linkedin:job_id:1": {
                            "status": "applied",
                            "application_stage": "interview",
                        }
                    }
                }),
                encoding="utf-8",
            )
            changed = store.sync_if_changed(dashboard_path, state_path)

            self.assertTrue(first["synced"])
            self.assertFalse(unchanged["synced"])
            self.assertTrue(changed["synced"])
            self.assertEqual(
                store.job_records(status="applied")["total"],
                1,
            )
            self.assertEqual(store.application_count(stage="interview"), 1)

    def test_sync_normalizes_legacy_easy_apply_flag_without_explicit_method(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = OperationalStore(Path(temporary) / "job_scout.db")
            store.sync(
                {
                    "jobs": [
                        {
                            "board": "linkedin",
                            "job_id": "legacy-1",
                            "title": "Legacy Easy Apply Role",
                            "flags": ["creative_fit", "easy_apply"],
                        }
                    ],
                    "runs": [],
                },
                {"jobs": {}},
            )

            result = store.job_records(apply_method="easy_apply")

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["jobs"][0]["apply_method"], "easy_apply")
            self.assertTrue(result["jobs"][0]["easy_apply"])

    def test_sync_version_forces_one_reindex_for_unchanged_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dashboard_path = root / "dashboard.json"
            state_path = root / "state.json"
            store = OperationalStore(root / "job_scout.db")
            dashboard_path.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "board": "linkedin",
                                "job_id": "legacy-2",
                                "flags": ["easy_apply"],
                            }
                        ],
                        "runs": [],
                    }
                ),
                encoding="utf-8",
            )
            state_path.write_text('{"jobs":{}}', encoding="utf-8")
            old_signature = "|".join(
                f"{path.resolve()}:{path.stat().st_mtime_ns}:{path.stat().st_size}"
                for path in (dashboard_path, state_path)
            )
            with store._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('source_signature', ?)",
                    (old_signature,),
                )
                connection.commit()

            migrated = store.sync_if_changed(dashboard_path, state_path)
            unchanged = store.sync_if_changed(dashboard_path, state_path)

            self.assertTrue(migrated["synced"])
            self.assertFalse(unchanged["synced"])
            self.assertEqual(store.job_records(apply_method="easy_apply")["total"], 1)

    def test_jobs_api_payload_exposes_international_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = OperationalStore(Path(temporary) / "job_scout.db")
            store.sync(
                {
                    "jobs": [
                        {
                            "board": "linkedin",
                            "job_id": "intl-1",
                            "title": "Product Designer",
                            "company": "Example Gulf",
                            "location": "Dubai, United Arab Emirates",
                            "description": (
                                "Permanent contract with relocation support, housing allowance, "
                                "health insurance, annual flight, and visa sponsorship provided."
                            ),
                            "search_scope": {
                                "platform": "linkedin",
                                "search_market": "uae",
                                "location": "Dubai",
                                "radius_km": 40,
                                "employment": "full-time-preferred",
                            },
                        }
                    ],
                    "runs": [],
                },
                {"jobs": {}},
            )

            record = store.job_records(search_market="uae")["jobs"][0]

            self.assertEqual(record["sponsorship_status"], "confirmed")
            self.assertEqual(record["relocation_support"], "confirmed")
            self.assertEqual(record["housing_support"], "confirmed")
            self.assertEqual(record["health_insurance"], "confirmed")
            self.assertEqual(record["annual_flight_support"], "confirmed")
            self.assertEqual(record["contract_type"], "permanent")


if __name__ == "__main__":
    unittest.main()
