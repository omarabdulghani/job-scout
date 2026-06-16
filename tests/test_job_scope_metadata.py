import json
import tempfile
import unittest
from pathlib import Path

from agent.job_scope_metadata import (
    cap_score_for_scope,
    classify_historical_career_lane,
    classify_sponsorship,
    enrich_job_scope_metadata,
    evaluate_employment_policy,
    german_language_assessment,
    infer_employment_metadata,
    infer_international_metadata,
    market_eligibility,
)
from agent.job_scout import LinkedInJobScout


ROOT = Path(__file__).resolve().parents[1]


def scope(employment: str, *, market: str = "netherlands") -> dict:
    return {
        "platform": "linkedin",
        "search_market": market,
        "location": "Amstelveen" if market == "netherlands" else "Dubai",
        "radius_km": 40,
        "employment": employment,
    }


class EmploymentPolicyTests(unittest.TestCase):
    def test_full_time_only_rejects_explicit_part_time_only(self):
        result = evaluate_employment_policy(
            ["part-time"],
            False,
            scope("full-time-only"),
        )
        self.assertFalse(result["employment_eligible"])
        self.assertEqual(result["employment_match"], "incompatible")

    def test_full_time_only_accepts_full_time_and_flexible_roles(self):
        full_time = evaluate_employment_policy(
            ["full-time"],
            False,
            scope("full-time-only"),
        )
        flexible = evaluate_employment_policy(
            ["full-time", "part-time"],
            True,
            scope("full-time-only"),
        )
        self.assertTrue(full_time["employment_eligible"])
        self.assertTrue(flexible["employment_eligible"])
        self.assertEqual(full_time["employment_match"], "accepted")
        self.assertEqual(flexible["employment_match"], "accepted")

    def test_part_time_only_rejects_explicit_full_time_only(self):
        result = evaluate_employment_policy(
            ["full-time"],
            False,
            scope("part-time-only"),
        )
        self.assertFalse(result["employment_eligible"])
        self.assertEqual(result["employment_match"], "incompatible")

    def test_part_time_only_accepts_part_time_and_flexible_roles(self):
        part_time = evaluate_employment_policy(
            ["part-time"],
            False,
            scope("part-time-only"),
        )
        flexible = evaluate_employment_policy(
            ["full-time", "part-time"],
            True,
            scope("part-time-only"),
        )
        self.assertTrue(part_time["employment_eligible"])
        self.assertTrue(flexible["employment_eligible"])

    def test_full_time_preferred_applies_deterministic_adjustments(self):
        preferred = evaluate_employment_policy(
            ["full-time"],
            False,
            scope("full-time-preferred"),
        )
        penalty = evaluate_employment_policy(
            ["part-time"],
            False,
            scope("full-time-preferred"),
        )
        flexible = evaluate_employment_policy(
            ["full-time", "part-time"],
            True,
            scope("full-time-preferred"),
        )
        self.assertEqual(preferred["employment_score_adjustment"], 3)
        self.assertEqual(penalty["employment_score_adjustment"], -6)
        self.assertEqual(flexible["employment_score_adjustment"], 0)

    def test_equal_any_unknown_and_legacy_modes_are_neutral(self):
        for employment in ("full-or-part-time", "any"):
            result = evaluate_employment_policy(
                ["part-time"],
                False,
                scope(employment),
            )
            self.assertTrue(result["employment_eligible"])
            self.assertEqual(result["employment_score_adjustment"], 0)

        unknown = evaluate_employment_policy(
            [],
            False,
            scope("full-time-preferred"),
        )
        legacy = evaluate_employment_policy(
            ["part-time"],
            False,
            {"legacy_mode": True},
        )
        self.assertEqual(unknown["employment_match"], "unknown")
        self.assertEqual(unknown["employment_score_adjustment"], 0)
        self.assertEqual(legacy["employment_score_adjustment"], 0)

    def test_flexible_language_satisfies_both_strict_modes(self):
        job = {
            "title": "Operations Coordinator",
            "description": "This is a full-time role, but part-time is possible.",
        }
        metadata = infer_employment_metadata(job)
        self.assertEqual(
            set(metadata["employment_types"]),
            {"full-time", "part-time"},
        )
        self.assertTrue(metadata["flexible_hours"])
        for employment in ("full-time-only", "part-time-only"):
            result = evaluate_employment_policy(
                metadata["employment_types"],
                metadata["flexible_hours"],
                scope(employment),
            )
            self.assertTrue(result["employment_eligible"])

    def test_sponsorship_cap_runs_after_employment_bonus(self):
        metadata = enrich_job_scope_metadata(
            {
                "title": "Full-time Product Designer",
                "description": "International product role in Dubai.",
                "location": "Dubai",
            },
            scope("full-time-preferred", market="uae"),
            ai_result={"interview_probability_score": 68},
        )
        adjusted_score = 68 + metadata["employment_score_adjustment"]
        capped_score, reason = cap_score_for_scope(adjusted_score, metadata)
        self.assertEqual(metadata["employment_score_adjustment"], 3)
        self.assertEqual(metadata["sponsorship_status"], "unknown")
        self.assertEqual(capped_score, 69)
        self.assertIn("sponsorship", reason.lower())


class GermanyMarketTests(unittest.TestCase):
    def setUp(self):
        self.germany_scope = {
            "platform": "linkedin",
            "search_market": "germany",
            "location": "Berlin",
            "radius_km": 40,
            "employment": "full-time-preferred",
        }

    def test_mandatory_german_is_rejected(self):
        verdict = market_eligibility(
            {
                "title": "Junior Product Designer",
                "location": "Berlin, Germany",
                "description": "Fluent German is required for this role. English is also used.",
            },
            self.germany_scope,
        )
        self.assertFalse(verdict["eligible"])
        self.assertIn("Mandatory German", verdict["reasons"][0])

    def test_optional_german_is_a_concern_not_a_rejection(self):
        verdict = market_eligibility(
            {
                "title": "Junior Product Designer",
                "location": "Berlin, Germany",
                "description": "Our working language is English. German is a plus.",
            },
            self.germany_scope,
        )
        self.assertTrue(verdict["eligible"])
        self.assertIn("German preferred", verdict["concerns"])

    def test_english_friendly_germany_role_remains_eligible(self):
        verdict = market_eligibility(
            {
                "title": "Digital Product Coordinator",
                "location": "Berlin, Germany",
                "description": "Join our international team. English is the working language.",
            },
            self.germany_scope,
        )
        self.assertTrue(verdict["eligible"])
        self.assertEqual(verdict["reasons"], [])

    def test_predominantly_german_posting_without_english_signal_is_rejected(self):
        assessment = german_language_assessment(
            {
                "title": "Junior Designer",
                "location": "Berlin, Germany",
                "description": (
                    "Wir suchen dich und deine Erfahrung. Die Aufgaben und "
                    "Anforderungen der Bewerbung sind auf dieser Seite. "
                    "Unser Team bietet dir gute Arbeitszeit und Entwicklung."
                ),
            }
        )
        self.assertTrue(assessment["predominantly_german"])
        verdict = market_eligibility(
            {
                "title": "Junior Designer",
                "location": "Berlin, Germany",
                "description": (
                    "Wir suchen dich und deine Erfahrung. Die Aufgaben und "
                    "Anforderungen der Bewerbung sind auf dieser Seite. "
                    "Unser Team bietet dir gute Arbeitszeit und Entwicklung."
                ),
            },
            self.germany_scope,
        )
        self.assertFalse(verdict["eligible"])


class GulfMarketSafetyTests(unittest.TestCase):
    def setUp(self):
        self.uae_scope = {
            "platform": "linkedin",
            "search_market": "uae",
            "location": "Dubai",
            "radius_km": 40,
            "employment": "full-time-preferred",
        }

    def test_confirmed_sponsorship_remains_eligible(self):
        job = {
            "title": "Junior Product Designer",
            "location": "Dubai, United Arab Emirates",
            "description": "Work visa provided and relocation support are included.",
        }
        self.assertEqual(
            classify_sponsorship(job, self.uae_scope),
            "confirmed",
        )
        verdict = market_eligibility(job, self.uae_scope)
        self.assertTrue(verdict["eligible"])
        self.assertEqual(verdict["concerns"], [])

    def test_likely_international_hiring_is_visible_but_eligible(self):
        job = {
            "title": "Digital Product Coordinator",
            "location": "Dubai, United Arab Emirates",
            "description": (
                "International candidates are welcome. We offer a relocation "
                "package and global mobility support."
            ),
        }
        verdict = market_eligibility(job, self.uae_scope)
        self.assertTrue(verdict["eligible"])
        self.assertEqual(verdict["sponsorship_status"], "likely")
        self.assertTrue(
            any("confirm" in concern.lower() for concern in verdict["concerns"])
        )

    def test_unknown_sponsorship_is_human_review_and_score_capped(self):
        job = {
            "title": "Junior UX Designer",
            "location": "Dubai, United Arab Emirates",
            "description": "English-speaking product team based in Dubai.",
        }
        metadata = enrich_job_scope_metadata(
            job,
            self.uae_scope,
            ai_result={"career_lane": "primary"},
        )
        score, reason = cap_score_for_scope(88, metadata)
        self.assertTrue(metadata["market_eligible"])
        self.assertEqual(metadata["sponsorship_status"], "unknown")
        self.assertEqual(score, 69)
        self.assertIn("human review", reason.lower())

    def test_local_visa_only_role_is_rejected(self):
        job = {
            "title": "Content Coordinator",
            "location": "Dubai, United Arab Emirates",
            "description": "Applicants must already have a valid visa. No visa sponsorship.",
        }
        verdict = market_eligibility(job, self.uae_scope)
        self.assertFalse(verdict["eligible"])
        self.assertEqual(verdict["sponsorship_status"], "unavailable")
        self.assertIn("does not sponsor", verdict["reasons"][0])

    def test_english_and_arabic_are_compatible_signals(self):
        for language in ("English", "Arabic"):
            with self.subTest(language=language):
                verdict = market_eligibility(
                    {
                        "title": "Customer Success Coordinator",
                        "location": "Dubai, United Arab Emirates",
                        "description": (
                            f"{language} is the working language. "
                            "Visa sponsorship is provided."
                        ),
                    },
                    self.uae_scope,
                )
                self.assertTrue(verdict["eligible"])
                self.assertEqual(verdict["sponsorship_status"], "confirmed")

    def test_international_benefits_and_contract_terms_are_extracted_without_ai(self):
        metadata = infer_international_metadata(
            {
                "title": "Product Designer",
                "location": "Dubai, United Arab Emirates",
                "description": (
                    "Permanent contract with relocation package, housing allowance, "
                    "medical insurance, annual flight, and AED 12000 per month."
                ),
            },
            self.uae_scope,
        )
        self.assertEqual(metadata["relocation_support"], "confirmed")
        self.assertEqual(metadata["housing_support"], "confirmed")
        self.assertEqual(metadata["health_insurance"], "confirmed")
        self.assertEqual(metadata["annual_flight_support"], "confirmed")
        self.assertEqual(metadata["contract_type"], "permanent")
        self.assertIn("aed 12000", metadata["compensation_text"])

    def test_ai_unavailable_sponsorship_remains_a_market_rejection(self):
        metadata = enrich_job_scope_metadata(
            {
                "title": "Product Designer",
                "location": "Dubai, United Arab Emirates",
                "description": "English-speaking product team.",
            },
            self.uae_scope,
            ai_result={"sponsorship_status": "unavailable"},
        )
        self.assertFalse(metadata["market_eligible"])
        self.assertEqual(metadata["sponsorship_status"], "unavailable")

    def test_all_gulf_markets_rules_and_caps(self):
        gulf_markets = ["uae", "saudi-arabia", "qatar", "kuwait"]
        for market in gulf_markets:
            with self.subTest(market=market):
                market_scope = {
                    "platform": "linkedin",
                    "search_market": market,
                    "location": "Dubai" if market == "uae" else "Riyadh" if market == "saudi-arabia" else "Doha" if market == "qatar" else "Kuwait City",
                    "radius_km": 40,
                    "employment": "full-time-preferred",
                }
                
                # 1. Unknown sponsorship is capped at 69
                job_unknown = {
                    "title": "Junior UX Designer",
                    "location": "Dubai" if market == "uae" else "Riyadh",
                    "description": "English-speaking product team.",
                }
                metadata_unknown = enrich_job_scope_metadata(
                    job_unknown,
                    market_scope,
                    ai_result={"career_lane": "primary"},
                )
                score, reason = cap_score_for_scope(88, metadata_unknown)
                self.assertTrue(metadata_unknown["market_eligible"])
                self.assertEqual(metadata_unknown["sponsorship_status"], "unknown")
                self.assertEqual(score, 69)
                self.assertIn("human review", reason.lower())

                # 2. Local visa only / no visa sponsorship is rejected
                job_rejected = {
                    "title": "Content Coordinator",
                    "location": "Dubai" if market == "uae" else "Riyadh",
                    "description": "Applicants must already have a valid visa. No visa sponsorship.",
                }
                verdict_rejected = market_eligibility(job_rejected, market_scope)
                self.assertFalse(verdict_rejected["eligible"])
                self.assertEqual(verdict_rejected["sponsorship_status"], "unavailable")
                self.assertIn("does not sponsor", verdict_rejected["reasons"][0])

                # 3. Arabic and English working language are compatible
                for language in ("English", "Arabic"):
                    verdict_lang = market_eligibility(
                        {
                            "title": "Customer Success Coordinator",
                            "location": "Dubai" if market == "uae" else "Riyadh",
                            "description": f"{language} is the working language. Visa sponsorship is provided.",
                        },
                        market_scope,
                    )
                    self.assertTrue(verdict_lang["eligible"])
                    self.assertEqual(verdict_lang["sponsorship_status"], "confirmed")


class HistoricalCareerLaneTests(unittest.TestCase):
    def test_title_and_domain_agreement_classifies_legacy_job(self):
        lane = classify_historical_career_lane(
            {
                "title": "Junior Product Designer",
                "domain_category": "UX_UI_PRODUCT_DESIGN",
            }
        )
        self.assertEqual(lane, "primary")

    def test_discovery_group_and_domain_agreement_classifies_legacy_job(self):
        lane = classify_historical_career_lane(
            {
                "title": "Coordinator",
                "search_group": "bridge",
                "domain_category": "PRODUCT_PROJECT_OPERATIONS",
            }
        )
        self.assertEqual(lane, "bridge")

    def test_single_weak_signal_stays_other(self):
        lane = classify_historical_career_lane(
            {
                "title": "Coordinator",
                "description": "May occasionally support content tasks.",
                "domain_category": "OTHER",
            }
        )
        self.assertEqual(lane, "other")


class _FakeScoringBrain:
    scoring_model_label = "test:model"

    def __init__(self, score: int):
        self.score = score
        self.calls = 0

    def scoring_model_labels_for_cache(self):
        return {"test:model"}

    def score_interview_probability(self, **_kwargs):
        self.calls += 1
        return {
            "interview_probability_score": self.score,
            "reason": "Good realistic fit.",
            "model": self.scoring_model_label,
            "used_cv": self.calls > 1,
            "career_lane": "primary",
            "employment_types": ["full-time"],
            "weekly_hours": "40 hours",
            "flexible_hours": False,
            "sponsorship_status": "not_required",
            "market_concerns": [],
        }


class EmploymentPolicyScoutIntegrationTests(unittest.TestCase):
    def _scout(self, directory: Path, employment: str) -> LinkedInJobScout:
        profile = json.loads(
            (ROOT / "config" / "profile.json").read_text(encoding="utf-8")
        )
        preferences = json.loads(
            (ROOT / "config" / "preferences.json").read_text(encoding="utf-8")
        )
        preferences["_runtime_search_scope"] = scope(employment)
        scout = LinkedInJobScout(
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
        scout.brain = _FakeScoringBrain(68)
        return scout

    def test_strict_mode_rejects_explicit_mismatch_before_ai(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scout = self._scout(Path(temp_dir), "full-time-only")
            verdict = scout._evaluate_job(
                "junior product designer",
                {
                    "title": "Junior Product Designer - Part-time",
                    "company": "Example",
                    "location": "Amsterdam, Netherlands",
                    "url": "https://www.linkedin.com/jobs/view/123/",
                    "description": "A part-time role for a junior product designer.",
                },
            )
        self.assertEqual(verdict["status"], "rejected_employment_type")
        self.assertIn("part-time-only", verdict["reasons"][0].lower())

    def test_cached_score_does_not_compound_preference_bonus(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scout = self._scout(Path(temp_dir), "full-time-preferred")
            job = {
                "title": "Junior Product Designer - Full-time",
                "company": "Example",
                "location": "Amsterdam, Netherlands",
                "url": "https://www.linkedin.com/jobs/view/456/",
                "description": "A full-time junior product design role using Figma.",
            }
            verdict = {
                "status": "survived",
                "language": "english",
                "matched_terms": ["product designer"],
                "reasons": [],
            }
            first = scout._score_surviving_job(
                "junior product designer",
                dict(job),
                verdict,
            )
            reused = scout._score_surviving_job(
                "junior product designer",
                dict(job),
                verdict,
            )

        self.assertEqual(first["interview_probability_score"], 71)
        self.assertEqual(reused["interview_probability_score"], 71)
        self.assertEqual(first["employment_score_adjustment"], 3)
        self.assertEqual(reused["employment_score_adjustment"], 3)
        self.assertEqual(scout.brain.calls, 2)


if __name__ == "__main__":
    unittest.main()
