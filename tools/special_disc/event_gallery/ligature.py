"""Private ti and w glyphs for the gallery list, based on the installed font.

The shared font stays immutable. Unused codes/slots are reserved here and the
native atlas uploader sources only those slots from the gallery payload.
"""
import hashlib
from srwz.font import decode_glyph, encode_glyph, glyph_raster_metrics, standard_glyph_index

CHARACTER = '\ue100'
CODE = 0x81AE
INDEX = 110
ADDRESS = 0x821D00
SIZE = 288
W_CHARACTER = "\ue103"
W_CODE = 0x81B1
W_INDEX = 113
W_ADDRESS = 0x821400


def build(font: bytes, proposal: dict, table) -> tuple[bytes, dict]:
    assert standard_glyph_index(CODE) == INDEX
    assignments = [r for k in ('assignments', 'surface_alias_assignments',
                               'source_compatibility_assignments') for r in proposal.get(k, [])]
    if CODE in table.characters or any(r['glyph_index'] == INDEX or int(r['code'], 16) == CODE
                                       or r['character'] == CHARACTER for r in assignments):
        raise ValueError('gallery ti slot conflicts with the installed codebook')
    if any(decode_glyph(font, INDEX)):
        raise ValueError('gallery ti reserved font slot is no longer blank')
    sources = {c: decode_glyph(font, standard_glyph_index(code))
               for c, code in [('t', 0x8294), ('i', 0x8289), ('w', 0x8297), ('o', 0x828F)]}
    boxes = {c: glyph_raster_metrics(p) for c, p in sources.items()}
    bottom = boxes['o']['bbox_y'] + boxes['o']['bbox_height'] - 1
    pixels = bytearray(24 * 24)
    x = 2
    positions = {}
    for c in 'ti':
        b = boxes[c]
        dy = bottom - (b['bbox_y'] + b['bbox_height'] - 1)
        positions[c] = dict(x=x, y_delta=dy, source_bbox=b)
        if x + b['bbox_width'] > 23 or b['bbox_y'] + dy < 0 or bottom >= 23:
            raise ValueError('gallery ti raster exceeds its 24x24 cell')
        # User-approved t ascender: shorten its top by two source rows.
        for sy in range(b['bbox_y'] + (2 if c == 't' else 0), b['bbox_y'] + b['bbox_height']):
            for sx in range(b['bbox_x'], b['bbox_x'] + b['bbox_width']):
                pixels[(sy + dy) * 24 + x + sx - b['bbox_x']] = sources[c][sy * 24 + sx]
        x += b['bbox_width'] + 2
    packed = encode_glyph(pixels)
    receipt = dict(code=f'{CODE:04X}', glyph_index=INDEX, address=hex(ADDRESS),
                   visible_text='ti', source_font_sha256=hashlib.sha256(font).hexdigest(),
                   glyph_sha256=hashlib.sha256(packed).hexdigest(), sources=positions,
                   ink_bottom=bottom, inter_letter_blank_columns=2,
                   shared_font_unchanged=True, runtime_metrics='width 16, height 9, advance 12', t_top_trim=2)
    return packed, receipt


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
    """Final reviewed per-letter metrics; author-facing title stays plain text."""
    return ('<width:0E><space:0A><height:09>BIG-O·'
            '<width:14><space:14><height:09>'
            '<width:0E><space:0A><height:09>Sho'
            '<width:0E><space:0C><height:09>' + W_CHARACTER +
            '<width:10><space:0C><height:09>' + CHARACTER +
            '<width:10><space:0C><height:09>m'
            '<width:0E><space:0A><height:09>e'
            '<width:14><space:14><height:09>')
