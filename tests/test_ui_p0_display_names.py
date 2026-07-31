import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.codec import decode
from tools.srwz.display_names import parse_display_names
from tools.srwz.text import augment_text_table, load_text_table
from tools.srwz.ui_menu import load_ui_font_overrides


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/ui-writeback/ui-p0-display-names.json"
MANIFEST_PATH = PROJECT_ROOT / "manifests/ui-p0-display-names-validation.json"
COMPONENT_PATH = (
    PROJECT_ROOT / "work/build/ui-p0-display-names/components/DATA/COMPDATA.BN"
)


class UiP0DisplayNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_selection_and_remaining_scope_are_explicit(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["translation_entry_count"], 45)
        self.assertEqual(selection["pilot_translation_entry_count"], 42)
        self.assertEqual(selection["unit_translation_entry_count"], 3)
        self.assertEqual(selection["no_op_entry_count"], 0)
        self.assertEqual(selection["write_entry_count"], 45)
        self.assertEqual(len(selection["entries"]), 45)
        self.assertEqual(
            self.manifest["remaining_work"]["unselected_non_empty_entry_count"],
            2755,
        )
        self.assertTrue(self.manifest["ratchet"]["passed"])
        self.assertEqual(
            self.manifest["ratchet"]["expected"],
            self.config["ratchet"],
        )

    def test_component_round_trip_and_hash(self):
        component = COMPONENT_PATH.read_bytes()
        compressed = self.manifest["compressed_component"]
        self.assertEqual(len(component), compressed["output_size"])
        self.assertEqual(
            hashlib.sha256(component).hexdigest(),
            compressed["output_sha256"],
        )
        decoded = decode(component)
        self.assertEqual(decoded.consumed, len(component))
        self.assertEqual(
            hashlib.sha256(decoded.output).hexdigest(),
            self.manifest["decoded_component"]["output_sha256"],
        )
        self.assertTrue(compressed["decoded_round_trip_exact"])
        self.assertTrue(compressed["flags_preserved"])
        self.assertEqual(compressed["strategy"], "rust-maximum")
        self.assertEqual(compressed["maximum_output_size"], 145408)
        self.assertEqual(compressed["sector_size"], 2048)
        self.assertEqual(compressed["maximum_sectors"], 71)
        self.assertEqual(compressed["sector_count"], 71)
        self.assertTrue(compressed["within_sector_budget"])
        self.assertGreaterEqual(compressed["budget_headroom"], 0)

    def test_pointer_id_and_non_target_bytes_are_preserved(self):
        write = self.manifest["write"]
        self.assertEqual(write["unit_pointer_site_byte_count"], 3232)
        self.assertEqual(write["pilot_id_byte_count"], 1866)
        self.assertTrue(write["pointer_bytes_unchanged"])
        self.assertTrue(write["pilot_ids_unchanged"])
        self.assertTrue(write["non_target_bytes_unchanged"])
        self.assertTrue(write["target_reparse_exact"])

    def test_selected_names_reparse_from_component(self):
        structure_path = PROJECT_ROOT / self.config["structure"]["config"]
        structure = json.loads(structure_path.read_text(encoding="utf-8"))
        font_path = PROJECT_ROOT / self.config["font_candidate"]["manifest"]
        font_manifest = json.loads(font_path.read_text(encoding="utf-8"))
        overrides, _ = load_ui_font_overrides(
            PROJECT_ROOT,
            self.config,
            font_manifest,
        )
        table = load_text_table(PROJECT_ROOT / structure["text_table"]["path"])
        parsed = parse_display_names(
            decode(COMPONENT_PATH.read_bytes()).output,
            augment_text_table(table, overrides),
            structure,
            verify_text_preimages=False,
        )
        actual = {entry.entry_id: entry.text for entry in parsed.entries}
        translation_path = PROJECT_ROOT / self.config["translation_source"]["path"]
        translations = json.loads(translation_path.read_text(encoding="utf-8"))[
            "entries"
        ]
        self.assertEqual(
            {decision["id"]: actual[decision["id"]] for decision in translations},
            {decision["id"]: decision["translation"] for decision in translations},
        )

    def test_runtime_remains_unproven(self):
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")


if __name__ == "__main__":
    unittest.main()
