import copy
import unittest
from hashlib import sha256

from tools.srwz.ui_frame_joins import apply_frame_joins, frame_join_preimage_for_verification
from tools.srwz.ui_headings import UiHeadingError


class FrameJoinTests(unittest.TestCase):
    def setUp(self):
        self.before = b"head\x40\x80\x40\x17tail"
        self.after = b"head\x3f\x7e\x3e\x17tail"
        self.contract = {
            "member_size": len(self.before),
            "chunks": [{
                "index": 749, "start": 4, "end": 8,
                "before_sha256": sha256(self.before[4:8]).hexdigest(),
                "after_sha256": sha256(self.after[4:8]).hexdigest(),
                "changes": [
                    {"offset": 0, "before": 64, "after": 63},
                    {"offset": 1, "before": 128, "after": 126},
                    {"offset": 2, "before": 64, "after": 62},
                ],
            }],
        }

    def test_apply_and_reconstruct(self):
        patched, report = apply_frame_joins(self.before, self.contract)
        self.assertEqual(patched, self.after)
        self.assertEqual(report["byte_offsets"], [4, 5, 6])
        self.assertEqual(frame_join_preimage_for_verification(patched, self.contract), (self.before, report))

    def test_full_chunk_drift_is_rejected_in_both_directions(self):
        for payload, transform in (
            (self.before, apply_frame_joins),
            (self.after, frame_join_preimage_for_verification),
        ):
            with self.subTest(transform=transform.__name__), self.assertRaises(UiHeadingError):
                transform(payload[:7] + b"\xff" + payload[8:], self.contract)

    def test_duplicate_or_out_of_range_byte_is_rejected(self):
        for offset in (2, 4):
            contract = copy.deepcopy(self.contract)
            contract["chunks"][0]["changes"].append({"offset": offset, "before": 64, "after": 63})
            with self.subTest(offset=offset), self.assertRaises(UiHeadingError):
                apply_frame_joins(self.before, contract)
