"""Draw the frozen version mask on the Special Disc title's subtitle band."""
import base64
import hashlib
import struct
import zlib

from srwz.codec import decode_production, reencode_changed_suffix
from srwz.psmt4 import swizzle_psmt4, unswizzle_psmt4
from srwz.tim2 import parse_tim2

TABLE = 0x353790
LOGO = 28
LOGO_HASHES = {
    '387ea050dfac9f4a0cec23e7b7547f81c90d8cef62a31d6661d6daef11a66af9',
    '787445769fd7efe921e26ef727ab330bb252b9a81941402449346b295def4c5e',
}


def apply_title_version(archive, executable, badge):
    start, end = struct.unpack_from('<2I', executable, TABLE + 4 * LOGO)
    stored = archive[start:end]
    decoded = decode_production(stored).output
    if hashlib.sha256(decoded).hexdigest() not in LOGO_HASHES:
        raise ValueError('Unrecognized SP title artwork')
    pic = parse_tim2(decoded).pictures[0]
    offset = pic.offset + pic.header_size
    stop = offset + pic.image_size
    pixels = bytearray(unswizzle_psmt4(decoded[offset:stop], 512, 256, row_major_pages=True))
    mask = zlib.decompress(base64.b64decode(badge['mask_zlib_base64'], validate=True))
    if len(mask) != 3200 or hashlib.sha256(mask).hexdigest() != badge['mask_sha256']:
        raise ValueError('SP version glyph mask drift')
    # The subtitle band has room beneath the lettering for longer development identifiers.
    first = min(i % 160 for i, value in enumerate(mask) if value)
    y = 22 if first >= 120 else 34
    for i, value in enumerate(mask):
        if value:
            pixels[(y + i // 160) * 512 + 158 + i % 160] = (1, 10)[value - 1]
    raw = decoded[:offset] + swizzle_psmt4(bytes(pixels), 512, 256, row_major_pages=True) + decoded[stop:]
    encoded = reencode_changed_suffix(stored, raw, strategy='rust-maximum')
    growth = max(0, ((len(encoded) + 15) & ~15) - len(stored))
    out = bytearray(archive)
    exe = bytearray(executable)
    if growth:
        # Both donor slots contain a single compressed stream followed by
        # padding. Only use bytes past the stream's verified consumed length.
        cursor = end + growth
        for index in range(LOGO + 1, 54):
            begin, limit = struct.unpack_from('<2I', executable, TABLE + index * 4)
            slot = archive[begin:limit]
            if index in (40, 50, 53):
                stream = decode_production(slot)
                used = (stream.consumed + 15) & ~15
                take = min(cursor - begin, len(slot) - used)
                if take:
                    if any(slot[-take:]):
                        raise ValueError('Nonzero SP title padding')
                    slot = slot[:-take]
            struct.pack_into('<I', exe, TABLE + index * 4, cursor)
            out[cursor:cursor + len(slot)] = slot
            cursor += len(slot)
            if cursor == limit:
                break
        else:
            raise ValueError(f'SP title needs {growth} bytes of verified slot padding')
    out[start:end + growth] = encoded.ljust(end + growth - start, b'\0')
    if len(out) != len(archive) or decode_production(out[start:end + growth]).output != raw:
        raise ValueError('SP version readback differs')
    return bytes(out), bytes(exe), {'text': badge['text'], 'chunk': LOGO, 'growth': growth,
                                    'decoded_sha256': hashlib.sha256(raw).hexdigest()}
