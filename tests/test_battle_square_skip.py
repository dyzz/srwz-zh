from __future__ import annotations

import hashlib
import json
import shutil
import struct
import unittest
from pathlib import Path

from tools.srwz.battle_square_skip import (
    STATE_BLOCK_OFFSET,
    STATE_MARKER,
    BattleSquareSkipError,
    apply_battle_square_skip,
    executable_write_ranges,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RETAIL_EXECUTABLES = {
    "original": PROJECT_ROOT / "work/disc/SLPS_258.87",
}


def _synthetic_executable(contract: dict, edition: str) -> bytes:
    """A zero-filled executable carrying only the retail words the patch touches."""

    edition_contract = contract["editions"][edition]
    file_base = int(edition_contract["elf_file_offset_base"], 0)
    virtual_base = int(edition_contract["elf_virtual_address_base"], 0)
    cave = int(edition_contract["cave"]["virtual_address"], 0) - virtual_base + file_base
    size = max(
        [cave + int(edition_contract["cave"]["size"], 0)]
        + [
            int(site["virtual_address"], 0) - virtual_base + file_base + 4
            for site in edition_contract["patches"]
        ]
    )
    executable = bytearray(size + 16)
    for site in edition_contract["patches"]:
        offset = int(site["virtual_address"], 0) - virtual_base + file_base
        executable[offset : offset + 4] = bytes.fromhex(site["original_instruction_hex"])
    return bytes(executable)


class BattleSquareSkipTest(unittest.TestCase):
    def setUp(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "config/full-story-components.json").read_text(encoding="utf-8")
        )
        self.contract = config["battle_square_skip"]

    def test_contract_declares_both_editions_with_identical_layout(self) -> None:
        editions = self.contract["editions"]
        self.assertEqual(set(editions), {"original", "best"})
        for edition, contract in editions.items():
            blob = bytes.fromhex(contract["hook_hex"])
            self.assertEqual(len(blob), 0x3C0, edition)
            self.assertEqual(hashlib.sha256(blob).hexdigest(), contract["hook_sha256"], edition)
            self.assertEqual(
                struct.unpack_from("<I", blob, STATE_BLOCK_OFFSET + 0x1C)[0], STATE_MARKER, edition
            )
            self.assertEqual(struct.unpack_from("<I", blob, STATE_BLOCK_OFFSET)[0], 0, edition)
            self.assertEqual([site["id"] for site in contract["patches"]], [
                "battle_step_world_call",
                "draw_dispatch_sprite_call",
                "se_request_prologue_0",
                "se_request_prologue_1",
                "main_loop_present_call",
            ], edition)
            self.assertEqual(contract["cave"]["virtual_address"], "0x3F6000", edition)
        # Only addresses differ between the editions; the hook logic is shared.
        original = editions["original"]
        best = editions["best"]
        self.assertNotEqual(original["symbols"], best["symbols"])
        self.assertEqual(
            [site["kind"] for site in original["patches"]],
            [site["kind"] for site in best["patches"]],
        )

    def test_apply_is_exact_and_idempotent_on_synthetic_executables(self) -> None:
        for edition in ("original", "best"):
            with self.subTest(edition=edition):
                pristine = _synthetic_executable(self.contract, edition)
                patched, report = apply_battle_square_skip(pristine, self.contract, edition)
                self.assertEqual(len(patched), len(pristine))
                self.assertFalse(report["already_applied"])
                self.assertTrue(report["cave_preimage_all_zero"])
                self.assertTrue(report["all_replacements_exact"])
                self.assertEqual(report["site_count"], 5)
                self.assertEqual(report["extra_steps_per_frame"], 15)
                self.assertEqual(report["packet_limit_bytes"], 0x30000)
                self.assertTrue(report["sound_effects_muted_while_skipping"])
                self.assertTrue(report["sprites_skipped_in_extra_steps"])
                contract = self.contract["editions"][edition]
                cave_offset = int(report["cave_file_offset"], 0)
                blob = bytes.fromhex(contract["hook_hex"])
                self.assertEqual(patched[cave_offset : cave_offset + len(blob)], blob)
                # every byte outside the declared ranges is untouched
                ranges = executable_write_ranges(self.contract, edition)
                restored = bytearray(patched)
                for lo, hi in ranges:
                    restored[lo:hi] = pristine[lo:hi]
                self.assertEqual(bytes(restored), pristine)
                again, readback = apply_battle_square_skip(patched, self.contract, edition)
                self.assertEqual(again, patched)
                self.assertTrue(readback["already_applied"])
                self.assertEqual(readback["changed_byte_count"], 0)

    def test_replacement_words_encode_jumps_into_the_cave(self) -> None:
        for edition, contract in self.contract["editions"].items():
            cave = int(contract["cave"]["virtual_address"], 0)
            for site in contract["patches"]:
                word = struct.unpack("<I", bytes.fromhex(site["replacement_instruction_hex"]))[0]
                if site["kind"] == "nop":
                    self.assertEqual(word, 0, (edition, site["id"]))
                    continue
                opcode = {"jal": 3, "j": 2}[site["kind"]]
                target = cave + int(contract["stub_offsets"][site["stub"]], 0)
                self.assertEqual(word >> 26, opcode, (edition, site["id"]))
                self.assertEqual((word & 0x03FFFFFF) << 2, target, (edition, site["id"]))

    def test_drifted_preimages_fail_closed(self) -> None:
        pristine = bytearray(_synthetic_executable(self.contract, "original"))
        contract = self.contract["editions"]["original"]
        site = contract["patches"][0]
        offset = int(site["virtual_address"], 0) - 0x100000 + 0x1A80
        drifted = bytearray(pristine)
        drifted[offset] ^= 0x01
        with self.assertRaises(BattleSquareSkipError):
            apply_battle_square_skip(bytes(drifted), self.contract, "original")
        dirty_cave = bytearray(pristine)
        dirty_cave[int(contract["cave"]["virtual_address"], 0) - 0x100000 + 0x1A80 + 8] = 0x5A
        with self.assertRaises(BattleSquareSkipError):
            apply_battle_square_skip(bytes(dirty_cave), self.contract, "original")
        patched, _ = apply_battle_square_skip(bytes(pristine), self.contract, "original")
        partial = bytearray(patched)
        partial[offset : offset + 4] = bytes.fromhex(site["original_instruction_hex"])
        with self.assertRaises(BattleSquareSkipError):
            apply_battle_square_skip(bytes(partial), self.contract, "original")
        bad_hash = json.loads(json.dumps(self.contract))
        bad_hash["editions"]["original"]["hook_sha256"] = "0" * 64
        with self.assertRaises(BattleSquareSkipError):
            apply_battle_square_skip(bytes(pristine), bad_hash, "original")
        with self.assertRaises(BattleSquareSkipError):
            apply_battle_square_skip(bytes(pristine), self.contract, "unknown")

    def test_retail_executable_preimage_when_available(self) -> None:
        path = RETAIL_EXECUTABLES["original"]
        if not path.exists():
            self.skipTest("retail executable not extracted")
        patched, report = apply_battle_square_skip(path.read_bytes(), self.contract, "original")
        self.assertFalse(report["already_applied"])
        self.assertTrue(report["cave_preimage_all_zero"])
        self.assertEqual(len(patched), path.stat().st_size)

    def test_assembled_hook_matches_contract_when_assembler_available(self) -> None:
        if shutil.which("mipsel-linux-gnu-as") is None or shutil.which("mipsel-linux-gnu-objcopy") is None:
            self.skipTest("mipsel-linux-gnu binutils not installed")
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "assemble_hook", PROJECT_ROOT / "tools/native/battle-square-skip/assemble_hook.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        for edition, contract in self.contract["editions"].items():
            blob = module.assemble(contract["symbols"])
            self.assertEqual(hashlib.sha256(blob).hexdigest(), contract["hook_sha256"], edition)


if __name__ == "__main__":
    unittest.main()
