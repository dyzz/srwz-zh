from __future__ import annotations

import unittest
from unittest.mock import patch

from tools import promote_full_story_dialogue_drafts as promote


class FullStoryPromotionTests(unittest.TestCase):
    def test_title_normalization_handles_middle_dot(self) -> None:
        self.assertEqual(
            promote.replace_the_titles("“The·Heat和The·Crusher”", heat=True, crusher=True),
            "“THE HEAT和THE CRUSHER”",
        )

    def test_vector_surface_map_is_explicit(self) -> None:
        mapping = promote.SURFACE_MAPS["P:project-aquarion-vectors"]
        self.assertEqual(mapping["Vector Mars"], "火星战机")
        self.assertEqual(mapping["Vector Omega"], "欧米伽战机")
        self.assertEqual(mapping["Luna"], "月亮战机")

    def test_deferred_tam_has_no_surface_mapping(self) -> None:
        self.assertNotIn("P:unresolved-tam", promote.SURFACE_MAPS)
        self.assertNotIn("P:unresolved-tam", promote.SPECIAL_ITEMS)

    def test_serialization_tail_repair_is_exact(self) -> None:
        selected = {
            (81, 36): {"translation": "“正文。”},{”", "notes": ""},
            (81, 37): {"translation": "“正文。”", "notes": ""},
        }
        audit = []
        promote.repair_serialization_artifacts(selected, audit)
        self.assertEqual(selected[(81, 36)]["translation"], "“正文。”")
        self.assertEqual(selected[(81, 37)]["translation"], "“正文。”")
        self.assertEqual(len(audit), 1)

    def test_source_aware_repairs_only_touch_matching_source_rows(self) -> None:
        queue = {
            (24, 0): {"source_text": "「これがパラダイムシティ…」"},
            (24, 1): {"source_text": "「普通の街だ」"},
        }
        selected = {
            (24, 0): {"translation": "“这就是范式城……”"},
            (24, 1): {"translation": "“这就是范式城……”"},
        }
        decisions = {
            str(rule["decision_id"]): {"chosen_translation": rule["chosen_translation"]}
            for rule in promote.SOURCE_AWARE_DECISION_REPAIRS
        }
        audit = []
        promote.apply_source_aware_decision_repairs(queue, selected, decisions, audit)
        self.assertEqual(selected[(24, 0)]["translation"], "“这就是帕拉达伊姆城……”")
        self.assertEqual(selected[(24, 1)]["translation"], "“这就是范式城……”")
        self.assertEqual(len(audit), 1)

    def test_source_aware_repairs_remove_duplicated_canonical_suffix(self) -> None:
        queue = {
            (86, 122): {"source_text": "「パラダイム社へ向かう」"},
            (104, 271): {"source_text": "「ジェノサイドロンシステム」"},
        }
        selected = {
            (86, 122): {"translation": "“帕拉达伊姆公司公司”"},
            (104, 271): {"translation": "“杰诺赛德隆系统系统”"},
        }
        decisions = {
            str(rule["decision_id"]): {"chosen_translation": rule["chosen_translation"]}
            for rule in promote.SOURCE_AWARE_DECISION_REPAIRS
        }
        audit = []
        promote.apply_source_aware_decision_repairs(queue, selected, decisions, audit)
        self.assertEqual(selected[(86, 122)]["translation"], "“帕拉达伊姆公司”")
        self.assertEqual(selected[(104, 271)]["translation"], "“杰诺赛德隆系统”")
        self.assertEqual(len(audit), 2)

    def test_editorial_override_is_source_hash_and_translation_locked(self) -> None:
        document = {
            "entries": [{
                "review_id": "line-edit/test",
                "stage_index": 12,
                "unique_index": 4,
                "source_text_sha256": "abc",
                "expected_translation": "旧译",
                "translation": "新译",
            }],
        }
        queue = {(12, 4): {"source_text_sha256": "abc"}}
        selected = {(12, 4): {"translation": "旧译", "editorial_status": "draft"}}
        audit = []
        with patch.object(promote, "read_json", return_value=document):
            result = promote.apply_editorial_overrides(queue, selected, audit)
        self.assertEqual(result, {"reviewed_row_count": 1, "changed_row_count": 1})
        self.assertEqual(selected[(12, 4)]["translation"], "新译")
        self.assertEqual(selected[(12, 4)]["editorial_status"], "reviewed")
        self.assertEqual(len(audit), 1)


if __name__ == "__main__":
    unittest.main()
