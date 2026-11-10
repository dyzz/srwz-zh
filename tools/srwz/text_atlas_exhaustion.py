"""Submit accumulated text before returning when the native atlas fills.

This preserves the native capacity/truncation policy. It routes exhaustion to
the normal epilogue so text is emitted before the caller resets GS clipping.
"""
import struct

SITES = {'original': (0x13AA34, 0x13ABB0),
         'best': (0x13AA34, 0x13ABB0),
         'sp': (0x13B4D4, 0x13B650)}
BEFORE = struct.pack('<I', 0x0260102D)
AFTER = struct.pack('<I', 0x1000005E)


def install(executable: bytes, edition: str):
    if edition not in SITES:
        raise ValueError(f'Unaudited text atlas edition: {edition}')
    if len(executable) < 52 or executable[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('Text atlas patch requires little-endian ELF32')
    ph = struct.unpack_from('<I', executable, 28)[0]
    stride, count = struct.unpack_from('<HH', executable, 42)
    if stride != 32 or ph + stride * count > len(executable):
        raise ValueError('Invalid text atlas ELF program headers')
    headers = [struct.unpack_from('<8I', executable, ph + i * stride) for i in range(count)]

    def offset(address, size):
        offsets = [o + address - v for t, o, v, _, n, *_ in headers
                   if t == 1 and v <= address and address + size <= v + n
                   and o + n <= len(executable)]
        if len(offsets) != 1:
            raise ValueError(f'Text atlas address is not uniquely file-backed: {address:#x}')
        return offsets[0]

    site, target = SITES[edition]
    # Guard the capacity branch, its delay slot, the replaced word and the
    # new branch's delay slot. Guard the normal epilogue and emitter as well.
    guards = {
        site - 20: (0x3C017000, 0x8422002E, 0x284201E0,
                    0x1440000E, 0x3C017000, 0x0260102D, 0x8423002C),
        target: (0x3C017000, 0x8422002C, 0xA6220008),
        target + 44: (0x1260001E, 0xA6220012),
        target + 112: (0x0C000000 | ((target + 240) >> 2), 0xA6200002),
        target + 168: (0x3C017000, 0x8C230068, 0x0260102D, 0xA6230048),
    }
    for address, words in guards.items():
        expected = struct.pack('<' + 'I' * len(words), *words)
        at = offset(address, len(expected))
        if executable[at:at + len(expected)] != expected:
            raise ValueError(f'Text atlas preimage drift at {address:#x}')
    at = offset(site, 4)
    result = bytearray(executable)
    result[at:at + 4] = AFTER
    return bytes(result), {'address': hex(site), 'target': hex(target),
                           'file_offset': at, 'before': BEFORE.hex(), 'after': AFTER.hex(),
                           'capacity_changed': False}
