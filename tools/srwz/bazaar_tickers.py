"""Discover bazaar ticker owners through the initialized intermission script.

The bytes before a ticker are live record fields, not a string signature.
Original/BEST dispatch consumes 12-byte commands; opcode 0x0A supplies the
intermission's optional bazaar record at +8. The renderer reads record+0x194.
See docs/BAZAAR_TICKER_STATIC_ANALYSIS_20261005.md for native code evidence.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Sequence

from .stage import STAGE_BASE_ADDRESS, StageParseError


BAZAAR_RECORD_SIZE = 0x220
BAZAAR_TICKER_OFFSET = 0x194
BAZAAR_TICKER_ALLOCATION_SIZE = 140
ORIGINAL_SCRIPT_POINTER_GLOBAL = 0x594F98
BEST_SCRIPT_POINTER_GLOBAL = 0x595798
BAZAAR_TICKER_INVENTORY_CONTRACT = {
    "selection_authority": "initialized_intermission_script",
    "command_size": 12,
    "intermission_opcode": 10,
    "record_pointer_offset": 8,
    "record_size": BAZAAR_RECORD_SIZE,
    "ticker_offset": BAZAAR_TICKER_OFFSET,
    "slot_allocation_size": BAZAAR_TICKER_ALLOCATION_SIZE,
    "expected_records_per_stage": 1,
}


@dataclass(frozen=True)
class BazaarTickerOwner:
    stage_index: int
    script_root_offset: int
    command_offset: int
    record_offset: int

    @property
    def text_offset(self) -> int:
        return self.record_offset + BAZAAR_TICKER_OFFSET


def _script_root(data: bytes, function: int, base: int, root_global: int) -> int | None:
    """Decode only the straight-line initialization prefix, never guess a path.

    Unknown loads/arithmetic invalidate their destination. Calls/branches stop
    discovery. The source root store precedes control flow (including the
    stg_901 conditional's delay-slot copy to the second script global).
    """
    start = function - base
    if not 0 <= start <= len(data) - 4 or start % 4:
        raise StageParseError("bazaar initializer is outside the stage", offset=max(0, start))
    registers: dict[int, int | None] = {0: 0}
    for at in range(start, min(start + 128, len(data) - 3), 4):
        word = struct.unpack_from("<I", data, at)[0]
        opcode, source, target = word >> 26, (word >> 21) & 31, (word >> 16) & 31
        immediate = word & 0xFFFF
        signed = immediate if immediate < 0x8000 else immediate - 0x10000
        if opcode == 15:  # lui
            registers[target] = immediate << 16
        elif opcode in (9, 13):  # addiu / ori
            value = registers.get(source)
            registers[target] = None if value is None else (
                (value + signed) & 0xFFFFFFFF if opcode == 9 else value | immediate)
        elif opcode == 43:  # sw
            address = registers.get(source)
            if address is not None and (address + signed) & 0xFFFFFFFF == root_global:
                pointer = registers.get(target)
                if pointer is None:
                    raise StageParseError("bazaar script root value is unresolved", offset=at)
                root = pointer - base
                if root % 4 or not 0 <= root <= len(data) - 12:
                    raise StageParseError("bazaar script root is outside the stage", offset=at)
                return root
        elif (opcode in (1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23)
              or (opcode in (16, 17, 18) and source == 8)
              or (opcode == 0 and word & 63 in (8, 9, 12, 13))):
            break
        elif opcode == 0:  # arithmetic/shift destination (incl. move), not a known constant
            if word:
                registers.pop((word >> 11) & 31, None)
        elif opcode in (31, 40, 41, 42, 44, 45, 46, 63):
            pass  # R5900 SQ and ordinary memory stores do not change GPRs
        else:
            registers.pop(target, None)
        registers[0] = 0
    if len(data) < BAZAAR_RECORD_SIZE:
        return None  # Native small dispatcher/stub chunks cannot contain a record.
    raise StageParseError("bazaar script root was not established", offset=start)


def discover_bazaar_ticker_owners(
    decoded_chunks: Sequence[bytes],
    functions: Sequence[int],
    *,
    base_address: int = STAGE_BASE_ADDRESS,
    script_pointer_global: int = ORIGINAL_SCRIPT_POINTER_GLOBAL,
) -> tuple[BazaarTickerOwner, ...]:
    """Return every owned ticker, with errors for malformed/unclassified inputs.

    No source text, FF pattern, callback value or corpus decision participates
    in owner selection. Null intermission pointers have no bazaar record.
    The pinned baseline has at most one record per stage; changes fail closed.
    """
    if len(functions) != len(decoded_chunks):
        raise ValueError("bazaar stage function/chunk counts differ")
    result = []
    for stage_index, (data, function) in enumerate(zip(decoded_chunks, functions)):
        if stage_index == 0 and function == 0:
            continue  # flow.bin uses a different format, not a stage initializer.
        try:
            root = _script_root(data, function, base_address, script_pointer_global)
            if root is None:
                continue
            owners = []
            for at in range(root, len(data) - 11, 12):
                word, _argument, pointer = struct.unpack_from("<III", data, at)
                opcode = word & 0xFFFF
                if opcode in (0, 1, 3):
                    break  # terminal/next-stage dispatch does not advance this list
                if not 0 < opcode <= 0x46:
                    raise StageParseError("invalid intermission script command", offset=at)
                if opcode != 10 or pointer == 0:
                    continue
                record = pointer - base_address
                if record % 4 or not 0 <= record <= len(data) - BAZAAR_RECORD_SIZE:
                    raise StageParseError("bazaar record pointer is invalid or truncated", offset=at + 8)
                owners.append(BazaarTickerOwner(stage_index, root, at, record))
            else:
                raise StageParseError("unterminated intermission script", offset=root)
            if len(owners) > 1:
                raise StageParseError("multiple bazaar records in one stage", offset=root)
            result.extend(owners)
        except StageParseError as error:
            raise StageParseError(f"stage {stage_index}: {error}", offset=error.offset) from error
    return tuple(result)
