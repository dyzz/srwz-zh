"""Explicitly author SP stage-title snapshots from the reviewed frame corpus.

Writes a comparison sheet for visual review. Production builds use only the
frozen index planes; this authoring command is never invoked by the builder.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/special_disc/writeback')]
from migrate_stage_dialogue import read_disc_member
from migrate_slps_text import TABLE
from srwz.codec import decode_production, reencode_changed_suffix
from srwz.font import decode_glyph, ascii_glyph_index
from srwz.iso9660 import scan_iso9660, member_map
from srwz.stage_title_graphics import render_stage_title, LatinLayout, pack_linear_4bpp, unpack_linear_4bpp
from srwz.stage_title_snapshot import freeze_indexes
from srwz.text import decode_text, load_text_table
from special_disc.writeback.stage_titles import (MEMBER, GROUP_TABLE, TITLE_TABLE, RECORD_START,
    RECORD_STRIDE, SNAPSHOT, image_span, title_entries, sha, require)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-iso', type=Path, required=True)
    parser.add_argument('--proposal', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from PIL import Image, ImageDraw
    args.output.mkdir(parents=True, exist_ok=True)
    exe = read_disc_member('SLPS_259.20')
    vt = read_disc_member(MEMBER)
    a, b = struct.unpack_from('<2I', exe, GROUP_TABLE + 9 * 4)
    table_bytes = exe[TITLE_TABLE:TITLE_TABLE + 28 * 4]
    offsets = struct.unpack('<28I', table_bytes)
    require(offsets[0] == 0 and offsets[-1] == b-a, 'source title table bounds drift')
    members = member_map(scan_iso9660(args.font_iso))
    with args.font_iso.open('rb') as f:
        m = members['SLPS_259.20']; f.seek(m.extent_lba * 2048); current_exe = f.read(m.size)
        fa, fb = struct.unpack_from('<2I', current_exe, GROUP_TABLE + 3 * 4)
        f.seek(members[MEMBER].extent_lba * 2048 + fa)
        font = decode_production(f.read(fb-fa)).output
    proposal = json.loads(args.proposal.read_text())
    glyph_map = {r['character']: r['glyph_index'] for r in proposal['assignments']}
    compdata = decode_production(read_disc_member('DATA/COMPDATA.BN')).output
    text_table = load_text_table(TABLE)
    bindings = {}
    for chunk in range(1, 30):
        raw = compdata[RECORD_START + (chunk-1)*RECORD_STRIDE:RECORD_START + chunk*RECORD_STRIDE]
        words = struct.unpack('<12I', raw)
        source = decode_text(compdata, words[0]-0x764F80, text_table).text
        if source == '予備':
            continue
        selector = words[7] & 0xFFFF
        bindings.setdefault(selector, []).append(dict(chunk=chunk, source=source, record_hex=raw.hex()))
    require(sorted(bindings) == list(range(1, 22)), 'native stage-title selector coverage drift')
    rows = title_entries()
    targets = {loc: row for row in rows.values() for loc in row['locations']}
    titles = []; output = bytearray(vt[a:b])
    canvas = Image.new('RGB', (1080, 21*70), '#222222'); draw = ImageDraw.Draw(canvas)
    for selector in range(1, 22):
        native = bindings[selector]
        primary = native[0]
        row = targets[f"sd/stage-name/{primary['chunk']:03d}"]
        require(all(sha(r['source'].encode()) == row['source_text_sha256'] for r in native),
                'native title/corpus source mismatch')
        index = selector + 5; lo, hi = offsets[index:index+2]
        stored = vt[a+lo:a+hi]; decoded = decode_production(stored)
        require(not any(stored[decoded.consumed:]), 'native title padding nonzero')
        start, end = image_span(decoded.output)
        original = decoded.output[start:end]
        text = row['translation']; glyphs = {}
        for char in set(text):
            gi = ascii_glyph_index(ord(char)) if ' ' <= char <= '~' else glyph_map[char]
            glyph = decode_glyph(font, gi)
            # The stock ASCII apostrophe is blank; use its reviewed shared-font assignment.
            if char != ' ' and not any(glyph):
                gi = glyph_map[char]; glyph = decode_glyph(font, gi)
            require(char == ' ' or any(glyph), f'blank title glyph: {char!r}')
            glyphs[char] = glyph
        preserve = selector == 15
        if preserve:
            require(text == 'at the risk of pride', 'preserved English title drift')
            packed = original; encoded = stored; metadata = dict(mode='original_english_pixels')
        else:
            for levels in (16, 8, 4):
                raster = render_stage_title(text, glyphs, latin_layout=LatinLayout(), quantization_levels=levels)
                packed = pack_linear_4bpp(raster.indexes)
                data = decoded.output[:start] + packed + decoded.output[end:]
                encoded = reencode_changed_suffix(stored, data, strategy='rust-maximum', original_result=decoded)
                if len(encoded) <= hi-lo:
                    break
            require(len(encoded) <= hi-lo, f'title {selector} cannot fit original slot')
            require(decode_production(encoded).output == data, 'title codec reread')
            metadata = {k:v for k,v in asdict(raster).items() if k != 'indexes'}
            encoded += bytes(hi-lo-len(encoded))
        output[lo:hi] = encoded
        titles.append(dict(selector=selector, table_index=index, corpus_id=row['id'],
            translation=text, source_text_sha256=row['source_text_sha256'], locations=row['locations'],
            stage_chunks=[r['chunk'] for r in native], native_records=native,
            preserve_original=preserve, source_stored_sha256=sha(stored), output_stored_sha256=sha(encoded),
            non_image_sha256=sha(decoded.output[:start]+decoded.output[end:]),
            packed_indexes=freeze_indexes(packed), raster=metadata))
        for x, raw in ((30, original), (560, packed)):
            canvas.paste(Image.frombytes('L', (512,64), bytes(v*17 for v in unpack_linear_4bpp(raw))), (x,(selector-1)*70))
        draw.text((2,(selector-1)*70+5), str(selector), fill='white')
    snapshot = dict(schema_version=1, status='frozen_indexed_stage_titles',
        update_policy='explicit_authoring_and_visual_review', group_range=[a,b],
        table_sha256=sha(table_bytes), source_group_sha256=sha(vt[a:b]), output_group_sha256=sha(output),
        font_sha256=sha(font), proposal_sha256=sha(args.proposal.read_bytes()), titles=titles,
        notes=['Selector 17 (prologue) contains a duplicate of selector 16 in the original disc.',
               'Selector 15 already contains English artwork and is preserved byte for byte.',
               'Native COMPDATA selectors and all branch aliases are recorded; runtime acceptance is separate.'])
    SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2)+'\n')
    canvas.save(args.output/'contact.png')
    print(f'froze {len(titles)} title slots; source comparison: {args.output / "contact.png"}')


if __name__ == '__main__':
    main()
