import unittest
from unittest.mock import patch

from tools.run_aliyun_general_story_dialogue_stage import (
    build_messages,
    parse_translations,
    parse_args,
    stage_relevant_glossary,
)


def _row(index, source):
    return {
        "stage_index": 10,
        "unique_index": index,
        "source_text": source,
        "source_quote_shape": "dialogue_quoted",
        "structural_tokens": [],
        "glossary_terms": [],
    }


class AliyunGeneralStoryDialogueStageTests(unittest.TestCase):
    def test_targeted_indices_are_repeatable_cli_arguments(self):
        with patch(
            "sys.argv",
            [
                "runner",
                "--stage",
                "13",
                "--model",
                "qwen3.7-plus",
                "--unique-index",
                "68",
                "--unique-index",
                "96",
            ],
        ):
            args = parse_args()
        self.assertEqual(args.unique_index, [68, 96])

    def test_stage_relevant_glossary_keeps_only_matched_pairs(self):
        row = _row(0, "「ジュール隊が来た」")
        row["glossary_terms"] = [
            {
                "id": "group/joule",
                "source_terms": ["ジュール隊"],
                "translation": "玖尔队",
            }
        ]
        self.assertEqual(
            stage_relevant_glossary([row]),
            [{"source": "ジュール隊", "target": "玖尔队"}],
        )

    def test_compact_lines_keep_one_physical_line_per_stable_id(self):
        rows = [_row(0, "「一行目\n　二行目」"), _row(1, "「次」")]
        messages = build_messages(rows, [], [], profile="compact-lines")
        body = messages[1]["content"].split("待翻译分段 TSV：\n", 1)[1]
        lines = body.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith('10:0\t"'))
        self.assertIn("\\n", lines[0])
        self.assertTrue(lines[1].startswith('10:1\t"'))

    def test_output_requires_exact_ids_and_order(self):
        rows = [_row(0, "「甲」"), _row(1, "「乙」")]
        parsed, audit = parse_translations(
            '{"translations":['
            '{"id":"10:0","text":"“甲”"},'
            '{"id":"10:1","text":"“乙”"}]}',
            rows,
        )
        self.assertEqual([text for _, text in parsed], ["“甲”", "“乙”"])
        self.assertTrue(audit["exact_id_order"])

        parsed, audit = parse_translations(
            '{"translations":[{"id":"10:1","text":"“乙”"}]}', rows
        )
        self.assertEqual(parsed, [])
        self.assertFalse(audit["exact_id_order"])
        self.assertEqual(audit["missing_ids"], ["10:0"])


if __name__ == "__main__":
    unittest.main()
