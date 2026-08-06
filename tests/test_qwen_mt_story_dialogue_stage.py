import unittest

from tools.run_qwen_mt_story_dialogue_stage import (
    APICall,
    GroupTranslator,
    QwenMTStageError,
    build_segment_content,
    candidate_for_row,
    group_stage_rows,
    normalize_translation,
    parse_segment_response,
    preserved_candidate,
    relevant_terms,
    shadowed_glossary_term_ids,
)


def _row(index, *, section="Section 1.1", shape="dialogue_quoted", source="「テスト」"):
    return {
        "stage_index": 10,
        "unique_index": index,
        "source_text": source,
        "source_text_sha256": "a" * 64,
        "source_quote_shape": shape,
        "sections": [section],
        "glossary_terms": [],
        "glossary_conflicts": [],
        "structural_tokens": [],
    }


class QwenMTStoryDialogueStageTests(unittest.TestCase):
    def test_grouping_never_crosses_section_or_control_row(self):
        rows = [
            _row(0),
            _row(1),
            _row(2, shape="control_or_punctuation", source="？？？"),
            _row(3),
            _row(4, section="Section 1.2"),
            _row(5, section="Section 1.2"),
        ]
        groups = group_stage_rows(rows, 2)
        self.assertEqual(
            [[row["unique_index"] for row in group] for group in groups],
            [[0, 1], [3], [4, 5]],
        )

    def test_xml_segments_require_exact_ids_and_order(self):
        rows = [_row(0), _row(1)]
        content = build_segment_content(rows)
        self.assertIn('<srwz-seg id="10:0">', content)
        parsed = parse_segment_response(
            '<srwz-seg id="10:0">“甲”</srwz-seg>\n'
            '<srwz-seg id="10:1">“乙”</srwz-seg>',
            rows,
        )
        self.assertEqual(parsed, {"10:0": "“甲”", "10:1": "“乙”"})
        with self.assertRaises(QwenMTStageError):
            parse_segment_response(
                '<srwz-seg id="10:1">“乙”</srwz-seg>\n'
                '<srwz-seg id="10:0">“甲”</srwz-seg>',
                rows,
            )

    def test_terms_are_relevant_deduplicated_and_include_controls(self):
        row = _row(0, source="「ジュール隊、$n！」")
        row["glossary_terms"] = [
            {
                "id": "group/joule",
                "source_terms": ["ジュール隊", "未出现"],
                "translation": "玖尔队",
            },
            {
                "id": "group/joule-alias",
                "source_terms": ["ジュール隊"],
                "translation": "玖尔队",
            },
        ]
        row["structural_tokens"] = ["$n"]
        self.assertEqual(
            relevant_terms([row]),
            [
                {"source": "ジュール隊", "target": "玖尔队"},
                {"source": "$n", "target": "$n"},
            ],
        )

    def test_nested_only_glossary_match_is_excluded_and_explicit(self):
        row = _row(0, source="「ティターンズも退くだろう」")
        row["glossary_terms"] = [
            {
                "id": "organization/titans",
                "source_terms": ["ティターンズ"],
                "translation": "泰坦斯",
                "enforce": True,
            },
            {
                "id": "system/turn",
                "source_terms": ["ターン"],
                "translation": "回合",
                "enforce": True,
            },
        ]
        self.assertEqual(shadowed_glossary_term_ids(row), {"system/turn"})
        self.assertEqual(
            relevant_terms([row]),
            [{"source": "ティターンズ", "target": "泰坦斯"}],
        )
        candidate = candidate_for_row(row, "“泰坦斯也会撤退吧”")
        self.assertEqual(candidate["glossary_refs"], ["organization/titans"])
        self.assertEqual(candidate["glossary_exceptions"], ["system/turn"])

    def test_glossary_match_is_not_shadowed_when_it_also_appears_standalone(self):
        row = _row(0, source="「ティターンズは3ターン後に退く」")
        row["glossary_terms"] = [
            {
                "id": "organization/titans",
                "source_terms": ["ティターンズ"],
                "translation": "泰坦斯",
                "enforce": True,
            },
            {
                "id": "system/turn",
                "source_terms": ["ターン"],
                "translation": "回合",
                "enforce": True,
            },
        ]
        self.assertEqual(shadowed_glossary_term_ids(row), set())

    def test_one_character_system_term_inside_word_is_explicit_exception(self):
        row = _row(0, source="「我々は積極的に関与しない」")
        row["glossary_terms"] = [
            {
                "id": "skill/extreme",
                "source_terms": ["極"],
                "translation": "极",
                "enforce": True,
            }
        ]
        self.assertEqual(shadowed_glossary_term_ids(row), {"skill/extreme"})
        self.assertEqual(relevant_terms([row]), [])
        candidate = candidate_for_row(row, "“我们不会积极介入”")
        self.assertEqual(candidate["glossary_exceptions"], ["skill/extreme"])

        standalone = _row(1, source="「極」")
        standalone["glossary_terms"] = row["glossary_terms"]
        self.assertEqual(shadowed_glossary_term_ids(standalone), set())

    def test_shadowed_term_is_not_also_referenced_when_targets_match(self):
        row = _row(0, source="「アレックス・ディノだ」")
        row["glossary_terms"] = [
            {
                "id": "people/alex-dino-full",
                "source_terms": ["アレックス・ディノ"],
                "translation": "亚历士",
                "enforce": True,
            },
            {
                "id": "people/alex",
                "source_terms": ["アレックス"],
                "translation": "亚历士",
                "enforce": True,
            },
        ]
        candidate = candidate_for_row(row, "“我是亚历士”")
        self.assertEqual(candidate["glossary_refs"], ["people/alex-dino-full"])
        self.assertEqual(candidate["glossary_exceptions"], ["people/alex"])

    def test_normalization_is_mechanical_and_restores_quote_shape(self):
        row = _row(0)
        self.assertEqual(
            normalize_translation(row, "「可恶！\n　只有 一次...」"),
            "“可恶！只有一次……”",
        )
        unquoted = _row(1, shape="unquoted", source="（テスト）")
        self.assertEqual(normalize_translation(unquoted, "（测试）"), "（测试）")

    def test_normalization_removes_dialogue_layout_spaces_and_japanese_variant(self):
        row = _row(0)
        self.assertEqual(
            normalize_translation(
                row,
                "“PLANT 的行动！？\u3000 立即开始破砕作业”",
            ),
            "“PLANT的行动！？立即开始破碎作业”",
        )
        unquoted = _row(1, shape="unquoted", source="オーブ\u3000オノゴロ島")
        self.assertEqual(
            normalize_translation(unquoted, "奥布\u3000奥诺戈罗岛"),
            "奥布\u3000奥诺戈罗岛",
        )

    def test_candidates_keep_stable_identity_and_preserve_punctuation(self):
        row = _row(7, source="「ジュール隊」")
        row["glossary_terms"] = [
            {"id": "group/joule", "translation": "玖尔队", "source_terms": ["ジュール隊"]}
        ]
        candidate = candidate_for_row(row, "“玖尔队”")
        self.assertEqual(candidate["unique_index"], 7)
        self.assertEqual(candidate["glossary_refs"], ["group/joule"])
        punctuation = _row(8, shape="control_or_punctuation", source="？？？")
        preserved = preserved_candidate(punctuation)
        self.assertEqual(preserved["translation_action"], "preserve")
        self.assertEqual(preserved["translation"], "？？？")

    def test_malformed_group_is_bisected_to_valid_singletons(self):
        class FakeClient:
            def translate(self, rows):
                ids = [f'{row["stage_index"]}:{row["unique_index"]}' for row in rows]
                if len(rows) > 1:
                    text = "malformed group"
                else:
                    text = f'<srwz-seg id="{ids[0]}">“测试”</srwz-seg>'
                return APICall(text=text, record={"ids": ids, "response_text": text})

        rows = [_row(0), _row(1)]
        sunk = []
        translator = GroupTranslator(
            FakeClient(), format_attempts=1, record_sink=sunk.append
        )
        candidates, records = translator.translate(rows)
        self.assertEqual(
            [candidate["unique_index"] for candidate in candidates],
            [0, 1],
        )
        self.assertEqual(translator.split_count, 1)
        self.assertEqual(len(records), 3)
        self.assertEqual(len(sunk), 3)
        self.assertIn("format_error", records[0])

    def test_terminal_failure_is_sent_to_raw_record_sink(self):
        class BadClient:
            def translate(self, rows):
                ids = [f'{row["stage_index"]}:{row["unique_index"]}' for row in rows]
                return APICall(
                    text="malformed",
                    record={"ids": ids, "response_text": "malformed"},
                )

        sunk = []
        translator = GroupTranslator(
            BadClient(), format_attempts=1, record_sink=sunk.append
        )
        with self.assertRaises(QwenMTStageError):
            translator.translate([_row(0)])
        self.assertEqual(len(sunk), 1)
        self.assertIn("format_error", sunk[0])


if __name__ == "__main__":
    unittest.main()
