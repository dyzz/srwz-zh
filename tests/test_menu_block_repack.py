from __future__ import annotations

import struct
import unittest

from tools.srwz.menu import MenuParseResult, MenuTextEntry
from tools.srwz.text import TextTable, decode_text
from tools.srwz.writeback import WritebackError
from tools.srwz.writers import repack_menu_texts_in_block


BASE = 0x1000
BLOCK_START = 0x100
BLOCK_END = 0x140


def _entry(entry_id: str, ordinal: int, text: str, pointers, target: int, **extra):
    return MenuTextEntry(
        entry_id=entry_id,
        section="Stage Name",
        ordinal=ordinal,
        text=text,
        pointer_offsets=tuple(pointers),
        target_offsets=tuple(target for _ in pointers),
        **extra,
    )


class MenuBlockRepackTest(unittest.TestCase):
    """Synthetic COMPDATA-like buffer: pointer table, text block, other text."""

    @staticmethod
    def _fixture() -> tuple[bytes, MenuParseResult]:
        data = bytearray(0x200)
        # Text block: three strings at 8-byte aligned offsets plus zero padding.
        data[0x100:0x102] = b"A\x00"
        data[0x108:0x10B] = b"BB\x00"
        data[0x110:0x112] = b"C\x00"
        # Unrelated text outside the block.
        data[0x180:0x182] = b"Z\x00"
        # Pointer table: two pointers share the first string.
        for offset, target in ((0x00, 0x100), (0x04, 0x100), (0x08, 0x108),
                               (0x0C, 0x110), (0x10, 0x180)):
            struct.pack_into("<I", data, offset, BASE + target)
        # MIPS HI/LO pair addressing the second string.
        address = BASE + 0x108
        struct.pack_into("<H", data, 0x40, ((address + 0x8000) >> 16) & 0xFFFF)
        struct.pack_into("<h", data, 0x44, address & 0xFFFF)
        entries = (
            _entry("t/0", 0, "A", (0x00, 0x04), 0x100),
            _entry(
                "t/1", 1, "BB", (0x08,), 0x108,
                embedded_hi=(BASE + 0x40,), embedded_lo=(BASE + 0x44,),
            ),
            _entry("t/2", 2, "C", (0x0C,), 0x110),
            _entry("o/0", 0, "Z", (0x10,), 0x180),
        )
        parsed = MenuParseResult(
            friendly_name="Test",
            source_size=len(data),
            base_offset=BASE,
            entries=entries,
            section_names=("Stage Name", "Other"),
        )
        return bytes(data), parsed

    @staticmethod
    def _repack(data, parsed, replacements, **kwargs):
        return repack_menu_texts_in_block(
            data,
            parsed,
            TextTable(characters={}, tags={}),
            replacements=replacements,
            block_start=BLOCK_START,
            block_end=BLOCK_END,
            **kwargs,
        )

    def test_round_trip_relayout_updates_every_reference(self) -> None:
        data, parsed = self._fixture()
        replacements = {"t/0": "Longer title", "t/1": "B", "t/2": "Third one"}

        result = self._repack(data, parsed, replacements)

        self.assertEqual(len(result.allocations), 3)
        offsets = [item.block_offset for item in result.allocations]
        self.assertEqual(offsets, [0x100, 0x110, 0x118])
        self.assertTrue(all(offset % 8 == 0 for offset in offsets))
        self.assertEqual(result.block_used, 0x118 + 10 - BLOCK_START)
        self.assertEqual(result.source_owned_bytes, 2 + 3 + 2)
        table = TextTable(characters={}, tags={})
        for allocation in result.allocations:
            decoded = decode_text(result.data, allocation.block_offset, table)
            self.assertEqual(decoded.text, replacements[allocation.entry_ids[0]])
        for pointer_offset, expected in ((0x00, 0x100), (0x04, 0x100),
                                         (0x08, 0x110), (0x0C, 0x118)):
            self.assertEqual(
                struct.unpack_from("<I", result.data, pointer_offset)[0],
                BASE + expected,
            )
        hi = struct.unpack_from("<H", result.data, 0x40)[0]
        lo = struct.unpack_from("<h", result.data, 0x44)[0]
        self.assertEqual((hi << 16) + lo, BASE + 0x110)
        # Untouched regions stay byte-exact and the block tail is zero.
        self.assertEqual(result.data[0x14:0x40], data[0x14:0x40])
        self.assertEqual(result.data[0x46:0x100], data[0x46:0x100])
        self.assertEqual(result.data[BLOCK_END:], data[BLOCK_END:])
        self.assertFalse(any(result.data[0x118 + 10:BLOCK_END]))
        metadata = result.to_metadata()
        self.assertEqual(metadata["allocation_count"], 3)
        self.assertEqual(metadata["moved_allocation_count"], 2)

    def test_overflow_fails_closed(self) -> None:
        data, parsed = self._fixture()
        with self.assertRaisesRegex(WritebackError, "overflow"):
            self._repack(
                data, parsed,
                {"t/0": "x" * 30, "t/1": "y" * 20, "t/2": "z" * 20},
            )

    def test_unowned_non_zero_block_byte_fails_closed(self) -> None:
        data, parsed = self._fixture()
        polluted = bytearray(data)
        polluted[0x130] = 0x41
        with self.assertRaisesRegex(WritebackError, "unowned non-zero bytes at 0x130"):
            self._repack(bytes(polluted), parsed, {"t/0": "A", "t/1": "BB", "t/2": "C"})

    def test_unselected_block_entry_fails_closed(self) -> None:
        data, parsed = self._fixture()
        with self.assertRaisesRegex(WritebackError, "t/2 targets the block but is not selected"):
            self._repack(data, parsed, {"t/0": "A", "t/1": "BB"})

    def test_selected_entry_outside_block_fails_closed(self) -> None:
        data, parsed = self._fixture()
        with self.assertRaisesRegex(WritebackError, "o/0 owns a text target outside the block"):
            self._repack(data, parsed, {"t/0": "A", "t/1": "BB", "t/2": "C", "o/0": "Z"})

    def test_pointer_preimage_mismatch_fails_closed(self) -> None:
        data, parsed = self._fixture()
        broken = bytearray(data)
        struct.pack_into("<I", broken, 0x04, BASE + 0x102)
        with self.assertRaisesRegex(WritebackError, "t/0 direct pointer preimage mismatch"):
            self._repack(bytes(broken), parsed, {"t/0": "A", "t/1": "BB", "t/2": "C"})

    def test_source_text_preimage_mismatch_fails_closed(self) -> None:
        data, parsed = self._fixture()
        drifted = bytearray(data)
        drifted[0x100] = ord("Q")
        with self.assertRaisesRegex(WritebackError, "t/0 source text preimage mismatch"):
            self._repack(bytes(drifted), parsed, {"t/0": "A", "t/1": "BB", "t/2": "C"})

    def test_conflicting_shared_target_payloads_fail_closed(self) -> None:
        data, parsed = self._fixture()
        entries = list(parsed.entries)
        entries.append(_entry("t/3", 3, "A", (0x00,), 0x100))
        shared = MenuParseResult(
            friendly_name="Test",
            source_size=len(data),
            base_offset=BASE,
            entries=tuple(entries),
            section_names=parsed.section_names,
        )
        with self.assertRaisesRegex(WritebackError, "conflicting replacement payloads"):
            self._repack(
                data, shared,
                {"t/0": "A", "t/1": "BB", "t/2": "C", "t/3": "different"},
            )

    def test_inline_record_is_rejected(self) -> None:
        data, parsed = self._fixture()
        entries = list(parsed.entries)
        entries[2] = _entry("t/2", 2, "C", (0x110,), 0x110)
        inline = MenuParseResult(
            friendly_name="Test",
            source_size=len(data),
            base_offset=BASE,
            entries=tuple(entries),
            section_names=parsed.section_names,
        )
        with self.assertRaisesRegex(WritebackError, "pointer site lies inside the text block"):
            self._repack(data, inline, {"t/0": "A", "t/1": "BB", "t/2": "C"})


if __name__ == "__main__":
    unittest.main()
