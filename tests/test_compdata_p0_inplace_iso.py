import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MANIFEST = (
    PROJECT_ROOT
    / "manifests/compdata-step-02-p0-menu-inplace-runtime-validation.json"
)
ISO_REPORT = (
    PROJECT_ROOT
    / "build/iso/compdata-step-02-p0-menu-inplace/iso-validation.json"
)


class CompdataP0InplaceIsoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = json.loads(
            RUNTIME_MANIFEST.read_text(encoding="utf-8")
        )
        cls.iso_report = json.loads(
            ISO_REPORT.read_text(encoding="utf-8")
        )

    def test_every_iso_member_keeps_its_original_lba(self):
        layout = self.iso_report["layout"]
        self.assertEqual(layout["shifted_member_count"], 0)
        self.assertEqual(layout["shift_sectors"], 0)
        self.assertEqual(
            layout["lba_prefix_preserved_through"],
            "DMY/DMY.BIN",
        )
        self.assertTrue(
            self.runtime["iso_build"][
                "nisvdata_and_later_lba_unchanged"
            ]
        )

    def test_runtime_receipt_is_bound_to_the_exact_iso(self):
        runtime = self.runtime["runtime"]
        output = self.runtime["iso_build"]["output"]
        self.assertEqual(
            output["sha256"],
            "4ddaa69512d5118c549016b0cea28d720f7039dfdd7da571d4f1bff21fd30c3e",
        )
        self.assertEqual(runtime["status"], "boot_smoke_passed_visual_not_tested")
        self.assertTrue(runtime["pine_connected"])
        self.assertEqual(runtime["pine_status"], 0)
        self.assertEqual(runtime["tlb_miss_count"], 0)
        self.assertIsNone(runtime["first_tlb_miss"])

    def test_visual_boundary_remains_explicit(self):
        acceptance = self.runtime["acceptance"]
        self.assertTrue(acceptance["complete_p0_component"])
        self.assertTrue(acceptance["within_71_sector_budget"])
        self.assertTrue(acceptance["later_lba_unchanged"])
        self.assertTrue(acceptance["pcsx2_pine_boot_passed"])
        self.assertFalse(acceptance["intermission_visual_passed"])
        self.assertEqual(
            self.runtime["runtime"]["navigation_status"],
            "not_tested",
        )


if __name__ == "__main__":
    unittest.main()
