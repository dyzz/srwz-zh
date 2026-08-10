import json
import unittest

from tools import extract_library_v02_corpus as extract
from tools import audit_library_v02_machine_draft as audit
from tools import run_aliyun_library_v02_all as run_all
from tools import run_aliyun_library_v02_batch as batch
from tools.srwz.library import LibraryScopeError


class AliyunLibraryV02BatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.row = {
            "schema_version": 1,
            "id": "library-text/0123456789abcdef",
            "source_text": "ティターンズ",
            "model_source_text": "ティターンズ",
            "source_text_sha256": batch.sha256_text("ティターンズ"),
            "references": [
                {
                    "field_id": "library/glossary/007/word",
                    "domain": "glossary",
                    "entry_index": 7,
                    "tag": "WORD",
                }
            ],
            "glossary_terms": [
                {
                    "id": "organization/titans",
                    "matched_source_terms": ["ティターンズ"],
                    "translation": "提坦斯",
                    "enforce": True,
                    "status": "approved",
                }
            ],
        }

    def test_prompt_includes_exact_and_required_terms(self):
        terms = batch.prompt_terms(self.row)
        self.assertEqual(terms[0]["target"], "提坦斯")
        self.assertIs(terms[0]["required"], True)
        messages = batch.build_messages([self.row])
        self.assertIn("library-text/0123456789abcdef", messages[1]["content"])

    def test_default_model_is_locked_aliyun_deepseek_v4_flash_snapshot(self):
        self.assertEqual(batch.DEFAULT_MODEL, "deepseek-v4-flash-0731")
        self.assertIn(
            "deepseek-v4-flash-0731",
            str(audit.DEFAULT_DRAFT),
        )

    def test_translation_validator_requires_approved_term(self):
        result = batch.validate_translation(self.row, "提坦斯")
        self.assertEqual(result["glossary_refs"], ["organization/titans"])
        with self.assertRaisesRegex(LibraryScopeError, "required glossary"):
            batch.validate_translation(self.row, "泰坦斯")

    def test_translation_validator_rejects_kana_and_manual_wrap(self):
        with self.assertRaisesRegex(LibraryScopeError, "Japanese kana"):
            batch.validate_translation(self.row, "ティターンズ")
        with self.assertRaisesRegex(LibraryScopeError, "manual line breaks"):
            batch.validate_translation(self.row, "提坦\n斯")

    def test_response_requires_exact_id_order_and_fields(self):
        text = json.dumps(
            {
                "translations": [
                    {"id": self.row["id"], "text": "提坦斯"}
                ]
            },
            ensure_ascii=False,
        )
        paired, audit = batch.parse_response(text, [self.row])
        self.assertTrue(audit["exact_id_order"])
        self.assertEqual(paired[0][1], "提坦斯")

        malformed = json.dumps(
            {
                "translations": [
                    {"id": self.row["id"], "text": "提坦斯", "jp": "x"}
                ]
            },
            ensure_ascii=False,
        )
        paired, audit = batch.parse_response(malformed, [self.row])
        self.assertEqual(paired, [])
        self.assertFalse(audit["exact_id_order"])

    def test_domain_selection_is_bounded(self):
        selected = batch.select_rows(
            [self.row], domain="glossary", tags=(), phase=None, offset=0, limit=1
        )
        self.assertEqual(selected, [self.row])
        with self.assertRaisesRegex(LibraryScopeError, "empty"):
            batch.select_rows(
                [self.row], domain="robot", tags=(), phase=None, offset=0, limit=1
            )

        by_tag = batch.select_rows(
            [self.row], domain=None, tags=("WORD",), phase=None, offset=0, limit=1
        )
        self.assertEqual(by_tag, [self.row])

        metadata = batch.select_rows(
            [self.row],
            domain=None,
            tags=(),
            phase="metadata",
            offset=0,
            limit=1,
        )
        self.assertEqual(metadata, [self.row])

    def test_kana_glossary_matching_does_not_hit_inside_a_longer_name(self):
        terms = [
            {
                "id": "people/rand",
                "source_terms": ["ランド"],
                "translation": "兰德",
                "enforce": False,
                "declared_enforce": True,
                "status": "researched",
            },
            {
                "id": "people/holland",
                "source_terms": ["ホランド"],
                "translation": "霍兰德",
                "enforce": False,
                "declared_enforce": True,
                "status": "researched",
            },
            {
                "id": "people/jamitov",
                "source_terms": ["ジャミトフ"],
                "translation": "加米托夫",
                "enforce": False,
                "declared_enforce": True,
                "status": "researched",
            },
        ]
        matches = extract.relevant_terms(
            "ホランドが軍を脱走し、ジャミトフ・ハイマンが就任した。",
            terms,
        )
        self.assertEqual(
            [item["id"] for item in matches],
            ["people/holland", "people/jamitov"],
        )

    def test_spirit_term_is_only_hard_enforced_as_a_whole_field(self):
        terms = [
            {
                "id": "spirit/cheer",
                "source_terms": ["応援"],
                "translation": "应援",
                "enforce": True,
                "declared_enforce": True,
                "status": "approved",
            }
        ]
        prose = extract.relevant_terms("兄を応援する少年。", terms)
        label = extract.relevant_terms("応援", terms)
        self.assertIs(prose[0]["enforce"], False)
        self.assertIs(label[0]["enforce"], True)

    def test_phase_aggregation_keeps_source_queue_order(self):
        body = {
            **self.row,
            "id": "library-text/body",
            "source_text": "本文",
            "model_source_text": "本文",
            "source_text_sha256": batch.sha256_text("本文"),
            "references": [
                {
                    "field_id": "library/glossary/007/dscr",
                    "domain": "glossary",
                    "entry_index": 7,
                    "tag": "DSCR",
                }
            ],
            "glossary_terms": [],
        }
        queue = [body, self.row]
        expected_rows = run_all.expected_rows_for_phases(
            queue, ("metadata", "body")
        )
        self.assertEqual(
            [row["id"] for row in expected_rows],
            ["library-text/body", self.row["id"]],
        )

    def test_editorial_audit_flags_missing_hint_and_ascii_word(self):
        row = {
            **self.row,
            "glossary_terms": [
                {
                    "id": "unit/naikick",
                    "translation": "奈基克",
                    "status": "proposed",
                }
            ],
        }
        reasons = audit.risk_reasons(row, "Naikick机")
        self.assertEqual(
            [reason["code"] for reason in reasons],
            ["ascii_word", "glossary_hint_mismatch"],
        )


if __name__ == "__main__":
    unittest.main()
