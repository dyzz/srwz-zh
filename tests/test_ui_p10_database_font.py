import json
import unittest
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    PROJECT_ROOT
    / "config/encoding/ui-p10-database-font-allocations.json"
)
BASE_PROPOSAL_PATH = (
    PROJECT_ROOT / "work/writeback/ui-p7-embedded-codebook-proposal.json"
)
PROPOSAL_PATH = (
    PROJECT_ROOT / "work/writeback/ui-p10-database-codebook-proposal.json"
)
BUILD_REPORT_PATH = (
    PROJECT_ROOT
    / "work/build/ui-p10-database-font/components/font-validation.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-p10-database-font-validation.json"
)


class UiP10DatabaseFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(
            REGISTRY_PATH.read_text(encoding="utf-8")
        )
        cls.base_proposal = json.loads(
            BASE_PROPOSAL_PATH.read_text(encoding="utf-8")
        )
        cls.proposal = json.loads(
            PROPOSAL_PATH.read_text(encoding="utf-8")
        )
        cls.build = json.loads(
            BUILD_REPORT_PATH.read_text(encoding="utf-8")
        )
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_final_twelve_slots_are_consumed_exactly(self):
        self.assertEqual(
            self.registry["base_registry"]["registered_character_count"],
            724,
        )
        self.assertEqual(
            self.registry["appended_characters"],
            "咫垫挡斩框歼药赋赖镜闪－",
        )
        capacity = self.manifest["capacity"]
        self.assertEqual(capacity["combined_registered_character_count"], 736)
        self.assertEqual(capacity["remaining_candidate_slot_count"], 0)

    def test_increment_reuses_bond_code_after_allocations_and_rerasters(self):
        added = [
            assignment
            for assignment in self.proposal["assignments"]
            if assignment["id"].startswith("ui-p10-database-")
        ]
        self.assertEqual(
            Counter(assignment["status"] for assignment in added),
            Counter(
                {
                    "proposed_allocation": 12,
                    "proposed_reraster": 14,
                    "proposed_semantic_reraster": 1,
                }
            ),
        )
        bond = next(
            assignment
            for assignment in added
            if assignment["character"] == "绊"
        )
        self.assertEqual(
            {
                "code": bond["code"],
                "glyph_index": bond["glyph_index"],
                "mapping": bond["mapping"],
                "status": bond["status"],
                "source_character": bond["source_character"],
            },
            {
                "code": "E34A",
                "glyph_index": 910,
                "mapping": "pinned_text_table_semantic_replacement",
                "status": "proposed_semantic_reraster",
                "source_character": "絆",
            },
        )
        inherited = [
            assignment
            for assignment in self.proposal["assignments"]
            if not assignment["id"].startswith("ui-p10-database-")
        ]
        self.assertEqual(inherited, self.base_proposal["assignments"])

    def test_database_renderer_coverage_is_complete_runtime_pending(self):
        coverage = self.manifest[
            "database_fixed_core_renderer_coverage"
        ]
        self.assertEqual(coverage["unique_entry_count"], 403)
        self.assertEqual(coverage["missing_renderer_character_count"], 0)
        self.assertEqual(coverage["original_font_han_count"], 0)
        self.assertEqual(
            self.build["status"],
            "offline_font_validated_runtime_not_tested",
        )
        self.assertTrue(self.build["font"]["codec_round_trip_exact"])
        self.assertTrue(self.build["archive"]["offset_reread_exact"])
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertEqual(
            self.manifest["semantic_code_replacements"]["count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
