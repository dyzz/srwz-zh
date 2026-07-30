import json
import unittest
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    PROJECT_ROOT / "config/encoding/ui-p7-embedded-font-allocations.json"
)
BASE_PROPOSAL_PATH = (
    PROJECT_ROOT
    / "work/writeback/ui-p2-display-name-codebook-proposal.json"
)
PROPOSAL_PATH = (
    PROJECT_ROOT
    / "work/writeback/ui-p7-embedded-codebook-proposal.json"
)
BUILD_REPORT_PATH = (
    PROJECT_ROOT
    / "work/build/ui-p7-embedded-font/components/font-validation.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-p7-embedded-font-validation.json"
)


class UiP7EmbeddedFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
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

    def test_registry_appends_seven_and_leaves_twelve_slots(self):
        self.assertEqual(
            self.registry["base_registry"]["registered_character_count"],
            717,
        )
        self.assertEqual(
            self.registry["appended_characters"],
            "忆显缓网锋页额",
        )
        capacity = self.manifest["capacity"]
        self.assertEqual(capacity["combined_registered_character_count"], 724)
        self.assertEqual(capacity["remaining_candidate_slot_count"], 12)

    def test_inherited_p2_assignments_are_not_reassigned(self):
        inherited = [
            assignment
            for assignment in self.proposal["assignments"]
            if not assignment["id"].startswith("ui-p7-embedded-")
        ]
        self.assertEqual(inherited, self.base_proposal["assignments"])

    def test_increment_has_seven_allocations_and_four_rerasters(self):
        added = [
            assignment
            for assignment in self.proposal["assignments"]
            if assignment["id"].startswith("ui-p7-embedded-")
        ]
        self.assertEqual(
            Counter(assignment["status"] for assignment in added),
            Counter(
                {
                    "proposed_allocation": 7,
                    "proposed_reraster": 4,
                }
            ),
        )
        self.assertEqual(
            {
                assignment["character"]
                for assignment in added
                if assignment["status"] == "proposed_allocation"
            },
            set("忆显缓网锋页额"),
        )
        self.assertEqual(
            {
                assignment["character"]
                for assignment in added
                if assignment["status"] == "proposed_reraster"
            },
            set("振滑画符"),
        )

    def test_renderer_coverage_is_complete_but_runtime_is_pending(self):
        coverage = self.manifest["embedded_ui_renderer_coverage"]
        self.assertEqual(coverage["unique_entry_count"], 93)
        self.assertEqual(coverage["missing_renderer_character_count"], 0)
        self.assertEqual(coverage["original_font_han_count"], 0)
        self.assertEqual(
            self.build["status"],
            "offline_font_validated_runtime_not_tested",
        )
        self.assertTrue(self.build["font"]["codec_round_trip_exact"])
        self.assertTrue(self.build["archive"]["offset_reread_exact"])
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")


if __name__ == "__main__":
    unittest.main()
