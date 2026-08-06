import json
import unittest
from pathlib import Path

from tools.srwz.canary import double_byte_width_class
from tools.srwz.codec import decode
from tools.srwz.display_names import parse_display_names
from tools.srwz.text import (
    encode_text,
    load_text_table,
    original_fullwidth_ascii_overrides,
)
from tools.srwz.ui_menu import project_ui_runtime_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = PROJECT_ROOT / "work/writeback/full-story-codebook-proposal.json"
BASE_CODEBOOK = PROJECT_ROOT / "config/encoding/codebook.json"
COMPONENT_REPORT = (
    PROJECT_ROOT
    / "work/build/ui-p10-full-story/components/component-validation.json"
)
COMPDATA = (
    PROJECT_ROOT / "work/build/ui-p10-full-story/components/DATA/COMPDATA.BN"
)
STRUCTURE = PROJECT_ROOT / "config/display-names/compdata.json"


class FullStorySurfaceAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
        cls.base_codebook = json.loads(
            BASE_CODEBOOK.read_text(encoding="utf-8")
        )
        cls.report = json.loads(COMPONENT_REPORT.read_text(encoding="utf-8"))
        cls.structure = json.loads(STRUCTURE.read_text(encoding="utf-8"))
        cls.primary = {
            item["character"]: item for item in cls.proposal["assignments"]
        }
        cls.aliases = cls.proposal["surface_alias_assignments"]
        cls.alias_codes = {
            item["character"]: int(item["code"], 16) for item in cls.aliases
        }

    def test_aliases_leave_the_conditional_width_range(self):
        self.assertEqual(len(self.aliases), 701)
        self.assertEqual(len(self.alias_codes), 701)
        self.assertEqual(len({item["code"] for item in self.aliases}), 701)
        self.assertEqual(len({item["glyph_index"] for item in self.aliases}), 701)
        for alias in self.aliases:
            primary = self.primary[alias["character"]]
            self.assertEqual(alias["primary_code"], primary["code"])
            self.assertEqual(
                double_byte_width_class(int(primary["code"], 16)),
                "conditional_double_byte",
            )
            self.assertEqual(
                double_byte_width_class(int(alias["code"], 16)),
                "default_double_byte",
            )
            self.assertEqual(
                alias["raster"]["packed_glyph_sha256"],
                primary["raster"]["packed_glyph_sha256"],
            )

    def test_every_affected_display_name_is_reencoded_exactly(self):
        table = load_text_table(
            PROJECT_ROOT / self.structure["text_table"]["path"]
        )
        overrides = {
            item["character"]: int(item["code"], 16)
            for item in self.base_codebook["assignments"]
        }
        overrides.update({
            character: int(assignment["code"], 16)
            for character, assignment in self.primary.items()
        })
        output_table = project_ui_runtime_text_table(table, overrides)
        output_table = project_ui_runtime_text_table(
            output_table,
            self.alias_codes,
        )
        ascii_overrides = original_fullwidth_ascii_overrides(table)
        output_table = project_ui_runtime_text_table(
            output_table,
            ascii_overrides,
        )
        overrides.update(self.alias_codes)
        overrides.update(ascii_overrides)
        overrides[" "] = 0x20
        stored = COMPDATA.read_bytes()
        decoded = decode(stored)
        self.assertEqual(decoded.consumed, len(stored))
        parsed = parse_display_names(
            decoded.output,
            output_table,
            self.structure,
            verify_text_preimages=False,
        )
        normalized = {entry.entry_id: entry.text for entry in parsed.entries}
        affected = [
            entry
            for entry in parsed.entries
            if normalized[entry.entry_id]
            and any(
                character in self.alias_codes
                for character in normalized[entry.entry_id]
            )
        ]
        self.assertEqual(len(affected), 1880)
        for entry in affected:
            encoded = encode_text(
                normalized[entry.entry_id],
                table,
                overrides=overrides,
                terminate=True,
            )
            self.assertEqual(
                len(encoded),
                entry.encoded_size,
                entry.entry_id,
            )
            self.assertEqual(
                decoded.output[
                    entry.target_offset : entry.target_offset + len(encoded)
                ],
                encoded,
                entry.entry_id,
            )

    def test_executable_renderer_patch_is_removed(self):
        geometry = self.report["composition"][
            "intermission_list_font_geometry"
        ]
        self.assertFalse(geometry["enabled"])
        self.assertEqual(geometry["strategy"], "surface-safe-code-aliases")
        self.assertFalse(geometry["executable_geometry_patch_applied"])
        self.assertTrue(geometry["original_list_renderer_preserved"])
        self.assertTrue(
            self.report["acceptance"][
                "intermission_list_safe_aliases_scoped"
            ]
        )


if __name__ == "__main__":
    unittest.main()
