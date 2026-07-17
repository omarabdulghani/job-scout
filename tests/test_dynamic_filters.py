import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from agent.search_scope import (
    SEARCH_MARKETS,
    MARKET_PROFILES,
    build_search_scope,
    reload_market_profiles,
)
from agent.job_scope_metadata import cap_score_for_scope, enrich_job_scope_metadata
from agent.job_scout import LinkedInJobScout

ROOT = Path(__file__).resolve().parents[1]

class DynamicFiltersTests(unittest.TestCase):
    def test_dynamic_experience_levels_saved_in_scope(self):
        scope = build_search_scope(
            search_market="netherlands",
            experience_levels=["internship", "mid-senior"]
        )
        self.assertEqual(scope["experience_levels"], ["internship", "mid-senior"])

    def test_sponsorship_policy_override_bypasses_cap(self):
        # Default policy for UAE is required, which caps unknown sponsorship at 69
        default_scope = build_search_scope(search_market="uae")
        job = {
            "title": "UX Designer",
            "company": "UAE Corp",
            "location": "Dubai",
            "description": "Awesome role.",
        }
        meta_default = enrich_job_scope_metadata(job, default_scope)
        self.assertEqual(meta_default["sponsorship_status"], "unknown")
        self.assertEqual(meta_default["sponsorship_policy"], "required")
        
        capped_score, reason = cap_score_for_scope(85, meta_default)
        self.assertEqual(capped_score, 69)
        self.assertIn("Visa sponsorship is not confirmed", reason)

        # Override sponsorship policy to not_required
        override_scope = build_search_scope(
            search_market="uae",
            sponsorship_policy="not_required"
        )
        meta_override = enrich_job_scope_metadata(job, override_scope)
        self.assertEqual(meta_override["sponsorship_status"], "not_required")
        self.assertEqual(meta_override["sponsorship_policy"], "not_required")
        
        uncapped_score, reason = cap_score_for_scope(85, meta_override)
        self.assertEqual(uncapped_score, 85)
        self.assertEqual(reason, "")

    def test_custom_market_dynamic_merging_and_cleanup(self):
        custom_path = ROOT / "data" / "user_workspace" / "custom_markets.json"
        custom_path.parent.mkdir(parents=True, exist_ok=True)
        
        test_profile = {
            "france": {
                "label": "France Test",
                "availability": "stable",
                "country": "France",
                "country_codes": ["FR"],
                "default_location": "Paris",
                "locations": ["Paris", "France"],
                "authorized_without_sponsorship": True,
                "sponsorship_policy": "not_required",
                "language_policy": "english_friendly",
                "compatible_languages": ["English", "French"]
            }
        }
        
        # Backup existing
        original_custom = ""
        if custom_path.exists():
            original_custom = custom_path.read_text(encoding="utf-8")
            
        try:
            custom_path.write_text(json.dumps(test_profile), encoding="utf-8")
            reload_market_profiles()
            
            self.assertIn("france", SEARCH_MARKETS)
            self.assertIn("france", MARKET_PROFILES)
            self.assertEqual(MARKET_PROFILES["france"]["label"], "France Test")
            
            # Check building search scope with france
            scope = build_search_scope(search_market="france", location="Paris")
            self.assertEqual(scope["search_market"], "france")
            self.assertEqual(scope["market_label"], "France Test")
        finally:
            # Clean up
            if original_custom:
                custom_path.write_text(original_custom, encoding="utf-8")
            elif custom_path.exists():
                custom_path.unlink()
            reload_market_profiles()
            
            self.assertNotIn("france", SEARCH_MARKETS)
            self.assertNotIn("france", MARKET_PROFILES)

    def test_linkedin_url_uses_custom_experience_codes(self):
        profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
        preferences = json.loads((ROOT / "config" / "preferences.json").read_text(encoding="utf-8"))
        
        with tempfile.TemporaryDirectory() as temp_dir:
            search_scope = build_search_scope(
                search_market="netherlands",
                experience_levels=["internship", "mid-senior", "director"]
            )
            preferences["_runtime_search_scope"] = search_scope
            scout = LinkedInJobScout(
                profile,
                preferences,
                browser=None,
                output_path=Path(temp_dir) / "output.json"
            )
            url = scout._build_search_url("product designer", "Amstelveen")
            
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        # Internship -> 1, Mid-Senior -> 4, Director -> 5
        self.assertIn("f_E", parsed)
        codes = parsed["f_E"][0].split(",")
        self.assertEqual(set(codes), {"1", "4", "5"})

if __name__ == "__main__":
    unittest.main()
