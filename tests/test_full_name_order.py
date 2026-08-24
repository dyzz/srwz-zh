from __future__ import annotations

import unittest

from tools.srwz.full_name_order import (
    FullNameOrderError,
    apply_route_specific_full_name_order,
)


def _contract() -> dict[str, object]:
    return {
        "member": "SLPS_258.87",
        "policy": "select_chinese_full_name_order_by_protagonist_route",
        "elf_file_offset_base": "0x1A80",
        "elf_virtual_address_base": "0x100000",
        "virtual_address": "0x201334",
        "file_offset": "0x102DB4",
        "base_register_runtime_value": "0x570000",
        "original_instruction_hex": "72852380",
        "replacement_instruction_hex": "6E852380",
        "original_load_address": "0x568572",
        "replacement_load_address": "0x56856E",
        "savedata_formatter": {
            "virtual_address": "0x3EA61C",
            "file_offset": "0x2EC09C",
            "original_instruction_hex": "2D006280",
            "replacement_instruction_hex": "2B100400",
            "route_argument_multiplier": 7,
        },
        "savedata_writeback": {
            "virtual_address": "0x3EAA70",
            "file_offset": "0x2EC4F0",
            "base_register_runtime_value": "0x570000",
            "original_instruction_hex": "72852380",
            "replacement_instruction_hex": "6E852380",
            "original_load_address": "0x568572",
            "replacement_load_address": "0x56856E",
        },
        "route_values": {"rand": 0, "setsuko": 1},
        "output_orders": {
            "rand": "given_middle_dot_family",
            "setsuko": "family_given",
        },
    }


class FullNameOrderTest(unittest.TestCase):
    def _executable(self) -> bytes:
        contract = _contract()
        offset = int(str(contract["file_offset"]), 0)
        formatter = contract["savedata_formatter"]
        writeback = contract["savedata_writeback"]
        self.assertIsInstance(formatter, dict)
        self.assertIsInstance(writeback, dict)
        formatter_offset = int(str(formatter["file_offset"]), 0)
        writeback_offset = int(str(writeback["file_offset"]), 0)
        executable = bytearray(max(offset, formatter_offset, writeback_offset) + 8)
        executable[offset : offset + 4] = bytes.fromhex(
            str(contract["original_instruction_hex"])
        )
        executable[formatter_offset : formatter_offset + 4] = bytes.fromhex(
            str(formatter["original_instruction_hex"])
        )
        executable[writeback_offset : writeback_offset + 4] = bytes.fromhex(
            str(writeback["original_instruction_hex"])
        )
        return bytes(executable)

    def test_applies_route_specific_name_order_patch(self) -> None:
        contract = _contract()
        offset = int(str(contract["file_offset"]), 0)
        source = self._executable()

        output, report = apply_route_specific_full_name_order(source, contract)

        self.assertEqual(output[offset : offset + 4], bytes.fromhex("6E852380"))
        formatter_offset = int(
            str(contract["savedata_formatter"]["file_offset"]), 0
        )
        writeback_offset = int(
            str(contract["savedata_writeback"]["file_offset"]), 0
        )
        self.assertEqual(
            output[formatter_offset : formatter_offset + 4],
            bytes.fromhex("2B100400"),
        )
        self.assertEqual(
            output[writeback_offset : writeback_offset + 4],
            bytes.fromhex("6E852380"),
        )
        self.assertEqual(len(output), len(source))
        self.assertEqual(report["changed_instruction_count"], 3)
        self.assertEqual(report["changed_byte_count"], 6)
        self.assertTrue(report["instruction_replacement_exact"])
        self.assertTrue(report["all_instruction_replacements_exact"])
        self.assertTrue(
            report["savedata_formatter"]["instruction_replacement_exact"]
        )
        self.assertTrue(
            report["savedata_writeback"]["instruction_replacement_exact"]
        )
        self.assertEqual(report["route_values"], {"rand": 0, "setsuko": 1})
        self.assertEqual(
            report["output_orders"],
            {
                "rand": "given_middle_dot_family",
                "setsuko": "family_given",
            },
        )

    def test_accepts_final_iso_readback_idempotently(self) -> None:
        contract = _contract()
        first, _first_report = apply_route_specific_full_name_order(
            self._executable(), contract
        )

        second, report = apply_route_specific_full_name_order(first, contract)

        self.assertEqual(second, first)
        self.assertTrue(report["already_patched"])
        self.assertEqual(report["changed_instruction_count"], 0)
        self.assertEqual(report["changed_byte_count"], 0)

    def test_rejects_instruction_preimage_drift(self) -> None:
        contract = _contract()
        offset = int(str(contract["file_offset"]), 0)
        executable = bytearray(self._executable())
        executable[offset] = 0x00

        with self.assertRaisesRegex(FullNameOrderError, "preimage drift"):
            apply_route_specific_full_name_order(bytes(executable), contract)

    def test_rejects_route_contract_drift(self) -> None:
        contract = _contract()
        contract["route_values"] = {"rand": 1, "setsuko": 0}

        with self.assertRaisesRegex(FullNameOrderError, "route values drift"):
            apply_route_specific_full_name_order(self._executable(), contract)

    def test_rejects_savedata_formatter_preimage_drift(self) -> None:
        contract = _contract()
        formatter_offset = int(
            str(contract["savedata_formatter"]["file_offset"]), 0
        )
        executable = bytearray(self._executable())
        executable[formatter_offset] = 0x00

        with self.assertRaisesRegex(
            FullNameOrderError, "savedata formatter instruction preimage drift"
        ):
            apply_route_specific_full_name_order(bytes(executable), contract)


if __name__ == "__main__":
    unittest.main()
