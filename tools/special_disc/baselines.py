"""Keep build baselines as verified deltas, materializing disposable ISO inputs."""
from __future__ import annotations
import atexit
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from special_disc import view_cache
from special_disc.source import ROOT, SOURCE_ISO
from srwz.file_identity import remember_digest, sha256_file
from srwz.release_inputs import copy_file

DIRECTORY = ROOT / 'work/build/special-disc/baselines'
ISO_TEMP_DIRECTORY = ROOT / 'build/iso/.tmp/baselines'
ENV_PREFIX = 'SRWZ_SP_BASELINE_'
_CACHE = {}
_TEMPS = []


def digest(path):
    """Identity-cached SHA-256; see srwz.file_identity."""
    return sha256_file(path)


def environment_name(name):
    return ENV_PREFIX + name.upper().replace('-', '_')


def export_baseline(name):
    """Restore once and let every child process of this build reuse the same verified file."""
    restored = baseline_iso(name)
    os.environ[environment_name(name)] = str(restored)
    return restored


def new_temp_iso(label):
    ISO_TEMP_DIRECTORY.mkdir(parents=True, exist_ok=True)
    directory = tempfile.TemporaryDirectory(prefix=f'.{label}-', dir=ISO_TEMP_DIRECTORY)
    _TEMPS.append(directory)
    atexit.register(directory.cleanup)
    return Path(directory.name) / 'temporary.iso'


def xdelta():
    program = shutil.which('xdelta3')
    if not program:
        raise RuntimeError('xdelta3 is required to restore the SP build baseline')
    return program


def freeze_baseline(name, iso, *, source=SOURCE_ISO):
    """Store and roundtrip-check a build input before its full ISO is removed."""
    if name not in ('preview', 'text-canary'):
        raise ValueError('unknown SP baseline')
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    target = DIRECTORY / f'{name}.xdelta'
    temporary = target.with_suffix('.tmp.xdelta')
    if temporary.exists():
        raise ValueError(f'baseline write already pending: {temporary}')
    source_hash, target_hash = digest(source), digest(iso)
    tool = xdelta()
    directory = os.environ.get(view_cache.ENV)
    slot = Path(directory) / f'{name}.delta' if directory else None
    key = view_cache.cache_key([source_hash, target_hash, source.name, iso.name,
                                digest(Path(tool)), os.environ.get('XDELTA', '')]) if slot else None
    cached = view_cache.read_entry(slot, key) if slot else None
    if cached is None:
        subprocess.run([tool, '-e', '-s', str(source), str(iso), str(temporary)], check=True)
        restored = new_temp_iso(f'check-{name}')
        subprocess.run([tool, '-d', '-s', str(source), str(temporary), str(restored)], check=True)
        if digest(restored) != target_hash or restored.stat().st_size != iso.stat().st_size:
            raise ValueError('SP baseline delta roundtrip failed')
        restored.unlink()
        if slot:
            view_cache.write_entry(slot, key, temporary.read_bytes())
    else:
        temporary.write_bytes(cached)
        print(f'[sp-cache] {name}: reused roundtrip-verified delta', flush=True)
    record = dict(schema_version=1, source_sha256=source_hash, iso_sha256=target_hash,
                  iso_size=iso.stat().st_size, patch_sha256=digest(temporary), patch=target.name)
    temporary.replace(target)
    lock = target.with_suffix('.json')
    lock.write_text(json.dumps(record, indent=2) + '\n')
    if directory:
        # Private language-view workspace only. Later independent tools in this capture
        # need the same bytes; snapshot cleanup removes these disposable ISO clones.
        materialized = ISO_TEMP_DIRECTORY / f'verified-{name}.iso'
        copy_file(iso, materialized)
    _CACHE.pop(name, None)
    return lock


def baseline_iso(name):
    """Return a process-local input; automatically remove it when the process exits."""
    if name not in ('preview', 'text-canary'):
        raise ValueError('unknown SP baseline')
    if name in _CACHE:
        return _CACHE[name]
    record = json.loads((DIRECTORY / f'{name}.json').read_text())
    exported = os.environ.get(environment_name(name))
    if exported:
        # A parent build already restored and verified this baseline. The file
        # keeps its exact size and hash; the parent owns its lifetime.
        shared = Path(exported)
        if (not shared.is_file() or shared.stat().st_size != record['iso_size']
                or digest(shared) != record['iso_sha256']):
            raise ValueError('exported SP baseline identity drift')
        _CACHE[name] = shared
        return shared
    if digest(SOURCE_ISO) != record['source_sha256']:
        raise ValueError('SP baseline patch/source hash drift')
    if os.environ.get(view_cache.ENV):
        materialized = ISO_TEMP_DIRECTORY / f'verified-{name}.iso'
        if (materialized.is_file() and materialized.stat().st_size == record['iso_size']
                and digest(materialized) == record['iso_sha256']):
            _CACHE[name] = materialized
            return materialized
    restored = _restore_sparse(name, record)
    if restored is None:
        patch = DIRECTORY / f'{name}.xdelta'
        if digest(patch) != record['patch_sha256']:
            raise ValueError('SP baseline patch/source hash drift')
        restored = new_temp_iso(name)
        subprocess.run([xdelta(), '-d', '-s', str(SOURCE_ISO), str(patch), str(restored)], check=True)
        if restored.stat().st_size != record['iso_size'] or digest(restored) != record['iso_sha256']:
            raise ValueError('restored SP baseline identity drift')
        _record_sparse(name, record, restored)
    # The writer has finished and the hash was just verified against the lock,
    # so children of this build may reuse it instead of reading 3.7 GB again.
    remember_digest(restored, record['iso_sha256'], settled=True)
    _CACHE[name] = restored
    return restored


SPARSE_BLOCK = 64 * 1024
_READ_BLOCK = 4 * 1024 * 1024


def _sparse_paths(name):
    return DIRECTORY / f'{name}.sparse.json', DIRECTORY / f'{name}.sparse.bin'


def _restore_sparse(name, record):
    """Clone the source disc and rewrite only the recorded differing spans.

    The sparse sidecar is derived from the locked xdelta once; the restored
    image must still hash to the locked identity, otherwise the sidecar is
    discarded and the xdelta path runs.
    """
    meta_path, data_path = _sparse_paths(name)
    if not meta_path.is_file() or not data_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text())
    except ValueError:
        return None
    if (meta.get('schema_version') != 1 or meta.get('iso_sha256') != record['iso_sha256']
            or meta.get('source_sha256') != record['source_sha256'] or meta.get('iso_size') != record['iso_size']
            or digest(data_path) != meta.get('data_sha256')):
        return None
    restored = new_temp_iso(name)
    copy_file(SOURCE_ISO, restored)
    with restored.open('r+b') as image, data_path.open('rb') as data:
        image.truncate(record['iso_size'])
        for offset, length in meta['spans']:
            image.seek(offset)
            image.write(data.read(length))
    if restored.stat().st_size != record['iso_size'] or digest(restored) != record['iso_sha256']:
        restored.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        data_path.unlink(missing_ok=True)
        return None
    return restored


def _record_sparse(name, record, restored):
    """Store the byte ranges where the verified baseline differs from the source disc."""
    meta_path, data_path = _sparse_paths(name)
    spans, pending = [], data_path.with_suffix('.tmp.bin')
    with SOURCE_ISO.open('rb') as left, restored.open('rb') as right, pending.open('wb') as out:
        offset = 0
        while True:
            a, b = left.read(_READ_BLOCK), right.read(_READ_BLOCK)
            if not a and not b:
                break
            if a != b:
                for at in range(0, max(len(a), len(b)), SPARSE_BLOCK):
                    piece = b[at:at + SPARSE_BLOCK]
                    if piece != a[at:at + SPARSE_BLOCK] and piece:
                        if spans and spans[-1][0] + spans[-1][1] == offset + at:
                            spans[-1][1] += len(piece)
                        else:
                            spans.append([offset + at, len(piece)])
                        out.write(piece)
            offset += max(len(a), len(b))
    pending.replace(data_path)
    meta = dict(schema_version=1, iso_sha256=record['iso_sha256'], iso_size=record['iso_size'],
                source_sha256=record['source_sha256'], data_sha256=digest(data_path),
                span_count=len(spans), data_bytes=sum(length for _, length in spans), spans=spans)
    meta_path.write_text(json.dumps(meta) + '\n')
