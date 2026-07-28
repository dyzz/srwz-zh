import hashlib
import json
import unittest
from pathlib import Path

from tools.srwz.codec import decode
from tools.srwz.display_name_coverage import audit_display_name_coverage
from tools.srwz.display_names import (
    build_display_name_component,
    parse_display_names,
)
from tools.srwz.text import augment_text_table, load_text_table
from tools.srwz.ui_menu import load_ui_font_overrides


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    PROJECT_ROOT / "config/ui-writeback/ui-p2-display-names.json"
)
COVERAGE_CONFIG_PATH = (
    PROJECT_ROOT / "config/display-names/researched-coverage.json"
)
MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/ui-p2-display-names-validation.json"
)
COMPONENT_PATH = (
    PROJECT_ROOT
    / "work/build/ui-p2-display-names/components/DATA/COMPDATA.BN"
)


class UiP2DisplayNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.component = COMPONENT_PATH.read_bytes()

    def test_component_and_manifest_rebuild_exactly(self):
        component, manifest = build_display_name_component(
            PROJECT_ROOT,
            CONFIG_PATH,
        )
        self.assertEqual(component, self.component)
        self.assertEqual(manifest, self.manifest)

    def test_selection_and_remaining_scope_are_exact(self):
        selection = self.manifest["selection"]
        self.assertEqual(selection["translation_entry_count"], 1307)
        self.assertEqual(selection["pilot_translation_entry_count"], 1263)
        self.assertEqual(selection["unit_translation_entry_count"], 44)
        self.assertEqual(selection["no_op_entry_count"], 94)
        self.assertEqual(selection["write_entry_count"], 1213)
        self.assertEqual(selection["pointer_write_count"], 0)
        self.assertEqual(
            self.manifest["remaining_work"][
                "unselected_non_empty_entry_count"
            ],
            1493,
        )
        self.assertTrue(self.manifest["ratchet"]["passed"])

    def test_component_round_trip_and_non_target_contract(self):
        compressed = self.manifest["compressed_component"]
        self.assertEqual(len(self.component), compressed["output_size"])
        self.assertEqual(
            hashlib.sha256(self.component).hexdigest(),
            compressed["output_sha256"],
        )
        decoded = decode(self.component)
        self.assertEqual(decoded.consumed, len(self.component))
        self.assertEqual(
            hashlib.sha256(decoded.output).hexdigest(),
            self.manifest["decoded_component"]["output_sha256"],
        )
        write = self.manifest["write"]
        self.assertTrue(write["pointer_bytes_unchanged"])
        self.assertTrue(write["pilot_ids_unchanged"])
        self.assertTrue(write["non_target_bytes_unchanged"])
        self.assertTrue(write["target_reparse_exact"])

    def test_all_selected_names_reparse_exactly(self):
        structure_path = PROJECT_ROOT / self.config["structure"]["config"]
        structure = json.loads(structure_path.read_text(encoding="utf-8"))
        font_path = PROJECT_ROOT / self.config["font_candidate"]["manifest"]
        font_manifest = json.loads(font_path.read_text(encoding="utf-8"))
        overrides, _ = load_ui_font_overrides(
            PROJECT_ROOT,
            self.config,
            font_manifest,
        )
        table = load_text_table(
            PROJECT_ROOT / structure["text_table"]["path"]
        )
        parsed = parse_display_names(
            decode(self.component).output,
            augment_text_table(table, overrides),
            structure,
            verify_text_preimages=False,
        )
        actual = {entry.entry_id: entry.text for entry in parsed.entries}

        prior_path = (
            PROJECT_ROOT
            / self.config["translation_sources"]["reviewed_prior"]["path"]
        )
        prior = json.loads(prior_path.read_text(encoding="utf-8"))[
            "entries"
        ]
        coverage, _ = audit_display_name_coverage(
            PROJECT_ROOT,
            COVERAGE_CONFIG_PATH,
        )
        researched = coverage["selection"]["entries"]
        expected = {
            decision["id"]: decision["translation"]
            for decision in (*prior, *researched)
        }
        self.assertEqual(
            {entry_id: actual[entry_id] for entry_id in expected},
            expected,
        )

    def test_committed_manifest_contains_no_translation_payloads(self):
        def visit(value):
            if isinstance(value, dict):
                self.assertNotIn("source_text", value)
                self.assertNotIn("translation", value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(self.manifest)
        self.assertEqual(self.manifest["runtime"]["status"], "not_tested")


if __name__ == "__main__":
    unittest.main()
