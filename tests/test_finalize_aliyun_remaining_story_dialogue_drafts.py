from __future__ import annotations

import unittest

from tools import finalize_aliyun_remaining_story_dialogue_drafts as finalize


class RemainingDraftFinalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.key = (16, 137)
        self.queue = {
            self.key: {
                "stage_index": 16,
                "unique_index": 137,
                "source_text": "エクソダスしてるのよ！",
                "source_text_sha256": "0" * 64,
                "source_quote_shape": "plain",
                "glossary_terms": [
                    {
                        "id": "event/exodus",
                        "translation": "大逃亡",
                        "enforce": True,
                    }
                ],
            }
        }
        self.candidates = {
            self.key: {
                "stage_index": 16,
                "unique_index": 137,
                "source_text_sha256": "0" * 64,
                "translation": "我们也在逃亡！",
                "translation_action": "translate",
                "glossary_refs": [],
                "glossary_exceptions": [],
                "notes": "",
            }
        }

    def test_term_replacement_is_audited_and_validator_clean(self) -> None:
        audit = finalize.apply_decisions(
            self.queue,
            self.candidates,
            {
                "term_replacements": [
                    {
                        "term_id": "event/exodus",
                        "find": "逃亡",
                        "replace": "大逃亡",
                        "reason": "采用事件规范译名。",
                    }
                ],
                "row_overrides": [],
                "glossary_exceptions": [],
            },
        )
        self.assertEqual(self.candidates[self.key]["translation"], "我们也在大逃亡！")
        self.assertEqual(len(audit), 1)
        self.assertEqual(finalize.strict_failures(self.queue, self.candidates), [])

    def test_scoped_replacement_fails_closed_when_it_matches_nothing(self) -> None:
        with self.assertRaisesRegex(ValueError, "matched no rows"):
            finalize.apply_decisions(
                self.queue,
                self.candidates,
                {
                    "term_replacements": [
                        {
                            "term_id": "event/exodus",
                            "find": "逃亡",
                            "replace": "大逃亡",
                            "reason": "采用事件规范译名。",
                            "keys": ["16:999"],
                        }
                    ],
                    "row_overrides": [],
                    "glossary_exceptions": [],
                },
            )

    def test_term_exception_is_explicit_and_validator_clean(self) -> None:
        audit = finalize.apply_decisions(
            self.queue,
            self.candidates,
            {
                "term_replacements": [],
                "term_exceptions": [
                    {
                        "term_id": "event/exodus",
                        "reason": "当前语境明确采用一般含义。",
                    }
                ],
                "row_overrides": [],
                "glossary_exceptions": [],
            },
        )
        self.assertEqual(audit[0]["kind"], "term_exception")
        self.assertEqual(
            self.candidates[self.key]["glossary_exceptions"], ["event/exodus"]
        )
        self.assertEqual(finalize.strict_failures(self.queue, self.candidates), [])

    def test_scoped_text_replacement_is_audited(self) -> None:
        self.candidates[self.key]["translation"] = "Overman从钢铁齿轮里出来了！"
        audit = finalize.apply_decisions(
            self.queue,
            self.candidates,
            {
                "term_replacements": [],
                "text_replacements": [
                    {
                        "find": "Overman",
                        "replace": "超限人",
                        "reason": "采用项目中文术语。",
                        "keys": ["16:137"],
                    }
                ],
                "term_exceptions": [],
                "row_overrides": [],
                "glossary_exceptions": [],
            },
        )
        self.assertEqual(self.candidates[self.key]["translation"], "超限人从钢铁齿轮里出来了！")
        self.assertEqual(audit[0]["kind"], "text_replacement")

    def test_text_replacement_requires_every_scoped_row_to_match(self) -> None:
        with self.assertRaisesRegex(ValueError, "did not match scoped rows"):
            finalize.apply_decisions(
                self.queue,
                self.candidates,
                {
                    "term_replacements": [],
                    "text_replacements": [
                        {
                            "find": "Overman",
                            "replace": "超限人",
                            "reason": "采用项目中文术语。",
                            "keys": ["16:137"],
                        }
                    ],
                    "term_exceptions": [],
                    "row_overrides": [],
                    "glossary_exceptions": [],
                },
            )

    def test_semantic_allowlist_includes_glossary_and_audited_terms(self) -> None:
        allowed = finalize.semantic_ascii_allowlist(
            self.queue,
            {
                "semantic_allowlist": {
                    "ascii_terms": [
                        {"term": "LFO", "reason": "作品内规范缩写。"}
                    ]
                }
            },
        )
        self.assertEqual(allowed, {"LFO"})
        risks = finalize.semantic_risks(
            self.queue,
            {
                self.key: {
                    **self.candidates[self.key],
                    "translation": "LFO已经出击。",
                }
            },
            allowed,
        )
        self.assertEqual(risks, [])

    def test_semantic_unchanged_allowlist_is_scoped_and_audited(self) -> None:
        self.queue[self.key]["source_text"] = "平原"
        allowed = finalize.semantic_unchanged_allowlist(
            self.queue,
            {
                "semantic_allowlist": {
                    "unchanged_source_rows": [
                        {"key": "16:137", "reason": "日中同形的地形名称。"}
                    ]
                }
            },
        )
        self.assertEqual(allowed, {self.key})
        risks = finalize.semantic_risks(
            self.queue,
            {
                self.key: {
                    **self.candidates[self.key],
                    "translation": "平原",
                }
            },
            allowed_unchanged_keys=allowed,
        )
        self.assertEqual(risks, [])


if __name__ == "__main__":
    unittest.main()
