import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "config/encoding/ui-p0-allocations.json"
PROPOSAL_PATH = PROJECT_ROOT / "work/writeback/ui-p0-codebook-proposal.json"
BUILD_REPORT_PATH = PROJECT_ROOT / "work/build/ui-p0/components/font-validation.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-p0-font-validation.json"


class UiP0FontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.proposal = json.loads(PROPOSAL_PATH.read_text(encoding="utf-8"))
        cls.build = json.loads(BUILD_REPORT_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_incremental_registry_preserves_three_slots(self):
        self.assertEqual(
            self.registry["appended_characters"],
            "养减删效昵编节览陆",
        )
        self.assertEqual(
            self.manifest["capacity"]["combined_registered_character_count"],
            647,
        )
        self.assertEqual(
            self.manifest["capacity"]["remaining_candidate_slot_count"],
            3,
        )

    def test_new_allocations_are_append_only_and_contiguous(self):
        assignments = {
            assignment["character"]: assignment
            for assignment in self.proposal["assignments"]
            if assignment["id"].startswith("ui-p0")
            and assignment["status"] == "proposed_allocation"
        }
        self.assertEqual(set(assignments), set("养减删效昵编节览陆"))
        self.assertEqual(
            [assignments[character]["code"] for character in "养减删效昵编节览陆"],
            [f"{code:04X}" for code in range(0x86F1, 0x86FA)],
        )
        self.assertEqual(
            [
                assignments[character]["glyph_index"]
                for character in "养减删效昵编节览陆"
            ],
            list(range(1137, 1146)),
        )

    def test_combined_font_has_no_p0_renderer_or_font_source_gap(self):
        coverage = self.manifest["p0_renderer_coverage"]
        self.assertEqual(coverage["unique_entry_count"], 462)
        self.assertEqual(coverage["missing_renderer_character_count"], 0)
        self.assertEqual(coverage["missing_renderer_occurrence_count"], 0)
        self.assertEqual(coverage["original_font_han_count"], 0)
        self.assertEqual(
            self.manifest["combined_assignments"],
            {
                "allocation_assignment_count": 636,
                "reraster_existing_assignment_count": 816,
                "font_assignment_count": 1452,
            },
        )

    def test_component_is_size_preserving_and_not_runtime_accepted(self):
        self.assertEqual(
            self.build["status"], "offline_font_validated_runtime_not_tested"
        )
        self.assertEqual(
            self.build["archive"]["source_size"],
            self.build["archive"]["output_size"],
        )
        self.assertTrue(self.build["archive"]["offset_reread_exact"])
        self.assertTrue(self.build["font"]["codec_round_trip_exact"])
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")
        self.assertTrue(
            all(
                item["exact"]
                for item in self.manifest["base_first_five_components"].values()
            )
        )


if __name__ == "__main__":
    unittest.main()
