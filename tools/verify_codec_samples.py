#!/usr/bin/env python3
"""Verify local ignored codec samples against committed size/hash metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "manifests" / "codec-samples.json"
CHUNK_SIZE = 4 * 1024 * 1024


def hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def check_file(path: Path, expected_size: int, expected_sha256: str) -> bool:
    if not path.is_file():
        print(f"[MISSING] {path}")
        return False
    actual_size, actual_sha256 = hash_file(path)
    matches = actual_size == expected_size and actual_sha256 == expected_sha256
    print(f"[{'OK' if matches else 'FAIL'}] {path}")
    if not matches:
        print(f"  size:   {actual_size} (expected {expected_size})")
        print(f"  sha256: {actual_sha256}")
        print(f"  expect: {expected_sha256}")
    return matches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify ignored SRWZ codec fixtures without decoding them."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    if not manifest_path.is_file():
        print(f"error: manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    with manifest_path.open(encoding="utf-8") as source:
        manifest = json.load(source)

    archive_path = PROJECT_ROOT / manifest["local_paths"]["archive"]
    archive = manifest["archive"]
    success = check_file(archive_path, archive["size"], archive["sha256"])

    chunk_root = PROJECT_ROOT / manifest["local_paths"]["chunks"]
    for sample in manifest["samples"]:
        path = chunk_root / f"{sample['index']:03d}.bin"
        success &= check_file(path, sample["size"], sample["sha256"])

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
