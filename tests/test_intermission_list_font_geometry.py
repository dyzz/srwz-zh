import struct
import unittest
from pathlib import Path

from tools.srwz.canary import double_byte_width_class
from tools.srwz.intermission_font_geometry import (
    CAVE_CAPACITY,
    CAVE_VA,
    DEFAULT_METRICS_PREIMAGE,
    DEFAULT_METRICS_VA,
    ENTRY_PREIMAGE,
    IntermissionFontGeometryError,
    IntermissionFontGeometryMetrics,
    PILOT_ENTRY_VA,
    PILOT_RESTORE_CALL_VA,
    RESTORE_TRAMPOLINE_VA,
    SET_CONDITIONAL_METRICS_PREIMAGE,
    SET_CONDITIONAL_METRICS_VA,
    SET_METRICS_PREIMAGE,
    SET_METRICS_VA,
    STORE_HELPER_VA,
    TRAMPOLINE_SIZE,
    UNIT_ENTRY_VA,
    UNIT_RESTORE_CALL_VA,
    apply_intermission_font_geometry_patch,
    build_trampoline,
    va_to_file_offset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_SLPS = PROJECT_ROOT / "work/disc/SLPS_258.87"


def words(data: bytes) -> tuple[int, ...]:
    return struct.unpack(f"<{len(data) // 4}I", data)


def jump_target(word: int, pc: int) -> int:
    return ((pc + 4) & 0xF0000000) | ((word & 0x03FFFFFF) << 2)


class IntermissionListFontGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ORIGINAL_SLPS.read_bytes()
        cls.metrics = IntermissionFontGeometryMetrics()
        cls.output, cls.report = apply_intermission_font_geometry_patch(
            cls.source,
            metrics=cls.metrics,
        )

    def test_patch_is_size_preserving_and_scope_locked(self):
        self.assertEqual(len(self.output), len(self.source))
        self.assertEqual(
            self.report["scope"],
            "intermission pilot and unit list standard metrics only",
        )
        self.assertEqual(
            self.report["metrics"],
            {
                "render_width": 22,
                "render_height": 11,
                "advance_width": 22,
                "advance_height": 11,
            },
        )
        self.assertTrue(self.report["changed_bytes_confined_to_patch_plan"])
        self.assertTrue(self.report["restores_geometry_after_each_renderer"])
        self.assertTrue(self.report["conditional_width_mode_disabled"])
        self.assertTrue(self.report["conditional_metric_groups_ignored"])
        self.assertEqual(
            self.report["metric_groups"],
            ["main"],
        )
        self.assertTrue(
            self.report["style_cleanup_preserved_without_global_reset"]
        )

    def test_both_list_renderers_call_the_same_local_trampolines(self):
        for entry_va in (PILOT_ENTRY_VA, UNIT_ENTRY_VA):
            offset = va_to_file_offset(entry_va)
            before = self.source[offset : offset + len(ENTRY_PREIMAGE)]
            after = self.output[offset : offset + len(ENTRY_PREIMAGE)]
            self.assertEqual(before, ENTRY_PREIMAGE)
            instructions = words(after)
            self.assertEqual(jump_target(instructions[0], entry_va), CAVE_VA)
            self.assertEqual(instructions[1], words(ENTRY_PREIMAGE)[0])

        for restore_va in (PILOT_RESTORE_CALL_VA, UNIT_RESTORE_CALL_VA):
            instruction = words(
                self.output[
                    va_to_file_offset(restore_va) :
                    va_to_file_offset(restore_va) + 4
                ]
            )[0]
            self.assertEqual(
                jump_target(instruction, restore_va),
                RESTORE_TRAMPOLINE_VA,
            )

    def test_trampoline_uses_standard_metrics_and_disables_conditional_width(self):
        trampoline = build_trampoline(self.metrics)
        self.assertEqual(len(trampoline), TRAMPOLINE_SIZE)
        self.assertLessEqual(len(trampoline), CAVE_CAPACITY)
        cave_offset = va_to_file_offset(CAVE_VA)
        self.assertEqual(
            self.source[cave_offset : cave_offset + TRAMPOLINE_SIZE],
            bytes(TRAMPOLINE_SIZE),
        )
        self.assertEqual(
            self.output[cave_offset : cave_offset + TRAMPOLINE_SIZE],
            trampoline,
        )
        instructions = words(trampoline)
        self.assertEqual(instructions[0] & 0xFFFF, 11)
        self.assertEqual(instructions[1] & 0xFFFF, 22)
        self.assertEqual(instructions[2] & 0xFFFF, 11)
        self.assertEqual(instructions[3] & 0xFFFF, 22)
        self.assertEqual(
            jump_target(instructions[4], CAVE_VA + 16),
            STORE_HELPER_VA,
        )
        restore_index = 6
        self.assertEqual(instructions[restore_index] & 0xFFFF, 11)
        self.assertEqual(instructions[restore_index + 1] & 0xFFFF, 22)
        self.assertEqual(
            jump_target(
                instructions[restore_index + 4],
                RESTORE_TRAMPOLINE_VA + 16,
            ),
            STORE_HELPER_VA,
        )

        helper = instructions[12:]
        self.assertEqual(len(helper), 8)
        self.assertEqual([word >> 26 for word in helper[:2]], [0x2B] * 2)
        self.assertEqual(
            [word & 0xFFFF for word in helper[:2]],
            [0xE344, 0xE348],
        )
        self.assertEqual(helper[2] >> 26, 0x29)
        self.assertEqual(helper[2] & 0xFFFF, 0xE378)
        self.assertEqual(helper[3:6], (0, 0, 0))
        self.assertEqual(helper[-1], words(ENTRY_PREIMAGE)[1])

    def test_global_default_and_generic_setter_are_not_modified(self):
        for address, expected in (
            (DEFAULT_METRICS_VA, DEFAULT_METRICS_PREIMAGE),
            (SET_METRICS_VA, SET_METRICS_PREIMAGE),
            (
                SET_CONDITIONAL_METRICS_VA,
                SET_CONDITIONAL_METRICS_PREIMAGE,
            ),
        ):
            offset = va_to_file_offset(address)
            self.assertEqual(self.source[offset : offset + len(expected)], expected)
            self.assertEqual(self.output[offset : offset + len(expected)], expected)

    def test_reported_meier_case_crosses_the_games_code_class_boundary(self):
        self.assertEqual(double_byte_width_class(0x947E), "default_double_byte")
        self.assertEqual(
            double_byte_width_class(0x846D),
            "conditional_double_byte",
        )

    def test_drifted_cave_fails_before_writing(self):
        drifted = bytearray(self.source)
        drifted[va_to_file_offset(CAVE_VA)] = 1
        with self.assertRaisesRegex(
            IntermissionFontGeometryError,
            "preimage mismatch",
        ):
            apply_intermission_font_geometry_patch(bytes(drifted))


if __name__ == "__main__":
    unittest.main()
