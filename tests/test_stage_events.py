from __future__ import annotations

import struct
import unittest
from pathlib import Path

from tools.srwz import stage_events
from tools.srwz.stage_events import (
    BASE,
    HandlerAnalyzer,
    ScriptWalker,
    consistent,
    decode,
    deployment_groups,
    installed_globals,
    ordered_groups,
    parse_battle_talk_table,
    script_operand,
    section_event_order,
    structure_condition,
)

ROOT = Path(__file__).resolve().parents[1]
STAGE_ARCHIVE = ROOT / "work" / "disc" / "DATA" / "STAGE.BIN"
STAGE_LAYOUT = ROOT / "config" / "stage-offsets.json"
SLPS = ROOT / "work" / "disc" / "SLPS_258.87"


def record(op: int, a: int = 0, b: int = 0, c: int = 0) -> bytes:
    return struct.pack("<4I", op, a & 0xFFFFFFFF, b & 0xFFFFFFFF, c & 0xFFFFFFFF)


class DecoderTest(unittest.TestCase):
    def test_decode_recognises_the_handler_subset(self) -> None:
        self.assertEqual(decode(0x3C010056).op, "lui")
        self.assertEqual(decode(0x0C05EA58).op, "jal")
        self.assertEqual(decode(0x0C05EA58).target, 0x17A960)
        self.assertEqual(decode(0x03E00008).op, "jr")
        self.assertEqual(decode(0x0000282D).op, "daddu")
        # dsll32/dsra32 sign-extension idioms pass the value through
        self.assertEqual(decode(0x0004263F).op, "dshift")

    def test_script_operands_follow_the_runtime_encoding(self) -> None:
        self.assertEqual(script_operand(0x90000004), {"kind": "imm", "value": 4})
        self.assertEqual(script_operand(0x9000FFFF), {"kind": "imm", "value": -1})
        self.assertEqual(script_operand(0x900F), {"kind": "var", "var": 0x900F})
        self.assertEqual(
            script_operand(0x920402CA),
            {"kind": "var2", "var": 0x9204, "arg": 0x2CA},
        )

    def test_contradictory_conditions_prune_a_path(self) -> None:
        part = ("global", 0x558815, 1)
        conds = [("==", part, ("const", 2))]
        self.assertFalse(consistent(conds, ("==", part, ("const", 1))))
        self.assertFalse(consistent(conds, ("!=", part, ("const", 2))))
        self.assertTrue(consistent(conds, ("==", part, ("const", 2))))
        flag = ("call", stage_events.FN_FLAG_TEST, (("const", 10), ("unknown", "r5"), ("unknown", "r6"), ("unknown", "r7")))
        conds = [("!=", flag, ("const", 0))]
        self.assertFalse(consistent(conds, ("==", flag, ("const", 0))))

    def test_structure_condition_names_helpers(self) -> None:
        call = ("call", stage_events.FN_UNIT_DESTROYED, (("const", 2), ("const", 0x2CA), ("unknown", "r6"), ("unknown", "r7")))
        self.assertEqual(
            structure_condition(("==", call, ("const", 1))),
            {"type": "unit_destroyed", "unit_kind": 2, "unit": 0x2CA, "value": 1},
        )
        turn = ("global", 0x5585D0, 2)
        self.assertEqual(
            structure_condition(("!=", ("lt", turn, 11, False), ("const", 0))),
            {"type": "turn", "op": "<", "value": 11},
        )


class ScriptWalkerTest(unittest.TestCase):
    def test_if_else_blocks_attach_conditions_to_dialogue(self) -> None:
        script = b"".join(
            [
                record(0x1389, 0x920402CA, 0x800, 0x90000000),  # IF hp(0x2ca) == 0
                record(0x0F, 4),
                record(0x138B),  # ELSE
                record(0x0F, 6),
                record(0x138C),  # ENDIF
                record(0x58, 1),  # part := 1
                record(0x0B),
            ]
        )
        data = bytes(0x80) + script
        walker = ScriptWalker(data)
        walker.walk(0x80)
        self.assertEqual([d.event_id for d in walker.dialogues], [4, 6])
        self.assertEqual(walker.dialogues[0].conds[0]["op"], "==")
        self.assertFalse(walker.dialogues[0].conds[0].get("negated"))
        self.assertTrue(walker.dialogues[1].conds[0]["negated"])
        self.assertEqual(walker.effects, [("set_part", 1)])
        self.assertEqual(walker.warnings, [])

    def test_absolute_jump_into_another_script_is_followed(self) -> None:
        second = 0x80 + 3 * 16
        script = b"".join(
            [
                record(0x0F, 3),
                record(0x20, BASE + second, 1, 0xD),  # jump when flag 13 is set
                record(0x0B),
                record(0x0F, 5),
                record(0x0B),
            ]
        )
        data = bytes(0x80) + script
        walker = ScriptWalker(data)
        walker.walk(0x80)
        self.assertEqual([d.event_id for d in walker.dialogues], [3, 5])
        self.assertEqual(walker.dialogues[1].conds, [{"type": "flag", "flag": 13, "value": 1}])

    def test_battle_talk_table_parses_until_terminator(self) -> None:
        table = struct.pack("<8h", 0x80, 0x2BF, 0x2CA, 0, 0, 0, 0x21, 0)
        table += struct.pack("<8h", 0x81, 0x2C0, -1, 0, 0, 0, 0x22, 0)
        table += struct.pack("<8h", -1, 0, 0, 0, 0, 0, 0, 0)
        entries = parse_battle_talk_table(bytes(0x80) + table, 0x80)
        self.assertEqual([(e["pilotA"], e["pilotB"], e["eventId"]) for e in entries], [(0x2BF, 0x2CA, 0x21), (0x2C0, -1, 0x22)])


@unittest.skipUnless(STAGE_ARCHIVE.exists() and SLPS.exists(), "original disc data is not extracted")
class StageEventsArchiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tools.srwz.archive import load_offset_layout, slice_archive
        from tools.srwz.codec import decode_production
        from tools.srwz.stage import read_stage_function_addresses

        layout = load_offset_layout(STAGE_LAYOUT)
        chunks = list(slice_archive(STAGE_ARCHIVE.read_bytes(), layout))
        cls.functions = read_stage_function_addresses(SLPS.read_bytes())
        cls.setsuko_32 = decode_production(chunks[57]).output
        cls.rand_32 = decode_production(chunks[84]).output

    def test_installed_globals_expose_dispatcher_and_dialogue_block(self) -> None:
        installed = installed_globals(self.setsuko_32, self.functions[57] - BASE)
        self.assertEqual(installed[0x595278], 0x756CB0)
        self.assertEqual(installed[0x5952E0], 0x759F98)
        self.assertEqual(deployment_groups(self.setsuko_32, installed)[0][0], 0x2CA)

    def test_setsuko_episode_32_triggers(self) -> None:
        analysis = stage_events.analyze_stage(self.setsuko_32, self.functions[57])
        self.assertEqual(analysis["warnings"], [])
        scripts = analysis["scripts"]
        opening = scripts["0x7e10"]
        self.assertEqual([d["eventId"] for d in opening["dialogues"]], [0, 1, 2, 3, 35])
        self.assertIn(("set_part", 0), opening["effects"])
        turn_four = scripts["0x7270"]
        self.assertEqual([d["eventId"] for d in turn_four["dialogues"]][:3], [4, 5, 6])
        self.assertEqual(turn_four["dialogues"][0]["conds"][0]["lhs"], {"kind": "var2", "var": 0x9204, "arg": 0x2CA})
        self.assertTrue(turn_four["dialogues"][2]["conds"][0]["negated"])
        talks = {(e["pilotA"], e["pilotB"]): e["eventId"] for e in analysis["battleTalks"]}
        self.assertEqual(talks, {(0x2BF, 0x2CA): 33, (0x2C0, 0x2DA): 34})
        events = {(t["event"], a["offset"]) for t in analysis["triggers"] for a in t["actions"] if a["type"] == "run_script"}
        self.assertIn((2, 0x7E10), events)
        self.assertIn((2, 0x7270), events)
        self.assertIn((7, 0x7270), events)
        self.assertIn((7, 0x71D0), events)
        self.assertIn((7, 0x6DE0), events)
        self.assertEqual(
            section_event_order(analysis),
            [0, 1, 2, 3, 35, 33] + list(range(4, 26)) + [34, 26, 31, 32, 27, 28, 29, 30],
        )
        groups = ordered_groups(analysis)
        self.assertEqual(groups[0]["setsPart"], 0)
        self.assertTrue(all(g["prerequisitesMet"] for g in groups if g["dialogues"]))

    def test_rand_episode_32_orders_battle_talks_before_turn_three(self) -> None:
        analysis = stage_events.analyze_stage(self.rand_32, self.functions[84])
        order = section_event_order(analysis)
        self.assertEqual(order[:8], [0, 1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(order[8:20], list(range(23, 35)))
        self.assertEqual(order[20:23], [8, 9, 10])
        self.assertEqual(len(analysis["battleTalks"]), 12)

    def test_handler_analysis_stays_bounded(self) -> None:
        installed = installed_globals(self.setsuko_32, self.functions[57] - BASE)
        analyzer = HandlerAnalyzer(self.setsuko_32, installed[0x5952A8] - BASE)
        analyzer.run(installed[0x595278] - BASE, {4: ("event",)})
        self.assertGreater(analyzer.budget, 3_000_000 - 20_000)
        self.assertEqual(analyzer.warnings, [])


if __name__ == "__main__":
    unittest.main()
