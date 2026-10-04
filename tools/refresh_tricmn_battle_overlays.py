#!/usr/bin/env python3
"""Write the reviewed TRICMN images into the current Original working ISO.

This asset-only path inherits the existing text build. It does not refresh
unrelated component inputs or rebuild text from a dirty working tree.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from build_iso import validate_output, verify_file
from build_tricmn_battle_overlays import _frozen_component
from special_disc.writeback.build_text_candidate import verify_iso_ranges
from srwz.file_identity import publish_verified, sha256_file
from srwz.iso9660 import member_map, scan_iso9660

ROOT = Path(__file__).resolve().parents[1]
MEMBER = 'BTL/TRICMN.BIN'
ISO_CONFIG = ROOT / 'config/iso/zh-release-current-build.json'
ASSET_CONFIG = ROOT / 'config/assets/tricmn-battle-overlays-zh.json'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lock(path: Path) -> dict:
    return dict(path=str(path.relative_to(ROOT)), size=path.stat().st_size,
                sha256=sha256_file(path))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def validate_member_delta(before: bytes, after: bytes, pictures: list) -> list:
    """Reject metadata, palette, size, or trailing-data changes."""
    if len(before) != len(after):
        raise ValueError('TRICMN member size changed')
    ranges = sorted((p['image_offset'], p['image_offset'] + p['image_size'])
                    for p in pictures)
    cursor = 0
    for start, end in ranges:
        if not cursor <= start <= end <= len(before):
            raise ValueError('TRICMN image range geometry drift')
        if before[cursor:start] != after[cursor:start]:
            raise ValueError('TRICMN delta escaped frozen image ranges')
        cursor = end
    if before[cursor:] != after[cursor:]:
        raise ValueError('TRICMN trailing data changed')
    return ranges


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    work = args.evidence.resolve()
    work.relative_to(ROOT)
    work.mkdir(parents=True, exist_ok=True)
    config_bytes = ISO_CONFIG.read_bytes()
    config = json.loads(config_bytes)
    asset_bytes = ASSET_CONFIG.read_bytes()
    asset = json.loads(asset_bytes)
    frozen, frozen_report = _frozen_component(ROOT, ASSET_CONFIG)
    iso = ROOT / config['output']['path']
    report_path = ROOT / config['output']['report']
    report_bytes = report_path.read_bytes()
    previous_report = json.loads(report_bytes)
    source_sha = sha256_file(iso)
    if (source_sha != previous_report['output_iso']['sha256'] or
            source_sha != config['output']['expected_sha256']):
        raise ValueError('current Original ISO identity drift')
    inventory = member_map(scan_iso9660(iso))
    member = inventory[MEMBER]
    at = member.extent_lba * 2048
    with iso.open('rb') as stream:
        stream.seek(at)
        before = stream.read(member.size)
    if sha(before) != previous_report['member_hashes'][MEMBER]:
        raise ValueError('current TRICMN readback differs from ISO receipt')
    if before == frozen:
        print('Current Original TRICMN already matches the frozen snapshot')
        return
    # These two images own the status, prompt and title revisions. The other
    # pictures must already match; replacing a whole member cannot hide drift.
    ranges = validate_member_delta(before, frozen, asset['tim2']['pictures'][:2])
    previous_iso = work / 'previous-original.iso'
    if previous_iso.exists():
        raise ValueError('evidence directory already contains an ISO revision')
    for path, data in ((ISO_CONFIG, config_bytes), (report_path, report_bytes),
                       (ASSET_CONFIG, asset_bytes)):
        (work / ('before-' + path.name)).write_bytes(data)
    subprocess.run(['cp', '-c', str(iso), str(previous_iso)], check=True)
    pending = work / 'candidate-original.iso'
    subprocess.run(['cp', '-c', str(iso), str(pending)], check=True)
    with pending.open('r+b') as stream:
        stream.seek(at)
        stream.write(frozen)
    reread_inventory = member_map(scan_iso9660(pending))
    if {k: (v.extent_lba, v.size) for k, v in inventory.items()} != {
            k: (v.extent_lba, v.size) for k, v in reread_inventory.items()}:
        raise ValueError('TRICMN update moved ISO members')
    with pending.open('rb') as stream:
        stream.seek(at)
        if stream.read(member.size) != frozen:
            raise ValueError('frozen TRICMN ISO readback drift')
    protected = verify_iso_ranges(previous_iso, pending,
                                  [(at + start, at + end) for start, end in ranges])
    candidate_config = deepcopy(config)
    replacement = next(r for r in candidate_config['replacements']
                       if r['member'] == MEMBER)
    replacement['size'], replacement['sha256'] = len(frozen), sha(frozen)
    candidate_config['output'].pop('expected_sha256', None)
    candidate_config['output'].pop('expected_member_manifest_sha256', None)
    source = ROOT / config['source_iso']['path']
    verify_file(source, config['source_iso']['size'], config['source_iso']['sha256'])
    # Reread every member, including independent UDF reads. This verifies ISO
    # content, not whether unrelated working-tree text inputs are current.
    result = validate_output(candidate_config, scan_iso9660(source), pending)
    result['output_iso']['path'] = config['output']['path']
    result['component_binding'] = dict(
        enforced=True, scope='frozen TRICMN only; other component bindings inherited',
        frozen_asset=frozen_report, inherited=previous_report.get('component_binding'),
        unrelated_working_tree_inputs_revalidated=False)
    result['runtime_acceptance'] = 'pending'
    result['emulator_executed_by_builder'] = False
    result['asset_update'] = dict(
        before_iso_sha256=source_sha, member=MEMBER,
        before_member_sha256=sha(before), after_member_sha256=sha(frozen),
        image_ranges=ranges, protected_iso_ranges=protected,
        metadata_clut_other_pictures_trailing_exact=True)
    receipt = work / 'production-readback.json'
    write_json(receipt, result)
    candidate_config['output']['expected_sha256'] = result['output_iso']['sha256']
    candidate_config['output']['expected_member_manifest_sha256'] = result['layout']['member_manifest_sha256']
    integrated_path = ROOT / config['component_validation_manifest']
    integrated_bytes = integrated_path.read_bytes()
    integrated = json.loads(integrated_bytes)
    (work / ('before-' + integrated_path.name)).write_bytes(integrated_bytes)
    # Refresh only this asset's deterministic locks; old text locks stay old
    # until their separate source changes are intentionally built.
    asset_manifest = ROOT / asset['outputs']['manifest']
    integrated['inputs']['tricmn_battle_overlay_component_manifest'] = lock(asset_manifest)
    for key, value in frozen_report['inputs'].items():
        integrated['inputs']['tricmn_battle_overlay_' + key] = value
    installed = ROOT / replacement['source']
    integrated['outputs'][MEMBER] = dict(path=str(installed.relative_to(ROOT)),
                                       size=len(frozen), sha256=sha(frozen))
    integrated['tricmn_battle_overlays'] = {
        k: frozen_report[k] for k in ('status', 'profile_id', 'seg', 'atlas', 'acceptance', 'runtime')}
    if (sha256_file(iso) != source_sha or ISO_CONFIG.read_bytes() != config_bytes or
            report_path.read_bytes() != report_bytes or ASSET_CONFIG.read_bytes() != asset_bytes or
            integrated_path.read_bytes() != integrated_bytes or
            _frozen_component(ROOT, ASSET_CONFIG)[0] != frozen):
        raise ValueError('ISO or frozen input changed during TRICMN update')
    installed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / frozen_report['outputs'][MEMBER]['path'], installed)
    if installed.read_bytes() != frozen:
        raise ValueError('installed frozen component drift')
    publish_verified(pending, iso, result['output_iso']['sha256'])
    write_json(report_path, result)
    write_json(integrated_path, integrated)
    write_json(ISO_CONFIG, candidate_config)
    print('Current Original ISO updated; frozen TRICMN only: ' + result['output_iso']['sha256'])


if __name__ == '__main__':
    main()
