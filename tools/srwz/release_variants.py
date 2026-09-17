"""Derive and independently verify optional skip ISOs from validated base ISOs."""
from __future__ import annotations

from pathlib import Path

from .battle_square_skip import apply_battle_square_skip, verify_battle_square_skip
from .edition import EditionError
from .iso9660 import member_map, scan_iso9660
from .release_inputs import copy_file, sha256_file


def verify_variant(base: Path, variant: Path, contract: dict, edition: str) -> dict:
    base_members = member_map(scan_iso9660(base))
    variant_members = member_map(scan_iso9660(variant))
    layout = lambda rows: [(n, m.extent_lba, m.size) for n, m in rows.items()]
    if base.stat().st_size != variant.stat().st_size or layout(base_members) != layout(variant_members):
        raise EditionError('skip variant disc layout drift')
    member = contract['editions'][edition]['member']
    row = base_members[member]
    offset = row.extent_lba * 2048
    with base.open('rb') as a, variant.open('rb') as b:
        a.seek(offset); b.seek(offset)
        original = a.read(row.size)
        verify_battle_square_skip(original, {**contract, 'enabled': False}, edition)
        expected, _ = apply_battle_square_skip(original, {**contract, 'enabled': True}, edition)
        actual = b.read(row.size)
        if actual != expected:
            raise EditionError('skip variant executable differs outside exact hook transformation')
        hook = verify_battle_square_skip(actual, {**contract, 'enabled': True}, edition)
        for lo, hi in ((0, offset), (offset + row.size, base.stat().st_size)):
            a.seek(lo); b.seek(lo)
            remaining = hi-lo
            while remaining:
                size = min(8 << 20, remaining)
                if a.read(size) != b.read(size):
                    raise EditionError('skip variant changed non-executable ISO bytes')
                remaining -= size
    return {'status': 'skip_variant_exact_transform_readback_passed', 'edition': edition,
            'base_sha256': sha256_file(base), 'sha256': sha256_file(variant),
            'size': variant.stat().st_size, 'only_declared_skip_changes': True,
            'native_member_sizes_and_lbas_preserved': True, 'hook': hook,
            'runtime': 'not_tested'}


def build_variant(base: Path, target: Path, contract: dict, edition: str) -> dict:
    if target.exists():
        raise EditionError(f'refusing to overwrite frozen variant: {target}')
    row = member_map(scan_iso9660(base))[contract['editions'][edition]['member']]
    with base.open('rb') as stream:
        stream.seek(row.extent_lba * 2048)
        original = stream.read(row.size)
    verify_battle_square_skip(original, {**contract, 'enabled': False}, edition)
    patched, _ = apply_battle_square_skip(original, {**contract, 'enabled': True}, edition)
    temporary = target.with_suffix('.iso.tmp')
    copy_file(base, temporary)
    with temporary.open('r+b') as stream:
        stream.seek(row.extent_lba * 2048)
        stream.write(patched)
    proof = verify_variant(base, temporary, contract, edition)
    temporary.replace(target)
    return proof
