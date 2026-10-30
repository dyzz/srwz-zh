import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from special_disc.event_gallery.fidelity import compile_scene, deploy_tables, speaker_table, spawn_record  # noqa: E402

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
                # Later BGM changes of the original script are declared with
                # their source beside the opening song, in timeline order.
                changes = fidelity["bgm"].get("changes", [])
                for change in changes:
                    self.assertIn("source", change, entry["id"])
                expected = [["bgm", fidelity["bgm"]["id"]]] + [["bgm", c["id"]] for c in changes]
                self.assertEqual(bgm_ops, expected, entry["id"])
            else:
                # The effect resource header starts this BGM; a script request
                # before it would restart the song at the effect.
                self.assertEqual(bgm_ops, [], entry["id"])

    def test_original_view_changes_are_retained(self):
        views = {e["id"]: e["camera"]["map_view"] for e in self.entries}
        self.assertEqual(views["effect-255"], 1)  # STAGE126 0xb710 switch at view 1; 0xb820 op 0x41 0 rotates inside the clip
        self.assertEqual(views["effect-259"], 2)  # STAGE107 0x141d0 op 0x41 2
        self.assertEqual(views["effect-297"], 1)  # STAGE084 0x9b70 op 0x41 1
        self.assertEqual(views["effect-298"], 1)  # STAGE057 0x7310 op 0x41 1
        self.assertEqual(views["effect-238"], 1)  # player-rotated in the event movie; STAGE009 init sets 3
        rotated = ("effect-255", "effect-259", "effect-297", "effect-298", "effect-238")
        self.assertTrue(all(v == 3 for k, v in views.items() if k not in rotated))

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

    def test_deploy_tables_match_original_stage_groups(self):
        # STAGE114 squad 1 / member record 1 (Agamemnon, Federation captain);
        # the gallery table starts its own squad indices at 0.
        squad = bytes.fromhex("0c" + "838d83538358".ljust(46, "0") + "10110e0100")
        member = bytes.fromhex("00000000000200003b03010001000000000000000000")
        lines = deploy_tables([{"unit": 512, "pilot": 827, "tile": [17, 14], "facing": 1, "side": 12,
                                "name": "ロゴス"}], "t")
        halfwords = [int(v) for v in lines[lines.index("t_records:") + 1].strip()[7:].split(",")]
        self.assertEqual(struct.pack("<11H", *halfwords), member)
        raw = bytes(int(v) for v in lines[lines.index("t_squads:") + 1].strip()[6:].split(","))
        self.assertEqual(raw, squad)
        self.assertIn("    .hword 0,0,1,0", lines)
        # An ace leader: level in half-words 5/6, flag word 10, squad flags at +0x18.
        ace = deploy_tables([{"unit": 327, "pilot": 273, "tile": [31, 30], "facing": 3, "side": 4, "name": "",
                              "level": 61, "flags": 0x80, "squad_flags": 0x22}], "a")
        halfwords = [int(v) for v in ace[ace.index("a_records:") + 1].strip()[7:].split(",")]
        self.assertEqual(halfwords, [0, 0, 327, 0, 273, 61, 61, 0, 0, 0, 0x80])
        raw = bytes(int(v) for v in ace[ace.index("a_squads:") + 1].strip()[6:].split(","))
        self.assertEqual(raw[24:], bytes([0x22, 31, 30, 3, 0]))

    def test_unit_ids_are_sp_definitions_with_original_evidence(self):
        for entry in self.entries:
            groups = list(entry["fidelity"].get("units", {}).values()) + list(entry["fidelity"].get("deploy", {}).values())
            for group in groups:
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

    def test_speaker_table_layout_matches_stage_tables(self):
        lines = speaker_table([
            {"speaker": 726, "kind": "no_cursor", "flags": 1, "condition_flag": 81},
            {"speaker": 592, "kind": "tile", "flags": 0, "condition_flag": None, "tile": [10, 0]},
            {"speaker": 655, "kind": "pilot", "flags": 0, "condition_flag": None, "target": 805},
        ], "t")
        rows = [[int(v, 0) for v in line.strip()[7:].split(",")] for line in lines if line.strip().startswith(".hword")]
        self.assertEqual(rows, [
            [726, 1 | 5 << 8, 0, 0, 0, 0, 81, 0],
            [592, 3 << 8, 10, 0, 0, 0, 0, 0],
            [655, 2 << 8, 805, 0, 0, 0, 0, 0],
            [0xFFFF, 0, 0, 0, 0, 0, 0, 0],
        ])

    def test_speakers_off_the_gallery_map_keep_their_pass_one_entries(self):
        # FUN_0017cd20 reads flag-bit-0 entries only when the speaker's pilot is
        # on the map; the gallery leaves the player characters off it.
        for entry in self.entries:
            fidelity = entry["fidelity"]
            on_map = set()
            for group in list(fidelity.get("units", {}).values()) + list(fidelity.get("deploy", {}).values()):
                for unit in group:
                    on_map.add(unit["pilot"])
                    on_map.update(m["pilot"] for m in unit.get("members", []))
                    on_map.update(unit.get("crew", []))
            for name, table in fidelity.get("speakers", {}).items():
                for i, item in enumerate(table):
                    if item["flags"] & 1 and item["speaker"] not in on_map:
                        copy = table[i + 1]
                        self.assertTrue(copy.get("off_map"), (entry["id"], name, item))
                        self.assertEqual({**item, "flags": item["flags"] & ~1, "off_map": True}, copy)
        row0 = self.entries[0]["fidelity"]
        self.assertIn(["flag", 81, 1], row0["timeline"])
        setsuko = [e for e in row0["speakers"]["stage002"] if e["speaker"] == 726]
        self.assertEqual([(e["kind"], e["flags"]) for e in setsuko], [("no_cursor", 1), ("no_cursor", 0)])

    def test_row3_vectors_use_the_npc_side_of_their_stage_group(self):
        # STAGE021 group 4 (the route in the event movie) spawns the vectors on
        # side 8, which draws the green cursor crystal.
        vectors = self.entries[3]["fidelity"]["units"]["vectors"]
        self.assertEqual([u["side"] for u in vectors], [8, 8, 8])


    def test_stage_positions_reported_on_2026_10_30(self):
        # 赞波特3: STAGE009 0x6dc0/0x6dd0 move ザンベース (pilot 908) to (29,24) and ザンブル (909) to (29,25).
        team = {u["unit"]: u["tile"] for u in self.entries[2]["fidelity"]["units"]["zambot_team"]}
        self.assertEqual((team[124], team[123]), ([29, 24], [29, 25]))
        # 阿克艾里昂: the light (op 0x139b at 0xa000b = x << 16 | y) lands on the camera tile (10,11).
        row3 = self.entries[3]
        self.assertIn(["effect", 20, [10, 11]], row3["fidelity"]["timeline"])
        self.assertEqual(row3["camera"]["tile"], [10, 11])
        # 大魔神特攻: the TFO spawns like STAGE047 0xac40 (op 0x0d mode 1, appear 0xff), so the
        # engine puts it on the air layer; effect 268 follows 甲児 to (33,15).
        row9 = self.entries[9]["fidelity"]
        self.assertIn(["spawn", "koji", 1], row9["timeline"])
        self.assertEqual(row9["units"]["koji"][0]["appear"], 0xFF)
        self.assertIn(["effect", 268, [33, 15]], row9["timeline"])
        # 格兰维昂合神 starts at section 21, as the event movie does.
        self.assertNotIn(["talk", 20], self.entries[1]["fidelity"]["timeline"])
        self.assertIn(["talk", 21], self.entries[1]["fidelity"]["timeline"])

    def test_spawn_op_takes_the_stage_spawn_mode(self):
        entry = self.entries[9]
        compiled = compile_scene(9, entry["fidelity"], entry["fidelity"]["units"]["koji"][0]["tile"],
                                 [268])
        spawns = [w for w in words(compiled["script"]) if w[0] == 0x0D]
        self.assertEqual([w[2] for w in spawns], [1, 2])


    def test_circle_mode_replays_each_sections_speakers(self):
        # Circle mode gosubs into runtime.S gallery_quiet_sub with the section's
        # speaking pilots (record +12, as apply.encode_talk writes it), so the
        # cursor and camera end where the dialogue leaves them.
        import tempfile
        from special_disc.event_gallery.runtime import generate
        talk_config = json.loads((ROOT / "config/products/special-disc/event-gallery-talk.json").read_text())["scenes"]
        talk = {}
        for scene, data in talk_config.items():
            talk[scene] = [{"section": sec["section"], "header": sec["header"], "records": [
                {"words": [*r["words"][:3], r["pilot_sp"], *r["words"][4:]] if "text" in r else r["words"],
                 "text": b"x" if "text" in r else None} for r in sec["records"]]} for sec in data["sections"]]
        with tempfile.TemporaryDirectory() as tmp:
            generate(self.entries, tmp, talk=talk)
            quiet = (Path(tmp) / "gallery-quiet.inc").read_text()
            scenes = (Path(tmp) / "gallery-scenes.inc").read_text()
        row0 = {sec["section"]: sec for sec in talk_config["effect-273"]["sections"]}
        pilots = [r["pilot_sp"] for r in row0[16]["records"] if "text" in r]
        self.assertEqual(pilots, [732, 726])
        talk_ops = [op[1] for op in self.entries[0]["fidelity"]["timeline"] if op[0] == "talk"]
        k = talk_ops.index(16)
        self.assertIn(f"gallery_quiet_0_{k}:\n    .hword 732,726,65535", quiet)
        # talk op table: record, section | cursor << 16 ("talk", 16, 1), speaker list
        self.assertIn(f",{16 | (1 << 16)},gallery_quiet_0_{k}", scenes)


if __name__ == "__main__":
    unittest.main()
