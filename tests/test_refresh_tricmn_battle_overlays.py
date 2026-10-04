import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from refresh_tricmn_battle_overlays import validate_member_delta


class FrozenTricmnIsoUpdateTest(unittest.TestCase):
    def test_only_image_ranges_can_change(self):
        original = bytes(range(32))
        pictures = [dict(image_offset=8, image_size=4),
                    dict(image_offset=20, image_size=4)]
        edited = bytearray(original)
        edited[8:12] = bytes(4)
        edited[20:24] = bytes(4)
        self.assertEqual(validate_member_delta(original, bytes(edited), pictures),
                         [(8, 12), (20, 24)])
        for protected_at in (0, 7, 12, 19, 24, 31):
            with self.subTest(protected_at=protected_at):
                corrupted = bytearray(edited)
                corrupted[protected_at] ^= 1
                with self.assertRaisesRegex(ValueError, 'escaped|trailing'):
                    validate_member_delta(original, bytes(corrupted), pictures)

    def test_size_and_invalid_ranges_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'size'):
            validate_member_delta(bytes(8), bytes(9), [])
        for ranges in ([dict(image_offset=-1, image_size=2)],
                       [dict(image_offset=4, image_size=8)],
                       [dict(image_offset=2, image_size=4), dict(image_offset=3, image_size=2)]):
            with self.subTest(ranges=ranges):
                with self.assertRaisesRegex(ValueError, 'geometry'):
                    validate_member_delta(bytes(8), bytes(8), ranges)
