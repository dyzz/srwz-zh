"""Carry the actual drawn width of SP map-dialogue numeric substitutions."""

from hashlib import sha256
import struct

from .proportional_hooks import Asm

ELF_BASE = 0xFF680
GALLERY_BASE = 0x820000
PAYLOAD = 0x822EC0  # Unused tail of gallery runtime.S before its .org 0x1000.
PAYLOAD_END = 0x823000
GALLERY_FILE_END = 0x846000
ROW_CORRECTION = 160  # Unused word in the native dialogue caller's stack frame.
DISPATCH = 0x100F50
NUMBER_HANDLER = 0x4416B0


def _jal(address):
    return 0x0C000000 | (address >> 2)


def _dispatch():
    a = Asm()
    a.i(9, 'sp', 'sp', -32)
    a.i(0x3F, 'sp', 'ra', 16)
    a.i(0x23, 'a2', 'v0', 16)  # Native run descriptor's handler.
    a.i(0x2B, 'sp', 'v0', 8)
    a.i(0x23, 'sp', 'v0', ROW_CORRECTION + 32)
    a.branch(4, 'v0', 'zero', 'invoke')
    # Carry signed correction in the tagged upper word. The callbacks forward
    # a3 to the coordinate helper; native cell arithmetic uses its low word.
    a.i(0xC, 'v0', 'v0', 0xFFFF)
    a.i(0xF, 'zero', 'v1', 1)
    a.r('v0', 'v1', 'v0', 0x25)
    a.r('zero', 'v0', 'v0', 0x3C)
    a.r('zero', 'a3', 'a3', 0x3C)
    a.r('zero', 'a3', 'a3', 0x3E)
    a.r('a3', 'v0', 'a3', 0x25)
    a.label('invoke')
    a.emit(_jal(DISPATCH))
    a.emit(0)
    a.i(0x23, 'sp', 't0', 8)
    a.li('t1', NUMBER_HANDLER)
    a.branch(5, 't0', 't1', 'done')
    a.branch(6, 'v0', 'zero', 'done')  # No digits emitted.
    a.i(0xF, 'zero', 't0', 0x7000)
    a.i(0x21, 't0', 't1', 0x38)
    a.i(9, 'zero', 't2', 20)
    a.branch(5, 't1', 't2', 'done')
    a.i(0x23, 't0', 't1', 0x3C)
    a.li('t2', 0x000B0014)
    a.branch(5, 't1', 't2', 'done')
    # Render pen minus origin gives the real advance, including digit metrics.
    # Keep the native logical column increment and correct only pixel positions.
    a.i(0x21, 't0', 't0', 0x30)
    a.i(0xF, 'zero', 't1', 0x0063)
    a.i(0x23, 't1', 't1', 0xEED8)
    a.r('t0', 't1', 't0', 0x23)
    a.r('zero', 'v0', 't1', 2, 1)  # Bytes / 2 = native character count.
    a.r('zero', 't1', 't2', 0, 2)
    a.r('zero', 't1', 't1', 0, 4)
    a.r('t1', 't2', 't1', 0x21)
    a.r('t0', 't1', 't0', 0x23)
    a.i(0x23, 'sp', 't1', ROW_CORRECTION + 32)
    a.r('t0', 't1', 't0', 0x21)
    a.i(0x2B, 'sp', 't0', ROW_CORRECTION + 32)
    a.label('done')
    a.i(0x37, 'sp', 'ra', 16)
    a.r('ra', 'zero', 'zero', 8)
    a.i(9, 'sp', 'sp', 32)
    return a.finish()


def _coordinate():
    a = Asm()
    a.emit(0x00831821)  # Native x = origin + logical column * step.
    a.r('zero', 'a2', 'a2', 0x3E)
    a.r('zero', 'a2', 'at', 2, 16)
    a.i(9, 'zero', 'a0', 1)
    a.branch(5, 'at', 'a0', 'store')
    a.r('zero', 'a2', 'a2', 0, 16)
    a.r('zero', 'a2', 'a2', 3, 16)
    a.r('v1', 'a2', 'v1', 0x21)
    a.label('store')
    a.emit(0xAD030000)
    a.jump(0x441844)
    return a.finish()


def patches():
    """Return (virtual address, native preimage, replacement) for readback."""
    dispatch = _dispatch()
    coord = PAYLOAD + len(dispatch)
    code = dispatch + _coordinate()
    if PAYLOAD + len(code) > PAYLOAD_END:
        raise ValueError('SP numeric template code exceeds its reserved slot')
    word = struct.Struct('<I').pack
    reset = word(0xAFA00000 | ROW_CORRECTION)
    return (
        (0x4412DC, word(0), reset),
        (0x441390, word(_jal(DISPATCH)), word(_jal(PAYLOAD))),
        (0x4413FC, word(0), reset),
        (0x44183C, struct.pack('<2I', 0x00831821, 0xAD030000),
         struct.pack('<2I', 0x08000000 | (coord >> 2), 0)),
        (PAYLOAD, bytes(len(code)), code),
    )


def install(executable):
    phoff = struct.unpack_from('<I', executable, 28)[0]
    stride, count = struct.unpack_from('<HH', executable, 42)
    for index in range(count):
        kind, offset, address, _, size, *_ = struct.unpack_from('<8I', executable, phoff + index * stride)
        if kind == 1 and address == GALLERY_BASE:
            if address + size != GALLERY_FILE_END or offset + size > len(executable):
                raise ValueError('SP numeric template load segment drift')
            break
    else:
        return executable, None  # Non-gallery fixtures have no reserved slot.
    result = bytearray(executable)
    writes = []
    for site, before, after in patches():
        at = offset + site - address if site == PAYLOAD else site - ELF_BASE
        if executable[at:at + len(before)] != before:
            raise ValueError(f'SP numeric template preimage drift at {site:#x}')
        result[at:at + len(after)] = after
        writes.append(dict(address=hex(site), size=len(after), sha256=sha256(after).hexdigest()))
    return bytes(result), {'writes': writes}
