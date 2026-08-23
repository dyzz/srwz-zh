import json
import struct
import unittest
from pathlib import Path

from tools.srwz.search_tab_alignment import (
    SearchTabAlignmentError,
    apply_search_tab_alignment,
)
from tools.srwz.text import decode_text, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config/full-story-components.json"
REMAINING_UI = PROJECT_ROOT / "corpus/zh/menu/remaining-ui.json"
SOURCE_SLPS = PROJECT_ROOT / "work/disc/SLPS_258.87"
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
UPSTREAM_ASM = PROJECT_ROOT.parent / "tools/asm/menu_search.asm"


class SearchTabAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        cls.contract = config["remaining_ui"]["search_tab_alignment"]
        cls.remaining = json.loads(REMAINING_UI.read_text(encoding="utf-8"))
        cls.source = SOURCE_SLPS.read_bytes()
        cls.table = load_text_table(TEXT_TABLE)

    def test_contract_covers_the_complete_five_label_table(self):
        self.assertEqual(self.contract["center_byte_hex"], "0F")
        patches = self.contract["patches"]
        self.assertEqual(
            [patch["surface"] for patch in patches],
            [
                "spirit_command",
                "special_skill",
                "leader_effect",
                "special_ability",
                "squad_bonus",
            ],
        )
        self.assertEqual(
            [patch["label"] for patch in patches],
            ["精神指令", "特殊技能", "队长效果", "特殊能力", "小队奖励"],
        )

        explicit_translations = self.remaining["slps_by_offset"]
        for patch in patches:
            source_offset = int(patch["source_string_file_offset"], 0)
            coordinate_offset = int(patch["file_offset"], 0)
            virtual_address = int(patch["virtual_address"], 0)
            self.assertEqual(
                virtual_address
                - int(self.contract["elf_virtual_address_base"], 0)
                + int(self.contract["elf_file_offset_base"], 0),
                coordinate_offset,
            )
            self.assertEqual(
                decode_text(self.source, source_offset, self.table).text,
                patch["source_text"],
            )
            self.assertEqual(
                self.source[coordinate_offset],
                int(patch["original_byte_hex"], 16),
            )
            pointer = struct.unpack_from("<I", self.source, coordinate_offset + 2)[0]
            self.assertEqual(
                pointer,
                source_offset
                + int(self.contract["elf_virtual_address_base"], 0),
            )
        self.assertEqual(explicit_translations["0x346248"], "精神指令")
        self.assertEqual(explicit_translations["0x346288"], "小队奖励")

    def test_upstream_english_width_patch_is_migration_only(self):
        self.assertEqual(
            self.contract["source_reference"], "tools/asm/menu_search.asm"
        )
        upstream = UPSTREAM_ASM.read_text(encoding="utf-8")
        for patch, upstream_byte in zip(
            self.contract["patches"][:2], ("22", "26")
        ):
            self.assertIn(f".org {patch['virtual_address']}", upstream)
            self.assertIn(f".byte 0x{upstream_byte}", upstream)
            self.assertIn(
                upstream_byte, patch["accepted_current_byte_hexes"]
            )
            self.assertNotEqual(upstream_byte, self.contract["center_byte_hex"])

    def test_apply_centers_all_five_labels_and_is_idempotent(self):
        output, report = apply_search_tab_alignment(self.source, self.contract)
        self.assertEqual(len(output), len(self.source))
        self.assertEqual(report["surface_count"], 5)
        self.assertEqual(report["changed_surface_count"], 3)
        self.assertEqual(report["changed_byte_count"], 3)
        self.assertTrue(report["all_replacements_exact"])
        self.assertTrue(report["executable_size_preserved"])
        for patch in self.contract["patches"]:
            offset = int(patch["file_offset"], 0)
            self.assertEqual(output[offset], 0x0F)

        repeated, repeated_report = apply_search_tab_alignment(
            output, self.contract
        )
        self.assertEqual(repeated, output)
        self.assertEqual(repeated_report["changed_byte_count"], 0)
        self.assertTrue(
            all(item["already_patched"] for item in repeated_report["patches"])
        )

    def test_previous_two_candidate_layouts_are_migration_preimages(self):
        for candidate_bytes in ((0x22, 0x26), (0x1E, 0x24)):
            with self.subTest(candidate_bytes=candidate_bytes):
                candidate = bytearray(self.source)
                for patch, value in zip(
                    self.contract["patches"][:2], candidate_bytes
                ):
                    candidate[int(patch["file_offset"], 0)] = value

                output, report = apply_search_tab_alignment(
                    bytes(candidate), self.contract
                )
                self.assertEqual(report["changed_byte_count"], 3)
                for patch in self.contract["patches"]:
                    self.assertEqual(output[int(patch["file_offset"], 0)], 0x0F)

    def test_unknown_preimage_is_rejected(self):
        changed = bytearray(self.source)
        offset = int(self.contract["patches"][0]["file_offset"], 0)
        changed[offset] ^= 0xFF
        with self.assertRaisesRegex(SearchTabAlignmentError, "preimage drift"):
            apply_search_tab_alignment(bytes(changed), self.contract)


if __name__ == "__main__":
    unittest.main()
