import json
import unittest

from tools import adjudicate_library_v02_full_editorial_audit as adjudication


class LibraryV02EditorialAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.review = {"id": "library-text/a"}

    def test_parses_current_proposed_and_custom(self):
        for choice, text in (
            ("current", ""),
            ("proposed", ""),
            ("custom", "最终译文。"),
        ):
            response = json.dumps(
                {
                    "decisions": [
                        {
                            "id": self.review["id"],
                            "choice": choice,
                            "text": text,
                            "issues": [] if choice == "current" else ["accuracy"],
                            "reason": "对照日文源裁决。",
                        }
                    ]
                },
                ensure_ascii=False,
            )
            decisions, report = adjudication.parse_decisions(
                response, [self.review]
            )
            self.assertEqual(report["errors"], {})
            self.assertTrue(report["exact_id_set"])
            self.assertEqual(decisions[0]["choice"], choice)

    def test_normalizes_corrected_text_to_custom_choice(self):
        response = json.dumps(
            {
                "decisions": [
                    {
                        "id": self.review["id"],
                        "choice": "proposed",
                        "text": "不应出现。",
                        "issues": ["accuracy"],
                        "reason": "字段契约错误。",
                    }
                ]
            },
            ensure_ascii=False,
        )
        decisions, report = adjudication.parse_decisions(response, [self.review])
        self.assertEqual(report["errors"], {})
        self.assertEqual(decisions[0]["choice"], "custom")
        self.assertEqual(
            report["normalized_non_custom_text_ids"], [self.review["id"]]
        )


if __name__ == "__main__":
    unittest.main()
