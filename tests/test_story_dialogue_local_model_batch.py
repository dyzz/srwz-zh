import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.export_story_dialogue_local_model_batch import build_batch_documents
from tools.import_story_dialogue_local_model_batch import (
    build_stage_drafts,
    load_queue,
    validate_model_output,
)
from tools.srwz.translation_review import TranslationReviewError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE = PROJECT_ROOT / "corpus" / "releases" / "v1.json"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _queue_row(
    *,
    stage: int,
    unique: int,
    source: str,
    review_state: str = "needs_machine_draft",
    existing=None,
) -> dict:
    return {
        "schema_version": 1,
        "stage_index": stage,
        "unique_index": unique,
        "source_text": source,
        "source_text_sha256": _hash(source),
        "occurrence_count": 1,
        "occurrence_ids": [f"story/{stage:03d}/dialogue/01.01/{unique:04d}"],
        "sections": ["Section 1.1"],
        "speaker_ids": [1],
        "pointer_offsets": [100 + unique],
        "source_quote_shape": "dialogue_quoted"
        if source.startswith("「")
        else "unquoted",
        "source_newline_count": source.count("\n"),
        "structural_tokens": [],
        "must_preserve": [],
        "review_state": review_state,
        "existing_translations": existing or [],
        "existing_translation": existing[0]["translation"] if existing else "",
        "existing_editorial_status": existing[0]["editorial_status"] if existing else "",
        "glossary_terms": [],
        "model_output": "",
    }


class StoryDialogueLocalModelBatchTests(unittest.TestCase):
    def test_stage_export_has_stable_deduped_queue_and_context(self):
        unique, records, metadata, extra = build_batch_documents(
            RELEASE,
            stage_filter={10},
        )
        self.assertEqual(len(records), 631)
        self.assertEqual(len(unique), 571)
        self.assertEqual(metadata["counts"]["stage_count"], 1)
        self.assertEqual(metadata["counts"]["needs_machine_draft_unique_count"], 571)
        self.assertEqual(len(extra["raw_terms"]), 1739)
        self.assertEqual(unique[0]["stage_index"], 10)
        self.assertEqual(unique[0]["unique_index"], 0)
        self.assertEqual(
            unique[0]["source_text_sha256"],
            _hash(unique[0]["source_text"]),
        )
        self.assertIn("model_output", unique[0])
        self.assertIn("must_preserve", unique[0])

    def test_queue_loader_rejects_stale_source_hash(self):
        row = _queue_row(stage=10, unique=0, source="「测试」")
        row["source_text_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.jsonl"
            path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            with self.assertRaises(TranslationReviewError):
                load_queue(path)

    def test_valid_model_output_preserves_quote_shape_and_builds_draft(self):
        queue = [_queue_row(stage=10, unique=0, source="「测试」")]
        model = [
            {
                "stage_index": 10,
                "unique_index": 0,
                "source_text_sha256": queue[0]["source_text_sha256"],
                "translation": "“测试”",
                "notes": "需人工确认语气",
            }
        ]
        validated, by_key, missing = validate_model_output(queue, model)
        self.assertEqual(missing, [])
        self.assertEqual(validated[0]["decision_source"], "local_model_draft")
        self.assertEqual(validated[0]["translation"], "“测试”")
        with tempfile.TemporaryDirectory() as directory:
            paths = build_stage_drafts(
                queue,
                {
                    (10, 0): validated[0],
                },
                Path(directory),
                force=False,
            )
            self.assertEqual(len(paths), 1)
            draft = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertEqual(draft["stage_index"], 10)
            self.assertEqual(draft["translations"], ["“测试”"])
            self.assertEqual(draft["editorial_status_by_index"], {"0": "draft"})

    def test_model_output_rejects_kana_and_structural_token_drift(self):
        queue = [_queue_row(stage=10, unique=0, source="「测试」")]
        bad_kana = [
            {
                "stage_index": 10,
                "unique_index": 0,
                "source_text_sha256": queue[0]["source_text_sha256"],
                "translation": "“テスト”",
            }
        ]
        with self.assertRaisesRegex(TranslationReviewError, "假名"):
            validate_model_output(queue, bad_kana)

        token_source = _queue_row(stage=10, unique=0, source="●　「测试」")
        bad_token = [
            {
                "stage_index": 10,
                "unique_index": 0,
                "source_text_sha256": token_source["source_text_sha256"],
                "translation": "“测试”",
            }
        ]
        # The source contains a runtime concealment marker which must not be dropped.
        with self.assertRaisesRegex(TranslationReviewError, "结构"):
            validate_model_output([token_source], bad_token)

    def test_model_output_rejects_json_or_markdown_response_residue(self):
        queue = [_queue_row(stage=10, unique=0, source="「测试」")]
        for translation in (
            "“测试}]}```json{”",
            "“测试}]}{”",
        ):
            model = [
                {
                    "stage_index": 10,
                    "unique_index": 0,
                    "source_text_sha256": queue[0]["source_text_sha256"],
                    "translation": translation,
                }
            ]
            with self.assertRaisesRegex(TranslationReviewError, "JSON/Markdown"):
                validate_model_output(queue, model)

    def test_partial_batch_reports_missing_without_faking_completion(self):
        queue = [
            _queue_row(stage=10, unique=0, source="「一」"),
            _queue_row(stage=10, unique=1, source="「二」"),
        ]
        model = [
            {
                "stage_index": 10,
                "unique_index": 0,
                "source_text_sha256": queue[0]["source_text_sha256"],
                "translation": "“一”",
            }
        ]
        validated, by_key, missing = validate_model_output(
            queue,
            model,
            allow_partial=True,
        )
        self.assertEqual(len(validated), 1)
        self.assertEqual(len(by_key), 1)
        self.assertEqual(missing, [{"stage_index": 10, "unique_index": 1, "reason": "missing_model_output"}])
        with tempfile.TemporaryDirectory() as directory:
            drafts = build_stage_drafts(queue, {key: validated[0] for key in [(10, 0)]}, Path(directory), force=False)
            self.assertEqual(drafts, [])

    def test_locked_reviewed_context_keeps_refs_exceptions_and_notes(self):
        existing = [
            {
                "translation": "“泰坦斯”",
                "editorial_status": "reviewed",
                "translation_action": "translate",
                "glossary_refs": ["organization/titans"],
                "glossary_exceptions": ["system/turn"],
                "notes": ["片假名子串误命中"],
            }
        ]
        queue = [
            _queue_row(
                stage=1,
                unique=0,
                source="「泰坦斯」",
                review_state="locked_reviewed",
                existing=existing,
            )
        ]
        validated, by_key, missing = validate_model_output(queue, [])
        self.assertEqual(missing, [])
        self.assertEqual(validated[0]["glossary_refs"], ["organization/titans"])
        self.assertEqual(validated[0]["glossary_exceptions"], ["system/turn"])
        self.assertEqual(validated[0]["notes"], "片假名子串误命中")


if __name__ == "__main__":
    unittest.main()
