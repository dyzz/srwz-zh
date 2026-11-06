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
        pilots = [r["pilot_sp"] for r in row0[13]["records"] if "text" in r]
        self.assertEqual(pilots, [477, 428, 405, 472])
        talk_ops = [op[1] for op in self.entries[0]["fidelity"]["timeline"] if op[0] == "talk"]
        k = talk_ops.index(13)
        self.assertIn(f"gallery_quiet_0_{k}:\n    .hword 477,428,405,472,65535", quiet)
        self.assertIn(f",{13},gallery_quiet_0_{k}", scenes)
        # Sections after the last effect are not replayed (user 2026-10-31: the
        # camera hopped between the speakers at the end): ("talk", 16, 1)
        k = talk_ops.index(16)
        self.assertIn(f"gallery_quiet_0_{k}:\n    .hword 65535", quiet)
        self.assertIn(f",{16 | (1 << 16)},gallery_quiet_0_{k}", scenes)

    def test_circle_mode_skips_the_row9_charge(self):
        # User 2026-10-31: circle mode goes straight to the row's own effect, so the
        # 0x13a3..0x13a4 charge (an intercept explosion every ~42 frames) lies in
        # the circle skip; circle mode sets the zoom and camera the skipped part
        # leaves (0x29 -16, camera on the TFO) and spawns the TFO at its end tile.
        timeline = self.entries[9]["fidelity"]["timeline"]
        skip = timeline.index(["circle_skip_to", "circle_0", [["zoom", -16], ["raw", 24, 2, 3, 0]]])
        mark = timeline.index(["mark", "circle_0"])
        on = timeline.index(["raw", 5027, 131075, 150994959, 2949120])
        off = timeline.index(["raw", 5028, 131075, 150994944, 0])
        self.assertTrue(skip < on < off < mark)
        self.assertNotIn("wait_modes", [op[0] for op in timeline[:mark]])
        self.assertEqual(timeline[mark + 1:mark + 3], [["talk", 4], ["bgm", 1]])  # section 4 moves the cursor
        compiled = compile_scene(9, self.entries[9]["fidelity"], [33, 24], [268])
        # circle mode: zoom -16, camera on the TFO, jump -- laid over the first three
        # records after the skip marker (talk 0 and talk 1), which triangle keeps
        circle = {}
        for label, triangle, value in compiled["mode_words"]:
            if label.startswith("gallery_circlerec_9_"):
                record, offset = label[len("gallery_circlerec_9_"):].split("+")
                circle.setdefault(int(record), {})[int(offset)] = (triangle, value)
        self.assertEqual(circle[0][0], ("15", str(0x13B9)))
        self.assertEqual(circle[0][4], ("0", str(-16 & 0xFFFFFFFF)))
        # over a talk record every word is laid: circle mode has already turned
        # word 2 into the quiet-replay pointer, which would make 0x13b9 animate
        self.assertEqual((circle[0][8], circle[0][12]), (("0", "0"), ("0", "0")))
        self.assertEqual(circle[1][0], ("15", "24"))
        self.assertEqual(circle[2][0][1], "20")
        self.assertEqual(circle[2][12][1], "gallery_mark_9_circle_0")
        self.assertEqual(sorted(circle), [0, 1, 2])
        script = compiled["script"]
        self.assertEqual(script[script.index("gallery_circlerec_9_0:") + 1], "    .word 15,0,0,0")

    def test_wait_modes_compile_to_mode_words(self):
        fidelity = {"timeline": [["wait_modes", 16, 1]]}
        compiled = compile_scene(0, fidelity, [0, 0], [])
        self.assertEqual(compiled["mode_words"], [("gallery_modewait_0_0+4", 16, 1)])
        with self.assertRaises(ValueError):
            compile_scene(0, {"timeline": [["wait_modes", 16, 0]]}, [0, 0], [])

    def test_row1_knights_move_in_after_section_21(self):
        # User 2026-10-31: in triangle mode G-Attacker and G-Shadow fly in before
        # Toga's last line, as STAGE007 0x9350-0x93f0 does; circle mode starts with
        # all five in place (spawn tiles are mode words) and jumps past section 21
        # and the move.
        entry = self.entries[1]
        units = {u["unit"]: u for u in entry["fidelity"]["units"]["gknights"]}
        self.assertEqual((units[677]["tile"], units[677]["circle_tile"]), ([6, 5], [10, 5]))
        self.assertEqual((units[680]["tile"], units[680]["facing"], units[680]["circle_tile"], units[680]["circle_facing"]),
                         ([2, 7], 2, [11, 8], 1))
        self.assertNotIn("tsugumi", entry["fidelity"]["units"])
        timeline = entry["fidelity"]["timeline"]
        start, end = timeline.index(["circle_skip_to", "knights_in_place"]), timeline.index(["talk", 22])
        # The squads section 23 cuts to are spawned for triangle mode only.
        self.assertEqual(timeline[start + 1:end], [
            ["spawn", "squads"], ["talk", 21], ["raw", 24, 2, 577, 0], ["raw", 5021, 0, 0, 0],
            ["raw", 5022, 1 << 16 | 677, 10 << 16 | 5, 0x80000002],
            ["raw", 5022, 1 << 16 | 680, 11 << 16 | 8, 0x80000002],
            ["raw", 5023, 0, 0, 0], ["raw", 22, 0, 0, 0],
            ["raw", 35, 1, 677, 1], ["raw", 35, 1, 680, 1],
            ["raw", 24, 2, 577, 0], ["wait", 30], ["mark", "knights_in_place"]])
        compiled = compile_scene(1, entry["fidelity"], [11, 6], [264])
        self.assertEqual([w for w in compiled["mode_words"] if not w[0].startswith(("gallery_bgm_", "gallery_modewait_"))], [
            ("gallery_spawn_1_0+12", 6 | 5 << 8 | 1 << 16, 10 | 5 << 8 | 1 << 16),
            ("gallery_spawn_1_0+108", 2 | 7 << 8 | 2 << 16, 11 | 8 << 8 | 1 << 16),
            # the squads' prep (0x14 prep,0,0) becomes "0x14 gallery_skip, 0, mark" in circle mode
            ("gallery_circlerec_1_0+4", "gallery_prep_1_2", "gallery_skip"),
            ("gallery_circlerec_1_0+12", "0", "gallery_mark_1_knights_in_place")])

    def test_row0_circle_mode_starts_with_meyrin(self):
        # User 2026-10-31: circle mode starts at the launch calls (effect 273);
        # the Abyss prelude (effects 15/1/8/33) and sections 10-14 are dialogue only.
        timeline = self.entries[0]["fidelity"]["timeline"]
        start, end = timeline.index(["circle_skip_to", "meyrin"]), timeline.index(["mark", "meyrin"])
        self.assertEqual(timeline[start - 1], ["spawn", "field"])
        self.assertEqual(timeline[end + 1:end + 6], [["bgm", 30], ["camera", 13, 13], ["raw", 28, 3, 0, 0],
                                                     ["wait_modes", 30, 1], ["effect", 273, [20, 12]]])
        skipped = [op[1] for op in timeline[start:end] if op[0] in ("effect", "talk")]
        self.assertEqual(skipped, [10, 11, 15, 15, 15, 12, 1, 1, 1, 8, 13, 33, 14])
        with self.assertRaises(ValueError):
            compile_scene(0, {**self.entries[0]["fidelity"], "timeline": [["mark", "meyrin"], ["circle_skip_to", "meyrin"]]},
                          [13, 13], [273])


    def test_circle_mode_starts_bgm_without_the_stream_wait(self):
        # User 2026-10-31: circle mode opens sooner. Op 0x43 holds the script until
        # the stream is ready (~40 frames); circle mode calls gallery_bgm_nowait.
        compiled = compile_scene(0, self.entries[0]["fidelity"], [20, 12], self.entries[0]["effects"])
        script = compiled["script"]
        label = script[script.index("gallery_mark_0_meyrin:") + 1]
        self.assertEqual(script[script.index(label) + 1], "    .word 67,30,0,0")
        words = {w[0]: w[1:] for w in compiled["mode_words"]}
        base = label.rstrip(":")
        self.assertEqual([words[f"{base}+{k}"] for k in (0, 4, 12)],
                         [("67", "20"), ("30", "gallery_bgm_nowait"), ("0", "30")])
        # BGM 69 lies in the circle skip: its record carries the skip overlay instead
        self.assertFalse(any(w.startswith("gallery_bgm_") and words[w][0] == "69" for w in words))
        self.assertIn("gallery_bgm_nowait:", (ROOT / "tools/special_disc/event_gallery/runtime.S").read_text())

    def test_row1_section_23_squads_stand_where_stage007_moves_them(self):
        squads = {u["pilot"]: u for u in self.entries[1]["fidelity"]["units"]["squads"]}
        self.assertEqual({p: tuple(u["tile"]) for p, u in squads.items()},
                         {138: (19, 20), 27: (20, 21), 3: (18, 21), 732: (19, 22)})
        self.assertEqual([m["pilot"] for m in squads[732]["members"]], [736, 726])

    def test_row18_effect_shift_keeps_the_timing_and_compiles_to_float_bits(self):
        # The shift sits inside the old wait 650, in the satellite close-up.
        timeline = self.entries[18]["fidelity"]["timeline"]
        start = timeline.index(["effect_shift", -0.0315, 0.0465])
        self.assertEqual([timeline[start - 1], timeline[start + 1]], [["wait", 150], ["wait", 499]])
        compiled = compile_scene(18, self.entries[18]["fidelity"], [20, 23], [255, 251])
        bits = struct.unpack("<2I", struct.pack("<2f", -0.0315, 0.0465))
        self.assertIn(f"    .word 20,gallery_effect_shift,{bits[0]},{bits[1]}", compiled["script"])

    def test_rows_15_and_16_match_the_movie_after_the_effect(self):
        # Row 15: group 15 is gone by the scene, its tiles belong to the ghost table.
        row15 = self.entries[15]["fidelity"]
        self.assertNotIn("zarogross", row15["deploy"])
        self.assertNotIn(["deploy", "zarogross"], row15["timeline"])
        # Row 16 brings the map back after the last line and fades out.
        timeline = self.entries[16]["fidelity"]["timeline"]
        self.assertEqual(timeline[-5:], [["talk", 102], ["wait", 30], ["raw", 5036, 0, 0, 0], ["fade", 0, 252, 4], ["wait_effects"]])

    def test_frame_loop_leaves_a_script_blank_alone(self):
        source = (ROOT / "tools/special_disc/event_gallery/runtime.S").read_text()
        loop = source.split("voice_ready:")[1].split("jal     0x00140290")[0]
        self.assertLess(loop.index("bne     $t2,$zero,map_draw_set"), loop.index("sw      $t1,0x45a0($t0)"))

    def test_cancelled_effect_cannot_leave_the_map_rotated(self):
        source = (ROOT / "tools/special_disc/event_gallery/runtime.S").read_text()
        regions = source.split("gallery_state_regions:")[1].split(".word 0,0")[0]
        self.assertIn(".word 0x00457784,4", regions)

    def test_circle_mode_leaves_the_song_to_effects_that_start_it(self):
        # These effects' resource headers start the music themselves. Circle mode
        # reaches them in seconds, so it only pauses the theater track, which the
        # header needs: without the pause the song outlives the scene.
        for row, track in ((1, 41), (3, 46), (6, 6), (7, 11), (8, 5), (11, 49)):
            with self.subTest(row=row):
                entry = self.entries[row]
                compiled = compile_scene(row, entry["fidelity"], entry["effect_tile"], entry["effects"])
                words = [w for w in compiled["mode_words"] if w[1] == str(track) and w[0].startswith("gallery_bgm_")]
                self.assertEqual([w[2] for w in words], ["gallery_bgm_pause"])

    def test_dialogue_auto_play_uses_native_level_2(self):
        source = (ROOT / "tools/special_disc/event_gallery/runtime.S").read_text()
        self.assertIn("addiu   $t7,$zero,2\n    sw      $t7,8($t6)", source.split("gallery_talk_auto:")[1])

    def test_scene_song_survives_the_roster_restore_for_the_bgm_restore(self):
        source = (ROOT / "tools/special_disc/event_gallery/runtime.S").read_text()
        code = source.split("jal     gallery_restore_roster")[0][-260:] + source.split("jal     gallery_restore_roster")[1][:200]
        self.assertIn("lbu     $t0,-0x4468($t0)", code)
        self.assertIn("sb      $t0,-0x4468($t1)", code)

    def test_circle_camera_and_row_fixes_20261031(self):
        # BIG-O opens on its own tile (no cut from Beck), Shin Choju-zan does not
        # replay section 43 (a cut to Hydwell), Bakuai Mugenkou has Tsugumi only.
        import tempfile
        from special_disc.event_gallery.runtime import generate
        self.assertEqual(self.entries[4]["fidelity"]["circle_camera"], [11, 14])
        talk_config = json.loads((ROOT / "config/products/special-disc/event-gallery-talk.json").read_text())["scenes"]
        talk = {scene: [{"section": sec["section"], "header": sec["header"], "records": [
            {"words": [*r["words"][:3], r["pilot_sp"], *r["words"][4:]] if "text" in r else r["words"],
             "text": b"x" if "text" in r else None} for r in sec["records"]]} for sec in data["sections"]]
            for scene, data in talk_config.items()}
        with tempfile.TemporaryDirectory() as tmp:
            generate(self.entries, tmp, talk=talk)
            scenes = (Path(tmp) / "gallery-scenes.inc").read_text()
        self.assertIn(f"gallery_scene_table+{32 * 4 + 4},7,11", scenes)
        self.assertIn(f"gallery_scene_table+{32 * 4 + 8},20,14", scenes)
        timeline = self.entries[15]["fidelity"]["timeline"]
        start = timeline.index(["circle_skip_to", "circle_1"])
        self.assertEqual(timeline[start - 1:start + 4],
                         [["bgm", 40], ["circle_skip_to", "circle_1"], ["talk", 43], ["wait", 30], ["mark", "circle_1"]])
        # ... and fades where the last explosions end, without the cut back to Toga.
        start = timeline.index(["circle_skip_to", "end"])
        self.assertEqual(timeline[start - 1:start + 2], [["wait_effects"], ["circle_skip_to", "end"], ["camera", 18, 4]])
        self.assertEqual(timeline[timeline.index(["mark", "end"]) + 1], ["fade", 0, 248, 8])
        timeline = self.entries[17]["fidelity"]["timeline"]
        start = timeline.index(["circle_skip_to", "solo"])
        self.assertEqual(timeline[start + 1:start + 4], [["deploy", "sara"], ["deploy", "asuham"], ["mark", "solo"]])

    def test_roster_snapshot_follows_the_payload_and_fits_the_segment(self):
        # The payload ends where gallery_save_roster's snapshot starts; the snapshot
        # (roster 0x76940, spawn results 0x100, the state regions) must end before
        # the private segment does.
        import re
        from special_disc.event_gallery.apply import PAYLOAD_BASE, PAYLOAD_SIZE, PRIVATE_END
        source = (ROOT / "tools/special_disc/event_gallery/runtime.S").read_text()
        bases = re.findall(r"lui +\$t\d,0x0084 +/\* snapshot base 0x([0-9a-f]+)", source)
        self.assertEqual(set(bases), {f"{PAYLOAD_BASE + PAYLOAD_SIZE:x}"})
        regions = source.split("gallery_state_regions:")[1].split(".word 0,0")[0]
        size = sum(int(v, 0) for v in re.findall(r"\.word 0x[0-9a-f]+,(0x[0-9a-f]+|\d+)", regions))
        self.assertLessEqual(PAYLOAD_BASE + PAYLOAD_SIZE + 0x76940 + 0x100 + size, PRIVATE_END)


if __name__ == "__main__":
    unittest.main()
