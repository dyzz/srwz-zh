#!/usr/bin/env python3
"""Freeze a verified Original+BEST+SP batch with skip built into every image.

Every current ISO produced by build_editions already contains the battle square
skip hook. Freezing copies the three verified images and their semantic readbacks
under the release tag, rereads each frozen executable to prove the hook, and
writes the schema 4 release config that build_release.py consumes. Nothing is
derived or patched after the build; there are no separate no-skip or skip
variants any more.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from srwz.daily_test import verify_skip
from srwz.edition import json_bytes
from srwz.release_inputs import copy_file, sha256_file
from verify_editions import verify_batch

ROOT = Path(__file__).resolve().parents[1]
RELEASE_EDITIONS = ('original', 'best', 'sp')


def lock(path: Path) -> dict:
    return {'path': str(path.relative_to(ROOT)), 'size': path.stat().st_size, 'sha256': sha256_file(path)}


def latest_xdelta_contract() -> dict:
    """Reuse the xdelta pin of the newest existing release instead of a hard-coded version."""
    configs = sorted(ROOT.glob('config/release/v*.json'),
                     key=lambda p: tuple(int(x) for x in p.stem[1:].split('.')))
    if not configs:
        raise ValueError('no previous release config to inherit the xdelta pin from')
    return json.loads(configs[-1].read_text(encoding='utf-8'))['xdelta']


def freeze(batch_path: Path, version: str, *, xdelta: dict | None = None) -> Path:
    tag = f'v{version}'
    verification = verify_batch(ROOT, batch_path)
    if set(verification.get('verified_editions', [])) != set(RELEASE_EDITIONS):
        raise ValueError('release requires original, best and sp in one verified batch')
    batch = json.loads(batch_path.read_text(encoding='utf-8'))
    inputs = ROOT / batch['input_snapshot']
    inputs = inputs.parent / 'project'
    badge = json.loads((inputs / 'config/assets/title-menu-zh.json').read_text())['version_badge']
    if badge['text'] != tag:
        raise ValueError(f"title badge is {badge['text']}; rebuild with --release-version {version} before freezing")
    frozen = ROOT / f'build/iso/{tag}'
    evidence = ROOT / f'manifests/releases/{tag}'
    config_path = ROOT / f'config/release/{tag}.json'
    if frozen.exists() or evidence.exists() or config_path.exists():
        raise ValueError('release already exists; refusing to replace frozen artifacts')
    frozen.mkdir(parents=True)
    evidence.mkdir(parents=True)
    validation = {'status': 'edition_build_and_static_readback_passed', 'skip': 'built_in',
                  'verification': verification, 'input_digest': batch['input_digest'],
                  'batch_manifest': str(batch_path.relative_to(ROOT)), 'outputs': {},
                  'readbacks': {}, 'skip_readbacks': {}, 'runtime': 'not_tested'}
    config = {'schema_version': 4, 'version': version, 'tag': tag, 'channel': 'stable', 'skip': 'built_in',
              'validation': f'manifests/releases/{tag}/validation.json', 'editions': {},
              'xdelta': xdelta or latest_xdelta_contract(),
              'output': {'directory': f'build/release/{tag}'}, 'known_limitations': [], 'evidence': []}
    for result in batch['results']:
        edition = result['edition_id']
        print(f'[{edition}] freeze verified image and reread its skip hook', flush=True)
        target = frozen / f'srwz-zh-{tag}-{edition}.iso'
        copy_file(ROOT / result['output']['path'], target)
        target_lock = lock(target)
        if any(target_lock[k] != result['output'][k] for k in ('size', 'sha256')):
            raise ValueError('frozen image identity mismatch')
        proof_path = evidence / f'{edition}-readback.json'
        copy_file(ROOT / result['readback']['path'], proof_path)
        if edition == 'sp':
            # Preserve the independent semantic proof outside disposable build
            # workspaces, retaining its hash binding from the build receipt.
            proof = json.loads(proof_path.read_text(encoding='utf-8'))
            independent = proof['independent_readback']
            independent_path = evidence / 'sp-independent-readback.json'
            copy_file(ROOT / result['workspace'] / independent['path'], independent_path)
            independent_lock = lock(independent_path)
            if independent_lock['sha256'] != independent['sha256']:
                raise ValueError('SP independent readback changed during freeze')
            validation['sp_independent_readback'] = independent_lock
        hook = verify_skip(target, inputs, edition)
        skip_proof = {'schema_version': 1, 'status': 'built_in_skip_hook_readback_passed', 'edition': edition,
                      'iso': target_lock, 'skip_enabled': True, 'battle_square_skip': hook, 'runtime': 'not_tested'}
        skip_path = evidence / f'{edition}-skip-readback.json'
        skip_path.write_bytes(json_bytes(skip_proof))
        validation['outputs'][edition] = target_lock
        validation['readbacks'][edition] = lock(proof_path)
        validation['skip_readbacks'][edition] = lock(skip_path)
        profile_path = f'config/editions/{edition}/edition.json'
        profile = json.loads((ROOT / profile_path).read_text(encoding='utf-8'))
        config['editions'][edition] = {'edition_config': profile_path, 'source_iso': profile['source_iso'],
                                       'target_iso': target_lock, 'patch_filename': f'srwz-zh-{tag}-{edition}.xdelta'}
    (evidence / 'validation.json').write_bytes(json_bytes(validation))
    config['evidence'] = [str(config_path.relative_to(ROOT)), 'config/full-story-components.json',
                          'config/products/special-disc/battle-square-skip.json',
                          *[f'config/editions/{edition}/edition.json' for edition in RELEASE_EDITIONS],
                          'tools/build_release.py', 'tools/freeze_release.py',
                          f'docs/RELEASE_NOTES_V{version}.md',
                          *[str(p.relative_to(ROOT)) for p in sorted(evidence.glob('*.json'))]]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(json_bytes(config))
    return config_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True, help='batch JSON written by build_editions.py')
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.version):
        parser.error('version must be a numeric release version')
    manifest = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    print(freeze(manifest, args.version))


if __name__ == '__main__':
    main()
