import struct
import unittest

from tools.srwz.font import (
    EXTENDED_GLYPH_TABLE_FILE_OFFSET,
    GLYPH_HEIGHT,
    GLYPH_SIZE,
    GLYPH_WIDTH,
    analyze_glyph_code_mapping,
    analyze_font_patch,
    ascii_glyph_index,
    decode_glyph,
    decode_font_stream,
    encode_glyph,
    extended_glyph_index,
    extended_glyph_mapping,
    glyph_index_for_code,
    inventory_codebook,
    is_cjk_unified_ideograph,
    read_extended_glyph_table,
    render_glyph_grid,
    replace_glyph,
    raw_standard_allocation_candidates,
    safe_standard_allocation_candidates,
    standard_glyph_index,
)
from tools.srwz.text import TextTable


class FontAnalysisTests(unittest.TestCase):
    def test_classifies_cjk_ideographs_without_absorbing_kana_or_symbols(self):
        self.assertTrue(is_cjk_unified_ideograph("中"))
        self.assertTrue(is_cjk_unified_ideograph("测"))
        self.assertFalse(is_cjk_unified_ideograph("セ"))
        self.assertFalse(is_cjk_unified_ideograph("“"))
        with self.assertRaisesRegex(ValueError, "one character"):
            is_cjk_unified_ideograph("中文")

    def test_decodes_compressed_font_without_absorbing_padding(self):
        # declared=3, flags=1, unknown=0, literal block, five zero pad bytes
        segment = b"\x07\x03\x01\x03\x01abc" + b"\x00" * 5
        result = decode_font_stream(segment)
        self.assertEqual(result.decoded, b"abc")
        self.assertEqual(result.padding, 5)
        self.assertTrue(result.padding_all_zero)

    def test_partitions_patch_into_fixed_blocks(self):
        original = bytes(GLYPH_SIZE * 4)
        candidate = bytearray(original)
        candidate[GLYPH_SIZE + 9] = 1
        candidate[GLYPH_SIZE * 2 + 14] = 2
        analysis = analyze_font_patch(
            original,
            bytes(candidate),
            region_start=GLYPH_SIZE,
            block_size=GLYPH_SIZE,
            block_count=2,
        )
        self.assertEqual(analysis.changed_byte_count, 2)
        self.assertEqual(analysis.difference_range_count, 2)
        self.assertEqual(analysis.changed_block_indices, (0, 1))
        self.assertEqual(analysis.changed_glyph_indices, (1, 2))
        self.assertEqual(analysis.changed_bytes_outside_region, 0)

    def test_reports_changes_outside_expected_region(self):
        original = bytes(GLYPH_SIZE * 3)
        candidate = bytearray(original)
        candidate[0] = 1
        analysis = analyze_font_patch(
            original,
            bytes(candidate),
            region_start=GLYPH_SIZE,
            block_size=GLYPH_SIZE,
            block_count=1,
        )
        self.assertEqual(analysis.changed_bytes_outside_region, 1)
        self.assertEqual(analysis.changed_block_indices, ())
        self.assertEqual(analysis.changed_glyph_indices, (0,))

    def test_ascii_patch_mapping_has_observed_skip(self):
        self.assertEqual(ascii_glyph_index(0x20), 0xBF)
        self.assertEqual(ascii_glyph_index(ord("A")), 224)
        self.assertEqual(ascii_glyph_index(ord("]")), 252)
        self.assertEqual(ascii_glyph_index(ord("^")), 254)
        self.assertEqual(ascii_glyph_index(ord("~")), 286)
        with self.assertRaisesRegex(ValueError, "outside"):
            ascii_glyph_index(0x1F)

    def test_standard_renderer_formula_covers_font_boundary(self):
        self.assertEqual(standard_glyph_index(0x8140), 0)
        self.assertEqual(standard_glyph_index(0x8240), 192)
        self.assertEqual(standard_glyph_index(0x8540), 768)
        self.assertEqual(standard_glyph_index(0x8940), 1536)
        self.assertEqual(standard_glyph_index(0x987E), 4478)
        self.assertEqual(standard_glyph_index(0x987F), 4479)
        with self.assertRaisesRegex(ValueError, "outside font"):
            standard_glyph_index(0x9880)
        with self.assertRaisesRegex(ValueError, "standard glyph branch"):
            standard_glyph_index(0x989F)

    def test_extended_position_matches_original_row_math(self):
        self.assertEqual(extended_glyph_index(4, 0x00), 896)
        self.assertEqual(extended_glyph_index(4, 0xDF), 1119)
        self.assertEqual(extended_glyph_index(3, 0x20), 704)

    def test_reads_terminated_extended_table_and_keeps_duplicates(self):
        executable = bytearray(EXTENDED_GLYPH_TABLE_FILE_OFFSET + 16)
        struct.pack_into(
            "<HbB",
            executable,
            EXTENDED_GLYPH_TABLE_FILE_OFFSET,
            0x989F,
            4,
            0x00,
        )
        struct.pack_into(
            "<HbB",
            executable,
            EXTENDED_GLYPH_TABLE_FILE_OFFSET + 4,
            0x989F,
            4,
            0x01,
        )
        entries = read_extended_glyph_table(bytes(executable))
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].glyph_index, 896)
        self.assertEqual(entries[1].glyph_index, 897)
        self.assertEqual(
            extended_glyph_mapping(entries),
            {0x989F: 896},
        )
        self.assertEqual(glyph_index_for_code(0x989F, entries), 896)
        with self.assertRaisesRegex(ValueError, "absent"):
            glyph_index_for_code(0x9999, entries)

    def test_analyzes_verified_text_code_coverage(self):
        executable = bytearray(EXTENDED_GLYPH_TABLE_FILE_OFFSET + 16)
        struct.pack_into(
            "<HbB",
            executable,
            EXTENDED_GLYPH_TABLE_FILE_OFFSET,
            0x989F,
            4,
            0,
        )
        struct.pack_into(
            "<HbB",
            executable,
            EXTENDED_GLYPH_TABLE_FILE_OFFSET + 4,
            0xFA93,
            4,
            1,
        )
        entries = read_extended_glyph_table(bytes(executable))
        table = TextTable(
            characters={
                0x8140: "A",
                0x989F: "B",
                0x9999: "C",
            },
            tags={},
        )
        analysis = analyze_glyph_code_mapping(table, entries)
        self.assertEqual(analysis.standard_text_code_count, 1)
        self.assertEqual(analysis.supported_extended_text_code_count, 1)
        self.assertEqual(analysis.supported_text_code_count, 2)
        self.assertEqual(analysis.unsupported_text_codes, (0x9999,))
        self.assertEqual(
            analysis.extended_codes_absent_from_text_table,
            (0xFA93,),
        )
        self.assertEqual(analysis.referenced_glyph_count, 2)
        self.assertEqual(
            analysis.standard_extended_glyph_overlap_count,
            0,
        )

    def test_glyph_pack_order_is_low_nibble_first(self):
        pixels = bytes(index & 0x0F for index in range(GLYPH_WIDTH * GLYPH_HEIGHT))
        packed = encode_glyph(pixels)
        self.assertEqual(len(packed), GLYPH_SIZE)
        self.assertEqual(packed[0], 0x10)
        self.assertEqual(packed[1], 0x32)
        self.assertEqual(decode_glyph(packed, 0), pixels)

    def test_replace_glyph_is_size_preserving(self):
        source = bytes(GLYPH_SIZE * 2)
        pixels = bytes([15]) * (GLYPH_WIDTH * GLYPH_HEIGHT)
        replaced = replace_glyph(source, 1, pixels)
        self.assertEqual(len(replaced), len(source))
        self.assertEqual(replaced[:GLYPH_SIZE], bytes(GLYPH_SIZE))
        self.assertEqual(decode_glyph(replaced, 1), pixels)

    def test_render_glyph_grid_writes_standard_png(self):
        source = bytes([0xF0]) * GLYPH_SIZE
        rendered = render_glyph_grid(source, (0,), scale=2)
        self.assertTrue(rendered.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IHDR", rendered)
        self.assertIn(b"IDAT", rendered)

    def test_inventories_candidate_unmapped_two_byte_codes(self):
        table = TextTable(
            characters={0x8140: "A", 0x8141: "A", 0x8240: "B"},
            tags={0x31: "color"},
        )
        inventory = inventory_codebook(table)
        self.assertEqual(inventory.lead_bytes, (0x81, 0x82))
        self.assertEqual(inventory.candidate_capacity, 376)
        self.assertEqual(inventory.mapped_code_count, 3)
        self.assertEqual(inventory.unique_character_count, 2)
        self.assertEqual(inventory.duplicate_character_count, 1)
        self.assertNotIn(0x8140, inventory.candidate_unmapped_codes)

    def test_safe_allocation_candidates_exclude_all_known_glyph_owners(self):
        table = TextTable(
            characters={0x8140: "A", 0x8240: "B"},
            tags={},
        )
        legacy, expanded = safe_standard_allocation_candidates(
            table,
            (),
            reserved_codes=(0x8141,),
            reserved_glyphs=(standard_glyph_index(0x8142),),
        )
        candidates = (*legacy, *expanded)
        codes = {code for code, _ in candidates}
        glyphs = {glyph for _, glyph in candidates}
        self.assertNotIn(0x8140, codes)
        self.assertNotIn(0x8240, codes)
        self.assertNotIn(0x8141, codes)
        self.assertNotIn(standard_glyph_index(0x8142), glyphs)
        self.assertNotIn(ascii_glyph_index(ord("A")), glyphs)
        self.assertEqual(len(codes), len(candidates))
        self.assertEqual(len(glyphs), len(candidates))

    def test_raw_standard_candidates_are_separate_and_stable(self):
        table = TextTable(
            characters={0x8140: "A", 0x8240: "B"},
            tags={},
        )
        safe = {
            code
            for group in safe_standard_allocation_candidates(table, ())
            for code, _ in group
        }
        raw = raw_standard_allocation_candidates(
            table,
            (),
            reserved_codes=(0x817F,),
            reserved_glyphs=(standard_glyph_index(0x82FD),),
        )
        self.assertTrue(raw)
        self.assertNotIn(0x817F, {code for code, _ in raw})
        self.assertNotIn(standard_glyph_index(0x82FD), {glyph for _, glyph in raw})
        self.assertTrue(all(code not in safe for code, _ in raw))
        self.assertEqual(
            [code & 0xFF for code, _ in raw],
            sorted(
                (code & 0xFF for code, _ in raw),
                key=(0x7F, 0xFD, 0xFE, 0xFF).index,
            ),
        )
        self.assertTrue(
            all(standard_glyph_index(code) == glyph for code, glyph in raw)
        )


if __name__ == "__main__":
    unittest.main()
