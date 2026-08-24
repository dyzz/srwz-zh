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
        "save_preview_formatter": {
            "virtual_address": "0x3E403C",
            "file_offset": "0x2E5ABC",
            "original_instruction_hex": "12004382",
            "replacement_instruction_hex": "0E004392",
            "saved_route_offset": 14,
            "saved_name_order_offset": 18,
            "joined_format": {
                "virtual_address": "0x445C98",
                "file_offset": "0x347718",
                "expected_hex": "2573257300",
                "accepted_preimage_hex": "2225732200",
            },
        },
        "savedata_formatter": {
            "virtual_address": "0x3EA61C",
            "file_offset": "0x2EC09C",
            "original_instruction_hex": "2D006280",
            "replacement_instruction_hex": "2B100400",
            "route_argument_multiplier": 7,
            "joined_format": {
                "virtual_address": "0x445F98",
                "file_offset": "0x347A18",
                "expected_hex": "2573257300",
                "accepted_preimage_hex": "2225732200",
            },
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
        preview = contract["save_preview_formatter"]
        formatter = contract["savedata_formatter"]
        writeback = contract["savedata_writeback"]
        self.assertIsInstance(preview, dict)
        self.assertIsInstance(formatter, dict)
        self.assertIsInstance(writeback, dict)
        preview_offset = int(str(preview["file_offset"]), 0)
        formatter_offset = int(str(formatter["file_offset"]), 0)
        writeback_offset = int(str(writeback["file_offset"]), 0)
        preview_format = preview["joined_format"]
        formatter_format = formatter["joined_format"]
        self.assertIsInstance(preview_format, dict)
        self.assertIsInstance(formatter_format, dict)
        preview_format_offset = int(str(preview_format["file_offset"]), 0)
        formatter_format_offset = int(str(formatter_format["file_offset"]), 0)
        executable = bytearray(
            max(
                offset,
                preview_offset,
                formatter_offset,
                writeback_offset,
                preview_format_offset,
                formatter_format_offset,
            )
            + 8
        )
        executable[offset : offset + 4] = bytes.fromhex(
            str(contract["original_instruction_hex"])
        )
        executable[preview_offset : preview_offset + 4] = bytes.fromhex(
            str(preview["original_instruction_hex"])
        )
        executable[formatter_offset : formatter_offset + 4] = bytes.fromhex(
            str(formatter["original_instruction_hex"])
        )
        executable[writeback_offset : writeback_offset + 4] = bytes.fromhex(
            str(writeback["original_instruction_hex"])
        )
        preview_expected = bytes.fromhex(str(preview_format["expected_hex"]))
        formatter_expected = bytes.fromhex(
            str(formatter_format["expected_hex"])
        )
        executable[
            preview_format_offset : preview_format_offset + len(preview_expected)
        ] = preview_expected
        executable[
            formatter_format_offset : formatter_format_offset
            + len(formatter_expected)
        ] = formatter_expected
        return bytes(executable)

    def test_applies_route_specific_name_order_patch(self) -> None:
        contract = _contract()
        offset = int(str(contract["file_offset"]), 0)
        source = self._executable()

        output, report = apply_route_specific_full_name_order(source, contract)

        self.assertEqual(output[offset : offset + 4], bytes.fromhex("6E852380"))
        preview_offset = int(
            str(contract["save_preview_formatter"]["file_offset"]), 0
        )
        formatter_offset = int(
            str(contract["savedata_formatter"]["file_offset"]), 0
        )
        writeback_offset = int(
            str(contract["savedata_writeback"]["file_offset"]), 0
        )
        self.assertEqual(
            output[preview_offset : preview_offset + 4],
            bytes.fromhex("0E004392"),
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
        self.assertEqual(report["changed_instruction_count"], 4)
        self.assertEqual(report["changed_format_count"], 0)
        self.assertEqual(report["changed_byte_count"], 8)
        self.assertTrue(report["instruction_replacement_exact"])
        self.assertTrue(report["all_instruction_replacements_exact"])
        self.assertTrue(
            report["save_preview_formatter"]["instruction_replacement_exact"]
        )
        self.assertTrue(
            report["save_preview_formatter"]["joined_format_exact"]
        )
        self.assertTrue(
            report["savedata_formatter"]["instruction_replacement_exact"]
        )
        self.assertTrue(report["savedata_formatter"]["joined_format_exact"])
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

    def test_rejects_save_preview_preimage_drift(self) -> None:
        contract = _contract()
        preview_offset = int(
            str(contract["save_preview_formatter"]["file_offset"]), 0
        )
        executable = bytearray(self._executable())
        executable[preview_offset] = 0x00

        with self.assertRaisesRegex(
            FullNameOrderError, "save preview formatter instruction preimage drift"
        ):
            apply_route_specific_full_name_order(bytes(executable), contract)

    def test_repairs_accepted_joined_name_format_preimage(self) -> None:
        contract = _contract()
        joined_format = contract["save_preview_formatter"]["joined_format"]
        joined_offset = int(str(joined_format["file_offset"]), 0)
        executable = bytearray(self._executable())
        executable[joined_offset : joined_offset + 5] = b'"%s"\0'

        output, report = apply_route_specific_full_name_order(
            bytes(executable), contract
        )

        self.assertEqual(output[joined_offset : joined_offset + 5], b"%s%s\0")
        self.assertEqual(report["changed_format_count"], 1)
        self.assertTrue(
            report["save_preview_formatter"]["joined_format_repaired"]
        )
        self.assertTrue(
            report["save_preview_formatter"]["joined_format_exact"]
        )

    def test_rejects_unknown_joined_name_format_drift(self) -> None:
        contract = _contract()
        joined_format = contract["save_preview_formatter"]["joined_format"]
        joined_offset = int(str(joined_format["file_offset"]), 0)
        executable = bytearray(self._executable())
        executable[joined_offset : joined_offset + 5] = b"BAD!\0"

        with self.assertRaisesRegex(
            FullNameOrderError, "save preview joined-name format drift"
        ):
            apply_route_specific_full_name_order(bytes(executable), contract)


if __name__ == "__main__":
    unittest.main()
