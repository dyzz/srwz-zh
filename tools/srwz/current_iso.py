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


def verify_regional_skip(path: Path, inputs: Path, edition: str, assembly: dict) -> dict:
    """Replay the regional boot patches from DMY against the final widescreen ELF."""
    import hashlib
    import struct
    from zh_hant.assemble_dual import Disc, Elf, SCRATCH_MAX
    contract = (load_json(inputs / 'config/products/special-disc/battle-square-skip.json') if edition == 'sp'
                else load_json(inputs / 'config/full-story-components.json')['battle_square_skip'])
    if contract.get('enabled', True) is not True:
        raise EditionError('regional discs require enabled square skip')
    disc = Disc(path)
    main = disc.read(contract['editions'][edition]['member'])
    dmy = disc.m['DMY/DMY.BIN']
    proofs = {}
    for region in ('sc', 'tw', 'hk'):
        elf = Elf(main)
        if region != 'sc':
            patch = (assembly if region == 'tw' else assembly['hk'])['patch']
            offset, length = patch['lba'] * 2048, patch['bytes']
            if (length < 32 or length > SCRATCH_MAX or length % 4 or offset < dmy.extent_lba * 2048
                    or offset + length > dmy.extent_lba * 2048 + dmy.size):
                raise EditionError('invalid regional patch extent')
            with path.open('rb') as source:
                source.seek(offset)
                data = source.read(length)
            magic, version, maps, count, size, checksum = struct.unpack_from('<4s5I', data)
            body = data[32:]
            if (magic != b'ZHTP' or version != 1 or size != len(body) or count != patch['records']
                    or maps != patch['vmap_rows'] or maps * 12 > size
                    or sum(x[0] for x in struct.iter_unpack('<I', body)) & 0xffffffff != checksum):
                raise EditionError('invalid regional patch header')
            cursor = maps * 12
            for _ in range(count):
                if cursor + 8 > size:
                    raise EditionError('truncated regional patch record')
                address, n = struct.unpack_from('<II', body, cursor)
                cursor += 8
                if not n or cursor + n > size:
                    raise EditionError('invalid regional patch record')
                elf.put(address, body[cursor:cursor + n])
                cursor += (n + 3) & ~3
            if cursor != size:
                raise EditionError('regional patch length mismatch')
        executable = bytes(elf.b)
        proofs[region] = {'sha256': hashlib.sha256(executable).hexdigest(),
                          'skip': verify_battle_square_skip(executable, contract, edition, file_offset=elf.fo)}
    return proofs
