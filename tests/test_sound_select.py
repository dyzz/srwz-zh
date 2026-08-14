import json
import unittest
from pathlib import Path

from tools.srwz.codec import decode_production
from tools.srwz.library import SoundTitleSpanLock, verify_sound_title_source
from tools.srwz.sound_select import (
    SoundSelectError,
    apply_sound_select_default_unlock,
    audit_sound_select_track_metadata,
)
from tools.srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SoundSelectDefaultUnlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = json.loads(
            (PROJECT_ROOT / "config/library/v0.2.0.json").read_text(
                encoding="utf-8"
            )
        )
        cls.contract = cls.scope["sound_select_default_unlock"]
        cls.executable = (PROJECT_ROOT / "work/disc/SLPS_258.87").read_bytes()
        stored = (
            PROJECT_ROOT / "work/disc/DATA/COMPDATA.BN"
        ).read_bytes()
        decoded = decode_production(stored)
        if decoded.consumed != len(stored):
            raise AssertionError("stock COMPDATA has trailing bytes")
        cls.decoded_compdata = decoded.output
        cls.table = load_text_table(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        )
        cls.titles = verify_sound_title_source(
            cls.decoded_compdata,
            cls.table,
            SoundTitleSpanLock.from_mapping(
                cls.scope["sound_select"]["decoded_compdata"]
            ),
        )

    def test_all_101_title_records_are_real_and_sentinel_is_excluded(self):
        report = audit_sound_select_track_metadata(
            self.decoded_compdata,
            self.titles,
            self.contract,
        )
        self.assertEqual(report["title_record_count"], 101)
        self.assertEqual(report["record_count"], 102)
        self.assertEqual(
            report["availability_rule_counts"],
            {"0": 1, "1": 95, "3": 6},
        )
        self.assertTrue(report["all_title_pointers_exact"])
        self.assertTrue(report["all_track_ids_sequential"])
        self.assertTrue(report["all_title_records_nonempty"])
        self.assertTrue(report["empty_sentinel_excluded"])

    def test_patch_changes_only_the_save_progress_branch(self):
        output, report = apply_sound_select_default_unlock(
            self.executable,
            self.contract,
        )
        offset = int(self.contract["file_offset"], 0)
        self.assertEqual(
            output[offset : offset + 4],
            bytes.fromhex(self.contract["replacement_instruction_hex"]),
        )
        self.assertEqual(output[:offset], self.executable[:offset])
        self.assertEqual(output[offset + 4 :], self.executable[offset + 4 :])
        self.assertEqual(report["changed_instruction_count"], 1)
        self.assertTrue(report["instruction_replacement_exact"])
        self.assertTrue(report["executable_size_preserved"])
        # The preceding beqz is the guard that skips rule-0 sentinel rows.
        sentinel_guard_offset = offset - 8
        self.assertEqual(
            output[sentinel_guard_offset : sentinel_guard_offset + 4],
            bytes.fromhex("2F006010"),
        )

    def test_patch_rejects_unknown_preimage(self):
        candidate = bytearray(self.executable)
        offset = int(self.contract["file_offset"], 0)
        candidate[offset] ^= 0xFF
        with self.assertRaisesRegex(
            SoundSelectError,
            "instruction preimage drift",
        ):
            apply_sound_select_default_unlock(bytes(candidate), self.contract)


if __name__ == "__main__":
    unittest.main()
