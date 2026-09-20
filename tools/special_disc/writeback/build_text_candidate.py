"""Build the two-stage SP development ISO on the locked image preview.

Uses the canonical shared font snapshot and the existing main-game font tools.
Only candidate paths are written. Required components and exact preimages are
checked before assembly; unmodified ISO ranges are compared after writing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools'), str(Path(__file__).resolve().parent)]
from srwz.iso9660 import member_map, scan_iso9660
from srwz.codec import decode_production
from install_font import sp_offsets, VT1_TABLE

WORK = ROOT / 'work/build/special-disc/text-candidate'
PREVIEW = ROOT / 'build/iso/special-disc/preview/sp-image-preview.iso'
PREVIEW_SHA256 = '51a819a426ce049a0ee6ae5c696bb48290445cd8322bf192e2cc45271d1e4a8b'
DEST = ROOT / 'build/iso/special-disc/text-candidate/sp-text-canary.iso'
EXE, VT1, STAGE = 'SLPS_259.20', 'DATA/VT1.BIN', 'DATA/STAGE.BIN'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def load(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build():
    profile = load(ROOT / 'config/fonts/zh-release-font.json')
    for key, value in dict(readiness='readiness.json', proposal='proposal.json',
                           component_root='components', validation='validation.json', manifest='manifest.json').items():
        profile['outputs'][key] = str((WORK / 'font' / value).relative_to(ROOT))
    write_json(WORK / 'font/profile.json', profile)
    def run(script, *args):
        print(f'[{Path(script).name}]', flush=True)
        with (WORK / f'{Path(script).stem}.log').open('w') as log:
            subprocess.run([sys.executable, str(ROOT / script), *map(str, args)], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
    font = WORK / 'font'
    run('tools/update_zh_release_font_snapshot.py')  # read-only: additions must already be explicit
    run('tools/prepare_zh_release_font.py', '--config', font/'profile.json', '--raster-output', font/'rasters.json', '--force')
    run('tools/build_zh_font_component.py', '--font-config', font/'profile.json', '--proposal', font/'proposal.json',
        '--raster-input', font/'rasters.json', '--output-root', font/'components', '--force')
    run('tools/verify_zh_release_font.py', '--config', font/'profile.json', '--refresh-manifest', '--force')
    run('tools/special_disc/writeback/install_font.py', '--source', font/'components', '--output', WORK/'sp-font')
    run('tools/special_disc/writeback/migrate_stage_dialogue.py', '--allow-draft', '--proposal', font/'proposal.json')


def read_member(path, members, name):
    m = members[name]
    with path.open('rb') as stream:
        stream.seek(m.extent_lba * 2048)
        return stream.read(m.size)


def verify_iso_ranges(before, after, patches):
    """Compare every byte outside the three declared member extents."""
    spans = sorted(patches)
    spans = [(0, 0)] + spans + [(before.stat().st_size, before.stat().st_size)]
    digest, count = hashlib.sha256(), 0
    with before.open('rb') as left, after.open('rb') as right:
        for (_, start), (end, _) in zip(spans, spans[1:]):
            left.seek(start); right.seek(start)
            remaining = end - start
            while remaining:
                a = left.read(min(4 * 1024 * 1024, remaining)); b = right.read(len(a))
                require(bool(a) and a == b, f'unowned ISO range changed at {left.tell()-len(a):X}')
                remaining -= len(a); count += len(a); digest.update(a)
    return dict(bytes=count, sha256=digest.hexdigest())


def assemble():
    require(file_sha(PREVIEW) == PREVIEW_SHA256, 'preview ISO identity drift')
    stage_report = load(WORK/'stage/report.json')
    font_report = load(WORK/'sp-font/report.json')
    require(stage_report['status'] == 'static_component_verified_runtime_pending', 'stage component failed')
    require(stage_report['chunks'] == [1, 39], 'unexpected canary stage scope')
    proposal = WORK/'font/proposal.json'
    require(stage_report['proposal']['sha256'] == file_sha(proposal), 'stage/font proposal mismatch')
    shared = load(ROOT/'config/fonts/zh-release-font.json')
    require(load(WORK/'font/profile.json')['allocation_snapshot'] == shared['allocation_snapshot'], 'shared snapshot drift')
    require(file_sha(ROOT/shared['allocation_snapshot']['path']) == shared['allocation_snapshot']['sha256'], 'shared snapshot hash drift')
    for path, expected in stage_report['inputs'].items():
        require(file_sha(ROOT/path) == expected, f'corpus drift: {path}')
    for directory, report in ((WORK/'stage', stage_report), (WORK/'sp-font', font_report)):
        for name, expected in report['files'].items():
            require(file_sha(directory/name) == expected, f'component hash drift: {name}')
    validation = load(WORK/'font/manifest.json')
    require(validation['proposal']['sha256'] == file_sha(proposal), 'font verification proposal drift')
    for key in ('report', 'slps', 'vt1'):
        lock = validation['font_component'][key]
        require(file_sha(ROOT/lock['path']) == lock['sha256'], f'verified font component drift: {key}')
    require(validation['font_component']['decoded_font_sha256'] == font_report['font']['decoded_sha256'],
            'installed font does not match the verified shared font')
    members = member_map(scan_iso9660(PREVIEW))
    old_root = ROOT/'work/build/special-disc/components/font'
    old_report = load(old_root/'report.json')
    old_exe, old_vt1 = (old_root/EXE).read_bytes(), (old_root/VT1).read_bytes()
    require(sha(old_exe) == old_report['files'][EXE] and sha(old_vt1) == old_report['files'][VT1], 'baseline font component drift')
    new_exe, new_vt1 = (WORK/'sp-font'/EXE).read_bytes(), (WORK/'sp-font'/VT1).read_bytes()
    preview_exe, preview_vt1 = read_member(PREVIEW,members,EXE), read_member(PREVIEW,members,VT1)
    old = sp_offsets(old_exe,VT1_TABLE,len(old_vt1)); new = sp_offsets(new_exe,VT1_TABLE,len(new_vt1))
    require(old[:2] == new[:2] and old[4:] == new[4:], 'unexpected font table movement')
    start, end = min(old[2],new[2]), old[4]
    require(preview_vt1[start:end] == old_vt1[start:end], 'preview font/audio preimage drift')
    patched_vt1 = preview_vt1[:start] + new_vt1[start:end] + preview_vt1[end:]
    patched_exe = bytearray(preview_exe)
    for index in (2,3):
        site = VT1_TABLE + index*4
        require(preview_exe[site:site+4] == old_exe[site:site+4], 'preview font table preimage drift')
        patched_exe[site:site+4] = new_exe[site:site+4]
    for site in (0x3B0E0,0x168A1C):
        require(patched_exe[site:site+4] == bytes.fromhex('9f820134'), 'text measurement range patch missing')
    require(sha(read_member(PREVIEW,members,STAGE)) == stage_report['baseline']['sha256'], 'preview STAGE preimage mismatch')
    font_decoded = decode_production(patched_vt1[new[3]:new[4]]).output
    require(sha(font_decoded) == font_report['font']['decoded_sha256'], 'candidate font readback mismatch')
    patches = {EXE: bytes(patched_exe), VT1: patched_vt1, STAGE: (WORK/'stage'/STAGE).read_bytes()}
    DEST.parent.mkdir(parents=True,exist_ok=True)
    temporary = DEST.with_suffix('.tmp.iso')
    shutil.copyfile(PREVIEW,temporary)
    with temporary.open('r+b') as output:
        for name, data in patches.items():
            require(len(data) == members[name].size, f'member length changed: {name}')
            output.seek(members[name].extent_lba*2048); output.write(data)
    reread_members = member_map(scan_iso9660(temporary))
    require({k:(v.extent_lba,v.size) for k,v in members.items()} == {k:(v.extent_lba,v.size) for k,v in reread_members.items()}, 'ISO layout changed')
    for name,data in patches.items():
        require(read_member(temporary,reread_members,name) == data, f'ISO member reread mismatch: {name}')
    protected = verify_iso_ranges(PREVIEW,temporary,[(members[n].extent_lba*2048,members[n].extent_lba*2048+len(d)) for n,d in patches.items()])
    temporary.replace(DEST)
    report = dict(schema_version=1,status='development_canary_static_verified_runtime_pending',
        iso=dict(path=str(DEST.relative_to(ROOT)),size=DEST.stat().st_size,sha256=file_sha(DEST)),
        baseline=dict(path=str(PREVIEW.relative_to(ROOT)),sha256=PREVIEW_SHA256),
        scope=dict(stage_chunks=[1,39],bindings=sum(len(r['bindings']) for r in stage_report['chunk_reports']),
                   pending=['formation names','VT1 challenge briefing','other stages and text surfaces','draft review','runtime acceptance']),
        files={name:sha(data) for name,data in patches.items()}, protected_iso_ranges=protected,
        font=font_report['font'],font_move=font_report['move'],proposal_sha256=file_sha(proposal),
        components={str(p.relative_to(ROOT)):file_sha(p) for p in [WORK/'stage/report.json',WORK/'sp-font/report.json',WORK/'font/manifest.json']},
        range_patch_sites=['0x3B0E0','0x168A1C'])
    write_json(DEST.with_suffix('.json'),report)
    print(json.dumps(report['iso'],indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assemble-only',action='store_true',help='Reuse components after validating their receipts.')
    args=parser.parse_args()
    WORK.mkdir(parents=True,exist_ok=True)
    if not args.assemble_only:
        build()
    assemble()


if __name__ == '__main__':
    main()
