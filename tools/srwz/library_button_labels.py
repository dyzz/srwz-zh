"""Remove faux bold and shear from the two encyclopedia portrait button labels.

Retarget their shared enable-style call to the existing reset-style helper.
The original helper applies shear=2 and an eight-offset bold pass. All metrics,
colors, text, button sprites, and the reset after the two labels stay untouched.
"""
import hashlib

SITES = {
    'original': (0x1135c8, '5015080c', '5c15080c', 'cd0a839d7b9e9b6fe8d693b9afcb5ac4e2954ab57607ce4d7753fc3eb3f8d286'),
    'best': (0x113988, '4016080c', '4c16080c', 'becec084d869c6a709cf819669cb56b5d6e09cf1eaaac9e5cbedc350257533bb'),
    'sp': (0x117268, '9026080c', '9c26080c', '287fb1e2168f68add0865d81a14bb5d180a6780a499cd4260500751ad6bb27bd'),
}

def write_ranges(edition):
    offset, *_ = SITES[edition]
    return [(offset, offset + 4)]

def apply_library_button_labels(executable, edition='original'):
    offset, before_hex, after_hex, context_sha = SITES[edition]
    before, after = bytes.fromhex(before_hex), bytes.fromhex(after_hex)
    if hashlib.sha256(executable[offset+4:offset+172]).hexdigest() != context_sha:
        raise ValueError(f'{edition}: library button-label call context drift')
    current = executable[offset:offset+4]
    if current not in (before, after):
        raise ValueError(f'{edition}: library button-label call preimage drift')
    out = bytearray(executable)
    out[offset:offset+4] = after
    return bytes(out), dict(edition=edition, offset=offset, before_hex=before_hex,
        after_hex=after_hex, already_applied=current == after,
        scope='encyclopedia expression/voice button labels',
        font_pixels_unchanged=True, metrics_and_colors_unchanged=True,
        faux_bold=False, shear=0, unchanged_size=True)

def verify_library_button_labels(executable, edition='original'):
    _, report = apply_library_button_labels(executable, edition)
    if not report['already_applied']:
        raise ValueError(f'{edition}: library button-label patch missing')
    return report
