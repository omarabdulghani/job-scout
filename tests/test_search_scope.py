import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from agent.brain import JobBrain
from agent.job_scout import LinkedInJobScout
from agent.search_scope import (
    EMPLOYMENT_PREFERENCES,
    LINKEDIN_RADIUS_KM_TO_MILES,
    MARKET_PROFILES,
    SEARCH_MARKETS,
    build_search_scope,
    linkedin_employment_codes,
    scope_learning_key,
)


ROOT = Path(__file__).resolve().parents[1]


class SearchScopeTests(unittest.TestCase):
    def test_every_market_profile_builds_with_expected_authorization(self):
        for market in SEARCH_MARKETS:
            profile = MARKET_PROFILES[market]
            with self.subTest(market=market):
                scope = build_search_scope(
                    search_market=market,
                    location=profile["default_location"],
                    radius_km=40,
                )
                self.assertEqual(scope["search_market"], market)
                self.assertEqual(scope["country"], profile["country"])
                self.assertEqual(
                    scope["authorized_without_sponsorship"],
                    profile["authorized_without_sponsorship"],
                )
                self.assertEqual(
                    scope["sponsorship_policy"],
                    profile["sponsorship_policy"],
                )
                self.assertEqual(
                    scope["market_availability"],
                    profile["availability"],
                )

    def test_market_availability_starts_conservatively(self):
        self.assertEqual(MARKET_PROFILES["netherlands"]["availability"], "stable")
        self.assertEqual(MARKET_PROFILES["germany"]["availability"], "stable")
        self.assertEqual(MARKET_PROFILES["uae"]["availability"], "stable")
        for market in ("saudi-arabia", "qatar", "kuwait"):
            self.assertEqual(MARKET_PROFILES[market]["availability"], "stable")

    def test_linkedin_radius_values_map_to_platform_miles(self):
        for radius_km, radius_miles in LINKEDIN_RADIUS_KM_TO_MILES.items():
            with self.subTest(radius_km=radius_km):
                scope = build_search_scope(radius_km=radius_km)
                self.assertEqual(scope["radius_km"], radius_km)
                self.assertEqual(scope["radius_miles"], radius_miles)

    def test_invalid_radius_and_indeed_international_scope_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not support"):
            build_search_scope(radius_km=25)
        with self.assertRaisesRegex(ValueError, "does not support"):
            build_search_scope(
                platform="indeed",
                search_market="germany",
                location="Berlin",
                radius_km=25,
                employment="any",
            )

    def test_country_wide_and_remote_searches_disable_radius(self):
        for location in ("Netherlands", "Remote"):
            with self.subTest(location=location):
                scope = build_search_scope(location=location, radius_km=40)
                self.assertIsNone(scope["radius_km"])
                self.assertIsNone(scope["radius_miles"])

    def test_every_employment_preference_has_expected_linkedin_codes(self):
        expected = {
            "full-time-preferred": ["F", "P"],
            "full-time-only": ["F"],
            "part-time-only": ["P"],
            "full-or-part-time": ["F", "P"],
            "any": [],
        }
        self.assertEqual(set(expected), set(EMPLOYMENT_PREFERENCES))
        for employment, codes in expected.items():
            with self.subTest(employment=employment):
                search_scope = build_search_scope(employment=employment)
                self.assertEqual(linkedin_employment_codes(search_scope), codes)

    def test_query_learning_key_isolated_by_market_group_and_employment(self):
        local_primary = scope_learning_key(
            build_search_scope(search_market="netherlands"),
            "primary",
        )
        germany_primary = scope_learning_key(
            build_search_scope(
                search_market="germany",
                location="Berlin",
            ),
            "primary",
        )
        local_fallback = scope_learning_key(
            build_search_scope(search_market="netherlands"),
            "fallback",
        )
        local_part_time = scope_learning_key(
            build_search_scope(
                search_market="netherlands",
                employment="part-time-only",
            ),
            "primary",
        )
        self.assertEqual(len({local_primary, germany_primary, local_fallback, local_part_time}), 4)


class LinkedInSearchUrlTests(unittest.TestCase):
    def _scout(self, directory: Path, search_scope: dict) -> LinkedInJobScout:
        profile = json.loads(
            (ROOT / "config" / "profile.json").read_text(encoding="utf-8")
        )
        preferences = json.loads(
            (ROOT / "config" / "preferences.json").read_text(encoding="utf-8")
        )
        preferences["_runtime_search_scope"] = search_scope
        return LinkedInJobScout(
            profile,
            preferences,
            browser=None,
            output_path=directory / "output.json",
            rejected_debug_path=directory / "rejected.json",
            ai_debug_path=directory / "debug.json",
            score_cache_path=directory / "cache.json",
            collected_jobs_path=directory / "collected.json",
            tracking_status_path=directory / "tracking.json",
            run_history_path=directory / "history.json",
        )

    def test_generated_url_uses_radius_and_employment_filters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scout = self._scout(
                Path(temp_dir),
                build_search_scope(
                    search_market="germany",
                    location="Berlin",
                    radius_km=16,
                    employment="part-time-only",
                ),
            )
            url = scout._build_search_url("product designer", "Berlin")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["distance"], ["10"])
        self.assertEqual(query["f_JT"], ["P"])
        self.assertEqual(query["location"], ["Berlin"])

    def test_any_employment_omits_linkedin_job_type_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scout = self._scout(
                Path(temp_dir),
                build_search_scope(employment="any"),
            )
            url = scout._build_search_url("ux designer", "Amstelveen")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertNotIn("f_JT", query)


class ScoringSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile = json.loads(
            (ROOT / "config" / "profile.json").read_text(encoding="utf-8")
        )
        preferences = json.loads(
            (ROOT / "config" / "preferences.json").read_text(encoding="utf-8")
        )
        cls.brain = JobBrain(profile, preferences)

    def test_all_structured_scoring_schemas_require_the_complete_contract(self):
        expected = set(self.brain._scoring_schema_properties())
        plain = self.brain._plain_scoring_json_schema()
        gemini = self.brain._gemini_scoring_response_schema()
        lmstudio = self.brain._lmstudio_scoring_response_format()["json_schema"]["schema"]
        for schema in (plain, gemini, lmstudio):
            self.assertEqual(set(schema["required"]), expected)

    def test_parser_returns_safe_defaults_for_missing_optional_provider_fields(self):
        parsed = self.brain._parse_scoring_payload(
            '{"interview_probability_score": 65, "reason": "Possible fit."}',
            backend="test",
        )
        self.assertEqual(parsed["interview_probability_score"], 65)
        self.assertEqual(parsed["reason"], "Possible fit.")


if __name__ == "__main__":
    unittest.main()
