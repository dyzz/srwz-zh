from __future__ import annotations

import unittest
from pathlib import Path

from tools.srwz.mapmodel_layout import member_for_map, member_offsets, parse_member

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
        cls.maps = {}
        for map_id in (40, 41, 72):
            m = member_for_map(map_id)
            cls.maps[map_id] = parse_member(decode_production(archive[offsets[m]:offsets[m + 1]]).output)

    def test_header_sections_and_map_size(self) -> None:
        requiem = self.maps[40]  # 第50話 STAGE115 loads map 40 = member 41
        self.assertEqual((requiem.width, requiem.height), (35, 35))
        self.assertEqual(len(requiem.sections), 8)
        self.assertEqual(requiem.sections[1], (0xA30, 0xA90))  # terrain-name records
        self.assertEqual(len(requiem.tiles), 35 * 35)
        self.assertEqual((self.maps[41].width, self.maps[41].height), (40, 40))
        self.assertEqual(self.maps[40].tile(0, 0)[0], 0)

    def test_models_are_hig_plugin_blocks_and_stage_objects(self) -> None:
        requiem = self.maps[40]
        self.assertEqual([name for name, _ in requiem.models[0].plugins], ["Frame", "Micro", "Shape", "Hrchy", "Tex2d"])
        # STAGE115's entry initialises models 0-5, STAGE114's (map 41) 0-4 and
        # STAGE047's (map 72) 1-5; LRPS2 shows 5 / 6 objects on maps 41 / 72
        self.assertEqual(len(requiem.stage_objects), 6)
        self.assertEqual(len(self.maps[41].stage_objects), 5)
        self.assertEqual(len(self.maps[72].stage_objects), 6)
        self.assertEqual(sum(m.animated for m in self.maps[72].stage_objects), 5)

    def test_hierarchy_nodes_and_animation_lengths_match_the_scripts(self) -> None:
        # the last key time is the frame the stage scripts animate to with 0x46 m,5,v
        self.assertEqual({o.key_times[-1] for o in self.maps[41].stage_objects[1:]}, {999})  # STAGE114 0x46 m,5,999
        self.assertEqual({o.key_times[-1] for o in self.maps[40].stage_objects[1:]}, {600})  # STAGE115 0x46 m,5,0x258
        self.assertEqual(self.maps[72].stage_objects[5].key_times[-1], 3400)  # STAGE047 runs to 3399
        self.assertEqual([o.nodes for o in self.maps[41].stage_objects], [1, 3, 3, 13, 44])


if __name__ == "__main__":
    unittest.main()
