import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from srwz.font import (  # noqa: E402
    GLYPH_COUNT,
    GLYPH_SIZE,
    configure_original_font_loader,
    original_font_loader_words,
    verify_original_font_loader,
    LINEAR_GLYPH_START,
    ExtendedGlyphEntry,
    FontCapacity,
    font_capacity,
    glyph_index_for_code,
    linear_area_codes,
    linear_glyph_index,
)


def entry(code, index):
    return ExtendedGlyphEntry(code=code, row=index // 224, packed_position=index % 224, glyph_index=index, table_offset=0)


class FontLinearAreaTests(unittest.TestCase):
    def test_absent_capacity_is_the_stock_store(self):
        self.assertEqual(font_capacity({}), FontCapacity(GLYPH_COUNT, False))

    def test_capacity_must_be_whole_linear_rows(self):
        self.assertEqual(font_capacity({"font_capacity": {"glyph_count": 4800, "linear_area": True}}), FontCapacity(4800, True))
        for bad in ({"glyph_count": 4700, "linear_area": True}, {"glyph_count": 4608, "linear_area": True},
                    {"glyph_count": 4800, "linear_area": False}, {"glyph_count": 4800}, {"glyph_count": 4800, "linear_area": True, "x": 1}):
            with self.assertRaises(ValueError):
                font_capacity({"font_capacity": bad})

    def test_single_language_loader_and_multilingual_donors(self):
        from zh_hant.assemble_dual import Elf, verify_main_font_loader
        from zh_hant.editions import ORIGINAL

        # A PT_LOAD with the original file layout and all seven guarded loader words.
        executable = bytearray(0x300000)
        struct.pack_into("<I", executable, 28, 0x34)
        struct.pack_into("<H", executable, 44, 1)
        struct.pack_into("<8I", executable, 0x34, 1, 0x1A80, 0x100000, 0, len(executable) - 0x1A80, 0, 0, 0)
        donor = Elf(executable)
        sites = ORIGINAL.main["font_loader"]
        donor.putw(ORIGINAL.main["font_buffer"], 0x13B000)
        for site, word in sites:
            donor.putw(site, word)
        stock = bytes(donor.b)
        self.assertIs(configure_original_font_loader(stock, FontCapacity()), stock)
        verify_main_font_loader(donor, sites)
        capacity = FontCapacity(4992, True)
        patched = configure_original_font_loader(stock, capacity)
        self.assertEqual(original_font_loader_words(patched), (0x15F000, 0x10000002, 0x90240061))
        self.assertIs(configure_original_font_loader(patched, capacity), patched)
        verify_original_font_loader(patched, capacity, 4992 * GLYPH_SIZE)
        verify_main_font_loader(Elf(patched), sites)
        with self.assertRaisesRegex(ValueError, "size and addressing"):
            verify_original_font_loader(stock, capacity, 4992 * GLYPH_SIZE)
        with self.assertRaisesRegex(ValueError, "size and addressing"):
            verify_original_font_loader(patched, capacity, 4480 * GLYPH_SIZE)
        partial = Elf(patched)
        partial.putw(*sites[-1])
        with self.assertRaisesRegex(ValueError, "preimage drift"):
            configure_original_font_loader(bytes(partial.b), capacity)
        with self.assertRaisesRegex(SystemExit, "fallback preimage drift"):
            verify_main_font_loader(partial, sites)

    def test_best_projects_all_three_runtime_words_to_native_sites(self):
        from zh_hant.editions import BEST, ORIGINAL

        contract = json.loads((Path(__file__).resolve().parents[1] / "config/editions/best/source-layout.json").read_text())
        guards = {row["original_offset"]: row for row in contract["elf_instructions"]}
        for original_site, best_site in zip(
            [ORIGINAL.main["font_buffer"], *(va for va, _ in ORIGINAL.main["font_loader"][-2:])],
            [BEST.main["font_buffer"], *(va for va, _ in BEST.main["font_loader"][-2:])],
        ):
            offset = original_site - 0xFE580
            target = best_site - 0xFE580
            [(start, _, dest)] = [span for span in contract["elf_spans"] if span[0] <= offset and offset + 4 <= span[1]]
            self.assertEqual(target, dest + offset - start)
            if original_site != ORIGINAL.main["font_buffer"]:
                guard = guards[offset]
                self.assertEqual(guard["best_offset"], target)
                self.assertEqual(guard["best"], struct.pack("<I", dict(BEST.main["font_loader"])[best_site]).hex())

    def test_linear_formula_and_bounds(self):
        self.assertEqual(LINEAR_GLYPH_START, 4608)
        self.assertEqual(linear_glyph_index(0x9940, glyph_count=4800), 4608)
        self.assertEqual(linear_glyph_index(0x99FF, glyph_count=4800), 4799)
        for code in (0x9A40, 0x9840, 0x993F):
            with self.assertRaises(ValueError):
                linear_glyph_index(code, glyph_count=4800)

    def test_table_wins_and_linear_needs_the_flag(self):
        table = [entry(0x9941, 100)]
        self.assertEqual(glyph_index_for_code(0x9941, table, glyph_count=4800, linear=True), 100)
        self.assertEqual(glyph_index_for_code(0x9942, table, glyph_count=4800, linear=True), 4610)
        with self.assertRaises(ValueError):
            glyph_index_for_code(0x9942, table, glyph_count=4800)

    def test_linear_area_codes_skip_shadowed_codes(self):
        rows = linear_area_codes([entry(0x9941, 100)], glyph_count=4800)
        self.assertEqual(len(rows), 191)
        self.assertNotIn(0x9941, {code for code, _ in rows})
        self.assertEqual(rows[0], (0x9940, 4608))


if __name__ == "__main__":
    unittest.main()
