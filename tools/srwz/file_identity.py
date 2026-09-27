"""Hash each physical file identity once; reuse verified digests across build steps.

The build chain hashes the same multi-gigabyte discs many times per run: the
preflight, every private workspace, the ISO builder, the readback verifier and
the publication step all recompute SHA-256 over bytes that nobody changed. This
module keeps the fail-closed checks exactly where they are and only removes the
repeated arithmetic.

A digest is bound to the file identity ``(device, inode, size, mtime_ns,
ctime_ns)`` -- the same binding ``build_iso`` and ``build_text_update_iso``
already used for their ISO receipts. Any in-place write, replace, copy or clone
produces a new identity and is hashed again. A digest is remembered only after
the file proved stable: its mtime is older than two seconds and its identity
did not change while hashing, so a file being written concurrently is never
recorded.

Two layers exist:

* an in-process memo for every file, so one process never hashes the same
  identity twice;
* a small JSON store for files of at least one MiB, so the subprocesses of one
  build (and the next build on the same machine) reuse each other's proofs.

The store lives at ``$SRWZ_FILE_IDENTITY_STORE`` or ``work/cache/file-identity.json``
under this repository. Setting ``SRWZ_REHASH=1`` disables the store, which makes
every process hash every large file again; the in-process memo stays.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
import time

CHUNK_SIZE = 8 * 1024 * 1024
PERSIST_MIN_SIZE = 1024 * 1024
STABLE_AGE_NS = 2_000_000_000
MAX_STORE_ENTRIES = 20000
STORE_SCHEMA_VERSION = 1
ENV_STORE = "SRWZ_FILE_IDENTITY_STORE"
ENV_REHASH = "SRWZ_REHASH"

_LOCK = threading.RLock()
_MEMO: dict[str, dict] = {}
_STORE: dict[str, dict] | None = None
_STORE_PATH: Path | None = None
_STORE_LOADED_FOR: Path | None = None


def identity_key(stat: os.stat_result) -> str:
    return f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"


def store_path() -> Path | None:
    """The persistent store, or None when disabled for this process."""
    if os.environ.get(ENV_REHASH, "") not in ("", "0"):
        return None
    raw = os.environ.get(ENV_STORE)
    if raw is None:
        return Path(__file__).resolve().parents[2] / "work/cache/file-identity.json"
    if not raw.strip():
        return None
    return Path(raw).expanduser().resolve()


def _load_store() -> dict[str, dict]:
    global _STORE, _STORE_LOADED_FOR, _STORE_PATH
    path = store_path()
    if path is None:
        _STORE_PATH = None
        return {}
    if _STORE is not None and _STORE_LOADED_FOR == path:
        return _STORE
    entries: dict[str, dict] = {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and document.get("schema_version") == STORE_SCHEMA_VERSION \
                and isinstance(document.get("entries"), dict):
            entries = {key: value for key, value in document["entries"].items()
                       if isinstance(value, dict) and (
                           isinstance(value.get("sha256"), str)
                           or (isinstance(value.get("ranges"), dict) and value["ranges"]
                               and all(isinstance(span, str) and isinstance(digest, str)
                                       for span, digest in value["ranges"].items())))}
    except (OSError, ValueError):
        entries = {}
    _STORE, _STORE_LOADED_FOR, _STORE_PATH = entries, path, path
    return entries


def _flush_store(new_entries: dict[str, dict]) -> None:
    """Merge into the on-disk store under a lock; never lose another process's proofs."""
    path = _STORE_PATH
    if path is None or not new_entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
                merged = dict(current.get("entries", {})) if isinstance(current, dict) else {}
            except (OSError, ValueError):
                merged = {}
            merged.update(new_entries)
            if len(merged) > MAX_STORE_ENTRIES:
                oldest = sorted(merged, key=lambda key: merged[key].get("seen", 0))
                for key in oldest[: len(merged) - MAX_STORE_ENTRIES]:
                    merged.pop(key, None)
            temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps({"schema_version": STORE_SCHEMA_VERSION, "entries": merged},
                                            sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(path)
            if _STORE is not None:
                _STORE.update(merged)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _lookup(key: str) -> dict | None:
    record = _MEMO.get(key)
    if record is None:
        record = _load_store().get(key)
        if record is not None:
            _MEMO[key] = record
    return record


def _remember(key: str, stat: os.stat_result, record: dict) -> None:
    record["seen"] = int(time.time())
    _MEMO[key] = record
    if stat.st_size >= PERSIST_MIN_SIZE and _STORE_PATH is not None:
        _flush_store({key: record})


def _stable(stat: os.stat_result, path: Path) -> bool:
    """True when the identity survived the hash and the file is not being written."""
    try:
        after = path.stat()
    except OSError:
        return False
    return identity_key(after) == identity_key(stat) and time.time_ns() - stat.st_mtime_ns > STABLE_AGE_NS


def _hash_range(path: Path, offset: int, length: int | None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        if offset:
            source.seek(offset)
        remaining = length
        while remaining is None or remaining:
            chunk = source.read(CHUNK_SIZE if remaining is None else min(remaining, CHUNK_SIZE))
            if not chunk:
                if remaining:
                    raise OSError(f"short read while hashing {path} at {offset}+{length}")
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


def sha256_file(path: Path | str) -> str:
    """SHA-256 of a regular file, computed once per file identity."""
    path = Path(path)
    stat = path.stat()
    key = identity_key(stat)
    with _LOCK:
        record = _lookup(key)
        if record is not None and "sha256" in record:
            return record["sha256"]
    digest = _hash_range(path, 0, None)
    with _LOCK:
        if _stable(stat, path):
            record = _lookup(key) or {}
            record["sha256"] = digest
            _remember(key, stat, record)
    return digest


def sha256_range(path: Path | str, offset: int, length: int) -> str:
    """SHA-256 of ``length`` bytes at ``offset``; ISO members reuse this across steps."""
    path = Path(path)
    stat = path.stat()
    key = identity_key(stat)
    if offset == 0 and length == stat.st_size:
        return sha256_file(path)
    span = f"{offset}:{length}"
    with _LOCK:
        record = _lookup(key)
        if record is not None and span in record.get("ranges", {}):
            return record["ranges"][span]
    digest = _hash_range(path, offset, length)
    with _LOCK:
        if _stable(stat, path):
            record = _lookup(key) or {}
            record.setdefault("ranges", {})[span] = digest
            if "sha256" not in record:
                # Range-only records still need a key; keep them memo/store shaped.
                record.setdefault("partial", True)
            _remember(key, stat, record)
    return digest


def record_clone(source: Path | str, target: Path | str) -> bool:
    """Carry verified digests from ``source`` to a byte-identical clone ``target``.

    Only call this right after a kernel clone (``cp -c``/clonefile), where the
    file system guarantees identical bytes. Returns False when nothing was known
    about the source, in which case the target is simply hashed on first use.
    """
    source, target = Path(source), Path(target)
    with _LOCK:
        known = _lookup(identity_key(source.stat()))
        if known is None or "sha256" not in known:
            return False
        stat = target.stat()
        if stat.st_size != source.stat().st_size:
            return False
        record = {"sha256": known["sha256"], "ranges": dict(known.get("ranges", {}))}
        _remember(identity_key(stat), stat, record)
    return True


def remember_digest(path: Path | str, digest: str) -> None:
    """Record a digest another verified step already computed for this exact file."""
    path = Path(path)
    stat = path.stat()
    with _LOCK:
        if _stable(stat, path):
            record = _lookup(identity_key(stat)) or {}
            record["sha256"] = digest
            _remember(identity_key(stat), stat, record)


def publish_verified(pending: Path | str, target: Path | str, digest: str) -> None:
    """Atomically move a verified file into place and keep its digest bound.

    A rename changes the inode's ctime, so the identity recorded for ``pending``
    would otherwise stop matching and the next reader would hash the multi-GB
    file again. The bytes are unchanged by the rename, which is why the digest
    may be carried over.
    """
    pending, target = Path(pending), Path(target)
    pending.replace(target)
    remember_digest(target, digest)


def forget_all() -> None:
    """Drop the in-process memo (tests and long-lived tools)."""
    global _STORE, _STORE_LOADED_FOR
    with _LOCK:
        _MEMO.clear()
        _STORE, _STORE_LOADED_FOR = None, None
