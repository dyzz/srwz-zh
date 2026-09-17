"""Typed ownership and readback of Best's ten-way map-event dispatch tables."""
from __future__ import annotations

import struct

from .edition import EditionError

ORIGINAL_BASE = 0x7566F0
BEST_BASE = 0x756EF0
TABLE_SIZE = 40
PATTERN = (0x00031880, 0x00641821, 0x8C630000, 0x00600008)


def require(ok, message):
    if not ok:
        raise EditionError(f'STAGE event dispatch: {message}')


def dispatchers(data, base=BEST_BASE):
    """Recover actual LUI/ADDIU consumers, including signed low immediates."""
    result = []
    for offset in range(0, len(data) - 23, 4):
        hi, lo, *rest = struct.unpack_from('<6I', data, offset)
        if hi & 0xFFFF0000 != 0x3C040000 or lo & 0xFFFF0000 != 0x24840000 or tuple(rest) != PATTERN:
            continue
        low = lo & 0xFFFF
        address = ((hi & 0xFFFF) << 16) + (low if low < 0x8000 else low - 0x10000)
        table = address - base
        require(table % 4 == 0 and 0 <= table <= len(data) - TABLE_SIZE, 'table outside overlay')
        result.append({'instruction_offset': offset, 'table_offset': table,
                       'targets': list(struct.unpack_from('<10I', data, table))})
    return result


def check_shared_tail(original, native, compiled, spec, text_start, regions):
    """Reject unknown table/code changes before copying the bounded text pool."""
    src, dst, site = spec['best_table'], spec['original_table'], spec['instruction_offset']
    require(len(original) == len(native) == len(compiled), 'native tail capacity')
    require(0 <= site < text_start <= src < dst <= len(original) - TABLE_SIZE, 'layout bounds')
    require(all(text_start <= lo < hi <= dst for lo, hi in regions), 'text overlaps event table')
    old, best = dispatchers(original, ORIGINAL_BASE), dispatchers(native)
    require(len(old) == len(best) == 1, 'expected one dispatcher')
    require(old[0]['instruction_offset'] == best[0]['instruction_offset'] == site
            and old[0]['table_offset'] == dst and best[0]['table_offset'] == src, 'consumer preimage drift')
    require(all(BEST_BASE <= x < BEST_BASE + text_start and x % 4 == 0 for x in best[0]['targets']), 'target outside code')
    require([x + BEST_BASE - ORIGINAL_BASE for x in old[0]['targets']] == best[0]['targets'], 'native target preimage drift')
    require(compiled[site:site+24] == original[site:site+24]
            and compiled[dst:] == original[dst:], 'shared compiler changed event structure')
    require(original[dst+TABLE_SIZE:] == native[dst+TABLE_SIZE:]
            == bytes(len(original)-dst-TABLE_SIZE), 'unknown trailing structure')
    return dst


def relocate_dispatch(out, native, spec):
    src, dst, site = spec['best_table'], spec['original_table'], spec['instruction_offset']
    require(out[site:site+24] == native[site:site+24], 'consumer changed before relocation')
    out[dst:dst+TABLE_SIZE] = native[src:src+TABLE_SIZE]
    address = BEST_BASE + dst
    struct.pack_into('<II', out, site, 0x3C040000 | ((address + 0x8000) >> 16),
                     0x24840000 | (address & 0xFFFF))


def verify_dispatch(native, output, spec=None):
    """Check every recovered consumer and all ten targets against native Best."""
    expected = dispatchers(native)
    if spec is not None:
        require(len(expected) == 1 and expected[0]['table_offset'] == spec['best_table']
                and expected[0]['instruction_offset'] == spec['instruction_offset'], 'native contract drift')
        expected = [{**expected[0], 'table_offset': spec['original_table']}]
    actual = dispatchers(output)
    require(actual == expected, 'consumer or target mismatch')
    return actual
