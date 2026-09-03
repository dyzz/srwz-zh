from __future__ import annotations

import struct
import unittest
from unittest.mock import patch

from tools.srwz import text as text_module
from tools.srwz.text import TextTable
from tools.srwz.runtime_keywords import discover_stage_keyword_pointer_owners
from tools.srwz.stage import parse_stage
from tools.srwz.stage_formations import discover_stage_formation_pointer_owners
from tools.srwz.writeback import WritebackError
from tools.srwz.writers import (
    PreparedStageMessageEncoders,
    StageExactAddressContract,
    encode_stage_message,
    repack_stage_texts_in_place,
)


class StageRepackSafetyTest(unittest.TestCase):
    @staticmethod
    def _fixture() -> tuple[int, bytes]:
        base = 0x7566F0
        source = bytearray(0x240)
        for index, target in enumerate((0x100, 0x120, 0x140)):
            high = ((base + target + 0x8000) >> 16) & 0xFFFF
            low = (base + target) & 0xFFFF
            struct.pack_into("<h", source, 0x90 + index * 16, high)
            struct.pack_into("<h", source, 0x98 + index * 16, low)
        struct.pack_into("<II", source, 0x120, base + 0x160, 1)
        struct.pack_into("<II", source, 0x140, 0, 1)
        struct.pack_into("<II", source, 0x160, base + 0x180, 0)
        struct.pack_into("<I", source, 0x1A0, 1)
        struct.pack_into("<I", source, 0x1B0, base + 0x200)
        struct.pack_into("<I", source, 0x1C0, 0x7E)
        source[0x200:0x209] = b"Pilot\nHi\x00"
        return base, bytes(source)

    def test_untyped_exact_address_candidate_fails_closed(self) -> None:
        base, raw = self._fixture()
        source = bytearray(raw)
        struct.pack_into("<I", source, 0x50, base + 0x200)

        with self.assertRaisesRegex(
            WritebackError,
            "untyped exact-address candidates.*automatic STAGE alias rewriting is disabled",
        ):
            repack_stage_texts_in_place(
                bytes(source),
                TextTable(characters={}, tags={}),
                stage_index=1,
                function_address=0,
                replacements={
                    "story/001/dialogue/01.01/0000": "Longer message",
                },
            )

    def test_pointer_like_interior_value_is_not_rewritten(self) -> None:
        base, raw = self._fixture()
        source = bytearray(raw)
        struct.pack_into("<I", source, 0x50, base + 0x202)

        result = repack_stage_texts_in_place(
            bytes(source),
            TextTable(characters={}, tags={}),
            stage_index=1,
            function_address=0,
            replacements={
                "story/001/dialogue/01.01/0000": "Hello",
            },
        )

        self.assertEqual(
            struct.unpack_from("<I", result.data, 0x50)[0],
            base + 0x202,
        )
        self.assertEqual(result.owned_regions, ((0x200, 0x210),))

    def test_preparsed_source_uses_targeted_output_reread(self) -> None:
        _base, source = self._fixture()
        table = TextTable(characters={}, tags={})
        parsed = parse_stage(
            source,
            table,
            stage_index=1,
            function_address=0,
        )

        with patch(
            "tools.srwz.writers.parse_stage",
            side_effect=AssertionError("unexpected full STAGE reparse"),
        ):
            result = repack_stage_texts_in_place(
                source,
                table,
                stage_index=1,
                function_address=0,
                replacements={
                    "story/001/dialogue/01.01/0000": "Hello",
                },
                parsed_source=parsed,
            )

        allocation = result.allocations[0]
        self.assertEqual(
            struct.unpack_from("<I", result.data, allocation.pointer_offset)[0],
            0x7566F0 + allocation.arena_offset,
        )

    def test_typed_alias_is_rewritten_to_the_unique_placement(self) -> None:
        base, raw = self._fixture()
        source = bytearray(raw)
        struct.pack_into("<I", source, 0x50, base + 0x200)

        result = repack_stage_texts_in_place(
            bytes(source),
            TextTable(characters={}, tags={}),
            stage_index=1,
            function_address=0,
            replacements={
                "story/001/dialogue/01.01/0000": "Hello",
            },
            exact_address_contracts=(
                StageExactAddressContract(
                    pointer_offset=0x50,
                    target_offset=0x200,
                    owner="test_alias_pointer",
                    action="rewrite_alias",
                ),
            ),
        )

        allocation = result.allocations[0]
        self.assertEqual(
            struct.unpack_from("<I", result.data, 0x50)[0],
            base + allocation.arena_offset,
        )
        self.assertEqual(result.exact_address_contracts[0].owner, "test_alias_pointer")

    def test_typed_nonpointer_is_preserved(self) -> None:
        base, raw = self._fixture()
        source = bytearray(raw)
        struct.pack_into("<I", source, 0x50, base + 0x200)

        result = repack_stage_texts_in_place(
            bytes(source),
            TextTable(characters={}, tags={}),
            stage_index=1,
            function_address=0,
            replacements={
                "story/001/dialogue/01.01/0000": "Hello",
            },
            exact_address_contracts=(
                StageExactAddressContract(
                    pointer_offset=0x50,
                    target_offset=0x200,
                    owner="test_u16_table_nonpointer",
                    action="preserve_nonpointer",
                ),
            ),
        )

        self.assertEqual(
            struct.unpack_from("<I", result.data, 0x50)[0],
            base + 0x200,
        )

    def test_typed_contract_preimage_mismatch_fails_closed(self) -> None:
        base, raw = self._fixture()
        source = bytearray(raw)
        struct.pack_into("<I", source, 0x50, base + 0x202)

        with self.assertRaisesRegex(WritebackError, "contract preimage mismatch"):
            repack_stage_texts_in_place(
                bytes(source),
                TextTable(characters={}, tags={}),
                stage_index=1,
                function_address=0,
                replacements={
                    "story/001/dialogue/01.01/0000": "Hello",
                },
                exact_address_contracts=(
                    StageExactAddressContract(
                        pointer_offset=0x50,
                        target_offset=0x200,
                        owner="test_alias_pointer",
                        action="rewrite_alias",
                    ),
                ),
            )

    def test_runtime_keyword_row_discovers_all_four_owned_pointers(self) -> None:
        base = 0x7566F0
        source = bytearray(0x280)
        struct.pack_into(
            "<4I",
            source,
            0x40,
            *(base + offset for offset in (0x200, 0x210, 0x220, 0x230)),
        )
        source[0x200:0x206] = b"Pilot\0"

        owners = discover_stage_keyword_pointer_owners(
            bytes(source),
            TextTable(characters={}, tags={}),
            ("Pilot",),
            runtime_base=base,
        )

        self.assertEqual(
            owners,
            {0x40: 0x200, 0x44: 0x210, 0x48: 0x220, 0x4C: 0x230},
        )

    def test_formation_record_discovers_owned_pointer(self) -> None:
        base = 0x7566F0
        source = bytearray(0x100)
        source[0x38:0x3A] = b"\xFF\xFF"
        source[0x3E:0x40] = b"\xFF\xFF"
        struct.pack_into("<4I", source, 0x40, base + 0x80, 0xFF, 0, 0)

        self.assertEqual(
            discover_stage_formation_pointer_owners(bytes(source)),
            {0x40: 0x80},
        )

    def test_prepared_stage_encoders_validate_overrides_only_at_creation(self) -> None:
        table = TextTable(
            characters={0x8173: "《", 0x8174: "》"},
            tags={},
        )
        overrides = {":": 0x9000, "《": 0x9001, "》": 0x9002}
        original_validator = text_module._validated_overrides
        with patch.object(
            text_module,
            "_validated_overrides",
            wraps=original_validator,
        ) as validator:
            prepared = PreparedStageMessageEncoders(table, overrides)
            creation_calls = validator.call_count
            self.assertEqual(creation_calls, 4)

            ordinary = encode_stage_message(
                table,
                overrides,
                entry_id="story/001/dialogue/01.01/0000",
                source_text="Text",
                replacement="Text",
                prepared_encoders=prepared,
            )
            condition = encode_stage_message(
                table,
                overrides,
                entry_id="story/001/condition/01.01/0000",
                source_text="Pilot:",
                replacement="Pilot:",
                prepared_encoders=prepared,
            )
            keyword = encode_stage_message(
                table,
                overrides,
                entry_id="story/001/dialogue/01.01/0001",
                source_text="《A》",
                replacement="《A》",
                prepared_encoders=prepared,
            )

            self.assertEqual(validator.call_count, creation_calls)
        self.assertEqual(ordinary, b"Text")
        self.assertTrue(condition.endswith(b":"))
        self.assertEqual(keyword, b"\x81\x73A\x81\x74")


if __name__ == "__main__":
    unittest.main()
