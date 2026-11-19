#!/usr/bin/env python3
"""Author the Traditional stage-title snapshot (107 VT1 title images) from the Traditional build's own font.

Same method the Simplified snapshot's explicit edits used ("authoring from existing release glyphs", see its
provenance): glyphs come from the release font a build actually wrote (VT1 chunk 2 of the Traditional integrated
ISO, looked up through the Traditional codebook), the raster policy and the builder's codec are the Simplified
snapshot's. Each title tries the policy's quantization levels in order until the stream fits its original slot.
Placement, selectors and source hashes are the Simplified snapshot's (same original slots).

Output: config/zh-hant/stage-title-graphics-indexed-snapshot.json (build_dual.py puts it into the Traditional
build) and build/zh-hant/stage-titles-contact.png (old | new, for review).
Usage: author_stage_titles.py [--iso TC_INTEGRATED_ISO]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(Path(__file__).resolve().parent)]
from assemble_dual import Disc                                                   # noqa: E402
from srwz.iso_layout import CORE_ARCHIVE_SPECS, read_executable_archive_offsets      # noqa: E402
from srwz.codec import decode, encode                                            # noqa: E402
from srwz.font import ascii_glyph_index, decode_glyph                            # noqa: E402
from srwz.stage_title_graphics import LatinLayout, pack_linear_4bpp, render_stage_title, unpack_linear_4bpp  # noqa: E402
from srwz.stage_title_snapshot import freeze_indexes, thaw_indexes               # noqa: E402
from srwz.tim2 import scan_tim2                                                  # noqa: E402

SC_SNAPSHOT = ROOT / 'config/assets/stage-title-graphics-indexed-snapshot.json'
TC_SNAPSHOT = ROOT / 'config/zh-hant/stage-title-graphics-indexed-snapshot.json'
DEFAULT_ISO = ROOT / 'build/iso/test/integrated-original-zh-hant-tw.iso'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tc_font(iso: Path) -> bytes:
    disc = Disc(iso)
    exe, vt1 = disc.read('SLPS_258.87'), disc.read('DATA/VT1.BIN')
    offsets = read_executable_archive_offsets(exe, CORE_ARCHIVE_SPECS['VT1.BIN'], len(vt1))
    return decode(vt1[offsets[2]:offsets[3]]).output


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--iso', type=Path, default=DEFAULT_ISO)
    a = p.parse_args()
    components = json.loads((ROOT / 'config/full-story-components.json').read_text(encoding='utf-8'))
    graphics = components['full_stage_titles']['graphics']
    policy, codec, group = graphics['raster'], graphics['codec'], graphics['archive']
    sc = json.loads(SC_SNAPSHOT.read_text(encoding='utf-8'))
    names = {e['id']: e['translation'] for e in
             json.loads((ROOT / 'corpus/zh-hant/menu/stage-names.json').read_text(encoding='utf-8'))['entries']}
    ledger = json.loads((ROOT / 'config/zh-hant/encoding/zh-release-font-assignments.json').read_text(encoding='utf-8'))
    glyph_of = {r['character']: r['glyph_index'] for r in ledger['primary_assignments']}
    font = tc_font(a.iso)
    vt1 = (ROOT / 'work/disc/DATA/VT1.BIN').read_bytes()
    output_group = bytearray(vt1[group['group_start']:group['group_end']])
    latin = LatinLayout(**policy['latin_layout'])
    titles, contact = [], []
    for old in sc['titles']:
        text = names[old['entry_id']]
        stored = vt1[old['stored_start']:old['stored_end']]
        source = decode(stored)
        picture = scan_tim2(source.output)[0].pictures[0]
        start = picture.offset + picture.header_size
        end = start + picture.image_size
        if sha(unpack_linear_4bpp(source.output[start:end])) != old['source_indexes_sha256']:
            raise SystemExit(f"title {old['ordinal']}: original slot does not match the Simplified snapshot")
        glyphs = {}
        for ch in set(text):
            index = ascii_glyph_index(ord(ch)) if ' ' <= ch <= '~' else glyph_of[ch]
            glyph = decode_glyph(font, index)
            if ch != ' ' and not any(glyph) and ch in glyph_of:
                glyph = decode_glyph(font, glyph_of[ch])
            if ch != ' ' and not any(glyph):
                raise SystemExit(f'blank title glyph {ch!r} in {text}')
            glyphs[ch] = glyph
        attempts = []
        for levels in policy['quantization_levels']:
            raster = render_stage_title(text, glyphs, doubled_glyph_width=policy['doubled_glyph_width'],
                                        advance=policy['advance'], y=policy['y'], quantization_levels=levels,
                                        latin_layout=latin)
            packed = pack_linear_4bpp(raster.indexes)
            modified = source.output[:start] + packed + source.output[end:]
            encoded = encode(modified, strategy=codec['strategy'], flags=source.flags,
                             header_unknown_0=source.metadata.get('header_unknown_0'),
                             header_unknown_1=source.metadata['header_unknown_1'],
                             min_match_length=codec['min_match_length'], max_match_chain=codec['max_match_chain'])
            attempts.append({'quantization_levels': levels, 'encoded_size': len(encoded)})
            if len(encoded) <= len(stored):
                break
        else:
            raise SystemExit(f"title {old['ordinal']} ({text}) does not fit its slot at any quantization level")
        if decode(encoded).output != modified:
            raise SystemExit(f"title {old['ordinal']}: codec reread")
        padded = encoded + bytes(len(stored) - len(encoded))
        output_group[old['stored_start'] - group['group_start']:old['stored_end'] - group['group_start']] = padded
        titles.append({**{k: old[k] for k in ('ordinal', 'entry_id', 'selector', 'loader_table_index', 'stored_start',
                                              'stored_end', 'stored_size', 'source_consumed', 'source_indexes_sha256')},
                       'text': text, 'output_encoded_size': len(encoded), 'padding_size': len(stored) - len(encoded),
                       'quantization_levels': raster.quantization_levels, 'attempted_sizes': attempts,
                       'raster_x': raster.x, 'raster_y': raster.y, 'raster_width': raster.width,
                       'raster_height': raster.height, 'natural_width': raster.natural_width,
                       'cell_count': raster.cell_count, 'latin_cell_count': raster.latin_cell_count,
                       'layout_mode': raster.layout_mode, 'output_indexes_sha256': sha(raster.indexes),
                       'packed_indexes': freeze_indexes(packed), 'output_stored_sha256': sha(padded)})
        contact.append((unpack_linear_4bpp(thaw_indexes(old['packed_indexes'])), raster.indexes))
    snapshot = {k: sc[k] for k in ('schema_version', 'status', 'update_policy', 'raster_policy')}
    snapshot['provenance'] = {
        'method': 'Traditional titles authored by tools/zh_hant/author_stage_titles.py from the Traditional build font '
                  '(release glyphs as written to VT1 chunk 2), the Simplified snapshot raster policy and the builder '
                  'codec; placement and source hashes are the Simplified snapshot\'s.',
        'font_decoded_sha256': sha(font),
        'codebook_sha256': sha((ROOT / 'config/zh-hant/encoding/zh-release-font-assignments.json').read_bytes()),
        'stage_names_sha256': sha((ROOT / 'corpus/zh-hant/menu/stage-names.json').read_bytes()),
        'simplified_snapshot_sha256': sha(SC_SNAPSHOT.read_bytes())}
    snapshot['output_group_sha256'] = sha(bytes(output_group))
    snapshot['titles'] = titles
    TC_SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    reduced = [t['ordinal'] for t in titles if t['quantization_levels'] < 16]
    try:
        from PIL import Image
        sheet = Image.new('L', (1024, 64 * len(contact)))
        for i, (old_ix, new_ix) in enumerate(contact):
            for x, ix in ((0, old_ix), (512, new_ix)):
                sheet.paste(Image.frombytes('L', (512, 64), bytes(v * 17 for v in ix)), (x, 64 * i))
        out = ROOT / 'build/zh-hant/stage-titles-contact.png'; out.parent.mkdir(parents=True, exist_ok=True); sheet.save(out)
    except ImportError:
        pass
    print(json.dumps({'titles': len(titles), 'reduced_precision_ordinals': reduced,
                      'output_group_sha256': snapshot['output_group_sha256']}))


if __name__ == '__main__':
    main()
