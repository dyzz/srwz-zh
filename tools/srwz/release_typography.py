"""Portable final-renderer proof; retain ELF/metrics, never another full ISO."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile
from .iso9660 import member_map, scan_iso9660
from .release_inputs import copy_file
from .typography_iso import verify_iso


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
    return {'input': typography['input'], 'verification': proof,
            'original_elf': lock(elf), 'metrics': lock(metrics)}


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
    temporary_root = root / 'build/iso/.tmp'
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release-typography-', dir=temporary_root) as directory:
        temporary = Path(directory)
        registry = temporary / 'shared/text-layout/proportional-metrics.mjs'
        registry.parent.mkdir(parents=True)
        registry.write_bytes(metrics)
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
