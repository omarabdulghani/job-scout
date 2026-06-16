from pathlib import Path
import unittest
from unittest.mock import patch

from agent.search_query_plan import (
    DEFAULT_FALLBACK_QUERIES,
    build_search_query_plan,
    flatten_query_groups,
    migrate_flat_queries,
    resolve_search_groups,
)
from scout_jobs_multi import _expected_query_file


class SearchQueryPlanTests(unittest.TestCase):
    def test_migration_preserves_input_order_and_seeds_fallback(self):
        queries = [
            "junior ux designer",
            "customer success coordinator",
            "brand coordinator",
            "data analyst",
        ]

        groups = migrate_flat_queries(queries)

        self.assertEqual(
            groups["primary"],
            ["junior ux designer", "brand coordinator"],
        )
        self.assertEqual(
            groups["bridge"],
            ["customer success coordinator", "data analyst"],
        )
        self.assertEqual(groups["fallback"], DEFAULT_FALLBACK_QUERIES)
        self.assertEqual(
            flatten_query_groups(groups)[:4],
            [
                "junior ux designer",
                "brand coordinator",
                "customer success coordinator",
                "data analyst",
            ],
        )

    def test_adaptive_plan_uses_initial_batches_then_remaining_queries(self):
        groups = {
            "primary": [f"primary {index}" for index in range(12)],
            "bridge": [f"bridge {index}" for index in range(10)],
            "fallback": [f"fallback {index}" for index in range(8)],
        }

        plan = build_search_query_plan(
            groups,
            search_goal="broad",
            learning_enabled=False,
        )

        self.assertEqual(plan["queries"][:10], groups["primary"][:10])
        self.assertEqual(plan["queries"][10:18], groups["bridge"][:8])
        self.assertEqual(plan["queries"][18:24], groups["fallback"][:6])
        self.assertEqual(plan["initial_coverage_count"], 24)
        self.assertEqual(plan["queries"][24:26], groups["primary"][10:])
        self.assertEqual(plan["queries"][26:28], groups["bridge"][8:])
        self.assertEqual(plan["queries"][28:], groups["fallback"][6:])

    def test_cross_group_duplicate_is_emitted_once_with_all_memberships(self):
        groups = {
            "primary": ["product operations"],
            "bridge": ["Product Operations", "customer success"],
            "fallback": [],
        }

        plan = build_search_query_plan(
            groups,
            search_goal="career-growth",
            learning_enabled=False,
        )

        self.assertEqual(plan["queries"], ["product operations", "customer success"])
        self.assertEqual(
            plan["entries"][0]["matched_search_groups"],
            ["primary", "bridge"],
        )

    def test_single_group_plan_keeps_complete_group_order(self):
        plan = build_search_query_plan(
            {
                "primary": ["ux", "ui"],
                "bridge": ["data"],
                "fallback": ["support", "admin"],
            },
            search_goal="income",
            learning_enabled=False,
        )

        self.assertEqual(plan["queries"], ["support", "admin"])
        self.assertEqual(plan["initial_coverage_count"], 0)
        self.assertEqual(plan["ai_budget_eligible_after_index"], -1)

    def test_custom_groups_follow_stable_priority_order(self):
        self.assertEqual(
            resolve_search_groups("custom", ["fallback", "primary"]),
            ["primary", "fallback"],
        )
        with self.assertRaisesRegex(ValueError, "at least one"):
            resolve_search_groups("custom", [])

    def test_query_learning_runs_independently_for_each_selected_group(self):
        groups = {
            "primary": ["primary one", "primary two"],
            "bridge": ["bridge one", "bridge two"],
            "fallback": [],
        }

        def order_group(queries, **_kwargs):
            ordered = list(reversed(queries))
            return ordered, {"ordered_queries": ordered}

        with patch(
            "agent.search_query_plan.order_queries_with_learning",
            side_effect=order_group,
        ) as mocked:
            plan = build_search_query_plan(
                groups,
                search_goal="career-growth",
                learning_enabled=True,
            )

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(plan["queries"], [
            "primary two",
            "primary one",
            "bridge two",
            "bridge one",
        ])
        self.assertEqual(
            plan["query_learning"]["primary"]["ordered_queries"],
            ["primary two", "primary one"],
        )
        self.assertEqual(
            plan["query_learning"]["bridge"]["ordered_queries"],
            ["bridge two", "bridge one"],
        )

    def test_resume_uses_saved_query_source_for_legacy_and_grouped_runs(self):
        self.assertEqual(
            _expected_query_file(
                Path("search_query_groups.json"),
                progress={"query_file": "C:/saved/search_queries.txt"},
                resume=True,
            ),
            "C:/saved/search_queries.txt",
        )
        self.assertEqual(
            _expected_query_file(
                Path("search_query_groups.json"),
                progress={},
                resume=False,
            ),
            str(Path("search_query_groups.json").resolve()),
        )


if __name__ == "__main__":
    unittest.main()
