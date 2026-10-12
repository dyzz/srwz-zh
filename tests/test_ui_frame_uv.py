from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.ui_frame_uv import (apply_frame_uv_patches, load_frame_uv_contract,
                            verify_frame_uv_patches, frame_uv_preimage_for_verification)
from srwz.ui_headings import UiHeadingError


class UiFrameUvTests(unittest.TestCase):
    def make_source(self, contract):
        # Synthetic surrounding bytes exercise non-target preservation without
        # checking a complete game resource into the repository.
        source = bytearray(b"\xa5" * contract["member_size"])
        expected = bytearray(source)
        for patch in contract["patches"]:
            offset = patch["offset"]
            source[offset:offset + 22] = bytes.fromhex(patch["before_hex"])
            expected[offset:offset + 22] = bytes.fromhex(patch["after_hex"])
        chunk = contract["chunk"]
        a, b = chunk["start"], chunk["end"]
        chunk["sha256"] = hashlib.sha256(source[a:b]).hexdigest()
        chunk["output_sha256"] = hashlib.sha256(expected[a:b]).hexdigest()
        return bytes(source)

    def setUp(self):
        self.contract = json.loads((ROOT / "config/assets/ui-headings-zh.json").read_text())["shared_frame_uv"]
        self.source = self.make_source(self.contract)

    def test_complete_style_only_changes_nine_left_u1_bytes(self):
        output, report = apply_frame_uv_patches(self.source, self.contract)
        offsets = {p["offset"] + 20 for p in self.contract["patches"]}
        self.assertEqual(len(output), len(self.source))
        self.assertEqual({i for i, (a, b) in enumerate(zip(self.source, output)) if a != b}, offsets)
        for offset in offsets:
            self.assertEqual((self.source[offset], output[offset]), (24, 23))
        self.assertEqual(report["byte_count"], 9)
        self.assertEqual(apply_frame_uv_patches(self.source, self.contract), (output, report))

    def test_reject_drift_in_mirrors_headers_or_other_chunk_bytes(self):
        owned = {p["offset"] + 20 for p in self.contract["patches"]}
        for offset in (self.contract["chunk"]["start"], self.contract["chunk"]["end"] - 1, min(owned)):
            corrupt = bytearray(self.source)
            corrupt[offset] ^= 1
            with self.assertRaisesRegex(UiHeadingError, "preimage"):
                apply_frame_uv_patches(bytes(corrupt), self.contract)
        output, _ = apply_frame_uv_patches(self.source, self.contract)
        with self.assertRaisesRegex(UiHeadingError, "preimage"):
            apply_frame_uv_patches(output, self.contract)

    def test_reject_edits_to_vertices_v_colors_or_mirrors(self):
        for byte in (0, 4, 5, 6, 10, 14, 18, 19, 21):
            contract = copy.deepcopy(self.contract)
            after = bytearray.fromhex(contract["patches"][0]["after_hex"])
            after[byte] ^= 1
            contract["patches"][0]["after_hex"] = after.hex()
            with self.assertRaisesRegex(UiHeadingError, "U1-only"):
                apply_frame_uv_patches(self.source, contract)

    def test_reject_missing_layer_duplicate_or_out_of_bounds(self):
        contract = copy.deepcopy(self.contract)
        contract["patches"].pop()
        with self.assertRaisesRegex(UiHeadingError, "three left"):
            apply_frame_uv_patches(self.source, contract)
        contract = copy.deepcopy(self.contract)
        contract["patches"][-1] = contract["patches"][0]
        with self.assertRaisesRegex(UiHeadingError, "overlaps"):
            apply_frame_uv_patches(self.source, contract)
        contract = copy.deepcopy(self.contract)
        contract["patches"][0]["offset"] = 0
        with self.assertRaisesRegex(UiHeadingError, "bounds"):
            apply_frame_uv_patches(self.source, contract)

    def test_each_edition_rejects_wrong_layout_and_verifies_complete_output(self):
        for edition in ("original", "best", "sp"):
            with self.subTest(edition=edition):
                contract = load_frame_uv_contract(ROOT, edition)
                chunk = contract["chunk"]
                source = self.make_source(contract)
                output, report = apply_frame_uv_patches(source, contract)
                verified = verify_frame_uv_patches(output, contract)
                self.assertEqual(frame_uv_preimage_for_verification(output, contract), source)
                self.assertTrue(all(report[k] == v for k, v in verified.items()))
                with self.assertRaisesRegex(UiHeadingError, "patched chunk"):
                    verify_frame_uv_patches(bytes(source), contract)
                corrupt = bytearray(output)
                corrupt[chunk["end"] - 1] ^= 1
                with self.assertRaisesRegex(UiHeadingError, "patched chunk"):
                    verify_frame_uv_patches(bytes(corrupt), contract)
                wrong = load_frame_uv_contract(ROOT, "original" if edition == "sp" else "sp")
                with self.assertRaisesRegex(UiHeadingError, "member size"):
                    apply_frame_uv_patches(bytes(source), wrong)


if __name__ == "__main__":
    unittest.main()
