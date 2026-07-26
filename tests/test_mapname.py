import unittest

from tools.srwz.mapname import (
    MAP_NAME_RECORD_SIZE,
    MapNameError,
    parse_map_names,
)


def record(text: str, *, padding_byte: int = 0) -> bytes:
    payload = text.encode("shift_jis") + b"\0"
    return payload + bytes([padding_byte]) * (MAP_NAME_RECORD_SIZE - len(payload))


class MapNameTests(unittest.TestCase):
    def test_parses_fixed_shift_jis_records_with_stable_ids(self):
        records = parse_map_names(record("月面") + record("宇宙空間（１）"))

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].stable_id, "map/name/000")
        self.assertEqual(records[1].offset, 256)
        self.assertEqual(records[1].text, "宇宙空間（１）")

    def test_rejects_partial_record(self):
        with self.assertRaisesRegex(MapNameError, "not divisible"):
            parse_map_names(b"x")

    def test_rejects_missing_terminator(self):
        with self.assertRaisesRegex(MapNameError, "no NUL terminator"):
            parse_map_names(b"x" * MAP_NAME_RECORD_SIZE)

    def test_rejects_nonzero_padding(self):
        with self.assertRaisesRegex(MapNameError, "nonzero padding"):
            parse_map_names(record("月面", padding_byte=1))

    def test_rejects_invalid_shift_jis(self):
        raw = b"\x82\0" + bytes(MAP_NAME_RECORD_SIZE - 2)
        with self.assertRaisesRegex(MapNameError, "not valid Shift-JIS"):
            parse_map_names(raw)


if __name__ == "__main__":
    unittest.main()
