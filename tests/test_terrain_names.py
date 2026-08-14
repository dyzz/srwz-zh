import json
import struct
import unittest
from pathlib import Path

from tools.srwz.codec import decode_production, encode
from tools.srwz.terrain_names import inventory_terrain_names
from tools.srwz.text import (
    decode_text,
    encode_text,
    load_text_table,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEXT_TABLE = (
    PROJECT_ROOT / "vendor" / "upstream-python" / "project" / "tbl_all.json"
)


class TerrainNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = load_text_table(TEXT_TABLE)

    def test_inventories_records_from_frame_anchor(self):
        decoded = bytearray(0x120)
        record_start = 0x40
        for index, name in enumerate(("海", "森")):
            offset = record_start + index * 0x1C
            payload = encode_text(name, self.table, terminate=True)
            decoded[offset : offset + len(payload)] = payload
        frame = record_start + 2 * 0x1C + 0x1C
        decoded[frame : frame + 6] = b"Frame\0"
        stored = encode(bytes(decoded))

        rows = inventory_terrain_names(
            stored,
            (0, len(stored)),
            self.table,
            first_member=0,
            last_member=0,
        )

        self.assertEqual(
            rows,
            (
                {
                    "member": 0,
                    "decoded_offset": 0x40,
                    "source": "海",
                    "source_consumed": 3,
                },
                {
                    "member": 0,
                    "decoded_offset": 0x5C,
                    "source": "森",
                    "source_consumed": 3,
                },
            ),
        )

    def test_inventories_long_composite_name(self):
        decoded = bytearray(0x120)
        record_start = 0x40
        payload = encode_text("月面基地施設", self.table, terminate=True)
        decoded[record_start : record_start + len(payload)] = payload
        frame = record_start + 0x30
        decoded[frame : frame + 6] = b"Frame\0"
        stored = encode(bytes(decoded))

        rows = inventory_terrain_names(
            stored,
            (0, len(stored)),
            self.table,
            first_member=0,
            last_member=0,
        )

        self.assertEqual(rows[0]["source"], "月面基地施設")
        self.assertEqual(rows[0]["source_consumed"], 13)

    def test_locked_inventory_covers_the_complete_terrain_member_range(self):
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        terrain = config["world_map_titles"]["terrain_names"]
        locked = tuple(
            json.loads(
                (PROJECT_ROOT / terrain["inventory"]["path"]).read_text(
                    encoding="utf-8"
                )
            )["occurrences"]
        )
        slps = (PROJECT_ROOT / terrain["original_slps"]["path"]).read_bytes()
        archive = (
            PROJECT_ROOT / terrain["original_archive"]["path"]
        ).read_bytes()
        archive_config = terrain["archive"]
        table_start = int(archive_config["offset_table_start"], 0)
        offset_count = archive_config["offset_count"]
        offsets = struct.unpack(
            f"<{offset_count}I",
            slps[table_start : table_start + offset_count * 4],
        )

        discovered = inventory_terrain_names(
            archive,
            offsets,
            self.table,
            first_member=archive_config["first_member"],
            last_member=archive_config["last_member"],
        )

        self.assertEqual(discovered, locked)
        self.assertEqual(len(discovered), 475)
        self.assertEqual(len({row["source"] for row in discovered}), 84)
        self.assertEqual(len({row["member"] for row in discovered}), 80)
        self.assertEqual(archive_config["last_member"], 80)

    def test_all_reviewed_names_are_exact_in_current_component(self):
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(
                encoding="utf-8"
            )
        )
        component = json.loads(
            (
                PROJECT_ROOT
                / "manifests/full-story-components-validation.json"
            ).read_text(encoding="utf-8")
        )
        assignments = json.loads(
            (
                PROJECT_ROOT
                / "config/encoding/zh-release-font-assignments.json"
            ).read_text(encoding="utf-8")
        )
        primary = {
            row["character"]: int(row["code"], 16)
            for row in assignments["primary_assignments"]
        }
        aliases = {
            row["character"]: int(row["code"], 16)
            for row in assignments["surface_alias_assignments"]
        }
        output_table = project_runtime_text_table(self.table, primary)
        output_table = project_runtime_text_table(output_table, aliases)
        output_table = project_runtime_text_table(
            output_table,
            original_fullwidth_ascii_overrides(self.table),
        )

        terrain = config["world_map_titles"]["terrain_names"]
        inventory = json.loads(
            (PROJECT_ROOT / terrain["inventory"]["path"]).read_text(
                encoding="utf-8"
            )
        )["occurrences"]
        translations = {
            row["source"]: row["translation"]
            for row in json.loads(
                (PROJECT_ROOT / terrain["corpus"]["path"]).read_text(
                    encoding="utf-8"
                )
            )["entries"]
        }

        slps = (PROJECT_ROOT / terrain["original_slps"]["path"]).read_bytes()
        archive_config = terrain["archive"]
        table_start = int(archive_config["offset_table_start"], 0)
        offset_count = archive_config["offset_count"]
        offsets = struct.unpack(
            f"<{offset_count}I",
            slps[table_start : table_start + offset_count * 4],
        )
        archive = (
            PROJECT_ROOT
            / component["outputs"]["MAP/MAPMODEL.BIN"]["path"]
        ).read_bytes()
        decoded_members = {}
        for row in inventory:
            member = row["member"]
            if member not in decoded_members:
                decoded_members[member] = decode_production(
                    archive[offsets[member] : offsets[member + 1]]
                ).output
            self.assertEqual(
                decode_text(
                    decoded_members[member],
                    row["decoded_offset"],
                    output_table,
                ).text,
                translations[row["source"]],
            )


if __name__ == "__main__":
    unittest.main()
