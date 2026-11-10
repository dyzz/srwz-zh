"""Portable final-renderer proof; retain ELF/metrics, never another full ISO."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile
from .iso9660 import member_map, scan_iso9660
from .release_inputs import copy_file
from .typography_iso import verify_iso
from .ui_battle_select import CONFIG as BATTLE_SELECT, SP_CONFIG as SP_BATTLE_SELECT


def checked(root, lock):
    path = (root / lock['path']).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('release typography path escapes root')
    raw = path.read_bytes()
    if len(raw) != lock['size'] or hashlib.sha256(raw).hexdigest() != lock['sha256']:
        raise ValueError('release typography evidence drift')
    return raw


def freeze_typography(root, inputs, result, evidence, lock):
    typography = result['typography']
    source = root / result['workspace'] / typography['input']['path']
    proof = typography['verification']
    member = member_map(scan_iso9660(source))[proof['member']]
    with source.open('rb') as stream:
        stream.seek(member.extent_lba * 2048)
        raw = stream.read(member.size)
    elf = evidence / (result['edition_id'] + '-pre-typography.elf')
    elf.write_bytes(raw)
    metrics = evidence / 'proportional-metrics.mjs'
    metrics.write_bytes((inputs / 'shared/text-layout/proportional-metrics.mjs').read_bytes())
    frozen = {'input': typography['input'], 'verification': proof,
              'original_elf': lock(elf), 'metrics': lock(metrics)}
    if titles := proof['payload'].get('battle_select_titles'):
        path = SP_BATTLE_SELECT if result['edition_id'] == 'sp' else BATTLE_SELECT
        raw = (inputs / path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != titles['config_sha256']:
            raise ValueError('release battle SELECT title contract drift')
        contract = evidence / f"{result['edition_id']}-battle-select.json"
        contract.write_bytes(raw)
        frozen['battle_select'] = lock(contract)
    return frozen


@contextmanager
def verified_typography_input(root, target, edition, typography):
    """Reconstruct the pre-renderer image temporarily and reprove the full transform."""
    root = Path(root).resolve()
    proof = typography['verification']
    if (proof['source_sha256'] != typography['input']['sha256'] or
            proof['size'] != typography['input']['size']):
        raise ValueError('release typography input binding mismatch')
    raw = checked(root, typography['original_elf'])
    metrics = checked(root, typography['metrics'])
    titles = proof.get('payload', {}).get('battle_select_titles')
    temporary_root = root / 'build/iso/.tmp'
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release-typography-', dir=temporary_root) as directory:
        temporary = Path(directory)
        registry = temporary / 'shared/text-layout/proportional-metrics.mjs'
        registry.parent.mkdir(parents=True)
        registry.write_bytes(metrics)
        if titles:
            contract = checked(root, typography['battle_select'])
            if hashlib.sha256(contract).hexdigest() != titles['config_sha256']:
                raise ValueError('release battle SELECT title contract drift')
            config_path = temporary / (SP_BATTLE_SELECT if edition == 'sp' else BATTLE_SELECT)
            config_path.parent.mkdir(parents=True)
            config_path.write_bytes(contract)
        source = temporary / 'pre-typography.iso'
        copy_file(target, source)
        member = member_map(scan_iso9660(source))[proof['member']]
        if len(raw) != member.size:
            raise ValueError('release typography ELF size mismatch')
        with source.open('r+b') as stream:
            stream.seek(member.extent_lba * 2048)
            stream.write(raw)
        verify_iso(temporary, edition, source, target, proof)
        yield source
