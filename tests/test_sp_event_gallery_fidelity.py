import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from special_disc.event_gallery.fidelity import compile_scene, spawn_record  # noqa: E402

CONFIG = ROOT / "config/products/special-disc/event-gallery.json"


def words(lines):
    out = []
    for line in lines:
        line = line.strip()
        if line.startswith(".word "):
            out.append([int(v) if v.lstrip("-").isdigit() else v for v in line[6:].split(",")])
    return out


class FidelityTimelineTests(unittest.TestCase):
    def setUp(self):
        self.entries = json.loads(CONFIG.read_text())["entries"]

    def test_every_scene_has_explicit_bgm_zoom_and_view(self):
        for entry in self.entries:
            fidelity = entry["fidelity"]
            self.assertIn(fidelity["bgm"]["mode"], ("script", "effect_header"), entry["id"])
            self.assertIn("source", fidelity["bgm"])
            self.assertIsInstance(fidelity["zoom"]["value"], int)
            self.assertIn(entry["camera"]["map_view"], (0, 1, 2, 3))
            timeline = fidelity["timeline"]
            self.assertEqual(timeline[0], ["zoom", fidelity["zoom"]["value"]], entry["id"])
            bgm_ops = [op for op in timeline if op[0] == "bgm"]
            if fidelity["bgm"]["mode"] == "script":
                self.assertEqual(bgm_ops, [["bgm", fidelity["bgm"]["id"]]], entry["id"])
            else:
                # The effect resource header starts this BGM; a script request
                # before it would restart the song at the effect.
                self.assertEqual(bgm_ops, [], entry["id"])

    def test_original_view_changes_are_retained(self):
        views = {e["id"]: e["camera"]["map_view"] for e in self.entries}
        self.assertEqual(views["effect-255"], 0)  # STAGE126 0xb820 op 0x41 0
        self.assertEqual(views["effect-259"], 2)  # STAGE107 0x141d0 op 0x41 2
        self.assertTrue(all(v == 3 for k, v in views.items() if k not in ("effect-255", "effect-259")))

    def test_compiled_timelines_cover_catalog_effects_and_wait(self):
        for row, entry in enumerate(self.entries):
            compiled = compile_scene(row, entry["fidelity"], entry["effect_tile"], entry["effects"])
            records = words(compiled["script"])
            effects = [records[i + 1][1] for i, r in enumerate(records) if r[0] == 0x56]
            self.assertEqual(effects, entry["effects"], entry["id"])
            hold = entry["fidelity"].get("hold_after_effect")
            if hold:
                self.assertEqual(records[-1], [1, hold["frames"], 0, 0], entry["id"])
                self.assertEqual(records[-2][0], 0x57, entry["id"])
            else:
                self.assertEqual(records[-1][0], 0x57, entry["id"])

    def test_spawn_record_layout_matches_native_list(self):
        # STAGE047 0x7930 Mazinger Z record, squad pointer replaced.
        original = bytes.fromhex("04020100fffffffffeff0000200d01000200ffffffff0000ffffffff")
        line = spawn_record({"unit": 0, "pilot": 2, "tile": [32, 13], "facing": 1, "side": 0,
                             "appear": 1, "class": 4}, "0")[0]
        values = [int(v) for v in line.strip()[6:].split(",")][:7]
        self.assertEqual(struct.pack("<7I", *values), original)

    def test_unit_ids_are_sp_definitions_with_original_evidence(self):
        for entry in self.entries:
            for group in entry["fidelity"].get("units", {}).values():
                for unit in group:
                    self.assertIn("original", unit)
                    self.assertIn("source", unit)
                    self.assertLess(unit["unit"], 853)
                    self.assertLess(unit["pilot"], 969)

    def test_placeholder_table_uses_sp_unit_ids(self):
        entry = next(e for e in self.entries if e["id"] == "effect-265")
        ghost = entry["fidelity"]["ghost_table"]
        mapping = {623: 671, 621: 668, 615: 659}
        for item in ghost["groups"][0]:
            self.assertEqual(item["unit"], mapping[item["original_unit"]])
        self.assertEqual(len(ghost["groups"][0]), 26)
        self.assertEqual(ghost["visible_flags"], list(range(30, 55)))


if __name__ == "__main__":
    unittest.main()
