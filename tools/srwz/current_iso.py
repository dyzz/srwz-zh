"""Verify default square skip directly in a native current edition ISO."""
from pathlib import Path

from .battle_square_skip import verify_battle_square_skip
from .edition import EditionError, load_json
from .iso9660 import member_map, scan_iso9660


def verify_skip(path: Path, inputs: Path, edition: str) -> dict:
    if edition == 'sp':
        contract = load_json(inputs / 'config/products/special-disc/battle-square-skip.json')
    else:
        contract = load_json(inputs / 'config/full-story-components.json')['battle_square_skip']
    if contract.get('enabled', True) is not True:
        raise EditionError('current ISO requires square skip enabled in build inputs')
    member = member_map(scan_iso9660(path))[contract['editions'][edition]['member']]
    with path.open('rb') as source:
        source.seek(member.extent_lba * 2048)
        executable = source.read(member.size)
    return verify_battle_square_skip(executable, contract, edition)
