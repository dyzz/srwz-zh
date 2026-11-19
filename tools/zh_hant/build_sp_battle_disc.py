"""Rebuild SP's three battle subtitle archives concurrently and update one validated multilingual disc.

This incremental writer owns BTL/SRVC.BIN only. The base supplies all other
assets and the fixed three-slot layout. The caller supplies its locked SHA-256.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.file_identity import sha256_file
from srwz.iso9660 import scan_iso9660, member_map
from srwz.release_inputs import copy_file

MEMBER = 'BTL/SRVC.BIN'
REGIONS = [('zh', ''), ('zh-hant', '-zh-hant-tw'), ('zh-hant-hk', '-zh-hant-hk')]


def load(path):
    return json.loads(path.read_text())


def compile_region(spec, work):
    tree, suffix = spec
    receipt = load(ROOT / f'manifests/editions/sp/candidate{suffix}.json')
    workspace = ROOT / receipt['workspace']
    report_path = ROOT / receipt['readback']['path']
    if sha256_file(report_path) != receipt['readback']['sha256']:
        raise ValueError(f'{tree}: prior SP verification report changed')
    report = load(report_path)
    component, digest = next((workspace / p, h) for p, h in report['components'].items()
                             if Path(p).parent.name == 'srvc')
    if sha256_file(component) != digest:
        raise ValueError(f'{tree}: prior subtitle receipt changed')
    previous = load(component)
    proposal = workspace / 'work/build/special-disc/text-candidate/font/proposal.json'
    if sha256_file(proposal) != previous['proposal_sha256']:
        raise ValueError(f'{tree}: codebook does not match the verified base')
    out = work / tree
    subprocess.run([sys.executable, str(ROOT / 'tools/special_disc/writeback/migrate_srvc.py'),
                    '--proposal', str(proposal), '--output', str(out), '--corpus-tree', tree,
                    '--include-sp', '--allow-draft'], cwd=ROOT, stdout=subprocess.DEVNULL, check=True)
    result = out / MEMBER
    if sha256_file(result) != load(out / 'report.json')['files'][MEMBER]:
        raise ValueError(f'{tree}: generated subtitle archive changed')
    return previous['files'][MEMBER], result.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--base-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    start = time.monotonic()
    if args.output.exists():
        parser.error('output must be a new file')
    if sha256_file(args.base) != args.base_sha256:
        parser.error('base hash mismatch')
    disc = load(args.base.with_suffix('.receipt.json'))
    if disc['edition'] != 'sp' or disc['languages'] != 3:
        parser.error('base must be a three-language SP disc')
    entries = member_map(scan_iso9660(args.base))
    original, dmy = entries[MEMBER], entries['DMY/DMY.BIN']
    slots = [(original.extent_lba * 2048, original.size)]
    for name in (MEMBER, 'HK ' + MEMBER):
        item, = [x for x in disc['dmy'] if x['item'] == name]
        offset = (item['lba'] - dmy.extent_lba) * 2048
        if not 0 <= offset <= dmy.size - item['bytes']:
            parser.error('regional subtitle slot outside DMY')
        slots.append((item['lba'] * 2048, item['bytes']))
    ordered = sorted(slots)
    if any(a + n > b for (a, n), (b, _) in zip(ordered, ordered[1:])):
        parser.error('overlapping subtitle slots')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temp:
        work = Path(temp)
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda spec: compile_region(spec, work), REGIONS))
        staged = work / 'candidate.iso'
        copy_file(args.base, staged)
        with staged.open('r+b') as f:
            for (offset, size), (before, data) in zip(slots, results):
                f.seek(offset)
                if len(data) != size or hashlib.sha256(f.read(size)).hexdigest() != before:
                    raise ValueError('subtitle slot does not match the verified language archive')
                f.seek(offset)
                f.write(data)
            for (offset, size), (_, data) in zip(slots, results):
                f.seek(offset)
                if f.read(size) != data:
                    raise ValueError('final subtitle readback failed')
        digest = sha256_file(staged)
        os.link(staged, args.output)  # Publish only if the requested output is still absent.
    print(f'{digest}  {args.output}  {time.monotonic()-start:.2f}s')


if __name__ == '__main__':
    main()
