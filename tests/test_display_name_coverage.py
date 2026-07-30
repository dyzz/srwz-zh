import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.srwz.display_name_coverage import (
    DisplayNameCoverageError,
    audit_display_name_coverage,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT / "config/display-names/researched-coverage.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/display-name-researched-coverage.json"
)
REVIEW_PATH = (
    PROJECT_ROOT / "work/review/display-name-researched-coverage.json"
)
TSV_PATH = (
    PROJECT_ROOT / "work/review/display-name-researched-coverage.tsv"
)


class DisplayNameCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.expected_manifest = audit_display_name_coverage(
            PROJECT_ROOT,
            CONFIG_PATH,
        )
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))

    def test_committed_manifest_is_reproducible(self):
        self.assertEqual(self.manifest, self.expected_manifest)
        self.assertEqual(self.review, self.report)

    def test_researched_exact_selection_has_no_conflict_or_overflow(self):
        summary = self.manifest["summary"]
        self.assertEqual(summary["selected_entry_count"], 1262)
        self.assertEqual(summary["selected_pilot_entry_count"], 1221)
        self.assertEqual(summary["selected_unit_entry_count"], 41)
        self.assertEqual(summary["selected_unique_source_count"], 307)
        self.assertEqual(
            self.manifest["inputs"]["glossary"]["conflict_source_count"],
            0,
        )
        self.assertEqual(summary["projected_overflow_entry_count"], 0)
        self.assertTrue(
            self.manifest["acceptance"][
                "projected_fixed_allocation_overflow_count_zero"
            ]
        )

    def test_font_gap_is_bounded_to_twenty_one_characters(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["font_ready_entry_count"], 1166)
        self.assertEqual(selection["font_missing_entry_count"], 96)
        self.assertEqual(selection["missing_character_count"], 21)
        self.assertEqual(
            selection["missing_characters"],
            "伦侣凤凯妮姬娅岛庆户滨琪苏萝谦贾赛赞钢钱阳",
        )

    def test_renderer_gap_fits_remaining_candidate_slots(self):
        renderer = self.manifest["renderer_readiness"]
        self.assertEqual(renderer["ready_entry_count"], 1134)
        self.assertEqual(renderer["missing_entry_count"], 128)
        self.assertEqual(renderer["missing_character_count"], 28)
        self.assertEqual(
            renderer["missing_characters"],
            "伦佛侣凤凯勒妮姬娅岛庆惠户杰滨琪艾苏莎菲萝谦贾赛赞钢钱阳",
        )
        self.assertEqual(
            renderer["original_font_han_character_count"],
            29,
        )
        self.assertEqual(
            renderer["reactivatable_registered_character_count"],
            4,
        )
        self.assertEqual(
            renderer["reactivatable_registered_characters"],
            "娅杰艾贾",
        )
        self.assertEqual(renderer["new_allocation_character_count"], 24)
        self.assertEqual(
            renderer["projected_remaining_candidate_slot_count"],
            24,
        )
        self.assertTrue(
            self.manifest["acceptance"][
                "renderer_allocation_fits_available_slots"
            ]
        )

    def test_source_text_stays_only_in_ignored_review_outputs(self):
        def visit(value):
            if isinstance(value, dict):
                self.assertNotIn("source_text", value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(self.manifest)
        sample = next(
            entry
            for entry in self.report["selection"]["entries"]
            if entry["id"] == "display-name/pilot/0001/display"
        )
        self.assertEqual(sample["translation"], "甲儿")
        self.assertEqual(
            sample["source_refs"],
            ["people/speaker-52bd0a2936b4"],
        )

    def test_tsv_is_one_row_per_non_empty_display_name_field(self):
        with TSV_PATH.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(len(rows), 2800)
        counts = {}
        for row in rows:
            counts[row["disposition"]] = (
                counts.get(row["disposition"], 0) + 1
            )
        self.assertEqual(
            counts,
            {
                "prior_translation": 45,
                "selected_researched_exact": 1262,
                "unresolved": 1493,
            },
        )

    def test_ratchet_mutation_fails_closed(self):
        document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        document["ratchet"]["selected_entry_count"] += 1
        work_root = PROJECT_ROOT / "work"
        with tempfile.TemporaryDirectory(dir=work_root) as directory:
            path = Path(directory) / "mutated.json"
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                DisplayNameCoverageError,
                "ratchet drift",
            ):
                audit_display_name_coverage(PROJECT_ROOT, path)


if __name__ == "__main__":
    unittest.main()
