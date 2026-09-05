import hashlib
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from tools import build_full_story_components as full
from tools import build_text_update_iso as text_build
from tools import ui_atlas
from tools import rebuild_zh_font
from tools import build_iso
from tools.srwz.patch_audit import PatchAuditError, changed_offsets
from tools.srwz.psmt4 import Psmt4Error, swizzle_psmt4, unswizzle_psmt4


def write_json(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return lock(root, path)


def lock(root, path):
    data = path.read_bytes()
    return {"path": str(path.relative_to(root)), "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


class BuildOptimizationTests(unittest.TestCase):




    def test_sparse_diff_matches_byte_oracle_across_block_edges(self):
        rng = random.Random(42)
        for size in (0, 1, 4095, 4096, 4097, 16001):
            before = bytes(rng.randrange(256) for _ in range(size))
            for dense in (False, True):
                after = bytearray(before)
                positions = range(size) if dense else (0, 4095, 4096, 8192, size - 1)
                for offset in positions:
                    if 0 <= offset < size:
                        after[offset] ^= 255
                expected = tuple(i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1])
                self.assertEqual(changed_offsets(before, bytes(after)), expected)
        with self.assertRaises(PatchAuditError):
            changed_offsets(b"a", b"ab")

    def test_psmt4_matches_preoptimization_golden_layouts(self):
        cases = (
            (32, 32, False, "c299cd3679ae2e5bca94e9b227f354e4886cf8fbf879fd74340bfb54a11fe249"),
            (64, 64, False, "3e18c4f732bb8e98999ba192bcfa2c0a7a96f48b41a0b6c0256fea10e6536d8d"),
            (128, 128, False, "8e8a5b3d714e3956f8ddf9e5c903623200a9ad79d1d6e0bf60ee9c95eec189e4"),
            (256, 256, False, "12e4e8b97b5a6ae62f60ed31957b90d2ff45605e42b56783002bd31cb6b5d703"),
            (512, 256, True, "9bc1893ec384d3552467bebe67cf2efad62940609184c722baba0769e60bcdc8"),
            (256, 512, True, "aae86d95e037ffc8cd60fd66c5723dbb9c3d6cb224461218ee7d26deca3e8eb3"),
        )
        for width, height, row_major, digest in cases:
            logical = bytes((i * 7 + i // width) % 16 for i in range(width * height))
            for _ in range(2):  # Both the first validation and the cached permutation.
                stored = swizzle_psmt4(logical, width, height, row_major_pages=row_major)
                self.assertEqual(hashlib.sha256(stored).hexdigest(), digest)
                self.assertEqual(unswizzle_psmt4(stored, width, height, row_major_pages=row_major), logical)
        with self.assertRaises(Psmt4Error):
            swizzle_psmt4(bytes([16]) * 1024, 32, 32)
        with self.assertRaises(Psmt4Error):
            unswizzle_psmt4(b"", 32, 32)





    def test_written_atlas_corruption_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "work/archive.bin"
            path.parent.mkdir()
            path.write_bytes(b"bad")
            with patch.object(ui_atlas, "PROJECT_ROOT", root), patch.object(ui_atlas, "WORK_ROOT", root / "work"):
                with self.assertRaisesRegex(SystemExit, "written output differs"):
                    ui_atlas._verify_written_build({"outputs": {"validation": "work/report.json"}}, {path: b"good"}, {})




if __name__ == "__main__":
    unittest.main()
