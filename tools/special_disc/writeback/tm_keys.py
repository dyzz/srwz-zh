"""The SP numeric-template dispatcher matches these five stock byte strings."""

import struct

from srwz.text import TM_STOCK_KEYS

# SLPS_259.20 at 0x441aa0 loads the table at 0x4a4480.
_ELF_BASE = 0xFF680
_POINTER_TABLE = 0x4A4480
_KEY_ADDRESSES = (0x4C4640, 0x4C4650, 0x4C4668, 0x4C4670, 0x4C4680)


def stock_key_slots(exe: bytes, *, verify=True) -> dict[int, bytes]:
    pointers = struct.unpack_from('<5Q', exe, _POINTER_TABLE - _ELF_BASE)
    if pointers != _KEY_ADDRESSES:
        raise ValueError('SP numeric template key pointer drift')
    slots = {}
    for address, key in zip(pointers, TM_STOCK_KEYS.values(), strict=True):
        start = address - _ELF_BASE
        wire = key + b'\0'
        if verify and exe[start:start + len(wire)] != wire:
            raise ValueError(f'SP stock numeric template key drift at {address:#x}')
        slots[start] = wire
    return slots
