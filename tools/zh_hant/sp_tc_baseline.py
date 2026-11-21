#!/usr/bin/env python3
"""Rebuild SP's frozen baseline in Traditional, the way the Simplified one was made (S4).

The Simplified SP baseline (work/build/special-disc/baselines) was assembled in September by the component
converters (tools/special_disc/writeback/migrate_*.py), which take the finished Original build as their answer key:
each Japanese string SP shares with Original takes the bytes the Original build wrote for it. Run in a prepared
Traditional SP clone (build_dual_sp.py) with the Traditional Original build as the answer key, the same converters
give the Traditional text, from the same parallel corpus as Original.

Steps (in the clone): point the converters' answer-key path at the Traditional Original components and their font
proposal at the Traditional SP one; run the converter chain; return the strings the SP system-text writer owns to
their Japanese bytes (in September the converters left them, the system-text writer translates them); rebuild the
system-text component, the preview baseline (including the frozen Traditional pictures) and the text canary; point the
SP builder at the new canary and refresh every lock.

Usage: sp_tc_baseline.py CLONE --answer-key TC_ORIGINAL_COMPONENTS --simplified-answer-key SC_ORIGINAL_COMPONENTS
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
HB_TABLE = 0x5170       # HEDBDY/HB.BIN STAGE table (migrate_flow.HB_TABLE)
ANSWER_KEY_DIR = ('work/build/zh-release-original/388152fa50e72ed8f4edf6887d9eb1f37130dfc5ee92ba7baf3238aaee22c02f'
                  '/project/work/build/zh-release-full-story/components')
PROPOSAL = 'work/writeback/zh-release-codebook-proposal.json'
SP_PROPOSAL = 'work/build/special-disc/text-candidate/font/proposal.json'
CHAIN = ['migrate_slps_text', 'migrate_srvc', 'migrate_compdata', 'migrate_library', 'migrate_nisv', 'migrate_names',
         'migrate_flow', 'migrate_exe_patches']
# migrate_textures is not re-run: the Original's atlases changed after September, so SP keeps its Simplified textures
# component plus the Original's own Simplified -> Traditional delta (sp_textures.py).
EXE = 'SLPS_259.20'
HELD_KVM = 'build/zh-hant-sp/kvmdata-traditional-delta.bin'   # sp_menu_atlas.py applies it after SP's image chain


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(clone: Path, *cmd):
    print('$', ' '.join(map(str, cmd)), flush=True)
    started = time.perf_counter()
    r = subprocess.run(list(map(str, cmd)), cwd=clone, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'{cmd[1] if len(cmd) > 1 else cmd[0]} failed:\n' + (r.stdout + r.stderr)[-3000:])
    print(f'[sp-view] baseline/{Path(cmd[1]).stem}: {time.perf_counter()-started:.2f}s', flush=True)
    for line in r.stdout.splitlines():
        if line.startswith('[sp-cache]'):
            print(line, flush=True)
    return r.stdout


def return_system_text_strings(clone: Path) -> int:
    """Give the system-text writer back the executable strings it owns: their Japanese bytes, as in September."""
    sys.path[:0] = [str(clone / 'tools'), str(clone / 'tools/special_disc/writeback')]
    from srwz.iso9660 import member_map, scan_iso9660
    from srwz.text import decode_text, load_text_table
    inventory = json.loads((clone / 'config/products/special-disc/disc-inventory.json').read_text())
    iso = (clone / inventory['sp']['path']).resolve()
    rec = member_map(scan_iso9660(iso))[EXE]
    with open(iso, 'rb') as f:
        f.seek(rec.extent_lba * 2048); jp = f.read(rec.size)
    table = load_text_table(clone / 'vendor/upstream-python/project/tbl_all.json')
    owned = set()
    for rel in ('corpus/zh/special-disc/system-text.json', 'corpus/zh/special-disc/frame-text.json'):
        for e in json.loads((clone / rel).read_text(encoding='utf-8'))['entries']:
            for loc in [e.get('id', '')] + list(e.get('locations') or []):
                m = isinstance(loc, str) and re.fullmatch(r'sd/exe/([0-9A-F]+)', loc)
                if m: owned.add(int(m.group(1), 16))
    comp = clone / 'work/build/special-disc/components/text'
    exe = bytearray((comp / EXE).read_bytes())
    restored = 0
    for va in sorted(owned):
        off = va
        if not 0 <= off < len(jp): continue
        n = decode_text(jp, off, table).consumed
        if exe[off:off + n] != jp[off:off + n]:
            exe[off:off + n] = jp[off:off + n]; restored += 1
    (comp / EXE).write_bytes(bytes(exe))
    report = json.loads((comp / 'report.json').read_text())
    report['files'][EXE] = sha(bytes(exe))
    report['zh_hant_returned_to_system_text'] = restored
    (comp / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return restored


def return_compdata_strings(clone: Path) -> int:
    """Same for the COMPDATA strings the system-text writer owns (sd/compdata/<decoded offset>)."""
    from srwz.codec import decode_production, reencode_changed_suffix
    from srwz.iso9660 import member_map, scan_iso9660
    from srwz.text import decode_text, load_text_table
    name = 'DATA/COMPDATA.BN'
    inventory = json.loads((clone / 'config/products/special-disc/disc-inventory.json').read_text())
    iso = (clone / inventory['sp']['path']).resolve()
    rec = member_map(scan_iso9660(iso))[name]
    with open(iso, 'rb') as f:
        f.seek(rec.extent_lba * 2048); jp = decode_production(f.read(rec.size)).output
    table = load_text_table(clone / 'vendor/upstream-python/project/tbl_all.json')
    owned = set()
    for rel in ('corpus/zh/special-disc/system-text.json', 'corpus/zh/special-disc/frame-text.json'):
        for e in json.loads((clone / rel).read_text(encoding='utf-8'))['entries']:
            for loc in [e.get('id', '')] + list(e.get('locations') or []):
                m = isinstance(loc, str) and re.fullmatch(r'sd/compdata/([0-9A-F]+)', loc)
                if m: owned.add(int(m.group(1), 16))
    comp = clone / 'work/build/special-disc/components/compdata'
    stored = (comp / name).read_bytes(); result = decode_production(stored); cd = bytearray(result.output)
    restored = 0
    for off in sorted(owned):
        n = decode_text(jp, off, table).consumed
        if cd[off:off + n] != jp[off:off + n]:
            cd[off:off + n] = jp[off:off + n]; restored += 1
    strings = SpStrings()
    merged, filled = fill_missing(bytes(cd), jp, translated_ranges('compdata'), strings)
    cd = bytearray(merged); restored += filled
    print('COMPDATA SP-only strings written from config/zh-hant/sp-strings:', filled, flush=True)
    unification = json.loads((clone / 'config/products/special-disc/name-unification-20261017.json').read_text())
    owned_fields = frozenset(e['offset'] for e in unification['entries'])
    renamed = write_pilot_names(cd, strings, owned_fields); restored += renamed
    print('COMPDATA SP pilot name fields written from config/zh-hant/sp-strings:', renamed, flush=True)
    if restored:
        encoded = reencode_changed_suffix(stored, bytes(cd), strategy='rust-maximum', original_result=result)
        if decode_production(encoded).output != bytes(cd) or len(encoded) > len(stored):
            raise SystemExit('COMPDATA re-encode failed')
        out = encoded + bytes(len(stored) - len(encoded))
        (comp / name).write_bytes(out)
        report = json.loads((comp / 'report.json').read_text())
        report['files'][name] = sha(out); report['zh_hant_returned_to_system_text'] = restored
        (comp / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return restored


def runs(a: bytes, b: bytes):
    """Maximal [start, end) runs where a and b differ."""
    i, n = 0, min(len(a), len(b))
    while i < n:
        if a[i] == b[i]: i += 1; continue
        j = i
        while j < n and a[j] != b[j]: j += 1
        yield i, j; i = j


RANGES = ROOT / 'config/products/special-disc/sp-translated-ranges.json'


def translated_ranges(kind: str) -> list:
    """[start, end) ranges SP translates in every language (config/products/special-disc/sp-translated-ranges.json)."""
    return [tuple(r) for r in json.loads(RANGES.read_text(encoding='utf-8'))[kind]]


def touches(ranges: list, i: int, j: int) -> bool:
    """True when [i, j) meets one of the sorted, disjoint ranges."""
    import bisect
    k = bisect.bisect_right(ranges, (i, float('inf'))) - 1
    for start, end in ranges[max(k, 0):]:
        if start >= j: return False
        if end > i: return True
    return False


def keep_translated(tc: bytes, jp: bytes, ranges: list) -> tuple[bytes, int]:
    """This language's bytes only inside the ranges SP translates; every other run goes back to Japanese (later
    writers own those strings, or SP leaves them Japanese)."""
    out = bytearray(tc); reverted = 0
    for i, j in runs(tc, jp):
        if not touches(ranges, i, j):
            out[i:j] = jp[i:j]; reverted += 1
    return bytes(out), reverted


class SpStrings:
    """This language's SP-only COMPDATA strings (config/zh-hant/sp-strings/<variant>.json, maintained by hand):
    SP strings the Original build has no counterpart for, and SP pilot name fields."""
    def __init__(self):
        import sp_text
        self.path = ROOT / 'config/zh-hant/sp-strings' / f'{VARIANT}.json'
        _, self.code_of = sp_text.codebook(ROOT / 'config/zh-hant/encoding/zh-release-font-assignments.json')
        self.entries = json.loads(self.path.read_text(encoding='utf-8'))['entries']
        self.strings: dict = {}                       # start -> entries by end (a string can end at several NULs)
        for e in self.entries:
            if e['kind'] == 'string':
                self.strings.setdefault(int(e['offset'], 16), []).append(e)
        for v in self.strings.values():
            v.sort(key=lambda e: int(e['end'], 16))
        self.pilots = [e for e in self.entries if e['kind'] == 'pilot-name']
        self.encode = lambda e: sp_text.encode(e['text'], self.code_of)


def fill_missing(tc: bytes, jp: bytes, ranges: list, strings: SpStrings) -> tuple[bytes, int]:
    """Strings SP translates that the Original build gave no text (still Japanese here): this language's stored
    text over the whole NUL-delimited string."""
    out = bytearray(tc); filled = 0
    for i, j in ranges:
        if tc[i:j] != jp[i:j]: continue
        start = jp.rfind(b'\0', 0, i) + 1
        # the stored span of this run: the first one of this string that reaches the run's end
        entry = next((e for e in strings.strings.get(start, []) if int(e['end'], 16) >= j), None)
        if entry is None:
            raise SystemExit(f'SP string at COMPDATA {start:X} ({jp[start:jp.find(b"\\0", j)].hex()}) has no text in '
                             f'{strings.path.relative_to(ROOT)}')
        end = int(entry['end'], 16)
        out[start:end] = strings.encode(entry); filled += 1
    return bytes(out), filled


def write_pilot_names(cd: bytearray, strings: SpStrings, owned=frozenset()) -> int:
    """SP pilot name fields: this language's stored names (fields a later writer owns are left to it)."""
    renamed = 0
    for e in strings.pilots:
        at, capacity = int(e['offset'], 16), e['capacity']
        if at in owned: continue
        b = strings.encode(e)
        if len(b) >= capacity: raise SystemExit(f'SP pilot name at {at:X} does not fit its {capacity}-byte field')
        new = b + bytes(capacity - len(b))
        if cd[at:at + capacity] != new:
            cd[at:at + capacity] = new; renamed += 1
    return renamed


def guide_flow(clone: Path, root: Path) -> int:
    """STAGE chunk 0 (scenario chart) of the flow component: this language's text only where SP translates."""
    import struct
    from srwz.codec import decode_production, reencode_changed_suffix
    from srwz.iso9660 import member_map, scan_iso9660
    name = 'DATA/STAGE.BIN'; rel = 'work/build/special-disc/components/flow'
    inventory = json.loads((clone / 'config/products/special-disc/disc-inventory.json').read_text())
    iso = (clone / inventory['sp']['path']).resolve(); m = member_map(scan_iso9660(iso))
    def member(n):
        with open(iso, 'rb') as f:
            f.seek(m[n].extent_lba * 2048); return f.read(m[n].size)
    slot = struct.unpack_from('<I', member('HEDBDY/HB.BIN'), HB_TABLE + 4)[0]
    jp_stage = member(name); tc_stage = (clone / rel / name).read_bytes()
    jp = decode_production(jp_stage[:slot]).output
    tc_result = decode_production(tc_stage[:slot]); tc = tc_result.output
    if len(jp) != len(tc): raise SystemExit('flow chunk sizes differ')
    merged, reverted = keep_translated(tc, jp, translated_ranges('stage_chunk0'))
    if reverted:
        encoded = reencode_changed_suffix(tc_stage[:tc_result.consumed], merged, strategy='rust-maximum', original_result=tc_result)
        if decode_production(encoded).output != merged or len(encoded) > slot: raise SystemExit('flow re-encode failed')
        out = bytearray(tc_stage); out[:slot] = encoded + bytes(slot - len(encoded))
        (clone / rel / name).write_bytes(bytes(out))
        report = json.loads((clone / rel / 'report.json').read_text())
        report['files'][name] = sha(bytes(out)); report['zh_hant_untranslated_reverts'] = reverted
        (clone / rel / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return reverted


VARIANT = 'tw'


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('clone', type=Path)
    p.add_argument('--answer-key', type=Path, required=True)
    p.add_argument('--simplified-answer-key', type=Path, required=True,
                   help='the Simplified Original components built from the same inputs (texture delta)')
    p.add_argument('--variant', choices=('tw', 'hk'), default='tw', help='Traditional variant of the clone (drafting)')
    a = p.parse_args()
    global VARIANT
    VARIANT = a.variant
    c = a.clone.resolve()
    key = c / ANSWER_KEY_DIR
    key.parent.mkdir(parents=True, exist_ok=True)
    if key.is_symlink() or key.exists(): key.unlink()
    key.symlink_to(a.answer_key.resolve())
    proposal = (c / SP_PROPOSAL).read_bytes()
    (c / PROPOSAL).write_bytes(proposal)
    manifest_path = c / 'manifests/zh-release-font-validation.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['proposal'].update(size=len(proposal), sha256=sha(proposal))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    for step in CHAIN:
        args = ['--proposal', PROPOSAL] if step == 'migrate_srvc' else []
        run(c, sys.executable, f'tools/special_disc/writeback/{step}.py', *args)
        if step == 'migrate_slps_text':
            print('strings returned to the system-text writer:', return_system_text_strings(c), flush=True)
        if step == 'migrate_flow':
            print('flow runs back to Japanese (outside the SP translated ranges):', guide_flow(c, ROOT), flush=True)
        if step == 'migrate_compdata':
            print('COMPDATA strings returned to the system-text writer:', return_compdata_strings(c), flush=True)
    run(c, sys.executable, 'tools/special_disc/writeback/write_system_text.py', '--proposal', PROPOSAL)
    run(c, sys.executable, HERE / 'sp_textures.py', c, '--simplified', a.simplified_answer_key.resolve(),
              '--traditional', a.answer_key.resolve(), '--hold', f'KURODATA/KVMDATA.BIN={c / HELD_KVM}')
    print('Traditional SP components rebuilt', flush=True)
    # preview baseline (components + pictures), then the text canary on it (font + canary stage component)
    from sp_pictures import install_sp_pictures
    install_sp_pictures(c)
    run(c, sys.executable, 'tools/special_disc/writeback/build_preview.py')
    preview = json.loads((c / 'work/build/special-disc/baselines/preview.json').read_text())['iso_sha256']
    btc = c / 'tools/special_disc/writeback/build_text_candidate.py'
    btc.write_text(re.sub(r"^PREVIEW_SHA256 = '[0-9a-f]+'", f"PREVIEW_SHA256 = '{preview}'", btc.read_text(), flags=re.M))
    run(c, sys.executable, 'tools/special_disc/writeback/migrate_stage_dialogue.py', '--allow-draft', '--proposal', SP_PROPOSAL)
    run(c, sys.executable, 'tools/special_disc/writeback/build_text_candidate.py', '--assemble-only')
    canary = json.loads((c / 'work/build/special-disc/baselines/text-canary.json').read_text())['iso_sha256']
    bft = c / 'tools/special_disc/writeback/build_full_text.py'
    bft.write_text(re.sub(r"^BASE_SHA='[0-9a-f]+'", f"BASE_SHA='{canary}'", bft.read_text(), flags=re.M))
    from srwz.file_identity import sha256_file as filecmp_digest
    changed = []
    for f in (c / 'work/build/special-disc').rglob('*'):
        # logs name this project's directory and are locked nowhere: not a difference to look for
        if f.is_file() and not f.is_symlink() and f.suffix != '.log':
            rel = f.relative_to(c); o = ROOT / rel
            if not o.exists() or filecmp_digest(o) != filecmp_digest(f): changed.append(str(rel))
    sys.path.insert(0, str(HERE))
    from locks import refresh_locks
    print('Traditional SP baseline: preview', preview[:12], 'canary', canary[:12], 'changed files', len(changed),
          'locks refreshed', refresh_locks(c, changed), flush=True)


if __name__ == '__main__':
    main()
