import json
import unittest
from pathlib import Path

from tools.srwz.codec import decode_production as decode
from tools.srwz.font import sha256_bytes
from tools.srwz.world_map_titles import (
    index_bbox,
    pack_vertical_linear_4bpp,
    replace_title_inside_bbox,
    unpack_vertical_linear_4bpp,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WorldMapTitleTests(unittest.TestCase):
    def test_vertical_low_nibble_pack_round_trip(self):
        width = 8
        height = 4
        logical = bytes((index * 7) & 0x0F for index in range(width * height))
        raw = pack_vertical_linear_4bpp(
            logical,
            width=width,
            height=height,
        )
        self.assertEqual(len(raw), width * height // 2)
        self.assertEqual(raw[0] & 0x0F, logical[(height - 1) * width])
        self.assertEqual(
            unpack_vertical_linear_4bpp(raw, width=width, height=height),
            logical,
        )

    def test_replacement_is_confined_to_original_bbox(self):
        width = 12
        height = 6
        source = bytearray(width * height)
        source[1] = 4
        for y in range(1, 5):
            for x in range(3, 10):
                source[y * width + x] = 8
        rendered = bytearray(width * height)
        rendered[2 * width + 5] = 15
        rendered[3 * width + 6] = 7
        bbox = (3, 1, 9, 4)
        output = replace_title_inside_bbox(
            bytes(source),
            bytes(rendered),
            bbox,
            width=width,
            height=height,
        )
        self.assertEqual(output[1], 4)
        self.assertEqual(index_bbox(output, width=width, height=height), (1, 0, 6, 3))
        for y in range(height):
            for x in range(width):
                if 3 <= x <= 9 and 1 <= y <= 4:
                    continue
                self.assertEqual(output[y * width + x], source[y * width + x])

    def test_reviewed_corpus_covers_every_title_member_once(self):
        corpus = json.loads(
            (
                PROJECT_ROOT
                / "corpus/zh/ui-atlas/world-map-titles-v1.json"
            ).read_text(encoding="utf-8")
        )
        entries = corpus["entries"]
        members = [member for entry in entries for member in entry["members"]]
        self.assertEqual(len(entries), 78)
        self.assertEqual(sorted(members), list(range(81, 196)))
        self.assertEqual(len(members), 115)
        self.assertEqual(len(set(members)), 115)
        self.assertTrue(
            all(entry["editorial_status"] == "reviewed" for entry in entries)
        )
        self.assertEqual(
            sum(entry["source"] != entry["translation"] for entry in entries),
            70,
        )

    def test_rendered_results_are_frozen_and_locked(self):
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )["world_map_titles"]
        lock = config["render_snapshot"]
        path = PROJECT_ROOT / lock["path"]
        payload = path.read_bytes()
        snapshot = json.loads(payload.decode("utf-8"))
        corpus = json.loads(
            (PROJECT_ROOT / config["corpus"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(payload), lock["size"])
        self.assertEqual(sha256_bytes(payload), lock["sha256"])
        self.assertEqual(snapshot["status"], "reviewed_locked")
        self.assertEqual(
            snapshot["selection_authority"],
            "frozen_rendered_title_raw",
        )
        self.assertEqual(
            [entry["id"] for entry in snapshot["entries"]],
            [entry["id"] for entry in corpus["entries"]],
        )
        self.assertEqual(len(snapshot["entries"]), 78)
        self.assertTrue(snapshot["preview"]["png_base64"])

    def test_first_female_route_title_preimage_is_locked(self):
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )["world_map_titles"]
        archive = (PROJECT_ROOT / config["original_archive"]["path"]).read_bytes()
        slps = (PROJECT_ROOT / config["original_slps"]["path"]).read_bytes()
        table_start = int(config["archive"]["offset_table_start"], 0)
        count = config["archive"]["offset_count"]
        offsets = [
            int.from_bytes(
                slps[table_start + index * 4 : table_start + index * 4 + 4],
                "little",
            )
            for index in range(count)
        ]
        member = decode(archive[offsets[81] : offsets[82]])
        start = int(config["texture"]["japanese_raw_start"], 0)
        end = int(config["texture"]["japanese_raw_end"], 0)
        raw = member.output[start:end]
        self.assertEqual(
            sha256_bytes(raw),
            "0d6ed03699af05d1dbccbfe640683dd13889971497f04e44e8b0e3a151a803f9",
        )
        logical = unpack_vertical_linear_4bpp(raw, width=512, height=32)
        self.assertEqual(index_bbox(logical, width=512, height=32), (60, 4, 451, 29))


if __name__ == "__main__":
    unittest.main()
