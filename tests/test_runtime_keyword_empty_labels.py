from __future__ import annotations

import copy
import struct
import unittest
from types import SimpleNamespace

from tools.srwz.runtime_keywords import (
    KeywordAuthority,
    KeywordEntry,
    RuntimeKeywordError,
    apply_compdata_keyword_names,
)
from tools.srwz.text import TextTable


class RuntimeKeywordEmptyLabelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = 0x100000
        original = bytearray(0xC0)
        struct.pack_into("<II", original, 0x20, self.base + 0x80, self.base + 0x90)
        struct.pack_into("<I", original, 0x30, self.base + 0xA8)
        original[0x80] = ord("A")
        original[0x90] = ord("B")
        original[0xB0] = ord("C")
        self.original = bytes(original)
        self.authority = KeywordAuthority(
            entries=(KeywordEntry(0, "A", "", "long"), KeywordEntry(1, "B", "", "short")),
            fields=(
                {"WORD": SimpleNamespace(data=b"\x82\x60" * 8)},
                {"WORD": SimpleNamespace(data=b"\x82\x61" * 4)},
            ),
        )
        self.reference = {
            "expected": {
                "keyword_count": 2,
                "compdata_relocation_count": 1,
                "compdata_empty_label_relocation_count": 1,
            },
            "compdata_relocations": [
                {"keyword_index": 0, "donor_index": 1, "relocation_offset": 0x9A}
            ],
            "compdata_empty_label_relocations": [
                {"donor_index": 1, "pointer_offset": 0x30,
                 "source_offset": 0xA8, "relocation_offset": 0xAC}
            ],
        }

    def apply(self, current=None, reference=None):
        return apply_compdata_keyword_names(
            self.original if current is None else current,
            self.original,
            self.authority,
            TextTable(characters={}, tags={}),
            self.reference if reference is None else reference,
            runtime_base=self.base,
            pointer_table_offset=0x20,
        )

    def test_preserves_empty_label_and_unrelated_bytes_on_write_and_reread(self) -> None:
        output, report = self.apply()
        self.assertEqual(output[0x9A:0xAB], b"\x82\x60" * 8 + b"\0")
        self.assertEqual(struct.unpack_from("<I", output, 0x30)[0], self.base + 0xAC)
        self.assertEqual(output[0xAC], 0)
        allowed = set(range(0x20, 0x28)) | set(range(0x30, 0x34)) | set(range(0x90, 0xB0))
        self.assertTrue(all(a == b or i in allowed for i, (a, b) in enumerate(zip(self.original, output))))
        reread, verify = self.apply(output)
        self.assertEqual(reread, output)
        self.assertEqual(verify["changed_byte_count"], 0)
        self.assertEqual(report["empty_label_relocation_count"], 1)

    def test_undeclared_live_pointer_still_blocks_reclaim(self) -> None:
        current = bytearray(self.original)
        struct.pack_into("<I", current, 0x34, self.base + 0xAA)
        with self.assertRaisesRegex(RuntimeKeywordError, "live interior pointer"):
            self.apply(bytes(current))

    def test_nonempty_current_label_is_rejected(self) -> None:
        current = bytearray(self.original)
        current[0xA8] = ord("X")
        with self.assertRaisesRegex(RuntimeKeywordError, "empty-label text/pointer drift"):
            self.apply(bytes(current))

    def test_destination_cannot_overlap_relocated_word(self) -> None:
        reference = copy.deepcopy(self.reference)
        reference["compdata_empty_label_relocations"][0]["relocation_offset"] = 0xAA
        with self.assertRaisesRegex(RuntimeKeywordError, "empty-label text/pointer drift"):
            self.apply(reference=reference)

    def test_pointer_owner_drift_is_rejected(self) -> None:
        current = bytearray(self.original)
        struct.pack_into("<I", current, 0x30, self.base + 0xAD)
        with self.assertRaisesRegex(RuntimeKeywordError, "empty-label text/pointer drift"):
            self.apply(bytes(current))

    def test_expected_count_cannot_silently_omit_empty_label(self) -> None:
        reference = copy.deepcopy(self.reference)
        reference["compdata_empty_label_relocations"] = []
        with self.assertRaisesRegex(RuntimeKeywordError, "count drift"):
            self.apply(reference=reference)


if __name__ == "__main__":
    unittest.main()
