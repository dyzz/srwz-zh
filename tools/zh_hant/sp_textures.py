#!/usr/bin/env python3
"""Carry the Original's Simplified -> Traditional texture changes into the Traditional SP textures component.

SP's textures component (work/build/special-disc/components/textures) was made in September by migrate_textures.py:
the main game's Chinese texture changes copied into SP where SP still held the main game's Japanese pixels. The
Original has changed its atlases since, so re-running that converter with the Traditional Original as the answer key
would bring a different layout than SP's later image chain (command headings, title atlas, menu restore ...) expects.

Instead the Traditional SP component is the Simplified one plus the Original's own Simplified -> Traditional delta:
the current Simplified and Traditional Original builds differ only where Traditional text was drawn. For every TIM2
picture whose pixels differ between the two, each changed region (connected changed pixels, with a margin) is looked
for in SP's pictures of the same size and format at the same position; where SP holds exactly the Simplified pixels
of the whole region, it takes the Traditional ones. Only picture pixels change (no CLUT, header or non-image byte:
MAPMODEL also holds codebook-encoded terrain names, which SP's own writer owns). Regions SP does not hold are
reported; they are SP's own cells (image chain configs) or main-game art SP does not use.

Usage: sp_textures.py CLONE --simplified SC_ORIGINAL_COMPONENTS --traditional TC_ORIGINAL_COMPONENTS
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import zlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = 'work/build/special-disc/components/textures'
MARGIN = 2


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


LAYOUTS = ('linear', 'psmt4', 'psmt4-rows')     # stored order: plain rows, or the GS 4-bpp page swizzle


def unpack(raw: bytes, bpp: int, layout: str = 'linear', w: int = 0, h: int = 0) -> bytearray:
    if bpp == 8:
        return bytearray(raw)
    if layout == 'linear':
        return bytearray(v for b in raw for v in (b & 15, b >> 4))
    from srwz.psmt4 import unswizzle_psmt4
    return bytearray(unswizzle_psmt4(raw, w, h, row_major_pages=layout == 'psmt4-rows'))


def pack(pixels: bytearray, bpp: int, layout: str = 'linear', w: int = 0, h: int = 0) -> bytes:
    if bpp == 8:
        return bytes(pixels)
    if layout == 'linear':
        return bytes(pixels[i] | (pixels[i + 1] << 4) for i in range(0, len(pixels), 2))
    from srwz.psmt4 import swizzle_psmt4
    return swizzle_psmt4(bytes(pixels), w, h, row_major_pages=layout == 'psmt4-rows')


def layouts(bpp: int, w: int, h: int) -> tuple[str, ...]:
    pow2 = lambda v: v >= 32 and not v & (v - 1)
    return LAYOUTS if bpp == 4 and pow2(w) and pow2(h) else ('linear',)


def regions(a: bytes, b: bytes, w: int, h: int) -> list[tuple[int, int, int, int]]:
    """Bounding boxes (x0, y0, x1, y1 exclusive) of the changed pixels, grouped by MARGIN-dilated connectivity."""
    return mask_regions({(i % w, i // w) for i in range(w * h) if a[i] != b[i]}, w, h)


def mask_regions(changed: set, w: int, h: int, reach: int = 2 * MARGIN, margin: int = MARGIN
                 ) -> list[tuple[int, int, int, int]]:
    boxes, seen = [], set()
    for start in changed:
        if start in seen:
            continue
        stack, x0, y0, x1, y1 = [start], start[0], start[1], start[0], start[1]
        seen.add(start)
        while stack:
            x, y = stack.pop()
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for dx in range(-reach, reach + 1):
                for dy in range(-reach, reach + 1):
                    n = (x + dx, y + dy)
                    if n in changed and n not in seen:
                        seen.add(n); stack.append(n)
        boxes.append((max(0, x0 - margin), max(0, y0 - margin), min(w, x1 + 1 + margin), min(h, y1 + 1 + margin)))
    return sorted(boxes, key=lambda r: (r[1], r[0]))


def crop(px, w, box) -> bytes:
    x0, y0, x1, y1 = box
    return b''.join(bytes(px[y * w + x0:y * w + x1]) for y in range(y0, y1))


def overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def paste(px, w, box, tile: bytes) -> None:
    x0, y0, x1, y1 = box
    k = x1 - x0
    for r, y in enumerate(range(y0, y1)):
        px[y * w + x0:y * w + x1] = tile[r * k:(r + 1) * k]


def install_member(member, output, held, path, report):
    if output is None:
        return
    target = Path(held[member]) if member in held else path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(output)
    if member not in held:
        report['files'][member] = sha(output)


def apply_frozen(clone: Path, frozen_path: Path, held: dict) -> None:
    """Apply the frozen Traditional SP picture delta to the textures component (no Original build is read)."""
    import base64
    import migrate_textures as mt
    from srwz.codec import decode_production
    from srwz.iso9660 import member_map, scan_iso9660
    doc = json.loads(frozen_path.read_text(encoding='utf-8'))
    inventory = json.loads(mt.LOCKS.read_text())
    locks = {m['path']: m['sha256'] for m in inventory['sp']['members']}
    members = member_map(scan_iso9660(mt.ISO))
    sp_exe = mt.read_member(members, locks, mt.SD_EXE)
    out_dir = clone / COMPONENT
    report_path = out_dir / 'report.json'
    report = json.loads(report_path.read_text())
    summary = {}
    for member, (og_spec, sp_spec, storage) in mt.ARCHIVES.items():
        chunks = doc['members'].get(member)
        if not chunks:
            continue
        path = out_dir / member
        sp = path.read_bytes() if path.exists() else mt.read_member(members, locks, member)
        st = (mt.seg_table(mt.read_member(members, locks, sp_spec), len(sp)) if isinstance(og_spec, str)
              else mt.table_at(sp_exe, sp_spec, len(sp)))
        output = bytearray(sp)
        for key, c in sorted(chunks.items(), key=lambda kv: int(kv[0])):
            k = int(key); s0, s1 = st[k], st[k + 1]
            raw = sp[s0:s1]
            stream = False
            if storage != 'raw':
                try:
                    base = decode_production(raw).output; stream = True
                except Exception:  # noqa: BLE001 - not a codec stream
                    base = raw
            else:
                base = raw
            if sha(base) != c['before_sha256']:
                raise SystemExit(f'{member} chunk {k}: the SP textures component changed under the frozen delta')
            xor = zlib.decompress(base64.b64decode(c['xor_zlib_base64']))
            data = bytes(x ^ y for x, y in zip(base, xor))
            if sha(data) != c['after_sha256']:
                raise SystemExit(f'{member} chunk {k}: frozen delta readback')
            stored = mt.encode_into(raw, data, s1 - s0) if stream else data
            if stream and decode_production(stored).output != data:
                raise SystemExit(f'{member} chunk {k}: codec readback')
            if len(stored) > s1 - s0:
                raise SystemExit(f'{member} chunk {k}: Traditional pixels do not fit the slot')
            output[s0:s1] = stored + bytes(s1 - s0 - len(stored))
        install_member(member, bytes(output), held, path, report)
        summary[member] = {'chunks written': len(chunks), 'held for the image chain': int(member in held)}
    report['traditional_delta'] = dict(frozen=str(frozen_path.relative_to(ROOT)) if frozen_path.is_relative_to(ROOT)
                                       else str(frozen_path), members=summary)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('clone', type=Path)
    p.add_argument('--simplified', type=Path)
    p.add_argument('--traditional', type=Path)
    p.add_argument('--freeze', type=Path, help='authoring: also write the per-chunk delta this run applies (static '
                                               'Traditional SP pictures, config/zh-hant/sp-pictures/textures-delta.json)')
    p.add_argument('--frozen', type=Path, help='build: apply a frozen delta instead of reading the Original builds')
    p.add_argument('--review', type=Path, help='write crops of the regions SP does not hold here')
    p.add_argument('--hold', action='append', default=[], metavar='MEMBER=PATH',
                   help='write this member to PATH instead of the component (KVMDATA: SP\'s image chain seals the '
                        'whole atlas it receives, so its delta is applied after the chain, by sp_menu_atlas.py)')
    a = p.parse_args()
    clone = a.clone.resolve()
    sys.path[:0] = [str(clone / 'tools'), str(clone / 'tools/special_disc/writeback')]
    import migrate_textures as mt
    if a.frozen:
        return apply_frozen(clone, a.frozen, dict(h.split('=', 1) for h in a.hold))
    if not (a.simplified and a.traditional):
        raise SystemExit('--simplified and --traditional are needed unless --frozen is given')
    frozen_out = {}
    from srwz.codec import decode_production
    from srwz.iso9660 import member_map, scan_iso9660
    from srwz.tim2 import scan_tim2

    inventory = json.loads(mt.LOCKS.read_text())
    locks = {m['path']: m['sha256'] for m in inventory['sp']['members']}
    members = member_map(scan_iso9660(mt.ISO))
    sp_exe = mt.read_member(members, locks, mt.SD_EXE)
    sc_exe, tc_exe = (a.simplified / mt.OG_EXE).read_bytes(), (a.traditional / mt.OG_EXE).read_bytes()
    out_dir = clone / COMPONENT
    report_path = out_dir / 'report.json'
    report = json.loads(report_path.read_text())
    summary, unheld, relabeled = {}, [], []

    from special_disc import view_cache
    from srwz.codec import _rust_compressor_path
    from srwz.file_identity import sha256_file
    directory = os.environ.get(view_cache.ENV) if not (a.review or a.freeze) else None
    algorithms = []
    if directory:
        srwz = clone / 'tools/srwz'
        algorithms = [sha256_file(p) for p in (Path(__file__), Path(mt.__file__), _rust_compressor_path(),
                      srwz/'codec.py', srwz/'codec_contract.py', srwz/'codec_worker.py', srwz/'psmt4.py', srwz/'tim2.py')]
    held = dict(h.split('=', 1) for h in a.hold)
    cached_unheld = 0

    for member, (og_spec, sp_spec, storage) in mt.ARCHIVES.items():
        sc, tc = (a.simplified / member).read_bytes(), (a.traditional / member).read_bytes()
        og_jp = (ROOT / mt.OG_JAPANESE[member].relative_to(mt.ROOT)).read_bytes()
        sp_jp = mt.read_member(members, locks, member)
        path = out_dir / member
        sp = path.read_bytes() if path.exists() else mt.read_member(members, locks, member)
        if isinstance(og_spec, str):
            seg = (clone / 'work/disc' / og_spec).read_bytes()
            jt, zt = mt.seg_table(seg, len(sc)), mt.seg_table(seg, len(tc))
            st = mt.seg_table(mt.read_member(members, locks, sp_spec), len(sp))
        elif isinstance(og_spec, tuple):
            jt, zt = list(og_spec) + [len(sc)], list(og_spec) + [len(tc)]
            st = mt.table_at(sp_exe, sp_spec, len(sp))
        else:
            jt, zt = mt.table_at(sc_exe, og_spec, len(sc)), mt.table_at(tc_exe, og_spec, len(tc))
            st = mt.table_at(sp_exe, sp_spec, len(sp))
        if jt != zt:
            raise SystemExit(f'{member}: the Simplified and Traditional Original builds lay out chunks differently')

        # Cache each archive against its actual pixels, source bytes and parsed offset tables.
        # An unrelated executable edit or new Original workspace can still use the same result.
        slot = Path(directory) / (member.replace('/', '-') + '.texture') if directory else None
        if slot:
            key = view_cache.cache_key([algorithms, member, storage, member in held, jt, st,
                                        sha(sc), sha(tc), sha(og_jp), sha(sp), sha(sp_jp)])
            entry = view_cache.read_entry(slot, key)
            if entry is not None:
                header, payload = entry.split(b'\n', 1)
                counts, missing = json.loads(header)
                install_member(member, zlib.decompress(payload) if payload else None, held, path, report)
                summary[member] = counts
                cached_unheld += missing
                print(f'[sp-cache] textures/{member}: reused', flush=True)
                continue
        before_unheld = len(unheld)

        def content(blob: bytes) -> tuple[bytes, bool]:
            if storage == 'raw':
                return blob, False
            try:
                return decode_production(blob).output, True
            except Exception:  # noqa: BLE001 - not a codec stream
                return blob, False

        sp_data, sp_stream, sp_jp_data = {}, {}, {}
        index = collections.defaultdict(list)          # (w, h, type, image size) -> [(chunk, image offset)]
        for k, (s0, s1) in enumerate(zip(st, st[1:])):
            data, stream = content(sp[s0:s1])
            sp_data[k], sp_stream[k] = bytearray(data), stream
            sp_jp_data[k] = content(sp_jp[s0:s1])[0]
            for rec in scan_tim2(data):
                for pic in rec.pictures:
                    if pic.image_type in (4, 5):
                        index[(pic.width, pic.height, pic.image_type, pic.image_size)].append(
                            (k, pic.offset + pic.header_size))
        counts = collections.Counter()
        touched = set()
        for i in range(len(jt) - 1):
            sc_data, _ = content(sc[jt[i]:jt[i + 1]])
            jp_data, _ = content(og_jp[jt[i]:jt[i + 1]])
            tc_data, _ = content(tc[zt[i]:zt[i + 1]])
            if sc_data == tc_data:
                continue
            sc_recs, tc_recs = scan_tim2(sc_data), scan_tim2(tc_data)
            pics = [(x, y) for r, q in zip(sc_recs, tc_recs) for x, y in zip(r.pictures, q.pictures)]
            image_bytes = 0
            for ps, pt in pics:
                s0, t0 = ps.offset + ps.header_size, pt.offset + pt.header_size
                si, ti = sc_data[s0:s0 + ps.image_size], tc_data[t0:t0 + pt.image_size]
                if si == ti:
                    continue
                if (ps.offset, ps.width, ps.height, ps.image_type, ps.image_size) != \
                        (pt.offset, pt.width, pt.height, pt.image_type, pt.image_size) or \
                        sc_data[ps.offset:s0] != tc_data[pt.offset:t0] or \
                        sc_data[s0 + ps.image_size:ps.offset + ps.total_size] != \
                        tc_data[t0 + pt.image_size:pt.offset + pt.total_size]:
                    raise SystemExit(f'{member} chunk {i}: Traditional picture changes more than pixels')
                image_bytes += sum(x != y for x, y in zip(si, ti))
                bpp = 4 if ps.image_type == 4 else 8
                w, h = ps.width, ps.height
                # the stored order whose changes form the fewest regions is the picture's own (glyph-shaped)
                options = []
                for layout in layouts(bpp, w, h):
                    try:
                        spx, tpx = unpack(si, bpp, layout, w, h), unpack(ti, bpp, layout, w, h)
                    except ValueError:
                        continue
                    options.append((len(regions(spx, tpx, w, h)), layout, spx, tpx))
                _, layout, spx, tpx = min(options, key=lambda o: o[0])
                counts[f'pictures stored {layout}'] += 1
                cands = index.get((w, h, ps.image_type, ps.image_size), [])
                pending = []
                for box in regions(spx, tpx, w, h):
                    want, put = crop(spx, w, box), crop(tpx, w, box)
                    hit = done = 0
                    for k, off in cands:
                        cur = unpack(bytes(sp_data[k][off:off + ps.image_size]), bpp, layout, w, h)
                        got = crop(cur, w, box)
                        if got == want:
                            paste(cur, w, box, put)
                            sp_data[k][off:off + ps.image_size] = pack(cur, bpp, layout, w, h)
                            touched.add(k); hit += 1
                        elif got == put:
                            done += 1
                    if hit:
                        counts['regions applied'] += 1; counts['pictures written'] += hit
                    elif done:
                        counts['regions already Traditional'] += 1
                    else:
                        pending.append(box)
                # SP holds an older Simplified render of the region (the main game re-rendered its labels after
                # September): where SP's Japanese picture is the main game's Japanese one over the whole label and
                # the Simplified SP localized it, the label takes the Traditional Original's pixels whole.
                ojx = unpack(jp_data[s0:s0 + ps.image_size], bpp, layout, w, h) if pending else None
                resolved = set()
                for k, off in cands if pending else ():
                    jpx = unpack(sp_jp_data[k][off:off + ps.image_size], bpp, layout, w, h)
                    if sum(x == y for x, y in zip(jpx, ojx)) < 0.85 * w * h:
                        continue                                   # not the main game's picture
                    cur = unpack(bytes(sp_data[k][off:off + ps.image_size]), bpp, layout, w, h)
                    # a label: touching pixels where the Original's Japanese, Simplified and Traditional pictures or
                    # SP's Japanese and Simplified ones differ (8-connected: a word with its glow, not the block)
                    labels = [r for r in mask_regions({(n % w, n // w) for n in range(w * h)
                                                       if ojx[n] != spx[n] or ojx[n] != tpx[n] or jpx[n] != cur[n]},
                                                      w, h, reach=1, margin=1)
                              if any(overlaps(r, b) for b in pending)]
                    wrote = False
                    for label in labels:
                        hits = [b for b in pending if overlaps(b, label)]
                        if not hits:
                            continue
                        x0, y0, x1, y1 = label
                        pix = [y * w + x for y in range(y0, y1) for x in range(x0, x1)]
                        # SP's own Japanese art may differ from the main game's next to the text (SP edited
                        # cells); inside the Original's text footprint it must not
                        if any((ojx[n] != spx[n] or ojx[n] != tpx[n]) and jpx[n] != ojx[n] for n in pix):
                            continue
                        shared = [n for n in pix if jpx[n] == ojx[n]]
                        if all(cur[n] == jpx[n] for n in shared):
                            resolved.update(hits)                  # the Simplified SP left it Japanese
                            counts['labels the Simplified SP left Japanese'] += 1
                            continue
                        before = crop(cur, w, label)
                        for n in shared:
                            cur[n] = tpx[n]
                        if crop(cur, w, label) != before:
                            wrote = True
                            counts['labels re-rendered from the Traditional Original'] += 1
                            relabeled.append(dict(member=member, chunk=i, sp_chunk=k, picture=ps.offset, layout=layout,
                                                  size=[w, h], box=list(label), sp=before.hex(),
                                                  tc=crop(cur, w, label).hex()))
                        resolved.update(hits)
                    if wrote:
                        sp_data[k][off:off + ps.image_size] = pack(cur, bpp, layout, w, h)
                        touched.add(k)
                for box in pending:
                    if box in resolved:
                        continue
                    counts['regions SP does not hold'] += 1
                    unheld.append(dict(member=member, chunk=i, picture=ps.offset, size=[w, h], layout=layout,
                                       box=list(box), candidates=len(cands), sc=crop(spx, w, box).hex(),
                                       tc=crop(tpx, w, box).hex()))
            if not image_bytes:
                counts['chunks changed outside pictures (left)'] += 1
        if touched:
            output = bytearray(sp)
            for k in sorted(touched):
                s0, s1 = st[k], st[k + 1]
                data = bytes(sp_data[k])
                if a.freeze:
                    base = content(sp[s0:s1])[0]
                    frozen_out.setdefault(member, {})[str(k)] = dict(
                        before_sha256=sha(base), after_sha256=sha(data),
                        xor_zlib_base64=__import__('base64').b64encode(zlib.compress(bytes(x ^ y for x, y in zip(base, data)), 9)).decode())
                stored = mt.encode_into(sp[s0:s1], data, s1 - s0) if sp_stream[k] else data
                if sp_stream[k] and decode_production(stored).output != data:
                    raise SystemExit(f'{member} chunk {k}: codec readback')
                if len(stored) > s1 - s0:
                    raise SystemExit(f'{member} chunk {k}: Traditional pixels do not fit the slot')
                output[s0:s1] = stored + bytes(s1 - s0 - len(stored))
            if member in held:
                counts['held for the image chain'] = 1
            counts['SP chunks rewritten'] = len(touched)
        output = bytes(output) if touched else None
        install_member(member, output, held, path, report)
        summary[member] = dict(counts)
        if slot:
            header = json.dumps([counts, len(unheld) - before_unheld]).encode()
            payload = zlib.compress(output, 1) if output is not None else b''
            view_cache.write_entry(slot, key, header + b'\n' + payload)
    if a.freeze:
        a.freeze.parent.mkdir(parents=True, exist_ok=True)
        a.freeze.write_text(json.dumps({'schema_version': 1, 'members': frozen_out,
            'purpose': ('Traditional SP pictures over the SP textures component (shared by Taiwan and Hong Kong): '
                        'per member and chunk, the xor of the decoded chunk (sp_textures.py --frozen applies it; '
                        'KURODATA/KVMDATA.BIN is held for the image chain).')}, indent=1) + '\n', encoding='utf-8')
    report['traditional_delta'] = dict(simplified=str(a.simplified), traditional=str(a.traditional),
                                       members=summary, regions_not_held=len(unheld) + cached_unheld)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if a.review:
        a.review.mkdir(parents=True, exist_ok=True)
        (a.review / 'unheld.json').write_text(json.dumps(unheld, indent=1) + '\n')
        (a.review / 'relabeled.json').write_text(json.dumps(relabeled, indent=1) + '\n')
        try:
            from PIL import Image
        except ImportError:
            return
        for prefix, rows, left in (('unheld', unheld, 'sc'), ('relabeled', relabeled, 'sp')):
            for n, u in enumerate(rows):
                x0, y0, x1, y1 = u['box']
                k = x1 - x0; hgt = y1 - y0
                im = Image.new('L', (2 * k + 4, hgt), 128)
                mul = 17 if max(bytes.fromhex(u[left])) < 16 else 1
                im.paste(Image.frombytes('L', (k, hgt), bytes(v * mul for v in bytes.fromhex(u[left]))), (0, 0))
                im.paste(Image.frombytes('L', (k, hgt), bytes(v * mul for v in bytes.fromhex(u['tc']))), (k + 4, 0))
                name = f"{prefix}-{n:03d}-{u['member'].split('/')[-1].split('.')[0]}-{u['chunk']}-{x0}-{y0}.png"
                im.resize((im.width * 3, im.height * 3), Image.NEAREST).save(a.review / name)


if __name__ == '__main__':
    main()
