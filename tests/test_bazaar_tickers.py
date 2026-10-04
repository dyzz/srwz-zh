from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_story_component import (  # noqa: E402
    _discover_story_tickers, _load_overrides, _load_story_tickers, _write_story_tickers,
)
from srwz.bazaar_tickers import (  # noqa: E402
    BEST_SCRIPT_POINTER_GLOBAL, discover_bazaar_ticker_owners,
)
from srwz.codec import decode_production  # noqa: E402
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660  # noqa: E402
from srwz.iso_layout import read_executable_archive_offsets  # noqa: E402
from srwz.stage import StageParseError, read_stage_function_addresses  # noqa: E402
from srwz.stage_formations import STAGE_OFFSET_SPEC  # noqa: E402
from srwz.text import (  # noqa: E402
    decode_text, load_text_table, original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)


class BazaarTickerCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config/story-component.json").read_text())
        cls.reference = cls.config["translations"]["tickers"]
        _, cls.entries = _load_story_tickers(cls.reference)
        archive = (ROOT / cls.config["source"]["stage"]["path"]).read_bytes()
        offsets = json.loads((ROOT / "config/stage-offsets.json").read_text())["offsets"]
        cls.chunks = [decode_production(archive[a:b]).output for a, b in zip(offsets, offsets[1:])]
        cls.functions = read_stage_function_addresses(
            (ROOT / cls.config["source"]["slps"]["path"]).read_bytes())[:len(cls.chunks)]
        cls.table = load_text_table(ROOT / cls.config["source"]["text_table"]["path"])
        cls.targets, cls.report = _discover_story_tickers(
            cls.chunks, cls.table, cls.entries, cls.reference, functions=cls.functions)

    def owners_108(self, data):
        return discover_bazaar_ticker_owners([bytes(data)], [self.functions[108]])

    def discover_108(self, data, entries=None):
        return _discover_story_tickers([bytes(data)], self.table,
            self.entries if entries is None else entries, {}, functions=(self.functions[108],))

    def test_all_stage_owners_equal_independent_static_audit(self):
        owners = discover_bazaar_ticker_owners(self.chunks, self.functions)
        # Golden stage set from the independent native-code audit; not found
        # through a text prefix or translation-corpus scan.
        expected = {
            13,14,15,16,18,19,20,21,25,26,27,28,29,30,31,33,34,36,37,39,41,42,43,45,
            47,50,52,53,54,55,56,57,58,60,61,62,63,65,66,69,71,74,76,78,80,82,83,84,
            85,87,89,90,91,94,95,98,100,103,104,106,107,108,112,113,117,118,119,120,
            124,126,127,128,130,131,155,156,158,159,161,162,163,164,165,166,167,168,
            169,170,171,172,173,174,175,176,177,178,179,180,
        }
        self.assertEqual({x.stage_index for x in owners}, expected)
        self.assertEqual(len(owners), len(expected))
        self.assertEqual((self.report["target_count"], self.report["entry_count"]), (98, 49))
        self.assertTrue(self.report["owner_slots_exact"])
        self.assertEqual(self.report["selection_authority"], "initialized_intermission_script")
        self.assertEqual(self.report["prefix_kind_counts"], {"zero": 89, "runtime_pointer": 9})
        target = self.targets[108][0]
        self.assertEqual((target["command_offset"], target["record_offset"], target["decoded_offset"]),
                         (0xBDB4, 0xBB40, 0xBCD4))
        self.assertEqual(target["translation"], "天堂基地库存大放送！喷射模组大特惠！")
        self.assertTrue(all(t["source_slot_size"] == 140 for ts in self.targets.values() for t in ts))

    def test_record_fields_are_not_ticker_signatures(self):
        data = bytearray(self.chunks[108])
        data[0xBCCA:0xBCD4] = bytes.fromhex("341278569abc11223344")
        owner, = self.owners_108(data)
        self.assertEqual(owner.text_offset, 0xBCD4)

    def test_old_ff_text_decoy_and_command_after_terminal_are_ignored(self):
        data = bytearray(self.chunks[108])
        data[0x100:0x18C] = data[0xBCD4:0xBD60]
        data[0xF6:0x100] = b"\xff" * 6 + bytes(4)
        # Looks like a real command, but lies after the next-stage transition.
        data.extend(struct.pack("<III", 10, 0, 0x762230))
        owners = self.owners_108(data)
        self.assertEqual([x.text_offset for x in owners], [0xBCD4])

    def test_null_intermission_pointer_has_no_ticker(self):
        data = bytearray(self.chunks[108])
        struct.pack_into("<I", data, 0xBDBC, 0)
        self.assertEqual(self.owners_108(data), ())

    def test_missing_translation_fails_with_owned_location(self):
        entries = dict(self.entries)
        del entries[self.targets[108][0]["source_text"]]
        with self.assertRaisesRegex(SystemExit, "unregistered owned story ticker sources") as failure:
            _discover_story_tickers(self.chunks, self.table, entries,
                                   self.reference, functions=self.functions)
        self.assertIn("(108, 48340,", str(failure.exception))

    def test_malformed_owned_text_fails_instead_of_being_skipped(self):
        for payload in (b"\x01" * 140, bytes(140)):
            with self.subTest(payload=payload[:2]):
                data = bytearray(self.chunks[108])
                data[0xBCD4:0xBD60] = payload
                with self.assertRaisesRegex(SystemExit, "invalid owned story ticker"):
                    self.discover_108(data)

    def test_nonzero_owned_padding_fails(self):
        data = bytearray(self.chunks[108])
        data[0xBD5F] = 1
        with self.assertRaisesRegex(SystemExit, "termination or padding"):
            self.discover_108(data)

    def test_invalid_pointer_or_duplicate_record_fails(self):
        data = bytearray(self.chunks[108])
        struct.pack_into("<I", data, 0xBDBC, 0x7566F0 + len(data) - 140)
        with self.assertRaisesRegex(StageParseError, "invalid or truncated"):
            self.owners_108(data)
        data = bytearray(self.chunks[108])
        struct.pack_into("<III", data, 0xBDA8, 10, 0, 0x762230)
        with self.assertRaisesRegex(StageParseError, "multiple bazaar records"):
            self.owners_108(data)

    def test_changed_initializer_or_unterminated_script_fails(self):
        for word in (0x03E00008, 0x50000000, 0x45000000):  # jr / beql / bc1f
            with self.subTest(word=hex(word)):
                data = bytearray(self.chunks[108])
                struct.pack_into("<I", data, self.functions[108] - 0x7566F0, word)
                with self.assertRaisesRegex(StageParseError, "root was not established"):
                    self.owners_108(data)
        data = bytearray(self.chunks[108][:0xBDCC])
        struct.pack_into("<III", data, 0xBDC0, 20, 0, 0)
        with self.assertRaisesRegex(StageParseError, "unterminated intermission script"):
            self.owners_108(data)

    def test_native_best_uses_its_own_initializers_and_record_offsets(self):
        iso = ROOT / "rom/best.iso"
        members = member_map(scan_iso9660(iso))
        with iso.open("rb") as stream:
            def read(name):
                member = members[name]
                stream.seek(member.extent_lba * SECTOR_SIZE)
                return stream.read(member.size)
            elf, archive, hb = read("SLPS_732.70"), read("DATA/STAGE.BIN"), read("HEDBDY/HB.BIN")
        offsets = read_executable_archive_offsets(hb, STAGE_OFFSET_SPEC, len(archive))
        chunks = [decode_production(archive[a:b]).output for a, b in zip(offsets, offsets[1:])]
        functions = read_stage_function_addresses(elf, start=0x2FF830, end=0x2FFB67)[:len(chunks)]
        owners = discover_bazaar_ticker_owners(chunks, functions,
            base_address=0x756EF0, script_pointer_global=BEST_SCRIPT_POINTER_GLOBAL)
        by_stage = {x.stage_index: x for x in owners}
        self.assertEqual(set(by_stage), set(self.targets))
        self.assertEqual((by_stage[26].text_offset, by_stage[161].text_offset), (0x93A4, 0x10B4))
        for owner in owners:
            source = decode_text(chunks[owner.stage_index], owner.text_offset,
                                 self.table, end=owner.text_offset + 140)
            self.assertEqual(source.text, self.targets[owner.stage_index][0]["source_text"])

    def test_writeback_preserves_all_non_owned_bytes_and_record_fields(self):
        config = self.config
        overrides, _ = _load_overrides(ROOT / config["font"]["proposal"],
            ROOT / config["font"]["allocation_registry"],
            ROOT / config["source"]["base_codebook"]["path"])
        overrides.update(original_fullwidth_ascii_overrides(self.table))
        runtime = project_runtime_text_table(self.table, overrides)
        for stage, targets in self.targets.items():
            with self.subTest(stage=stage):
                before = self.chunks[stage]
                after, report = _write_story_tickers(before, self.table, stage_index=stage,
                                                     targets=targets, overrides=overrides)
                target, = targets
                at = target["decoded_offset"]
                self.assertEqual(after[:at], before[:at])
                self.assertEqual(after[at+140:], before[at+140:])
                self.assertEqual(len(after), len(before))
                self.assertTrue(report["story_ticker_fixed_slots_exact"])
                self.assertTrue(report["story_ticker_translated_reread_exact"])
                reread = decode_text(after, at, runtime, end=at+140)
                if stage == 108:
                    self.assertEqual(reread.text, "天堂基地库存大放送！喷射模组大特惠！")
                    self.assertEqual(after[0xBCCA:0xBCD4], bytes.fromhex("ffffab00ac0030197600"))


if __name__ == "__main__":
    unittest.main()
