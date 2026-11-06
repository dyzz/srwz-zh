"""Private w glyph for the gallery list, based on the installed font.

The shared font stays immutable. Unused codes/slots are reserved here and the
native atlas uploader sources only those slots from the gallery payload.
"""
import hashlib
from srwz.font import decode_glyph, encode_glyph, glyph_raster_metrics, standard_glyph_index

W_CHARACTER = "\ue103"
W_CODE = 0x81B1
W_INDEX = 113
W_ADDRESS = 0x821400


def build_w(font: bytes, proposal: dict, table) -> tuple[bytes, dict]:
    """Match w ink to o vertically; reserve a gallery-only glyph."""
    assignments = [r for k in ('assignments', 'surface_alias_assignments',
                               'source_compatibility_assignments') for r in proposal.get(k, [])]
    if W_CODE in table.characters or any(r['glyph_index'] == W_INDEX or int(r['code'], 16) == W_CODE
                                         or r['character'] == W_CHARACTER for r in assignments):
        raise ValueError('gallery w slot conflicts with the installed codebook')
    if standard_glyph_index(W_CODE) != W_INDEX or any(decode_glyph(font, W_INDEX)):
        raise ValueError('gallery w reserved font slot is no longer blank')
    source = decode_glyph(font, standard_glyph_index(0x8297))
    target = glyph_raster_metrics(decode_glyph(font, standard_glyph_index(0x828F)))
    box = glyph_raster_metrics(source)
    if min(box['bbox_height'], target['bbox_height']) < 2:
        raise ValueError('gallery w/o source glyph is empty or degenerate')
    pixels = bytearray(24 * 24)
    for y in range(target['bbox_height']):
        sy = box['bbox_y'] + round(y * (box['bbox_height'] - 1) / (target['bbox_height'] - 1))
        dy = target['bbox_y'] + y
        pixels[dy * 24:(dy + 1) * 24] = source[sy * 24:(sy + 1) * 24]
    packed = encode_glyph(pixels)
    return packed, dict(code=f'{W_CODE:04X}', glyph_index=W_INDEX, address=hex(W_ADDRESS),
                        glyph_sha256=hashlib.sha256(packed).hexdigest(),
                        source_bbox=box, target_bbox=target, shared_font_unchanged=True)


def showtime_text() -> str:
    """Per-letter metrics using ordinary t/i glyphs; no caption-scratch raster."""
    return ('<width:0E><space:0A><height:09>BIG-O·'
            '<width:14><space:14><height:09>'
            '<width:0E><space:0A><height:09>Sho'
            '<width:0E><space:09><height:09>' + W_CHARACTER +
            '<width:0E><space:06><height:08>t'
            '<width:0E><space:08><height:09>i'
            '<width:10><space:0C><height:09>m'
            '<width:0E><space:0A><height:09>e'
            '<width:14><space:14><height:09>')
