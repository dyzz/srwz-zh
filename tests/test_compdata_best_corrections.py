import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from srwz.compdata_best_corrections import (
    PROFILE_ID,
    apply_compdata_best_corrections,
    audit_compdata_best_corrections,
)


class CompdataBestCorrectionsTests(unittest.TestCase):
    def setUp(self):
        self.config = {"profile_id": PROFILE_ID}
        # Nonzero sentinels expose unintended writes into text, code or tables.
        self.data = bytearray(b"\xA5" * 524032)
        self.data[:4] = b"MWo3"
        for offset, width, value in (
            (8, 4, 0x6D6800),
            (0x7120, 2, 116), (0x7165, 1, 1),
            (0x59F60, 2, 800), (0x59F9D, 1, 21), (0x59F9E, 2, 315),
            (0x56C1C, 2, 607), (0x56C59, 1, 17), (0x56C5A, 2, 252),
            (0x5B02E, 2, 254), (0x5B1B0, 2, 316),
            (0x5D4FF, 1, 18), (0x5D5C0, 1, 21),
        ):
            self.data[offset:offset + width] = value.to_bytes(width, "little")
        self.data = bytes(self.data)

    def test_exact_four_byte_delta_and_complete_u16_values(self):
        patched, report = apply_compdata_best_corrections(self.data, self.config)
        delta = {i: (a, b) for i, (a, b) in enumerate(zip(self.data, patched)) if a != b}
        self.assertEqual(delta, {
            0x7165: (1, 0), 0x59F9E: (0x3B, 0x3C),
            0x5B02E: (0xFE, 0xFC), 0x5D4FF: (18, 17),
        })
        self.assertEqual(patched[0x59F9E:0x59FA0], b"\x3C\x01")
        self.assertEqual(patched[0x5B02E:0x5B030], b"\xFC\x00")
        self.assertEqual(len(patched), len(self.data))
        self.assertTrue(report["embedded_code_unchanged"])
        self.assertEqual(report["changed_byte_count"], 4)
        self.assertTrue(audit_compdata_best_corrections(patched, self.config)["all_corrected_fields_exact"])

    def test_high_byte_drift_in_either_u16_is_rejected_before_write(self):
        for offset in (0x59F9F, 0x5B02F):
            with self.subTest(offset=offset):
                corrupt = bytearray(self.data)
                corrupt[offset] ^= 1
                before = bytes(corrupt)
                with self.assertRaisesRegex(ValueError, "preimage drift"):
                    apply_compdata_best_corrections(before, self.config)
                self.assertEqual(bytes(corrupt), before)

    def test_wrong_owner_or_duplicate_association_is_rejected(self):
        for offset in (0x7120, 0x59F60, 0x56C1C, 0x56C59, 0x56C5A, 0x5B1B0):
            corrupt = bytearray(self.data)
            corrupt[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, "owner/association drift"):
                apply_compdata_best_corrections(bytes(corrupt), self.config)

    def test_native_best_layout_and_truncation_are_rejected(self):
        best = bytearray(self.data)
        best[8:12] = (0x6D7000).to_bytes(4, "little")
        for data in (bytes(best), self.data[:-1]):
            with self.assertRaisesRegex(ValueError, "Original decoded layout"):
                apply_compdata_best_corrections(data, self.config)

    def test_readback_requires_all_four_corrections_and_full_field_width(self):
        patched, _ = apply_compdata_best_corrections(self.data, self.config)
        for offset in (0x7165, 0x59F9E, 0x5B02E, 0x5D4FF, 0x59F9F, 0x5B02F):
            corrupt = bytearray(patched)
            corrupt[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, "readback mismatch"):
                audit_compdata_best_corrections(bytes(corrupt), self.config)

    def test_reapplication_and_missing_profile_fail_closed(self):
        patched, _ = apply_compdata_best_corrections(self.data, self.config)
        with self.assertRaisesRegex(ValueError, "preimage drift"):
            apply_compdata_best_corrections(patched, self.config)
        for config in (None, {}, {"profile_id": "best-layout"}):
            with self.assertRaisesRegex(ValueError, "profile drift"):
                apply_compdata_best_corrections(self.data, config)


if __name__ == "__main__":
    unittest.main()
