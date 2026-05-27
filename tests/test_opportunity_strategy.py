import json
import unittest
from pathlib import Path

from agent.job_scout import LinkedInJobScout


ROOT = Path(__file__).resolve().parents[1]


class OpportunityStrategyFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
        preferences = json.loads((ROOT / "config" / "preferences.json").read_text(encoding="utf-8"))
        cls.scout = LinkedInJobScout(profile, preferences, browser=None)

    def _job(self, title, description, *, company="Example", location="Amsterdam, Netherlands"):
        return {
            "title": title,
            "company": company,
            "location": location,
            "preview_text": description[:220],
            "description": description,
            "url": "https://www.linkedin.com/jobs/view/123456789/",
        }

    def _evaluate(self, query, title, description, **kwargs):
        return self.scout._evaluate_job(query, self._job(title, description, **kwargs))

    def test_internship_without_current_student_requirement_is_kept_for_review(self):
        verdict = self._evaluate(
            "digital designer",
            "Trigger Digital Creative Design Intern",
            (
                "Creative design internship for an early-career designer in Rotterdam. "
                "You will support content, campaigns, UX ideas, and AI experiments. "
                "Allowance EUR 500 per month."
            ),
            location="Rotterdam, Netherlands",
        )

        self.assertEqual(verdict["status"], "accepted")
        self.assertTrue(any("Internship-style role allowed" in reason for reason in verdict["reasons"]))

    def test_current_student_internship_is_rejected(self):
        verdict = self._evaluate(
            "digital designer",
            "Digital Design Intern",
            "Internship requires current student status and you must be enrolled at a university.",
        )

        self.assertEqual(verdict["status"], "rejected_internship")

    def test_strict_three_to_six_year_ux_role_is_rejected(self):
        verdict = self._evaluate(
            "ux designer",
            "UX Designer",
            "Basic-Fit style role requires 3-6 years product UX experience and ownership of UX strategy.",
            company="Basic-Fit",
        )

        self.assertEqual(verdict["status"], "rejected_entry_level")

    def test_five_plus_year_ui_role_is_rejected(self):
        verdict = self._evaluate(
            "ui designer",
            "UI Designer",
            "Monks style role requiring 5+ years of UI design experience and platform migration ownership.",
            company="Monks",
        )

        self.assertEqual(verdict["status"], "rejected_entry_level")

    def test_junior_ecommerce_with_plain_fluent_dutch_is_kept(self):
        verdict = self._evaluate(
            "ecommerce specialist",
            "Junior E-commerce Specialist",
            "Junior e-commerce role using CMS, product content, merchandising, and analytics. Fluent Dutch and English requested.",
            company="Dynamic",
        )

        self.assertEqual(verdict["status"], "accepted")

    def test_training_based_data_role_with_b2_dutch_is_kept(self):
        verdict = self._evaluate(
            "data analyst",
            "Data Analyst Training Programme",
            "Graduate-friendly data analyst programme teaching SQL, Python, Power BI, dashboards, and reporting. B2 Dutch preferred.",
            company="CFG",
        )

        self.assertEqual(verdict["status"], "accepted")

    def test_senior_data_engineer_is_rejected(self):
        verdict = self._evaluate(
            "data analyst",
            "Senior Data Engineer",
            "Requires 5+ years hands-on Python, Snowflake, dbt, production data engineering, and ownership.",
        )

        self.assertEqual(verdict["status"], "rejected_entry_level")

    def test_recruitment_with_fluent_dutch_and_calls_is_rejected(self):
        verdict = self._evaluate(
            "customer success coordinator",
            "Recruitment Consultant",
            "Fluent Dutch is required because this role involves recruitment calls, cold calling, and sales targets.",
        )

        self.assertEqual(verdict["status"], "rejected_dutch")

    def test_customer_success_saas_bridge_role_is_kept(self):
        verdict = self._evaluate(
            "customer success coordinator",
            "Customer Success Coordinator",
            "English-friendly SaaS customer success role supporting onboarding, customer operations, insights, and product feedback.",
        )

        self.assertEqual(verdict["status"], "accepted")

    def test_talk360_support_operations_bridge_role_is_kept(self):
        verdict = self._evaluate(
            "customer operations specialist",
            "Customer Operations Specialist",
            "Talk360 style support operations role supporting customers, app feedback, documentation, and internal process improvements in English.",
            company="Talk360",
        )

        self.assertEqual(verdict["status"], "accepted")

    def test_joolz_junior_product_manager_is_kept(self):
        verdict = self._evaluate(
            "junior product manager",
            "Junior Product Manager",
            "Joolz style junior product role coordinating product marketing, e-commerce content, stakeholder input, and market insights. English-friendly.",
            company="Joolz",
        )

        self.assertEqual(verdict["status"], "accepted")

    def test_propharma_research_assistant_not_hard_rejected_for_local_language(self):
        verdict = self._evaluate(
            "research assistant",
            "Research Assistant",
            "Clinical study assistant role with part-time hours, research administration, local language preferred, and documentation support.",
            company="ProPharma",
        )

        self.assertEqual(verdict["status"], "accepted")

    def test_accenture_song_junior_designer_is_kept(self):
        verdict = self._evaluate(
            "junior digital designer",
            "Junior Designer",
            "Accenture Song style junior designer role supporting brand, UX/UI, digital campaigns, Figma prototypes, and client-facing creative work.",
            company="Accenture Song",
        )

        self.assertEqual(verdict["status"], "accepted")

    def test_procurement_trainee_is_kept_as_bridge_role(self):
        verdict = self._evaluate(
            "procurement trainee",
            "Procurement Trainee",
            "Graduate trainee role with training, supplier coordination, Excel reporting, operations exposure, and mentorship.",
        )

        self.assertEqual(verdict["status"], "accepted")


class OpportunityStrategyBrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
        preferences = json.loads((ROOT / "config" / "preferences.json").read_text(encoding="utf-8"))
        cls.brain = LinkedInJobScout(profile, preferences, browser=None).brain

    def test_language_screening_answer_is_truthful(self):
        answer = self.brain.get_structured_question_answer("Are you fluent in Dutch and English?")
        self.assertIn("fluent in English", answer)
        self.assertIn("B1/intermediate", answer)

    def test_language_screening_radio_answer_is_no(self):
        answer = self.brain.get_structured_question_answer(
            "Are you fluent in Dutch and English?",
            context="radio options: Yes / No",
        )
        self.assertEqual(answer, "No")

    def test_low_paid_strategic_internship_is_human_review_not_apply(self):
        match = self.brain.evaluate_job_match(
            {
                "title": "Trigger Digital Creative Design Intern",
                "company": "Trigger",
                "location": "Rotterdam, Netherlands",
                "salary": "EUR 500 per month internship allowance",
                "description": (
                    "Full-time creative design internship for recent graduates. "
                    "AI-assisted creative concepts, psychology-led campaigns, Figma prototypes, "
                    "content design, and brand activations."
                ),
            }
        )

        self.assertFalse(match["apply"])
        self.assertTrue(match["human_review"])
        self.assertLess(match["score"], 70)

    def test_internal_process_does_not_count_as_internship(self):
        match = self.brain.evaluate_job_match(
            {
                "title": "Customer Case Investigation Specialist",
                "company": "Talk360",
                "location": "Amsterdam, Netherlands",
                "description": (
                    "English-friendly support operations role for recent graduates. "
                    "Investigate customer cases, payment issues, app feedback, documentation, "
                    "and internal process improvements."
                ),
            }
        )

        self.assertTrue(match["apply"])
        self.assertFalse(any("Employment type 'internship'" in reason for reason in match["reasons"]))

    def test_part_time_research_with_local_language_and_utrecht_is_human_review(self):
        match = self.brain.evaluate_job_match(
            {
                "title": "Research Assistant",
                "company": "ProPharma",
                "location": "Utrecht, Netherlands",
                "description": (
                    "Part-time research assistant / clinical study assistant role. "
                    "Support research administration and documentation. Local language preferred."
                ),
            }
        )

        self.assertFalse(match["apply"])
        self.assertTrue(match["human_review"])
        self.assertLess(match["score"], 70)

    def test_plain_fluent_dutch_is_not_hard_blocked_without_context(self):
        marker = self.brain._high_dutch_fluency_requirement(
            {
                "title": "Junior E-commerce Specialist",
                "description": "Fluent Dutch and English requested for a junior e-commerce CMS role.",
            }
        )
        self.assertEqual(marker, "")

    def test_fluent_dutch_with_recruitment_context_is_hard_blocked(self):
        marker = self.brain._high_dutch_fluency_requirement(
            {
                "title": "Recruitment Consultant",
                "description": "Fluent Dutch is required for recruitment calls and sales calls.",
            }
        )
        self.assertIn("fluent", marker.lower())


if __name__ == "__main__":
    unittest.main()
