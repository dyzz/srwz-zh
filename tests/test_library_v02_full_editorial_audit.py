import json
import unittest

from tools import run_library_v02_full_editorial_audit as audit


class LibraryV02FullEditorialAuditTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "id": "library-text/a",
            "source_text": "\u3000\u30c6\u30b9\u30c8\u3002",
            "source_text_sha256": "0" * 64,
            "candidate_translation": "测试。",
            "tags": ["DSCR"],
            "glossary_terms": [],
            "references": [
                {"domain": "robot", "entry_index": 1, "tag": "DSCR"}
            ],
        }

    def test_phase_and_plan_cover_metadata_and_prose(self):
        metadata = {**self.row, "id": "library-text/b", "tags": ["RBTN"]}
        self.assertEqual(audit.phase_of(self.row), "prose")
        self.assertEqual(audit.phase_of(metadata), "metadata")
        jobs, counts = audit.plan_jobs(
            [metadata, self.row],
            ["metadata", "prose"],
            metadata_chunk_size=80,
            prose_chunk_size=16,
        )
        self.assertEqual(counts, {"metadata": 1, "prose": 1})
        self.assertEqual([job.key for job in jobs], ["metadata-0000-0001", "prose-0000-0001"])

    def test_keep_and_revise_response_contract(self):
        keep = json.dumps(
            {
                "reviews": [
                    {
                        "id": self.row["id"],
                        "verdict": "keep",
                        "text": "",
                        "issues": [],
                        "reason": "准确自然。",
                    }
                ]
            },
            ensure_ascii=False,
        )
        reviews, report = audit.parse_reviews(keep, [self.row])
        self.assertTrue(report["exact_id_order"])
        self.assertEqual(reviews[0]["translation"], "测试。")

        revise = json.dumps(
            {
                "reviews": [
                    {
                        "id": self.row["id"],
                        "verdict": "revise",
                        "text": "已校对。",
                        "issues": ["fluency"],
                        "reason": "修正生硬措辞。",
                    }
                ]
            },
            ensure_ascii=False,
        )
        reviews, report = audit.parse_reviews(revise, [self.row])
        self.assertEqual(report["errors"], {})
        self.assertEqual(reviews[0]["translation"], "已校对。")

        no_op_revise = json.dumps(
            {
                "reviews": [
                    {
                        "id": self.row["id"],
                        "verdict": "revise",
                        "text": "测试。",
                        "issues": ["fluency"],
                        "reason": "复核后无可执行改动。",
                    }
                ]
            },
            ensure_ascii=False,
        )
        reviews, report = audit.parse_reviews(no_op_revise, [self.row])
        self.assertEqual(report["errors"], {})
        self.assertEqual(reviews[0]["verdict"], "keep")
        self.assertEqual(reviews[0]["issues"], [])

    def test_response_rejects_inconsistent_verdict(self):
        malformed = json.dumps(
            {
                "reviews": [
                    {
                        "id": self.row["id"],
                        "verdict": "keep",
                        "text": "改写。",
                        "issues": ["fluency"],
                        "reason": "不一致。",
                    }
                ]
            },
            ensure_ascii=False,
        )
        reviews, report = audit.parse_reviews(malformed, [self.row])
        self.assertEqual(reviews, [])
        self.assertIn(self.row["id"], report["errors"])

    def test_legacy_metadata_prompt_is_rejected_but_prose_is_reusable(self):
        metadata_job = audit.Job("metadata", 0, 1)
        prose_job = audit.Job("prose", 0, 1)
        self.assertFalse(audit.prompt_version_ok({}, metadata_job))
        self.assertTrue(audit.prompt_version_ok({}, prose_job))
        self.assertTrue(
            audit.prompt_version_ok({"prompt_version": 2}, metadata_job)
        )


if __name__ == "__main__":
    unittest.main()
