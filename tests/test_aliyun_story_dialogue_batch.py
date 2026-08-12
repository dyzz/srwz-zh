import copy
import json
import unittest

from tools import run_aliyun_story_dialogue_batch as batch
from tools.srwz.library import LibraryScopeError


class AliyunStoryDialogueBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        source = "「今後は、あの部隊と協力するのか？」"
        self.row = {
            "surface": "story_dialogue",
            "id": "story/154/dialogue/00.01/0003",
            "source_text_sha256": batch.sha256_text(source),
            "source_text": source,
            "stage_index": 154,
            "section": "Section 0.1",
            "speaker": {
                "ja": "カミーユ",
                "zh": "卡缪",
                "identity": "卡缪·维丹",
                "work": "《机动战士Z高达》",
            },
            "context_before": [
                {
                    "id": "story/154/dialogue/00.01/0002",
                    "speaker": {
                        "ja": "ブライト",
                        "zh": "布莱德",
                        "identity": "布莱德·诺亚",
                        "work": "《机动战士Z高达》",
                    },
                    "jp": "「そうだ」",
                }
            ],
            "context_after": [],
            "required_terms": [],
        }

    def test_locked_model_and_prompt_include_speaker_work_and_context(self):
        self.assertEqual(batch.DEFAULT_MODEL, "deepseek-v4-flash-0731")
        batch.validate_queue([self.row])
        messages = batch.build_messages([self.row])
        prompt = messages[1]["content"]
        self.assertIn("卡缪·维丹", prompt)
        self.assertIn("《机动战士Z高达》", prompt)
        self.assertIn("ブライト", prompt)

    def test_queue_fails_closed_without_identity_work_or_context(self):
        for field in ("identity", "work"):
            row = copy.deepcopy(self.row)
            row["speaker"][field] = ""
            with self.assertRaises(LibraryScopeError):
                batch.validate_queue([row])
        row = copy.deepcopy(self.row)
        row["context_before"] = []
        with self.assertRaisesRegex(LibraryScopeError, "no adjacent context"):
            batch.validate_queue([row])

    def test_response_requires_exact_fields_and_preserves_variables(self):
        row = copy.deepcopy(self.row)
        row["source_text"] = "「$nも行くのか？」"
        row["source_text_sha256"] = batch.sha256_text(row["source_text"])
        item = {
            "id": row["id"],
            "text": "“$n也要去吗？”",
            "confidence": "high",
            "semantic_roles": ["speaker", "addressee"],
            "ambiguous": False,
            "referent": "卡缪询问玩家主人公",
        }
        response = json.dumps({"translations": [item]}, ensure_ascii=False)
        parsed, audit = batch.parse_response(response, [row])
        self.assertTrue(audit["exact_id_order"])
        self.assertEqual(batch.validate_translation(row, parsed[0])["translation"], item["text"])

        changed = copy.deepcopy(item)
        changed["text"] = "“他也要去吗？”"
        with self.assertRaisesRegex(LibraryScopeError, "variable set changed"):
            batch.validate_translation(row, changed)


if __name__ == "__main__":
    unittest.main()
