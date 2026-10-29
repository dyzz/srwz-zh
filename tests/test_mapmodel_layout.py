from __future__ import annotations

import unittest
from pathlib import Path

from tools.srwz.mapmodel_layout import member_offsets, parse_member

ROOT = Path(__file__).resolve().parents[1]
SLPS = ROOT / "work" / "disc" / "SLPS_258.87"
MAPMODEL = ROOT / "work" / "disc" / "MAP" / "MAPMODEL.BIN"


@unittest.skipUnless(SLPS.exists() and MAPMODEL.exists(), "original disc data is not extracted")
class MapModelLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tools.srwz.codec import decode_production

        offsets = member_offsets(SLPS.read_bytes())
        archive = MAPMODEL.read_bytes()
        cls.members = {m: parse_member(decode_production(archive[offsets[m]:offsets[m + 1]]).output) for m in (40, 41, 45)}

    def test_header_sections_and_map_size(self) -> None:
        requiem = self.members[41]  # 第50話 Requiem base (STAGE114)
        self.assertEqual((requiem.width, requiem.height), (35, 35))
        self.assertEqual(len(requiem.sections), 8)
        self.assertEqual(requiem.sections[1], (0xA30, 0xA90))  # terrain-name records
        self.assertEqual(len(requiem.tiles), 35 * 35)
        self.assertEqual((self.members[40].width, self.members[40].height), (40, 40))

    def test_models_are_hig_plugin_blocks(self) -> None:
        requiem = self.members[41]
        self.assertEqual([name for name, _ in requiem.models[0].plugins], ["Frame", "Micro", "Shape", "Hrchy", "Tex2d"])
        # five animated stage objects: STAGE114's entry initialises models 0-4
        self.assertEqual(len(requiem.stage_objects), 5)
        self.assertEqual(len(self.members[40].stage_objects), 2)
        self.assertEqual(len(self.members[45].stage_objects), 1)


if __name__ == "__main__":
    unittest.main()
