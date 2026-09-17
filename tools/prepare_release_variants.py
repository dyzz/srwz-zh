#!/usr/bin/env python3
"""Freeze a verified dual build and derive two independently checked skip variants."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from srwz.edition import json_bytes
from srwz.release_inputs import copy_file, sha256_file
from srwz.release_variants import build_variant
from verify_editions import verify_batch

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.version):
        parser.error('version must be a numeric release version')
    tag = f'v{args.version}'
    batch_path = ROOT / args.manifest
    verification = verify_batch(ROOT, batch_path)
    if not verification['both_editions']:
        raise ValueError('both editions are required')
    batch = json.loads(batch_path.read_text())
    frozen = ROOT / f'build/iso/{tag}'
    evidence = ROOT / f'manifests/releases/{tag}'
    config_path = ROOT / f'config/release/{tag}.json'
    if frozen.exists() or evidence.exists() or config_path.exists():
        raise ValueError('release already exists; refusing to replace frozen artifacts')
    frozen.mkdir(parents=True)
    evidence.mkdir(parents=True)
    contract = json.loads((ROOT/'config/full-story-components.json').read_text())['battle_square_skip']
    validation = {'status': 'dual_edition_build_and_static_readback_passed',
                  'verification': verification, 'input_digest': batch['input_digest'],
                  'batch_manifest': str(batch_path.relative_to(ROOT)), 'outputs': {},
                  'readbacks': {}, 'variants': {}, 'runtime': 'not_tested'}
    config = {'schema_version': 3, 'version': args.version, 'tag': tag, 'channel': 'stable',
              'validation': f'manifests/releases/{tag}/validation.json', 'editions': {},
              'xdelta': json.loads((ROOT/'config/release/v0.4.1.json').read_text())['xdelta'],
              'output': {'directory': f'build/release/{tag}'}, 'default_variant': 'no-skip',
              'known_limitations': [], 'evidence': []}
    for result in batch['results']:
        edition = result['edition_id']
        print(f'[{edition}] freeze base and verify skip derivative', flush=True)
        target = frozen / f'srwz-zh-{tag}-{edition}.iso'
        copy_file(ROOT/result['output']['path'], target)
        lock = {'path': str(target.relative_to(ROOT)), 'size': target.stat().st_size,
                'sha256': sha256_file(target)}
        if any(lock[k] != result['output'][k] for k in ('size','sha256')):
            raise ValueError('frozen base identity mismatch')
        proof_path = evidence / f'{edition}-readback.json'
        copy_file(ROOT/result['readback']['path'], proof_path)
        validation['outputs'][edition] = lock
        validation['readbacks'][edition] = {'path': str(proof_path.relative_to(ROOT)),
                                           'size': proof_path.stat().st_size, 'sha256': sha256_file(proof_path)}
        variant = frozen / f'srwz-zh-{tag}-{edition}-skip.iso'
        proof = build_variant(target, variant, contract, edition)
        variant_lock = {'path': str(variant.relative_to(ROOT)), 'size': proof['size'], 'sha256': proof['sha256']}
        variant_path = evidence/f'{edition}-skip-readback.json'
        variant_path.write_bytes(json_bytes(proof))
        validation['variants'][edition] = {'target_iso': variant_lock,
            'readback': {'path': str(variant_path.relative_to(ROOT)), 'size': variant_path.stat().st_size,
                         'sha256': sha256_file(variant_path)}}
        profile_path = f'config/editions/{edition}/edition.json'
        profile = json.loads((ROOT/profile_path).read_text())
        config['editions'][edition] = {'edition_config': profile_path, 'source_iso': profile['source_iso'],
            'target_iso': lock, 'patch_filename': f'srwz-zh-{tag}-{edition}.xdelta',
            'skip_variant': {'target_iso': variant_lock, 'patch_filename': f'srwz-zh-{tag}-{edition}-skip.xdelta'}}
    (evidence/'validation.json').write_bytes(json_bytes(validation))
    config['evidence'] = [str(config_path.relative_to(ROOT)), 'tools/build_release.py',
                          'tools/prepare_release_variants.py', 'tools/srwz/release_variants.py',
                          f'docs/RELEASE_NOTES_V{args.version}.md',
                          *[str(p.relative_to(ROOT)) for p in sorted(evidence.glob('*.json'))]]
    config_path.write_bytes(json_bytes(config))
    print(config_path)


if __name__ == '__main__':
    main()
