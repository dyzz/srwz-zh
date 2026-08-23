import struct
import unittest

from tools.srwz.codec import decode_production as decode
from tools.srwz.iso_layout import ExecutableOffsetSpec
from tools.srwz.menu import MenuParseResult, MenuTextEntry
from tools.srwz.text import TextTable
from tools.srwz.writeback import WritebackError
from tools.srwz.writers import (
    apply_summary_replacements,
    build_executable_offset_patch_plan,
    build_summary_patch_plan,
    encode_stage_message,
    rebuild_codec_archive,
    relocate_menu_texts_to_pool,
    relocate_stage_text_to_arena,
    relocate_stage_texts_to_arena,
    repack_stage_texts_in_place,
    replace_menu_texts_in_place,
)


def summary_fixture():
    data = bytearray(0x90)
    struct.pack_into("<I", data, 0x2C, 1)
    data[0x3C:0x40] = b"text"
    struct.pack_into("<I", data, 0x40, 0x40)
    struct.pack_into("<I", data, 0x66, 8)
    data[0x6A:0x72] = b"Hello\x00\x00\x00"
    return bytes(data)


def full_summary_fixture():
    data = bytearray(0x90)
    struct.pack_into("<I", data, 0x2C, 1)
    data[0x3C:0x40] = b"text"
    struct.pack_into("<I", data, 0x40, 0x40)
    struct.pack_into("<I", data, 0x66, 5)
    data[0x6A:0x6F] = b"Hello"
    return bytes(data)


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.table = TextTable(characters={}, tags={})

    def test_summary_writer_is_fixed_allocation_and_reparses(self):
        source = summary_fixture()
        replacements = {"summary/00/000": "Hi"}
        plan = build_summary_patch_plan(
            source,
            self.table,
            chunk_index=0,
            replacements=replacements,
        )
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].offset, 0x6A)
        self.assertEqual(len(plan.operations[0].after), 8)
        output = apply_summary_replacements(
            source,
            self.table,
            chunk_index=0,
            replacements=replacements,
        )
        self.assertEqual(output[0x6A:0x72], b"Hi\x00\x00\x00\x00\x00\x00")

    def test_stage_condition_runtime_name_placeholder_stays_raw_ascii(self):
        table = TextTable(characters={0x8146: ":"}, tags={})
        overrides = {":": 0x8146}
        encoded = encode_stage_message(
            table,
            overrides,
            entry_id="story/041/condition/01/02",
            source_text=":、またはトビーの撃墜。",
            replacement=": or Toby down.",
            terminate=True,
        )
        self.assertEqual(encoded[0], 0x3A)
        self.assertNotEqual(encoded[:2], b"\x81\x46")

    def test_stage_dialogue_visible_colon_keeps_release_override(self):
        table = TextTable(characters={0x8146: ":"}, tags={})
        encoded = encode_stage_message(
            table,
            {":": 0x8146},
            entry_id="story/041/dialogue/01.01/0000",
            source_text="A:B",
            replacement="A:B",
            terminate=True,
        )
        self.assertEqual(encoded, b"A\x81\x46B\x00")

    def test_stage_condition_runtime_name_placeholder_count_is_locked(self):
        with self.assertRaisesRegex(
            WritebackError,
            "runtime-name placeholder count mismatch",
        ):
            encode_stage_message(
                self.table,
                {":": 0x8146},
                entry_id="story/041/condition/01/02",
                source_text=":、またはトビーの撃墜。",
                replacement="or Toby down.",
            )

    def test_summary_writer_accepts_profile_codebook_overrides(self):
        source = summary_fixture()
        output = apply_summary_replacements(
            source,
            self.table,
            chunk_index=0,
            replacements={"summary/00/000": "测"},
            overrides={"测": 0x987E},
        )
        self.assertEqual(output[0x6A:0x72], b"\x98\x7e\x00\x00\x00\x00\x00\x00")

    def test_summary_writer_fails_on_overflow_and_unknown_id(self):
        source = summary_fixture()
        with self.assertRaisesRegex(WritebackError, "overflow"):
            build_summary_patch_plan(
                source,
                self.table,
                chunk_index=0,
                replacements={"summary/00/000": "too long"},
            )
        with self.assertRaisesRegex(WritebackError, "unknown summary"):
            build_summary_patch_plan(
                source,
                self.table,
                chunk_index=0,
                replacements={"summary/00/999": "x"},
            )

    def test_summary_writer_preserves_full_allocation_terminator_contract(self):
        source = full_summary_fixture()
        identity = build_summary_patch_plan(
            source,
            self.table,
            chunk_index=0,
            replacements={"summary/00/000": "Hello"},
        )
        self.assertEqual(identity.apply(source), source)
        shorter = apply_summary_replacements(
            source,
            self.table,
            chunk_index=0,
            replacements={"summary/00/000": "Hi"},
        )
        self.assertEqual(shorter[0x6A:0x6F], b"Hi\x00\x00\x00")

    def test_archive_rebuild_round_trips_and_aligns_every_chunk(self):
        sources = (b"abcabcabc", bytes(range(64)))
        rebuilt = rebuild_codec_archive(sources)
        self.assertEqual(rebuilt.chunk_count, 2)
        self.assertEqual(rebuilt.offsets[0], 0)
        self.assertTrue(all(offset % 16 == 0 for offset in rebuilt.offsets))
        for index, expected in enumerate(sources):
            result = decode(
                rebuilt.data[rebuilt.offsets[index] : rebuilt.offsets[index + 1]]
            )
            self.assertEqual(result.output, expected)

    def test_slps_offset_patch_writes_starts_not_terminal_size(self):
        executable = bytearray(32)
        struct.pack_into("<II", executable, 8, 0, 16)
        spec = ExecutableOffsetSpec(
            name="fixture",
            member="fixture.bin",
            table_start=8,
            table_end=15,
        )
        plan = build_executable_offset_patch_plan(
            bytes(executable),
            spec,
            (0, 32, 80),
        )
        output = plan.apply(bytes(executable))
        self.assertEqual(struct.unpack_from("<II", output, 8), (0, 32))
        self.assertEqual(output[:8], bytes(8))
        self.assertEqual(output[16:], bytes(16))

    def test_slps_offset_patch_preserves_table_with_terminal_size(self):
        executable = bytearray(32)
        struct.pack_into("<III", executable, 8, 0, 16, 32)
        spec = ExecutableOffsetSpec(
            name="fixture",
            member="fixture.bin",
            table_start=8,
            table_end=19,
        )
        plan = build_executable_offset_patch_plan(
            bytes(executable),
            spec,
            (0, 48, 96),
        )
        output = plan.apply(bytes(executable))
        self.assertEqual(
            struct.unpack_from("<III", output, 8),
            (0, 48, 96),
        )

    def test_stage_writer_relocates_growing_dialogue_to_aligned_arena(self):
        base = 0x7566F0
        source = bytearray(0x240)
        # Three block-reference instruction pairs resolve to 0x100, 0x120,
        # and 0x140. Only the latter two are dialogue block candidates.
        for index, target in enumerate((0x100, 0x120, 0x140)):
            high = ((base + target + 0x8000) >> 16) & 0xFFFF
            low = (base + target) & 0xFFFF
            struct.pack_into("<h", source, 0x90 + index * 16, high)
            struct.pack_into("<h", source, 0x98 + index * 16, low)
        # Block 1 has one section; block 2 is deliberately ignored.
        struct.pack_into("<II", source, 0x120, base + 0x160, 1)
        struct.pack_into("<II", source, 0x140, 0, 1)
        struct.pack_into("<II", source, 0x160, base + 0x180, 0)
        # One dialogue record followed by a terminating record type.
        struct.pack_into("<I", source, 0x1A0, 1)
        struct.pack_into("<I", source, 0x1B0, base + 0x200)
        struct.pack_into("<I", source, 0x1C0, 0x7E)
        source[0x200:0x209] = b"Pilot\nHi\x00"

        result = relocate_stage_text_to_arena(
            bytes(source),
            self.table,
            stage_index=1,
            function_address=0,
            entry_id="story/001/dialogue/01.01/0000",
            replacement="Longer message",
            alignment=16,
        )
        self.assertEqual(result.arena_offset, 0x200)
        self.assertEqual(result.pointer_offset, 0x1B0)
        self.assertGreater(result.payload_size, len(b"Pilot\nHi\x00"))
        self.assertEqual(
            struct.unpack_from("<I", result.data, 0x1B0)[0],
            base + 0x200,
        )
        self.assertEqual(
            result.data[0x200:0x215],
            b"Pilot\nLonger message\x00",
        )
        self.assertFalse(result.used_source_tail)
        self.assertTrue(result.used_source_allocation)
        self.assertEqual(len(result.data), len(source))

    def test_stage_writer_rejects_non_power_of_two_alignment(self):
        with self.assertRaisesRegex(ValueError, "power of two"):
            relocate_stage_text_to_arena(
                bytes(0x100),
                self.table,
                stage_index=0,
                function_address=0,
                entry_id="missing",
                replacement="x",
                alignment=3,
            )

    def test_stage_batch_writer_translates_speaker_and_message(self):
        base = 0x7566F0
        source = bytearray(0x220)
        for index, target in enumerate((0x100, 0x120, 0x140)):
            high = ((base + target + 0x8000) >> 16) & 0xFFFF
            low = (base + target) & 0xFFFF
            struct.pack_into("<h", source, 0x90 + index * 16, high)
            struct.pack_into("<h", source, 0x98 + index * 16, low)
        struct.pack_into("<II", source, 0x120, base + 0x160, 1)
        struct.pack_into("<II", source, 0x140, 0, 1)
        struct.pack_into("<II", source, 0x160, base + 0x180, 0)
        struct.pack_into("<I", source, 0x1A0, 1)
        struct.pack_into("<I", source, 0x1B0, base + 0x200)
        struct.pack_into("<I", source, 0x1C0, 0x7E)
        source[0x200:0x209] = b"Pilot\nHi\x00"

        result = relocate_stage_texts_to_arena(
            bytes(source),
            self.table,
            stage_index=1,
            function_address=0,
            replacements={
                "story/001/dialogue/01.01/0000": "Longer message",
            },
            speaker_replacements={1: "Lead"},
        )
        self.assertEqual(result.allocations[0].arena_offset, 0x220)
        self.assertEqual(result.decoded_growth, 32)
        self.assertEqual(
            result.data[0x220:0x234],
            b"Lead\nLonger message\x00",
        )
        self.assertEqual(
            struct.unpack_from("<I", result.data, 0x1B0)[0],
            base + 0x220,
        )

    def test_stage_in_place_repack_reuses_owned_source_region(self):
        base = 0x7566F0
        source = bytearray(0x220)
        for index, target in enumerate((0x100, 0x120, 0x140)):
            high = ((base + target + 0x8000) >> 16) & 0xFFFF
            low = (base + target) & 0xFFFF
            struct.pack_into("<h", source, 0x90 + index * 16, high)
            struct.pack_into("<h", source, 0x98 + index * 16, low)
        struct.pack_into("<II", source, 0x120, base + 0x160, 1)
        struct.pack_into("<II", source, 0x140, 0, 1)
        struct.pack_into("<II", source, 0x160, base + 0x180, 0)
        struct.pack_into("<I", source, 0x1A0, 1)
        struct.pack_into("<I", source, 0x1B0, base + 0x200)
        struct.pack_into("<I", source, 0x1C0, 0x7E)
        source[0x200:0x209] = b"Pilot\nHi\x00"

        result = repack_stage_texts_in_place(
            bytes(source),
            self.table,
            stage_index=1,
            function_address=0,
            replacements={
                "story/001/dialogue/01.01/0000": "Longer message",
            },
            speaker_replacements={1: "Lead"},
        )
        self.assertEqual(len(result.data), len(source))
        self.assertEqual(result.decoded_growth, 0)
        self.assertEqual(result.mode, "in_place_owned_regions")
        self.assertEqual(result.owned_regions, ((0x200, 0x220),))
        self.assertEqual(result.allocations[0].arena_offset, 0x200)
        self.assertEqual(
            result.data[0x200:0x214],
            b"Lead\nLonger message\x00",
        )
        self.assertEqual(
            struct.unpack_from("<I", result.data, 0x1B0)[0],
            base + 0x200,
        )

    def test_stage_in_place_repack_ignores_pointer_like_interior_word(self):
        base = 0x7566F0
        source = bytearray(0x220)
        for index, target in enumerate((0x100, 0x120, 0x140)):
            high = ((base + target + 0x8000) >> 16) & 0xFFFF
            low = (base + target) & 0xFFFF
            struct.pack_into("<h", source, 0x90 + index * 16, high)
            struct.pack_into("<h", source, 0x98 + index * 16, low)
        struct.pack_into("<II", source, 0x120, base + 0x160, 1)
        struct.pack_into("<II", source, 0x140, 0, 1)
        struct.pack_into("<II", source, 0x160, base + 0x180, 0)
        struct.pack_into("<I", source, 0x1A0, 1)
        struct.pack_into("<I", source, 0x1B0, base + 0x200)
        struct.pack_into("<I", source, 0x1C0, 0x7E)
        source[0x200:0x209] = b"Pilot\nHi\x00"

        # Aligned encoded text can coincidentally resemble an interior address.
        struct.pack_into("<I", source, 0x50, base + 0x202)

        result = repack_stage_texts_in_place(
            bytes(source),
            self.table,
            stage_index=1,
            function_address=0,
            replacements={
                "story/001/dialogue/01.01/0000": "Longer message",
            },
        )
        self.assertEqual(
            struct.unpack_from("<I", result.data, 0x50)[0],
            base + 0x202,
        )

    def test_stage_in_place_repack_repoints_registered_source_alias(self):
        base = 0x7566F0
        source = bytearray(0x240)
        for index, target in enumerate((0x100, 0x120, 0x140)):
            high = ((base + target + 0x8000) >> 16) & 0xFFFF
            low = (base + target) & 0xFFFF
            struct.pack_into("<h", source, 0x90 + index * 16, high)
            struct.pack_into("<h", source, 0x98 + index * 16, low)
        struct.pack_into("<II", source, 0x120, base + 0x160, 1)
        struct.pack_into("<II", source, 0x140, 0, 1)
        struct.pack_into("<II", source, 0x160, base + 0x180, 0)
        struct.pack_into("<I", source, 0x1A0, 1)
        struct.pack_into("<I", source, 0x1B0, base + 0x200)
        struct.pack_into("<I", source, 0x1C0, 0x7E)
        source[0x200:0x209] = b"Pilot\nHi\x00"
        struct.pack_into("<I", source, 0x50, base + 0x200)

        result = repack_stage_texts_in_place(
            bytes(source),
            self.table,
            stage_index=1,
            function_address=0,
            replacements={
                "story/001/dialogue/01.01/0000": "Longer message",
            },
        )

        self.assertEqual(
            struct.unpack_from("<I", result.data, 0x50)[0],
            base + result.allocations[0].arena_offset,
        )

    def test_stage_repack_preserves_original_keyword_control_codes(self):
        base = 0x7566F0
        source = bytearray(0x220)
        for index, target in enumerate((0x100, 0x120, 0x140)):
            high = ((base + target + 0x8000) >> 16) & 0xFFFF
            low = (base + target) & 0xFFFF
            struct.pack_into("<h", source, 0x90 + index * 16, high)
            struct.pack_into("<h", source, 0x98 + index * 16, low)
        struct.pack_into("<II", source, 0x120, base + 0x160, 1)
        struct.pack_into("<II", source, 0x140, 0, 1)
        struct.pack_into("<II", source, 0x160, base + 0x180, 0)
        struct.pack_into("<I", source, 0x1A0, 1)
        struct.pack_into("<I", source, 0x1B0, base + 0x200)
        struct.pack_into("<I", source, 0x1C0, 0x7E)
        source[0x200:0x210] = b"Pilot\n\x81\x73Key\x81\x74\x00"
        table = TextTable(
            characters={0x8173: "《", 0x8174: "》"},
            tags={},
        )
        overrides = {"《": 0x8FEC, "》": 0x8FEF, "测": 0x9000}

        result = repack_stage_texts_in_place(
            bytes(source),
            table,
            stage_index=1,
            function_address=0,
            replacements={
                "story/001/dialogue/01.01/0000": "《测》",
            },
            overrides=overrides,
        )
        offset = result.allocations[0].arena_offset
        self.assertEqual(
            result.data[offset : offset + 13],
            b"Pilot\n\x81\x73\x90\x00\x81\x74\x00",
        )
        self.assertNotIn(b"\x8f\xec", result.data[offset : offset + 13])
        self.assertNotIn(b"\x8f\xef", result.data[offset : offset + 13])

    def test_stage_repack_rejects_dropped_keyword_span(self):
        base = 0x7566F0
        source = bytearray(0x220)
        for index, target in enumerate((0x100, 0x120, 0x140)):
            high = ((base + target + 0x8000) >> 16) & 0xFFFF
            low = (base + target) & 0xFFFF
            struct.pack_into("<h", source, 0x90 + index * 16, high)
            struct.pack_into("<h", source, 0x98 + index * 16, low)
        struct.pack_into("<II", source, 0x120, base + 0x160, 1)
        struct.pack_into("<II", source, 0x140, 0, 1)
        struct.pack_into("<II", source, 0x160, base + 0x180, 0)
        struct.pack_into("<I", source, 0x1A0, 1)
        struct.pack_into("<I", source, 0x1B0, base + 0x200)
        struct.pack_into("<I", source, 0x1C0, 0x7E)
        source[0x200:0x210] = b"Pilot\n\x81\x73Key\x81\x74\x00"
        table = TextTable(
            characters={0x8173: "《", 0x8174: "》"},
            tags={},
        )

        with self.assertRaisesRegex(
            WritebackError,
            "STAGE keyword marker count mismatch",
        ):
            repack_stage_texts_in_place(
                bytes(source),
                table,
                stage_index=1,
                function_address=0,
                replacements={
                    "story/001/dialogue/01.01/0000": "测",
                },
                overrides={"测": 0x9000},
            )

    def test_stage_repack_keeps_translator_added_book_brackets_visible(self):
        base = 0x7566F0
        source = bytearray(0x220)
        for index, target in enumerate((0x100, 0x120, 0x140)):
            high = ((base + target + 0x8000) >> 16) & 0xFFFF
            low = (base + target) & 0xFFFF
            struct.pack_into("<h", source, 0x90 + index * 16, high)
            struct.pack_into("<h", source, 0x98 + index * 16, low)
        struct.pack_into("<II", source, 0x120, base + 0x160, 1)
        struct.pack_into("<II", source, 0x140, 0, 1)
        struct.pack_into("<II", source, 0x160, base + 0x180, 0)
        struct.pack_into("<I", source, 0x1A0, 1)
        struct.pack_into("<I", source, 0x1B0, base + 0x200)
        struct.pack_into("<I", source, 0x1C0, 0x7E)
        source[0x200:0x209] = b"Pilot\nHi\x00"
        table = TextTable(
            characters={0x8173: "《", 0x8174: "》"},
            tags={},
        )

        result = repack_stage_texts_in_place(
            bytes(source),
            table,
            stage_index=1,
            function_address=0,
            replacements={
                "story/001/dialogue/01.01/0000": "《测》",
            },
            overrides={"《": 0x8FEC, "》": 0x8FEF, "测": 0x9000},
        )
        offset = result.allocations[0].arena_offset
        self.assertEqual(
            result.data[offset : offset + 13],
            b"Pilot\n\x8f\xec\x90\x00\x8f\xef\x00",
        )

    def test_menu_pool_writer_updates_direct_and_mips_pointers(self):
        base = 0x100000
        source = bytearray(0x180)
        source[0x40:0x44] = b"Old\x00"
        struct.pack_into("<I", source, 0x10, base + 0x40)
        old_hi = ((base + 0x40 + 0x8000) >> 16) & 0xFFFF
        old_lo = (base + 0x40) & 0xFFFF
        struct.pack_into("<H", source, 0x20, old_hi)
        struct.pack_into("<H", source, 0x24, old_lo)
        entry = MenuTextEntry(
            entry_id="menu/SLPS/00/0000",
            section="fixture",
            ordinal=0,
            text="Old",
            pointer_offsets=(0x10,),
            target_offsets=(0x40,),
            embedded_hi=(base + 0x20,),
            embedded_lo=(base + 0x24,),
        )
        parsed = MenuParseResult(
            friendly_name="SLPS",
            source_size=len(source),
            base_offset=base,
            entries=(entry,),
            section_names=("fixture",),
        )

        result = relocate_menu_texts_to_pool(
            bytes(source),
            parsed,
            self.table,
            replacements={"menu/SLPS/00/0000": "测试"},
            overrides={"测": 0x987E, "试": 0x987F},
            pool_start=0x100,
            pool_end=0x140,
            alignment=16,
        )

        self.assertEqual(result.allocations[0].pool_offset, 0x100)
        self.assertEqual(
            result.data[0x100:0x105],
            b"\x98\x7e\x98\x7f\x00",
        )
        self.assertEqual(
            struct.unpack_from("<I", result.data, 0x10)[0],
            base + 0x100,
        )
        new_hi = struct.unpack_from("<H", result.data, 0x20)[0]
        new_lo = struct.unpack_from("<h", result.data, 0x24)[0]
        self.assertEqual((new_hi << 16) + new_lo, base + 0x100)
        self.assertEqual(result.pool_used, 5)
        self.assertEqual(result.to_metadata()["allocation_count"], 1)

    def test_menu_pool_writer_fails_closed_on_nonzero_pool(self):
        source = bytearray(0x80)
        source[0x20:0x24] = b"Old\x00"
        source[0x60] = 1
        struct.pack_into("<I", source, 0x10, 0x1020)
        parsed = MenuParseResult(
            friendly_name="Compdata",
            source_size=len(source),
            base_offset=0x1000,
            entries=(
                MenuTextEntry(
                    entry_id="menu/Compdata/00/0000",
                    section="fixture",
                    ordinal=0,
                    text="Old",
                    pointer_offsets=(0x10,),
                    target_offsets=(0x20,),
                ),
            ),
            section_names=("fixture",),
        )
        with self.assertRaisesRegex(WritebackError, "not zero-filled"):
            relocate_menu_texts_to_pool(
                bytes(source),
                parsed,
                self.table,
                replacements={"menu/Compdata/00/0000": "New"},
                pool_start=0x60,
                pool_end=0x70,
            )

    def test_menu_pool_writer_rejects_inline_text_as_pointer(self):
        source = bytearray(0x80)
        source[0x20:0x24] = b"Old\x00"
        parsed = MenuParseResult(
            friendly_name="SLPS",
            source_size=len(source),
            base_offset=0x1000,
            entries=(
                MenuTextEntry(
                    entry_id="menu/SLPS/00/0000",
                    section="fixture",
                    ordinal=0,
                    text="Old",
                    pointer_offsets=(0x20,),
                    target_offsets=(0x20,),
                ),
            ),
            section_names=("fixture",),
        )
        with self.assertRaisesRegex(
            WritebackError,
            "direct pointer preimage mismatch",
        ):
            relocate_menu_texts_to_pool(
                bytes(source),
                parsed,
                self.table,
                replacements={"menu/SLPS/00/0000": "New"},
                pool_start=0x60,
                pool_end=0x70,
            )

    def test_fixed_menu_writer_preserves_pointers_and_deduplicates_target(self):
        source = bytearray(0x80)
        source[0x40:0x44] = b"Old\x00"
        struct.pack_into("<I", source, 0x10, 0x1040)
        entries = (
            MenuTextEntry(
                entry_id="menu/SLPS/00/0000",
                section="one",
                ordinal=0,
                text="Old",
                pointer_offsets=(0x10,),
                target_offsets=(0x40,),
            ),
            MenuTextEntry(
                entry_id="menu/SLPS/01/0000",
                section="two",
                ordinal=0,
                text="Old",
                pointer_offsets=(),
                target_offsets=(0x40,),
                embedded_hi=(0x1020,),
                embedded_lo=(0x1024,),
            ),
        )
        parsed = MenuParseResult(
            friendly_name="SLPS",
            source_size=len(source),
            base_offset=0x1000,
            entries=entries,
            section_names=("one", "two"),
        )
        result = replace_menu_texts_in_place(
            bytes(source),
            parsed,
            self.table,
            replacements={
                "menu/SLPS/00/0000": "Hi",
                "menu/SLPS/01/0000": "Hi",
            },
        )
        self.assertEqual(result.data[0x40:0x44], b"Hi\x00\x00")
        self.assertEqual(result.data[0x10:0x14], source[0x10:0x14])
        self.assertEqual(result.entry_count, 2)
        self.assertEqual(len(result.targets), 1)
        self.assertEqual(result.targets[0].capacity, 4)

    def test_fixed_menu_writer_rejects_overflow_and_partial_shared_owner(self):
        source = bytearray(0x80)
        source[0x40:0x44] = b"Old\x00"
        entries = (
            MenuTextEntry(
                entry_id="menu/SLPS/00/0000",
                section="one",
                ordinal=0,
                text="Old",
                pointer_offsets=(),
                target_offsets=(0x40,),
            ),
            MenuTextEntry(
                entry_id="menu/SLPS/01/0000",
                section="two",
                ordinal=0,
                text="Old",
                pointer_offsets=(),
                target_offsets=(0x40,),
            ),
        )
        parsed = MenuParseResult(
            friendly_name="SLPS",
            source_size=len(source),
            base_offset=0x1000,
            entries=entries,
            section_names=("one", "two"),
        )
        with self.assertRaisesRegex(WritebackError, "unselected entries"):
            replace_menu_texts_in_place(
                bytes(source),
                parsed,
                self.table,
                replacements={"menu/SLPS/00/0000": "Hi"},
            )
        with self.assertRaisesRegex(WritebackError, "overflow"):
            replace_menu_texts_in_place(
                bytes(source),
                parsed,
                self.table,
                replacements={
                    "menu/SLPS/00/0000": "Long",
                    "menu/SLPS/01/0000": "Long",
                },
            )


if __name__ == "__main__":
    unittest.main()
