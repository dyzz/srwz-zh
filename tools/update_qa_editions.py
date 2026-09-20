#!/usr/bin/env python3
"""Refresh only the Q&A slot of a receipt-bound Original or The Best ISO.

The production Original compiler owns the shared Chinese Q&A. The Best backend
already uses that complete decoded Q&A, including the corrected descriptions.
This updater uses each edition's executable offset table and proves every byte
outside the existing Q&A slot unchanged. It does not claim a new full build.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct

from build_full_story_components import _full_story_overrides, _stored_text_overrides
from srwz.codec import decode_production, reencode_changed_suffix
from srwz.iso9660 import member_map, scan_iso9660
from srwz.nisv_strategy_qa import build_nisv_strategy_qa, parse_nisv_strategy_qa
from srwz.qa_typography import shared_records, styled_runs, validate_records
from srwz.release_inputs import sha256_file
from srwz.text import load_text_table, project_runtime_text_table
from verify_full_story_iso_content import verify_nisv_strategy_qa

ROOT = Path(__file__).resolve().parents[1]
MEMBER = 'DATA/NISVDATA.BIN'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def read_member(path, members, name):
    row = members[name]
    with path.open('rb') as stream:
        stream.seek(row.extent_lba * 2048)
        data = stream.read(row.size)
    require(len(data) == row.size, f'Short ISO member read: {name}')
    return data


def verify_protected(before, after, start, end):
    size = before.stat().st_size
    require(after.stat().st_size == size, 'ISO size changed')
    digest = hashlib.sha256()
    with before.open('rb') as a, after.open('rb') as b:
        for lo, hi in [(0, start), (end, size)]:
            a.seek(lo); b.seek(lo)
            remaining = hi-lo
            while remaining:
                n = min(4*1024*1024, remaining)
                x, y = a.read(n), b.read(n)
                require(x == y and len(x) == n, 'Change outside Q&A ISO slot')
                digest.update(x); remaining -= n
    return dict(bytes=size-(end-start), sha256=digest.hexdigest(), byte_exact=True)


def compile_qa():
    config_path = ROOT/'config/full-story-components.json'
    config = json.loads(config_path.read_text())['nisv_strategy_qa']
    corpus_path = ROOT/config['corpus']['path']
    source_path = ROOT/config['original_archive']['path']
    for path, lock in [(corpus_path, config['corpus']), (source_path, config['original_archive'])]:
        require(path.stat().st_size == lock['size'] and sha256_file(path) == lock['sha256'], f'Input lock drift: {path}')
    font_path = ROOT/'manifests/zh-release-font-validation.json'
    proposal, primary, aliases, _ = _full_story_overrides(json.loads(font_path.read_text()))
    table_path = ROOT/'vendor/upstream-python/project/tbl_all.json'
    table = load_text_table(table_path)
    overrides = _stored_text_overrides(table, primary, aliases)
    runtime = project_runtime_text_table(table, overrides)
    source = source_path.read_bytes()
    exe = (ROOT/'work/disc/SLPS_258.87').read_bytes()
    archive, report = build_nisv_strategy_qa(source, source, exe, config,
                                           json.loads(corpus_path.read_text()), table, overrides)
    proof = verify_nisv_strategy_qa(exe, archive, runtime, {'nisv_strategy_qa': report})
    a, b = config['target']['stored_start'], config['target']['stored_end']
    chunk = decode_production(archive[a:b]).output
    paths = [config_path, corpus_path, source_path, font_path, proposal, table_path,
             ROOT/'tools/srwz/qa_typography.py', ROOT/'tools/srwz/nisv_strategy_qa.py',
             ROOT/'tools/verify_full_story_iso_content.py', Path(__file__)]
    inputs = {str(p.relative_to(ROOT)): sha256_file(p) for p in paths}
    return chunk, runtime, report, proof, inputs


def update(edition, *, apply=False):
    receipt_path = ROOT/f'manifests/editions/{edition}/current.json'
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    iso = ROOT/receipt['output']['path']
    baseline = sha256_file(iso)
    require(baseline == receipt['output']['sha256'], 'Current ISO/receipt drift')
    members = member_map(scan_iso9660(iso))
    profile = json.loads((ROOT/f'config/editions/{edition}/edition.json').read_text())
    exe = read_member(iso, members, profile['executable']['member'])
    archive = read_member(iso, members, MEMBER)
    spec = next(r for r in json.loads((ROOT/'config/editions/best/source-layout.json').read_text())['archive_tables'] if r['member'] == MEMBER)
    a, b = struct.unpack_from('<II', exe, spec[f'{edition}_start']+24)
    require(0 < a < b <= len(archive), 'Edition Q&A slot drift')
    before = decode_production(archive[a:b])
    chunk, runtime, component, proof, inputs = compile_qa()
    old, new = parse_nisv_strategy_qa(before.output), parse_nisv_strategy_qa(chunk)
    require(len(before.output) == len(chunk) and old['entries'] == new['entries'], 'Q&A allocations changed')
    require(before.output[:old['pages'][0]['start']] == chunk[:new['pages'][0]['start']], 'Q&A metadata/index changed')
    changed = []
    for number, (left, right) in enumerate(zip(old['pages'], new['pages']), 1):
        require(left['sprite_bytes'] == right['sprite_bytes'] and left['size'] == right['size'], f'Q&A sprite/allocation drift: {number}')
        require(styled_runs(shared_records(left, runtime)) == styled_runs(shared_records(right, runtime)), f'Current Q&A text/colour drift: {number}')
        validate_records(shared_records(right, runtime))
        lo, size = left['start'], left['size']
        if before.output[lo:lo+size] != chunk[lo:lo+size]:
            changed.append(number)
    if not changed:
        return dict(edition=edition, status='already_current', iso=receipt['output'])
    packed = reencode_changed_suffix(archive[a:b], chunk, strategy='rust-maximum',
                                     max_output_size=b-a, original_result=before)
    require(decode_production(packed).output == chunk, 'Edition compression readback failed')
    payload = packed + bytes(b-a-len(packed))
    output_archive = archive[:a]+payload+archive[b:]
    # Preserve the prior receipt before replacing this updater's report path.
    # Repeated narrow updates must never create a self-referential proof chain.
    previous_readback = dict(receipt['readback'])
    previous_path = ROOT/previous_readback['path']
    require(sha256_file(previous_path) == previous_readback['sha256'], 'Prior readback receipt drift')
    frozen = ROOT/f'work/authoring/qa-main-20260920/{edition}/baselines/{baseline}/readback.json'
    frozen.parent.mkdir(parents=True, exist_ok=True)
    if frozen.exists():
        require(sha256_file(frozen) == previous_readback['sha256'], 'Archived prior readback drift')
    else:
        shutil.copyfile(previous_path, frozen)
    previous_readback['path'] = str(frozen.relative_to(ROOT))
    report = dict(schema_version=1, edition=edition,
                  status='qa_static_validated_runtime_pending',
                  baseline_iso=receipt['output'], baseline_build_readback=previous_readback,
                  source_inputs=inputs, executable_sha256=sha(exe),
                  slot=dict(start=a, end=b, compressed=len(packed), capacity=b-a),
                  decoded_sha256=sha(chunk), changed_pages=changed,
                  protected_metadata_and_sprites=True, styled_text_unchanged=True,
                  production_component_readback=proof,
                  layout_repairs=[dict(page=p['page'], repairs=p['layout_repairs']) for p in component['pages'] if p['layout_repairs']],
                  page_records=[dict(page=p['page'], records=p['records']) for p in component['pages']],
                  runtime='pending', full_build_validation='baseline plus byte-exact protection outside Q&A')
    work = ROOT/f'work/authoring/qa-main-20260920/{edition}'
    write_json(work/'proposal.json', report)
    (work/'NISVDATA.BIN').write_bytes(output_archive)
    if not apply:
        return dict(edition=edition, status='proposal_validated', changed_pages=changed,
                    proposal=str((work/'proposal.json').relative_to(ROOT)))
    temporary = iso.with_suffix('.qa-layout.tmp.iso')
    require(not temporary.exists(), 'Temporary ISO exists')
    try:
        shutil.copyfile(iso, temporary)
        at = members[MEMBER].extent_lba*2048
        with temporary.open('r+b') as stream:
            stream.seek(at+a); stream.write(payload)
        after = member_map(scan_iso9660(temporary))
        require({n:(r.extent_lba,r.size) for n,r in members.items()} == {n:(r.extent_lba,r.size) for n,r in after.items()}, 'ISO layout changed')
        require(read_member(temporary, after, MEMBER) == output_archive, 'ISO Q&A readback mismatch')
        report['protected_iso_ranges'] = verify_protected(iso, temporary, at+a, at+b)
        report['iso'] = dict(path=str(iso.relative_to(ROOT)), size=temporary.stat().st_size, sha256=sha256_file(temporary))
        require(sha256_file(iso) == baseline and receipt_path.read_bytes() == receipt_bytes, 'Concurrent current ISO/receipt change')
        report_path = ROOT/f'manifests/qa-{edition}-writeback-20260920.json'
        write_json(report_path, report)
        updated = dict(receipt)
        updated.update(output=report['iso'], runtime='pending', status='edition_qa_update_static_validated_runtime_pending',
                       qa_baseline=dict(output=receipt['output'], readback=previous_readback, status=receipt['status']),
                       readback=dict(path=str(report_path.relative_to(ROOT)),sha256=sha256_file(report_path),scope='Q&A and protected ISO ranges'))
        temporary.replace(iso)
        write_json(receipt_path, updated)
        return {k:report[k] for k in ('edition','iso','changed_pages','slot','protected_iso_ranges')}
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', required=True, choices=('original','best'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(update(args.edition, apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
