"""Bounded caches for repeatable steps in private Traditional SP build trees."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

ENV = 'SRWZ_SP_VIEW_CACHE'


def cache_key(inputs):
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).digest()


def read_entry(path: Path, key: bytes):
    try:
        with path.open('rb') as f:
            checksum, payload = f.read(32), f.read()
    except FileNotFoundError:
        return None
    digest = hashlib.sha256(key)
    digest.update(payload)
    return payload if digest.digest() == checksum else None


def write_entry(path: Path, key: bytes, payload: bytes):
    # One slot per region and product, replaced atomically. A failed or concurrent
    # build cannot pair another input key with this payload.
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(key)
    digest.update(payload)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        try:
            f.write(digest.digest())
            f.write(payload)
            f.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
