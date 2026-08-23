import json
import unittest
from pathlib import Path

from tools.srwz.library_unlock import (
    LibraryUnlockError,
    apply_library_default_unlock,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LibraryDefaultUnlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = json.loads(
            (PROJECT_ROOT / "config/library/v0.2.0.json").read_text(
                encoding="utf-8"
            )
        )
        cls.contract = cls.scope["library_default_unlock"]
        cls.executable = (PROJECT_ROOT / "work/disc/SLPS_258.87").read_bytes()

    def test_all_four_surfaces_change_only_one_and_to_or_instruction(self):
        output, report = apply_library_default_unlock(
            self.executable,
            self.contract,
        )
        self.assertEqual(report["surface_count"], 4)
        self.assertEqual(report["changed_instruction_count"], 4)
        self.assertEqual(report["changed_byte_count"], 4)
        self.assertTrue(report["all_instruction_replacements_exact"])
        self.assertTrue(report["save_writeback_functions_unchanged"])
        self.assertTrue(report["executable_size_preserved"])

        changed_offsets = {
            index
            for index, (before, after) in enumerate(
                zip(self.executable, output)
            )
            if before != after
        }
        expected_changed_offsets = {
            int(patch["file_offset"], 0)
            for patch in self.contract["patches"]
        }
        self.assertEqual(changed_offsets, expected_changed_offsets)

    def test_patch_is_idempotent(self):
        output, _report = apply_library_default_unlock(
            self.executable,
            self.contract,
        )
        second_output, second_report = apply_library_default_unlock(
            output,
            self.contract,
        )
        self.assertEqual(second_output, output)
        self.assertEqual(second_report["changed_instruction_count"], 0)
        self.assertEqual(second_report["changed_byte_count"], 0)

    def test_patch_rejects_unknown_preimage(self):
        candidate = bytearray(self.executable)
        offset = int(self.contract["patches"][0]["file_offset"], 0)
        candidate[offset + 1] ^= 0xFF
        with self.assertRaisesRegex(
            LibraryUnlockError,
            "instruction preimage drift",
        ):
            apply_library_default_unlock(bytes(candidate), self.contract)

    def test_patch_rejects_non_and_to_or_replacement(self):
        contract = json.loads(json.dumps(self.contract))
        contract["patches"][0]["replacement_instruction_hex"] = "00000000"
        with self.assertRaisesRegex(
            LibraryUnlockError,
            "AND-to-OR",
        ):
            apply_library_default_unlock(self.executable, contract)


if __name__ == "__main__":
    unittest.main()
