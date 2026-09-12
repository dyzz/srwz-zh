from __future__ import annotations

import copy
import base64
import json
import sys
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.ui_headings import UiHeadingError, apply_draw_patches, apply_index_cells, lock, sha


class UiHeadingTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "config/assets/ui-headings-zh.json").read_text())
        self.patches = self.config["draw_patches"]
        source = bytearray(b"\xa5" * self.config["source_drawings"]["size"])
        for patch in self.patches:
            start = patch["offset"]
            source[start:start + 34] = bytes.fromhex(patch["before_hex"])
        self.source = bytes(source)

    def test_drawing_edits_preserve_surroundings_topology_material_and_colors(self):
        output = apply_draw_patches(self.source, self.patches)
        owned = set()
        for patch in self.patches:
            start = patch["offset"]
            before, after = self.source[start:start + 34], output[start:start + 34]
            owned.update(range(start, start + 34))
            self.assertEqual(before[:4], after[:4])
            self.assertEqual(before[5:10], after[5:10])
            self.assertEqual(before[4] & 0xF0, after[4] & 0xF0)
        self.assertEqual(len(output), len(self.source))
        self.assertTrue(all(output[i] == self.source[i] for i in range(len(output)) if i not in owned))

    def test_preimage_and_duplicate_ownership_fail_closed(self):
        corrupt = bytearray(self.source)
        corrupt[self.patches[0]["offset"] + 1] ^= 1
        with self.assertRaisesRegex(UiHeadingError, "preimage"):
            apply_draw_patches(bytes(corrupt), self.patches)
        with self.assertRaisesRegex(UiHeadingError, "overlaps"):
            apply_draw_patches(self.source, self.patches + [self.patches[0]])

    def test_accidental_color_or_termination_changes_are_rejected(self):
        for offset in (0, 5, 6, 9):
            patches = copy.deepcopy(self.patches)
            after = bytearray.fromhex(patches[0]["after_hex"])
            after[offset] ^= 1
            patches[0]["after_hex"] = after.hex()
            with self.assertRaisesRegex(UiHeadingError, "flags or color"):
                apply_draw_patches(self.source, patches)

    def test_shared_english_letters_and_other_help_headings_are_not_edited(self):
        # DATA HELP is assembled from eight letters twice (shadow + foreground).
        # Its old source letters also feed CHARA, SYSTEM and other headings.
        data_help = [p for p in self.patches if p["chunk_index"] == 1167]
        self.assertEqual(len(data_help), 16)
        self.assertEqual(sum(bytes.fromhex(p["after_hex"])[10:30] == bytes(20) for p in data_help), 12)
        chunks = {p["chunk_index"] for p in self.patches}
        self.assertTrue(chunks.isdisjoint({20, 143, 937, 938, 939, 975, 1087, 1088, 1246, 1247}))
        self.assertTrue(all(p["after_hex"][8:10].endswith("4") for p in self.patches))
        self.assertTrue(all(c["rect"][1] in (80, 100) for c in self.config["cells"]))

    def test_odd_x_cell_preserves_neighbor_nibbles_clut_and_surroundings(self):
        # Odd x crosses two packed bytes: [2, 10, 2, 10] -> [2, 1, 15, 10].
        # Include a second row to distinguish linear storage from swizzling.
        chunk = b"header" + b"\xa2" * 32768 + b"palette-and-trailing-data"
        archive = b"prefix" + chunk + b"suffix"
        config = {
            "texture_chunk": {"start": 6, "end": 6 + len(chunk), **lock(chunk)},
            "cells": [{"id": "test", "rect": [1, 1, 2, 2],
                       "source_indices_sha256": sha(bytes([10, 2, 10, 2]))}],
        }
        pixels = bytes([1, 15, 7, 8])
        snapshot = {"cells": [{"id": "test", "indices": {
            **lock(pixels), "zlib_base64": base64.b64encode(zlib.compress(pixels)).decode(),
        }}]}
        picture = SimpleNamespace(width=256, height=256, image_type=4, offset=0,
                                  header_size=6, image_size=32768)
        with patch("srwz.ui_headings.parse_tim2", return_value=SimpleNamespace(pictures=[picture])):
            output = apply_index_cells(archive, config, snapshot)
        expected = bytearray(archive)
        expected[12 + 128:12 + 130] = b"\x12\xaf"
        expected[12 + 256:12 + 258] = b"\x72\xa8"
        self.assertEqual(output, bytes(expected))

        config["cells"][0]["source_indices_sha256"] = sha(bytes(4))
        with patch("srwz.ui_headings.parse_tim2", return_value=SimpleNamespace(pictures=[picture])):
            with self.assertRaisesRegex(UiHeadingError, "preimage"):
                apply_index_cells(archive, config, snapshot)


if __name__ == "__main__":
    unittest.main()
