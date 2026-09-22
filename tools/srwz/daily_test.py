"""Publish verified current ISOs for daily testing without deriving new bytes."""
from pathlib import Path

from .battle_square_skip import verify_battle_square_skip
from .edition import EditionError, load_json, project_path
from .iso9660 import member_map, scan_iso9660
from .release_inputs import copy_file, sha256_file


def verify_daily_test(root: Path, inputs: Path, result: dict, identity: dict) -> dict:
    edition = result['edition_id']
    expected_path = f'build/iso/daily-test/current-{edition}-skip.iso'
    if identity['path'] != expected_path:
        raise EditionError('daily-test edition path mismatch')
    path = project_path(root, identity['path'], 'build/iso/daily-test')
    if (identity['size'] != result['output']['size']
            or identity['sha256'] != result['output']['sha256']
            or path.stat().st_size != identity['size']
            or sha256_file(path) != identity['sha256']):
        raise EditionError('daily-test copy differs from validated current ISO')
    return verify_skip(path, inputs, edition)


def verify_skip(path: Path, inputs: Path, edition: str) -> dict:
    if edition == 'sp':
        contract = load_json(inputs / 'config/products/special-disc/battle-square-skip.json')
    else:
        contract = load_json(inputs / 'config/full-story-components.json')['battle_square_skip']
    if contract.get('enabled', True) is not True:
        raise EditionError('daily-test requires square skip enabled in build inputs')
    member = member_map(scan_iso9660(path))[contract['editions'][edition]['member']]
    with path.open('rb') as source:
        source.seek(member.extent_lba * 2048)
        executable = source.read(member.size)
    return verify_battle_square_skip(executable, contract, edition)


def publish_daily_test(root: Path, inputs: Path, result: dict) -> dict:
    edition = result['edition_id']
    if edition not in ('original', 'best', 'sp'):
        raise EditionError(f'unknown daily-test edition: {edition}')
    relative = f'build/iso/daily-test/current-{edition}-skip.iso'
    # Do not follow a stale symlink into a source, release or other edition.
    target = root / relative
    if target.resolve() != target or target.with_suffix('.iso.tmp').resolve() != target.with_suffix('.iso.tmp'):
        raise EditionError('daily-test output must not alias another path')
    source = project_path(root, result['output']['path'], 'build/iso')
    pending = target.with_suffix('.iso.tmp')
    try:
        copy_file(source, pending)
        if (pending.stat().st_size != result['output']['size']
                or sha256_file(pending) != result['output']['sha256']):
            raise EditionError('daily-test copy differs from validated current ISO')
        hook = verify_skip(pending, inputs, edition)
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return {
        'path': relative, 'size': result['output']['size'], 'sha256': result['output']['sha256'],
        'status': 'exact_current_copy_and_skip_readback_passed',
        'skip_enabled': True, 'battle_square_skip': hook, 'runtime': 'not_tested',
    }
