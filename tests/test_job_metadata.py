import unittest

from agent.job_metadata import normalize_apply_method, normalize_apply_method_fields


class JobMetadataTests(unittest.TestCase):
    def test_explicit_method_takes_precedence_over_legacy_flags(self):
        self.assertEqual(
            normalize_apply_method(
                {
                    "apply_method": "external_apply",
                    "easy_apply": True,
                    "flags": ["easy_apply"],
                }
            ),
            "external_apply",
        )

    def test_legacy_easy_apply_flag_is_normalized(self):
        normalized = normalize_apply_method_fields(
            {
                "title": "Designer",
                "flags": ["creative_fit", "easy_apply"],
            }
        )

        self.assertEqual(normalized["apply_method"], "easy_apply")
        self.assertEqual(normalized["apply_method_label"], "Easy Apply")
        self.assertTrue(normalized["easy_apply"])

    def test_unknown_is_used_when_no_apply_evidence_exists(self):
        self.assertEqual(normalize_apply_method({"flags": []}), "unknown")


if __name__ == "__main__":
    unittest.main()
