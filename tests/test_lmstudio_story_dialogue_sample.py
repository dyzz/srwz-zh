import unittest

from tools.run_lmstudio_story_dialogue_sample import (
    _native_response_text,
    _response_text,
    chunk_rows,
    parse_model_batch,
    parse_model_object,
    select_rows,
)
from tools.srwz.translation_review import TranslationReviewError


def _row(index, *, state="needs_machine_draft", shape="dialogue_quoted"):
    return {
        "stage_index": 10,
        "unique_index": index,
        "review_state": state,
        "source_quote_shape": shape,
        "source_text": "「测试」",
    }


class LMStudioStoryDialogueSampleTests(unittest.TestCase):
    def test_selection_skips_locked_and_control_rows(self):
        rows = [
            _row(0, state="locked_reviewed"),
            _row(1, shape="control_or_punctuation"),
            _row(2),
            _row(3),
        ]
        selected = select_rows(rows, stage=10, count=1)
        self.assertEqual([row["unique_index"] for row in selected], [2])

    def test_chunk_rows_preserves_order_and_boundaries(self):
        rows = [_row(index) for index in range(5)]
        chunks = chunk_rows(rows, 2)
        self.assertEqual(
            [[row["unique_index"] for row in chunk] for chunk in chunks],
            [[0, 1], [2, 3], [4]],
        )
        with self.assertRaises(TranslationReviewError):
            chunk_rows(rows, 0)

    def test_batch_parser_requires_only_translation_array(self):
        digest = "a" * 64
        value = parse_model_batch(
            '{"translations":[{"stage_index":10,"unique_index":2,"source_text_sha256":"'
            + digest
            + '","translation":"“甲”","notes":""},{"stage_index":10,"unique_index":3,"source_text_sha256":"'
            + digest
            + '","translation":"“乙”","notes":""}]}'
        )
        self.assertEqual([item["unique_index"] for item in value], [2, 3])
        with self.assertRaises(TranslationReviewError):
            parse_model_batch('{"translations":[],"extra":true}')

    def test_model_json_can_be_fenced_but_not_extended(self):
        value = parse_model_object(
            '```json\n{"stage_index":10,"unique_index":2,"source_text_sha256":"' + "a" * 64 + '","translation":"“测试”"}\n```'
        )
        self.assertEqual(value["translation"], "“测试”")
        with self.assertRaises(TranslationReviewError):
            parse_model_object('{"translation":"x","source_text":"偷带原文"}')

    def test_native_response_uses_message_output_not_reasoning(self):
        response = {
            "output": [
                {"type": "reasoning", "content": "internal"},
                {"type": "message", "content": '{"translation":"译文"}'},
            ]
        }
        self.assertEqual(_native_response_text(response), '{"translation":"译文"}')

    def test_openai_response_can_fall_back_to_reasoning_content(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": '{"translation":"译文"}',
                    }
                }
            ]
        }
        self.assertEqual(_response_text(response), '{"translation":"译文"}')


if __name__ == "__main__":
    unittest.main()
