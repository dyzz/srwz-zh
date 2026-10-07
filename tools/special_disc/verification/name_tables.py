"""Verify every SP roster name against shared/native text and actual font pixels."""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

from srwz.codec import decode_production
from srwz.compressed_workspace import decoded_view
from srwz.font import (ascii_glyph_index, decode_glyph, glyph_index_for_code,
                       read_extended_glyph_table, standard_glyph_index)
from srwz.text import decode_text, normalize_original_fullwidth_ascii
from srwz.library_work_titles import compact_library_list_name

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / 'config/products/special-disc/shared-name-reference.json'
UNIT_START, UNIT_COUNT, UNIT_STRIDE, BASE = 0x54B94, 854, 68, 0x764F80
PILOT_START, PILOT_COUNT, PILOT_STRIDE = 0x2B50, 969, 178
FIELDS = (('display', 2, 21), ('family', 23, 23), ('given', 46, 23))
EXTENDED_TABLE = 0x352E70
KANA = re.compile('[ぁ-ヺｦ-ﾟ]')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def text_codes(raw):
    """The name fields use the ordinary terminated text stream and width tags."""
    i = 0
    while i < len(raw):
        code = raw[i]
        i += 1
        if code == 0:
            return
        if 0x31 <= code <= 0x35:
            require(i < len(raw), 'SP name truncated control')
            i += 1
            continue
        if 0x80 <= code <= 0x9F or 0xE0 <= code <= 0xEA:
            require(i < len(raw), 'SP name truncated code')
            code = code * 256 + raw[i]
            i += 1
        else:
            require(0x20 <= code <= 0x7E, f'SP name invalid single-byte code: {code:02X}')
        yield code
    raise ValueError('SP name missing NUL')


def verify_encoded_glyphs(raw, font, proposal, *, extended=None, cache=None):
    """Check the encoded code, not merely the Unicode character's registration."""
    assignments = {int(r['code'], 16): r for group in
                   ('assignments', 'surface_alias_assignments', 'source_compatibility_assignments')
                   for r in proposal[group]}
    codes = set(text_codes(raw))
    for code in codes:
        if cache is not None and code in cache:
            continue
        row = assignments.get(code)
        if code < 0x80:
            index = ascii_glyph_index(code)
        elif extended is not None:
            index = glyph_index_for_code(code, extended)
        elif code < 0x989F:
            index = standard_glyph_index(code)
        else:
            require(row is not None, f'SP name unregistered extended glyph: {code:04X}')
            index = row['glyph_index']
        if row is not None:
            require(index == row['glyph_index'], f'SP name glyph mapping drift: {code:04X}')
        pixels = decode_glyph(font, index)
        if code not in (0x20, 0x8140) and (row is None or row['character'] not in (' ', '\u3000')):
            require(any(pixels), f'SP name blank glyph: {code:04X}')
        expected = (row or {}).get('raster', {}).get('pixels_4bpp_sha256')
        # SP deliberately restores native parentheses after the shared font.
        # verify_parentheses independently checks those exact source pixels.
        if row is not None and row['character'] in '()（）':
            expected = None
        if expected:
            require(sha(pixels) == expected, f'SP name glyph pixels drift: {code:04X}')
        if cache is not None:
            cache.add(code)
    return codes


def verify_name_tables(archive, source_archive, font, proposal, readback, source_table, exe):
    # Local imports avoid a cycle with the writers' preflight glyph check.
    from special_disc.writeback.unit_names import inputs as unit_inputs
    from special_disc.writeback.pilot_names import inputs as pilot_inputs

    data, source = (decoded_view(b).output for b in (archive, source_archive))
    require(len(data) == len(source) == 652800, 'SP name-table decoded size drift')
    reference = json.loads(REFERENCE.read_text())
    require(reference['schema_version'] == 1 and
            sha(source) == reference['provenance']['sp_original_decoded_sha256'],
            'SP name-table source identity drift')
    extended = read_extended_glyph_table(exe, table_offset=EXTENDED_TABLE)
    uc, ur, _ = unit_inputs()
    pc, pr, _ = pilot_inputs()
    unit_overrides = {s['offset']: ur[s['id']]['translation'] for s in uc['entries']}
    pilot_overrides = {s['offset']: pr[s['id']]['translation'] for s in pc['entries']}
    codes, inventory = set(), []

    def check(kind, index, field, old_at, at, capacity, expected):
        old = decode_text(source, old_at, source_table, end=old_at + capacity)
        actual = decode_text(data, at, readback, end=at + capacity)
        require(old.terminator == actual.terminator == 'nul' and actual.unknown_code_count == 0,
                f'SP name decoding failed: {kind}/{index:04X}/{field}')
        text = actual.text.replace('\u3000', ' ')
        require(bool(text) == bool(old.text), f'SP name empty-field drift: {kind}/{index:04X}/{field}')
        require(not KANA.search(text), f'SP name Japanese residue: {kind}/{index:04X}/{field}: {text}')
        if expected is None:
            expected = reference[kind].get(old.text)
            if expected is None:
                # Native XAN is an intentionally unchanged Latin identifier.
                latin = normalize_original_fullwidth_ascii(old.text)
                require(bool(re.fullmatch('[A-Za-z0-9 ?!.-]*', latin)),
                        f'SP name has no translation binding: {kind}/{index:04X}/{field}: {old.text}')
                expected = [latin]
        expected=[compact_library_list_name(value) for value in expected]
        require(text in expected, f'SP name translation mismatch: {kind}/{index:04X}/{field}: {text!r} != {expected!r}')
        verify_encoded_glyphs(data[at:at + actual.consumed], font, proposal, extended=extended, cache=codes)
        inventory.append(dict(kind=kind, index=index, field=field, offset=at,
                              source_text=old.text, translation=text,
                              encoded_sha256=sha(data[at:at + actual.consumed])))

    for i in range(UNIT_COUNT):
        site = UNIT_START + i * UNIT_STRIDE
        old_at = struct.unpack_from('<I', source, site)[0] - BASE
        at = struct.unpack_from('<I', data, site)[0] - BASE
        require(at == old_at and 0 <= at < len(data), f'SP unit name pointer drift: {i:04X}')
        value = unit_overrides.get(at)
        check('units', i, 'name', old_at, at, min(128, len(data)-at), [value] if value is not None else None)
    for i in range(PILOT_COUNT):
        for field, delta, capacity in FIELDS:
            at = PILOT_START + i * PILOT_STRIDE + delta
            value = pilot_overrides.get(at)
            check('pilots', i, field, at, at, capacity, [value] if value is not None else None)
    return dict(unit_records=UNIT_COUNT, unit_unique_targets=len({r['offset'] for r in inventory if r['kind']=='units'}),
                pilot_records=PILOT_COUNT, pilot_fields=PILOT_COUNT * len(FIELDS),
                pilot_nonempty_fields=sum(bool(r['translation']) for r in inventory if r['kind']=='pilots'),
                unique_glyph_codes=len(codes), kana_residue=0, unknown_codes=0, blank_nonspace_glyphs=0,
                unbound_names=0, translation_mismatches=0, reference_sha256=sha(REFERENCE.read_bytes()),
                inventory_sha256=sha(json.dumps(inventory, ensure_ascii=False, sort_keys=True).encode()),
                scope='All COMPDATA unit/pilot record names; shared main-game reference plus SP-native contracts.',
                runtime='pending')
