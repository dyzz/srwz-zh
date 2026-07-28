import json
import unittest
from collections import Counter
from pathlib import Path

from tools.srwz.font import standard_glyph_index


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    PROJECT_ROOT / "config/encoding/ui-p1-summary-allocations.json"
)
P0_PROPOSAL_PATH = PROJECT_ROOT / "work/writeback/ui-p0-codebook-proposal.json"
PROPOSAL_PATH = (
    PROJECT_ROOT / "work/writeback/ui-p1-summary-codebook-proposal.json"
)
BUILD_REPORT_PATH = (
    PROJECT_ROOT / "work/build/ui-p1-summary/components/font-validation.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-p1-summary-font-validation.json"
)


class UiP1SummaryFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.p0_proposal = json.loads(
            P0_PROPOSAL_PATH.read_text(encoding="utf-8")
        )
        cls.proposal = json.loads(PROPOSAL_PATH.read_text(encoding="utf-8"))
        cls.build = json.loads(BUILD_REPORT_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_registry_extends_p0_without_reassigning_it(self):
        self.assertEqual(
            self.registry["base_registry"]["registered_character_count"],
            647,
        )
        self.assertEqual(len(self.registry["appended_characters"]), 41)
        inherited = [
            assignment
            for assignment in self.proposal["assignments"]
            if not assignment["id"].startswith("ui-p1-summary-")
        ]
        self.assertEqual(inherited, self.p0_proposal["assignments"])

    def test_capacity_distinguishes_safe_and_raw_addressable_slots(self):
        capacity = self.manifest["capacity"]
        self.assertEqual(capacity["valid_sjis_safe_candidate_slot_count"], 650)
        self.assertEqual(
            capacity["raw_standard_addressable_candidate_slot_count"],
            86,
        )
        self.assertEqual(
            capacity["combined_renderer_addressable_candidate_slot_count"],
            736,
        )
        self.assertEqual(capacity["combined_registered_character_count"], 688)
        self.assertEqual(capacity["remaining_candidate_slot_count"], 48)

    def test_new_allocations_use_three_safe_then_thirty_eight_raw_slots(self):
        assignments = [
            assignment
            for assignment in self.proposal["assignments"]
            if assignment["id"].startswith("ui-p1-summary-")
            and assignment["status"] == "proposed_allocation"
        ]
        self.assertEqual(len(assignments), 41)
        self.assertEqual(
            Counter(assignment["mapping"] for assignment in assignments),
            Counter({"standard": 3, "standard_raw_trail_gap": 38}),
        )
        self.assertTrue(
            all(
                assignment["allocation"]["glyph_preimage_all_zero"]
                for assignment in assignments
            )
        )
        self.assertEqual(
            self.manifest["additional_allocations"]["blank_preimage_count"],
            41,
        )
        self.assertEqual(
            self.manifest["additional_allocations"][
                "raw_standard_trail_gap_count"
            ],
            38,
        )
        raw = [
            assignment
            for assignment in assignments
            if assignment["mapping"] == "standard_raw_trail_gap"
        ]
        self.assertEqual(
            {int(assignment["code"], 16) & 0xFF for assignment in raw},
            {0x7F, 0xFD},
        )
        self.assertTrue(
            all(
                standard_glyph_index(int(assignment["code"], 16))
                == assignment["glyph_index"]
                for assignment in raw
            )
        )

    def test_component_covers_p0_and_world_history_but_is_runtime_pending(self):
        coverage = self.manifest["selected_renderer_coverage"]
        self.assertEqual(coverage["unique_entry_count"], 490)
        self.assertEqual(coverage["missing_renderer_character_count"], 0)
        self.assertEqual(coverage["missing_renderer_occurrence_count"], 0)
        self.assertEqual(coverage["original_font_han_count"], 0)
        self.assertEqual(
            self.build["status"],
            "offline_font_validated_runtime_not_tested",
        )
        self.assertEqual(
            self.build["archive"]["source_size"],
            self.build["archive"]["output_size"],
        )
        self.assertTrue(self.build["font"]["codec_round_trip_exact"])
        self.assertTrue(self.build["archive"]["offset_reread_exact"])
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")

    def test_raw_policy_locks_static_windows_and_only_claims_one_precedent(self):
        policy = self.manifest["allocation_policy"]
        self.assertEqual(policy["raw_standard_trails"], ["7F", "FD", "FE", "FF"])
        self.assertEqual(len(policy["instruction_windows"]), 2)
        self.assertEqual(
            policy["runtime_precedent"],
            {
                "character": "试",
                "code": "987F",
                "glyph_index": 4479,
                "static_manifest": "manifests/static-canary-validation.json",
                "static_sha256": (
                    "c264e515d09e8d360628d3b7e3c3d58e2ccea2833e632b24011f5c5550d921cc"
                ),
                "runtime_manifest": "manifests/canary-iso-validation.json",
                "runtime_sha256": (
                    "fd391150af647538576c770c78bee3092dc0d1b3673868cb23714099f5f5146a"
                ),
                "runtime_bytes_exact": True,
                "characters_visible": True,
            },
        )
        self.assertIn("Runtime evidence exists for 0x7F only", policy["classification"])


if __name__ == "__main__":
    unittest.main()
