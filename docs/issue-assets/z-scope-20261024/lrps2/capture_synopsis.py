"""SP library flow synopsis (episode 3): candidate metrics for a compact 013.

After the natural flow route opens the synopsis, its text pointer (0x80BAAC)
is pointed at a fixture in free RAM (0x1E00000), the detail page is closed and
reopened so the native flow renderer draws it, then the pointer and RAM are
restored. Each fixture row is 特别小队 + 013 (one candidate) + 特别小队; the page
body is 16/16/10 natively. Ink is measured from the frame, glyph sizes from the
frame-end records. ISO and memory card hashes are asserted unchanged.

  python3 capture_synopsis.py [current|built] [final]
"""
import json
import struct
import sys

from PIL import Image

from capture_story import ROOT, Session

SITE, FIXTURE, FONT_STATE = 0x80BAAC, 0x1E00000, 0x4ED5B0
WORD = bytes.fromhex('93c194a48fac97c4')  # 特别小队
DIGITS = bytes.fromhex('824f82508252')  # 013


def scope(width, space, height=None, restore_height=True):
    head = bytes([0x32, width, 0x34, space]) + (bytes([0x33, height]) if height else b'')
    tail = bytes([0x32, 0x10, 0x34, 0x10]) + (bytes([0x33, 0x8A]) if height and restore_height else b'')
    return head + DIGITS + tail


# (label, bytes for 013). 0x8A decodes to height 10 (raw 0x0A is a line feed).
CANDIDATES = [
    ('plain 16/16/10', DIGITS),
    ('current 14/12 auto9', scope(0x0E, 0x0C)),
    ('14/12/10', scope(0x0E, 0x0C, 0x8A)),
    ('13/11/10', scope(0x0D, 0x0B, 0x8A)),
    ('12/11/10', scope(0x0C, 0x0B, 0x8A)),
    ('12/10/10', scope(0x0C, 0x0A, 0x8A)),
    ('13/11/9', scope(0x0D, 0x0B, 0x09)),
    ('12/11/9', scope(0x0C, 0x0B, 0x09)),
]


def final_rows():
    """Production FLOW_SYNOPSIS expansion of <z> next to the old and plain forms."""
    from capture_story import encoder
    from srwz.compact_scopes import FLOW_SYNOPSIS, expand
    enc = encoder()
    rows = [('plain', '特别小队013特别小队'),
            ('old 14/12 auto9', '特别小队<width:0E><space:0C>013<width:10><space:10>特别小队')]
    rows += [(f'<z>{run}</z>', f'特别小队<z>{run}</z>特别小队') for run in ('013', 'Orange', 'BIG-O', 'PLANT')]
    return [(label, enc.encode(expand(text, FLOW_SYNOPSIS))) for label, text in rows]


def ink(frame, records, row_index, glyph_index, offset):
    """Dark-ink rows (screen y) inside one glyph's columns."""
    x, y, w, h = records[row_index * 11 + glyph_index]
    left = x + offset
    band = [(px, py) for px in range(left, left + w) for py in range(0, frame.height)
            if sum(frame.getpixel((px, py))) < 240]
    return band


def main(variant, final=False):
    flow = [c['command'] for c in json.loads(
        (ROOT / 'docs/issue-assets/automatic-digits-20261021/flow/sp/receipt.json').read_text())['commands']]
    rows = final_rows() if final else [(label, WORD + body + WORD) for label, body in CANDIDATES]
    s = Session(variant, 'synopsis-final' if final else 'synopsis-candidates')
    payload = b'\n'.join(body for _, body in rows) + b'\0'
    pointer = saved = None
    try:
        s.replay(flow, 'shot target-reopened')
        pointer = s.read(SITE, 4)
        saved = s.read(FIXTURE, len(payload))
        s.write(FIXTURE, payload)
        s.write(SITE, struct.pack('<I', FIXTURE))
        for c in ('press cross 3', 'run 30', 'press circle 3', 'run 90'):
            s.cmd(c)
        s.shot('candidates')
        state = s.read(FONT_STATE, 0x90)
        raw = s.read(struct.unpack_from('<I', state, 0x58)[0], 32 * 14 * len(rows))
        records = [struct.unpack_from('<2h', raw, i * 32 + 4) + struct.unpack_from('<2h', raw, i * 32 + 12)
                   for i in range(14 * len(rows))]
        s.report.update(candidates=[label for label, _ in rows], payload_hex=payload.hex(),
                        original_pointer=pointer.hex(), records=records)
    finally:
        if pointer is not None:
            s.write(SITE, pointer)
            s.write(FIXTURE, saved)
            for c in ('press cross 3', 'run 30', 'press circle 3', 'run 90'):
                s.cmd(c)
            s.shot('restored')
        s.close()


if __name__ == '__main__':
    args = sys.argv[1:]
    main(next((a for a in args if a in ('current', 'built')), 'built'), final='final' in args)
