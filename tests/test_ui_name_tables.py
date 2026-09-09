import copy
import hashlib
import struct
import unittest

from tools.srwz.text import TextTable
from tools.srwz.ui_name_tables import MAP_INDICES, translate_names, verify_name_table


class NameTableTests(unittest.TestCase):
    def setUp(self):
        self.table = TextTable({0x8140: "\u3000"}, {})
        self.source = bytearray(29792)
        struct.pack_into("<H", self.source, 32, 104)
        self.rows = []
        for i in range(104):
            off = 34 + i * 286
            self.source[off:off + 2] = b"A\0"
            self.source[off + 28:off + 286] = bytes([i + 1]) * 258
            self.rows.append({"index": i, "source": "A",
                              "source_text_sha256": hashlib.sha256(b"A").hexdigest(),
                              "translation": "B", "editorial_status": "reviewed"})
        self.source = bytes(self.source)

    def write(self, rows=None, current=None):
        return translate_names(self.source, current or self.source, rows or self.rows,
                               kind="squad", table=self.table, overrides={})

    def test_squad_conditions_survive_and_final_readback_detects_corruption(self):
        output, report = self.write()
        self.assertEqual(report["entry_count"], 104)
        for i in range(104):
            off = 34 + 286 * i
            self.assertEqual(output[off + 28:off + 286], self.source[off + 28:off + 286])
        verify_name_table(self.source, output, self.rows, kind="squad",
                          source_table=self.table, runtime_table=self.table)
        changed = bytearray(output)
        changed[34 + 28] ^= 1
        with self.assertRaisesRegex(ValueError, "non-name"):
            verify_name_table(self.source, changed, self.rows, kind="squad",
                              source_table=self.table, runtime_table=self.table)
        changed = bytearray(output)
        changed[34] = ord("C")
        with self.assertRaisesRegex(ValueError, "text mismatch"):
            verify_name_table(self.source, changed, self.rows, kind="squad",
                              source_table=self.table, runtime_table=self.table)

    def test_overflow_and_missing_records_fail(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["translation"] = "B" * 28
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.write(rows)
        with self.assertRaisesRegex(ValueError, "missing"):
            self.write(self.rows[:-1])

    def test_unknown_current_preimage_and_source_drift_fail(self):
        changed = bytearray(self.source)
        changed[34] = ord("C")
        with self.assertRaisesRegex(ValueError, "preimage"):
            self.write(current=changed)
        rows = copy.deepcopy(self.rows)
        rows[0]["source"] = "C"
        with self.assertRaisesRegex(ValueError, "original text"):
            self.write(rows)

    def test_map_placeholders_remain_exact(self):
        source = bytearray(195 * 256)
        for i in range(195):
            source[i * 256:i * 256 + 2] = b"A\0"
        rows = [dict(self.rows[0], index=i) for i in MAP_INDICES]
        output, report = translate_names(bytes(source), bytes(source), rows, kind="map",
                                         table=self.table, overrides={})
        self.assertEqual(report["entry_count"], 73)
        for i in set(range(195)) - set(MAP_INDICES):
            self.assertEqual(output[i * 256:(i + 1) * 256], source[i * 256:(i + 1) * 256])


if __name__ == "__main__":
    unittest.main()
