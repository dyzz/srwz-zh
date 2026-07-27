import json
import unittest
from pathlib import Path

from tools.audit_first_five_language_quality import (
    audit_first_five_language_quality,
)
from tools.srwz.translation_review import (
    TranslationRecord,
    load_source_corpus,
    load_translations,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_PATH = PROJECT_ROOT / "corpus/releases/v1.json"


class FirstFiveLanguageQualityTests(unittest.TestCase):
    def test_current_first_five_language_quality_gate_passes(self):
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
        source_path = (
            PROJECT_ROOT / release["source_corpus"]["path"]
        ).resolve()
        translation_paths = [
            (PROJECT_ROOT / raw).resolve()
            for raw in release["translation_sources"]
        ]
        report, findings = audit_first_five_language_quality(
            load_source_corpus(source_path),
            load_translations(translation_paths),
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["entry_count"], 1711)
        self.assertEqual(report["unique_source_text_count"], 1359)
        self.assertEqual(
            report["stage_entry_counts"],
            {"1": 312, "2": 542, "3": 36, "4": 523, "5": 298},
        )
        self.assertEqual(report["hard_issue_count"], 0)
        self.assertLessEqual(
            report["maximum_render_line_characters"],
            report["render_line_character_limit"],
        )
        self.assertLessEqual(
            report["maximum_render_line_count"],
            report["render_line_count_limit"],
        )
        self.assertEqual(
            report["same_source_translation_variant_source_count"],
            4,
        )
        self.assertEqual(
            report["reviewed_contextual_variant_record_count"],
            14,
        )
        self.assertEqual(
            {finding["severity"] for finding in findings},
            {"reviewed"},
        )

    def test_gate_rejects_overlong_and_unannotated_source_drift(self):
        source_hash = "a" * 64
        sources = (
            {
                "id": "story/001/dialogue/01.01/0000",
                "domain": "story",
                "kind": "dialogue",
                "scope_index": 1,
                "section": "Section 1.1",
                "source_text": "「え…？」",
            },
            {
                "id": "story/002/dialogue/01.01/0000",
                "domain": "story",
                "kind": "dialogue",
                "scope_index": 2,
                "section": "Section 1.1",
                "source_text": "「え…？」",
            },
        )
        records = (
            TranslationRecord(
                entry_id=sources[0]["id"],
                source_text_sha256=source_hash,
                translation=f"“{'很' * 27}？”",
                editorial_status="reviewed",
                translation_action="translate",
                glossary_refs=(),
                glossary_exceptions=(),
                notes="",
                batch_id="v1-story-dialogue",
                source_path="stage-001.json",
            ),
            TranslationRecord(
                entry_id=sources[1]["id"],
                source_text_sha256=source_hash,
                translation="“咦……？”",
                editorial_status="reviewed",
                translation_action="translate",
                glossary_refs=(),
                glossary_exceptions=(),
                notes="",
                batch_id="v1-story-dialogue",
                source_path="stage-002.json",
            ),
        )
        report, findings = audit_first_five_language_quality(
            sources,
            records,
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["hard_issue_count"], 3)
        self.assertEqual(
            {
                finding["finding_type"]
                for finding in findings
                if finding["severity"] == "error"
            },
            {
                "line_too_long",
                "contextual_same_source_variant",
            },
        )


if __name__ == "__main__":
    unittest.main()
