from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from tools.srwz.psmt4 import swizzle_psmt4, unswizzle_psmt4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRICMN = PROJECT_ROOT / "work/disc/BTL/TRICMN.BIN"


class Psmt4Test(unittest.TestCase):
    def test_known_good_512_by_256_tricmn_fixture(self) -> None:
        source = TRICMN.read_bytes()
        stored = source[0x46CD0:0x56CD0]
        self.assertEqual(
            hashlib.sha256(stored).hexdigest(),
            "53e123d8487e78e7101b10f427f4b197fd24c94b289e8de9c32f437fbd129ab3",
        )
        logical = unswizzle_psmt4(
            stored, 512, 256, row_major_pages=True
        )
        self.assertEqual(
            hashlib.sha256(logical).hexdigest(),
            "1e0632e74552a6900fd6d95905b4de40506bfed9032e0c97ae800420b6949078",
        )
        self.assertEqual(
            swizzle_psmt4(logical, 512, 256, row_major_pages=True),
            stored,
        )


if __name__ == "__main__":
    unittest.main()
