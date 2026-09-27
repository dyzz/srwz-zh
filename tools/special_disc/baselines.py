"""Keep build baselines as verified deltas, materializing disposable ISO inputs."""
from __future__ import annotations
import atexit
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from special_disc.source import ROOT, SOURCE_ISO
from srwz.file_identity import sha256_file

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
    subprocess.run([xdelta(), '-e', '-s', str(source), str(iso), str(temporary)], check=True)
    record = dict(schema_version=1, source_sha256=digest(source), iso_sha256=digest(iso),
                  iso_size=iso.stat().st_size, patch_sha256=digest(temporary), patch=target.name)
    restored = new_temp_iso(f'check-{name}')
    subprocess.run([xdelta(), '-d', '-s', str(source), str(temporary), str(restored)], check=True)
    if digest(restored) != record['iso_sha256'] or restored.stat().st_size != record['iso_size']:
        raise ValueError('SP baseline delta roundtrip failed')
    restored.unlink()
    temporary.replace(target)
    lock = target.with_suffix('.json')
    lock.write_text(json.dumps(record, indent=2) + '\n')
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
    patch = DIRECTORY / f'{name}.xdelta'
    if digest(patch) != record['patch_sha256'] or digest(SOURCE_ISO) != record['source_sha256']:
        raise ValueError('SP baseline patch/source hash drift')
    restored = new_temp_iso(name)
    subprocess.run([xdelta(), '-d', '-s', str(SOURCE_ISO), str(patch), str(restored)], check=True)
    if restored.stat().st_size != record['iso_size'] or digest(restored) != record['iso_sha256']:
        raise ValueError('restored SP baseline identity drift')
    _CACHE[name] = restored
    return restored
