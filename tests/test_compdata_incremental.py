import json
import unittest
from pathlib import Path

from tools.srwz.codec import encode
from tools.srwz.compdata_diagnostics import build_one_sector_shift_control
from tools.srwz.ui_menu import _selected_p0_entries_for_prefix


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT
    / "config/ui-writeback/compdata-step-01a-p0-buttons.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/compdata-incremental-validation.json"
)


class CompdataIncrementalSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_one_scene_can_be_selected_without_changing_inventory(self):
        entries, report = _selected_p0_entries_for_prefix(
            PROJECT_ROOT,
            self.config["scene_inventory"],
            entry_prefix="menu/Compdata/",
            count_key="p0_compdata_entry_count",
        )
        self.assertEqual(
            report["scene_ids"],
            ["intermission/main-and-options"],
        )
        self.assertEqual(report["p0_unique_entry_count"], 121)
        self.assertEqual(report["p0_compdata_entry_count"], 24)
        self.assertEqual(len(entries), 24)
        self.assertTrue(
            all(entry_id.startswith("menu/Compdata/") for entry_id in entries)
        )

    def test_missing_scene_is_rejected(self):
        reference = dict(self.config["scene_inventory"])
        reference["included_scene_ids"] = ["does/not-exist"]
        with self.assertRaisesRegex(ValueError, "included UI scenes are absent"):
            _selected_p0_entries_for_prefix(
                PROJECT_ROOT,
                reference,
                entry_prefix="menu/Compdata/",
                count_key="p0_compdata_entry_count",
            )


class CompdataLbaShiftControlTests(unittest.TestCase):
    def test_control_changes_only_a_minimum_zero_tail(self):
        source = encode(b"same decoded bytes", strategy="literal")
        candidate, facts = build_one_sector_shift_control(
            source,
            sector_size=32,
        )
        self.assertEqual(candidate[: len(source)], source)
        self.assertEqual(
            candidate[len(source) :],
            bytes(facts["zero_tail_size"]),
        )
        self.assertEqual(
            facts["candidate_sectors"],
            facts["source_sectors"] + 1,
        )
        self.assertTrue(facts["compressed_stream_bytes_exact"])
        self.assertTrue(facts["decoded_bytes_exact"])

    def test_control_rejects_a_nonpositive_sector_size(self):
        source = encode(b"x", strategy="literal")
        with self.assertRaisesRegex(ValueError, "sector size"):
            build_one_sector_shift_control(source, sector_size=0)


class CompdataIncrementalManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )

    def test_causal_allocation_finding_is_locked(self):
        self.assertEqual(
            self.manifest["status"],
            "compdata_lba_dependency_causally_validated",
        )
        findings = self.manifest["causal_findings"]
        self.assertEqual(findings["original_allocation_sectors"], 71)
        self.assertEqual(findings["maximum_in_place_size"], 145408)
        self.assertTrue(
            findings["one_sector_shift_is_sufficient_to_fail_boot"]
        )
        self.assertTrue(
            findings["reencoded_compdata_can_boot_when_kept_in_place"]
        )

    def test_control_and_candidate_have_the_expected_runtime_split(self):
        experiments = self.manifest["experiments"]
        self.assertEqual(
            experiments["p0-buttons-inplace"]["boot"]["status"],
            "passed",
        )
        self.assertEqual(
            experiments["p0-buttons-inplace"]["compdata"]["sectors"],
            71,
        )
        for step_id in ("lba-shift-control", "p0-menu"):
            with self.subTest(step_id=step_id):
                self.assertEqual(
                    experiments[step_id]["boot"]["status"],
                    "failed",
                )
                self.assertEqual(
                    experiments[step_id]["compdata"]["sectors"],
                    72,
                )
                self.assertIn(
                    "pc=0x1c6ea0",
                    experiments[step_id]["boot"]["first_tlb_miss"],
                )

    def test_later_semantic_layers_fit_but_remain_runtime_pending(self):
        pending = {
            item["layer"]: item
            for item in self.manifest[
                "maximum_fit_runtime_pending_layers"
            ]
        }
        self.assertNotIn("all-p0-menu", pending)
        self.assertEqual(
            pending["database-fixed-core"]["entry_count"],
            170,
        )
        self.assertEqual(
            pending["database-fixed-core"]["maximum_size"],
            144700,
        )
        self.assertEqual(
            pending["database-fixed-core"]["budget_headroom"],
            708,
        )

    def test_complete_p0_is_promoted_without_lba_shift(self):
        promoted = self.manifest["promoted_result"]
        self.assertEqual(promoted["compdata"]["size"], 145057)
        self.assertEqual(promoted["compdata"]["sectors"], 71)
        self.assertEqual(promoted["compdata"]["budget_headroom"], 351)
        self.assertTrue(
            promoted["layout"]["all_member_lba_unchanged"]
        )
        self.assertEqual(promoted["layout"]["shifted_member_count"], 0)
        self.assertEqual(promoted["boot"]["status"], "passed")
        self.assertEqual(promoted["boot"]["tlb_miss_count"], 0)


if __name__ == "__main__":
    unittest.main()
