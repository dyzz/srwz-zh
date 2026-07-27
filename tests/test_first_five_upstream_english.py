import csv
import tempfile
import unittest
from pathlib import Path

from tools.audit_first_five_upstream_english import (
    UpstreamStoryEntry,
    audit_first_five_upstream_english,
    write_reference_tsv,
)
from tools.srwz.translation_review import TranslationRecord


def _source(entry_id, ordinal, text):
    return {
        "id": entry_id,
        "domain": "story",
        "kind": "dialogue",
        "scope_index": 1,
        "section": "Section 1.1",
        "ordinal": ordinal,
        "source_text": text,
    }


def _translation(source, translation):
    return TranslationRecord(
        entry_id=source["id"],
        source_text_sha256=str(source["ordinal"] + 1) * 64,
        translation=translation,
        editorial_status="reviewed",
        translation_action="translate",
        glossary_refs=(),
        glossary_exceptions=(),
        notes="",
        batch_id="v1-story-dialogue",
        source_path="stage-001.json",
    )


def _upstream(stage, ordinal, japanese, english):
    return UpstreamStoryEntry(
        stage_index=stage,
        kind="dialogue",
        section="Section 1.1",
        ordinal=ordinal,
        japanese=japanese,
        english=english,
        status="Translated" if english else "To Do",
        notes="",
    )


class FirstFiveUpstreamEnglishTests(unittest.TestCase):
    def test_direct_fallback_and_unreferenced_rows_are_separate(self):
        sources = (
            _source("story/001/dialogue/01.01/0000", 0, "直接"),
            _source("story/001/dialogue/01.01/0001", 1, "复用"),
            _source("story/001/dialogue/01.01/0002", 2, "无参考"),
        )
        translations = tuple(
            _translation(source, f"译文{index}")
            for index, source in enumerate(sources)
        )
        upstream = (
            _upstream(1, 0, "直接", "Direct reference"),
            _upstream(1, 1, "复用", ""),
            _upstream(1, 2, "无参考", ""),
            _upstream(13, 0, "复用", "Fallback one"),
            _upstream(14, 0, "复用", "Fallback two"),
        )
        report, rows = audit_first_five_upstream_english(
            sources,
            translations,
            upstream,
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["reference_coverage"], "limited")
        self.assertEqual(report["entry_count"], 3)
        self.assertEqual(report["direct_alignment_issue_count"], 0)
        self.assertEqual(report["direct_upstream_english_entry_count"], 1)
        self.assertEqual(report["exact_source_fallback_entry_count"], 1)
        self.assertEqual(report["reference_entry_count"], 2)
        self.assertEqual(report["reference_unique_source_count"], 2)
        self.assertEqual(report["no_reference_entry_count"], 1)
        self.assertEqual(
            {row["reference_kind"] for row in rows},
            {
                "direct_upstream_english",
                "exact_japanese_elsewhere",
            },
        )
        fallback = next(
            row
            for row in rows
            if row["reference_kind"] == "exact_japanese_elsewhere"
        )
        self.assertEqual(fallback["upstream_english_variant_count"], 2)
        self.assertIn("不能自动覆盖中文", fallback["review_caution"])

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "reference.tsv"
            write_reference_tsv(output, rows)
            with output.open(encoding="utf-8", newline="") as stream:
                written = list(csv.DictReader(stream, delimiter="\t"))
            self.assertEqual(len(written), 2)
            self.assertEqual(
                written[1]["fallback_reference_count"],
                "2",
            )

    def test_direct_japanese_mismatch_fails_alignment(self):
        source = _source(
            "story/001/dialogue/01.01/0000",
            0,
            "固定日文",
        )
        report, rows = audit_first_five_upstream_english(
            (source,),
            (_translation(source, "中文"),),
            (_upstream(1, 0, "漂移日文", "English"),),
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["direct_alignment_issue_count"], 1)
        self.assertEqual(report["reference_entry_count"], 0)
        self.assertEqual(rows, ())


if __name__ == "__main__":
    unittest.main()
