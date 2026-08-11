import json
import unittest
from pathlib import Path

from tools import build_full_story_components
from tools.srwz.codec import decode
from tools.srwz.display_names import (
    load_display_name_source,
    load_full_unit_name_corpus,
    parse_display_names,
)
from tools.srwz.text import (
    load_text_table,
    normalize_original_fullwidth_ascii,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config/full-story-components.json"
COMPONENT_MANIFEST_PATH = (
    PROJECT_ROOT / "manifests/full-story-components-validation.json"
)


class FullUnitNameWritebackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        font_reference = cls.config["full_story_font"]["manifest"]
        font_manifest = json.loads(
            (PROJECT_ROOT / font_reference["path"]).read_text(encoding="utf-8")
        )
        compdata_reference = cls.config["base_ui"]["members"]["compdata"]
        cls.base_compdata = (
            PROJECT_ROOT / compdata_reference["path"]
        ).read_bytes()
        (
            cls.rebuilt_compdata,
            cls.report,
            cls.structure_path,
            _speaker_path,
            _residual_path,
            cls.unit_corpus_path,
            _proposal_path,
        ) = build_full_story_components._apply_full_pilot_names(
            cls.base_compdata,
            cls.config["full_pilot_names"],
            font_manifest,
        )

        structure, _source, cls.source_names, _context = (
            load_display_name_source(PROJECT_ROOT, cls.structure_path)
        )
        cls.unit_decisions, _corpus_report = load_full_unit_name_corpus(
            PROJECT_ROOT,
            cls.unit_corpus_path,
            cls.source_names.unit_entries,
        )
        table = load_text_table(
            PROJECT_ROOT / structure["text_table"]["path"]
        )
        cls.unit_space_payload = table.inverse_characters["\u3000"].to_bytes(
            2, "big"
        )
        _proposal, primary, aliases, _alias_report = (
            build_full_story_components._full_story_overrides(font_manifest)
        )
        output_table = project_runtime_text_table(table, primary)
        output_table = project_runtime_text_table(output_table, aliases)
        output_table = project_runtime_text_table(
            output_table,
            original_fullwidth_ascii_overrides(table),
        )
        cls.base_names = parse_display_names(
            decode(cls.base_compdata).output,
            output_table,
            structure,
            verify_text_preimages=False,
        )
        cls.rebuilt_names = parse_display_names(
            decode(cls.rebuilt_compdata).output,
            output_table,
            structure,
            verify_text_preimages=False,
        )
        cls.rebuilt_payload = decode(cls.rebuilt_compdata).output
        cls.component_manifest = json.loads(
            COMPONENT_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        component_reference = cls.component_manifest["outputs"][
            "DATA/COMPDATA.BN"
        ]
        cls.component_names = parse_display_names(
            decode(
                (PROJECT_ROOT / component_reference["path"]).read_bytes()
            ).output,
            output_table,
            structure,
            verify_text_preimages=False,
        )

    def test_all_approved_unit_names_are_written_and_reread(self):
        actual = {
            entry.entry_id: entry.text.replace("\u3000", " ")
            for entry in self.rebuilt_names.unit_entries
        }
        expected = {
            entry_id: normalize_original_fullwidth_ascii(
                decision["translation"]
            )
            for entry_id, decision in self.unit_decisions.items()
        }
        self.assertEqual(actual, expected)
        self.assertEqual(self.report["unit_names"]["entry_count"], 348)
        self.assertTrue(self.report["unit_names"]["reread_exact"])

    def test_integrated_component_contains_the_same_348_unit_names(self):
        actual = {
            entry.entry_id: entry.text.replace("\u3000", " ")
            for entry in self.component_names.unit_entries
        }
        expected = {
            entry_id: normalize_original_fullwidth_ascii(
                decision["translation"]
            )
            for entry_id, decision in self.unit_decisions.items()
        }
        self.assertEqual(actual, expected)
        unit_report = self.component_manifest["pilot_names"]["unit_names"]
        self.assertEqual(unit_report["entry_count"], 348)
        self.assertTrue(unit_report["pointer_relocations_exact"])
        self.assertTrue(unit_report["reread_exact"])

    def test_gundam_x_divider_regression_reaches_the_binary(self):
        before = {
            entry.entry_id: entry.text for entry in self.base_names.unit_entries
        }
        after = {
            entry.entry_id: entry.text
            for entry in self.rebuilt_names.unit_entries
        }
        self.assertEqual(before["display-name/unit/0157/name"], "高达X分频者")
        self.assertEqual(before["display-name/unit/0158/name"], "高达X·分频者")
        self.assertEqual(after["display-name/unit/0157/name"], "高达X分裂者")
        self.assertEqual(after["display-name/unit/0158/name"], "高达X·分裂者")

    def test_long_approved_latin_names_stay_in_the_validated_unit_pool(self):
        self.assertEqual(
            self.report["unit_names"]["expanded_zero_padding_entry_ids"],
            [
                "display-name/unit/0008/name",
                "display-name/unit/0009/name",
                "display-name/unit/0010/name",
            ],
        )
        before = {
            entry.entry_id: entry for entry in self.base_names.unit_entries
        }
        after = {
            entry.entry_id: entry
            for entry in self.rebuilt_names.unit_entries
        }
        for entry_id in self.report["unit_names"][
            "expanded_zero_padding_entry_ids"
        ]:
            self.assertEqual(after[entry_id].target_offset, before[entry_id].target_offset)
            self.assertEqual(after[entry_id].pointer_offsets, before[entry_id].pointer_offsets)
            self.assertEqual(after[entry_id].capacity, 32)
        self.assertTrue(self.report["unit_names"]["pointer_relocations_exact"])
        self.assertTrue(self.report["unit_names"]["following_targets_unchanged"])

    def test_latin_word_separators_are_stored_as_two_byte_spaces(self):
        expected_ids = [
            "display-name/unit/0008/name",
            "display-name/unit/0009/name",
            "display-name/unit/0010/name",
            "display-name/unit/0298/name",
            "display-name/unit/0299/name",
        ]
        self.assertEqual(
            self.report["unit_names"]["two_byte_space_entry_ids"],
            expected_ids,
        )
        self.assertEqual(
            self.report["unit_names"]["two_byte_space_code"], "8140"
        )
        entries = {
            entry.entry_id: entry for entry in self.rebuilt_names.unit_entries
        }
        for entry_id in expected_ids:
            entry = entries[entry_id]
            payload = self.rebuilt_payload[
                entry.target_offset : entry.target_offset + entry.encoded_size
            ]
            self.assertNotIn(b"\x20", payload)
            self.assertEqual(payload.count(self.unit_space_payload), 1)
        self.assertTrue(self.report["unit_names"]["two_byte_spaces_exact"])

    def test_drill_spazer_space_uses_one_controlled_pointer_relocation(self):
        self.assertEqual(
            self.report["unit_names"]["relocated_entry_ids"],
            ["display-name/unit/0011/name"],
        )
        self.assertEqual(self.report["unit_names"]["relocated_pointer_count"], 3)
        before = {
            entry.entry_id: entry for entry in self.base_names.unit_entries
        }
        after = {
            entry.entry_id: entry for entry in self.rebuilt_names.unit_entries
        }
        entry_id = "display-name/unit/0011/name"
        self.assertEqual(before[entry_id].target_offset, 0x6D198)
        self.assertEqual(after[entry_id].target_offset, 0x6D1A0)
        self.assertEqual(after[entry_id].text, "中型碟")
        self.assertEqual(
            after[entry_id].pointer_offsets,
            before[entry_id].pointer_offsets,
        )
        self.assertTrue(self.report["unit_names"]["pointer_relocations_exact"])


if __name__ == "__main__":
    unittest.main()
