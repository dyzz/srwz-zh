"""Content-addressed cache helpers for previously validated build results."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CACHE_SCHEMA_VERSION = 1
HASH_CHUNK_SIZE = 4 * 1024 * 1024
IGNORED_TREE_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "target",
}
IGNORED_TREE_NAMES = {".DS_Store"}


@dataclass(frozen=True)
class CacheValidation:
    hit: bool
    reason: str
    checked_file_count: int = 0
    checked_byte_count: int = 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _project_path(project_root: Path, path: Path | str) -> Path:
    root = project_root.resolve()
    candidate = Path(path)
    candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"cache path escapes project root: {path}") from error
    return candidate


def relative_path(project_root: Path, path: Path | str) -> str:
    return _project_path(project_root, path).relative_to(
        project_root.resolve()
    ).as_posix()


def collect_tree_paths(
    project_root: Path,
    roots: Iterable[Path | str],
) -> set[Path]:
    """Collect every regular build-definition file under the selected roots."""

    paths: set[Path] = set()
    for raw_root in roots:
        root = _project_path(project_root, raw_root)
        if root.is_file():
            paths.add(root)
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if any(part in IGNORED_TREE_PARTS for part in path.parts):
                continue
            if path.name in IGNORED_TREE_NAMES:
                continue
            if path.is_file():
                paths.add(path.resolve())
    return paths


def collect_locked_paths(project_root: Path, document: object) -> set[Path]:
    """Find project files referenced by nested size/SHA-256 lock objects."""

    paths: set[Path] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            raw_path = value.get("path")
            size = value.get("size")
            sha256 = value.get("sha256")
            if (
                isinstance(raw_path, str)
                and raw_path
                and isinstance(size, int)
                and not isinstance(size, bool)
                and isinstance(sha256, str)
                and len(sha256) == 64
            ):
                paths.add(_project_path(project_root, raw_path))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(document)
    return paths


def _file_lock(project_root: Path, path: Path) -> dict:
    path = _project_path(project_root, path)
    stat = path.stat()
    return {
        "path": relative_path(project_root, path),
        "size": stat.st_size,
        "sha256": sha256_file(path),
    }


def write_verified_cache(
    *,
    project_root: Path,
    cache_path: Path,
    kind: str,
    paths: Iterable[Path],
    metadata: dict | None = None,
) -> dict:
    """Atomically record the exact files covered by a successful validation."""

    root = project_root.resolve()
    resolved_paths = {
        _project_path(root, path)
        for path in paths
    }
    if not resolved_paths:
        raise ValueError("verified cache inventory is empty")
    missing = [path for path in resolved_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"verified cache input is missing: {missing[0]}")
    locks = [
        _file_lock(root, path)
        for path in sorted(
            resolved_paths,
            key=lambda item: item.relative_to(root).as_posix(),
        )
    ]
    document = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "status": "validated_file_set_cached",
        "kind": kind,
        "metadata": metadata or {},
        "file_count": len(locks),
        "byte_count": sum(lock["size"] for lock in locks),
        "files": locks,
    }
    target = _project_path(root, cache_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return document


def validate_verified_cache(
    *,
    project_root: Path,
    cache_path: Path,
    kind: str,
    paths: Iterable[Path],
    metadata: dict | None = None,
) -> CacheValidation:
    """Rehash the current inventory and reuse only an exact validated match."""

    root = project_root.resolve()
    target = _project_path(root, cache_path)
    if not target.is_file():
        return CacheValidation(False, "cache file is missing")
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CacheValidation(False, "cache file is unreadable")
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != CACHE_SCHEMA_VERSION
        or document.get("status") != "validated_file_set_cached"
        or document.get("kind") != kind
        or document.get("metadata") != (metadata or {})
    ):
        return CacheValidation(False, "cache identity changed")
    locks = document.get("files")
    if not isinstance(locks, list):
        return CacheValidation(False, "cache file inventory is malformed")
    try:
        current_paths = {
            relative_path(root, path)
            for path in paths
        }
    except ValueError as error:
        return CacheValidation(False, str(error))
    cached_paths = {
        lock.get("path")
        for lock in locks
        if isinstance(lock, dict) and isinstance(lock.get("path"), str)
    }
    if (
        len(cached_paths) != len(locks)
        or cached_paths != current_paths
        or document.get("file_count") != len(locks)
    ):
        return CacheValidation(False, "cache file inventory changed")

    checked_bytes = 0
    # Small build definitions and receipts usually change more often than ISO
    # images. Check them first so a normal edit invalidates the cache without
    # needlessly hashing multi-gigabyte outputs.
    for lock in sorted(
        locks,
        key=lambda item: (
            item.get("size", 1 << 63) if isinstance(item, dict) else 1 << 63,
            item.get("path", "") if isinstance(item, dict) else "",
        ),
    ):
        raw_path = lock.get("path")
        size = lock.get("size")
        sha256 = lock.get("sha256")
        if (
            not isinstance(raw_path, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not isinstance(sha256, str)
            or len(sha256) != 64
        ):
            return CacheValidation(False, "cache file lock is malformed")
        try:
            path = _project_path(root, raw_path)
            stat = path.stat()
        except (OSError, ValueError):
            return CacheValidation(False, f"cached file is missing: {raw_path}")
        if not path.is_file() or stat.st_size != size:
            return CacheValidation(False, f"cached file size changed: {raw_path}")
        if sha256_file(path) != sha256:
            return CacheValidation(False, f"cached file content changed: {raw_path}")
        checked_bytes += size
    if document.get("byte_count") != checked_bytes:
        return CacheValidation(False, "cache byte count changed")
    return CacheValidation(
        True,
        "all cached files match",
        checked_file_count=len(locks),
        checked_byte_count=checked_bytes,
    )
