#!/usr/bin/env python3

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = PROJECT_ROOT / "rom" / "srwz.iso"
DEFAULT_MANIFEST = PROJECT_ROOT / "manifests" / "original-disc.json"
CHUNK_SIZE = 4 * 1024 * 1024


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def sha256_iso_member(iso_path: Path, member: str) -> tuple[int, str]:
    process = subprocess.Popen(
        [
            "7z",
            "x",
            "-so",
            "-bso0",
            "-bsp0",
            str(iso_path),
            member,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None

    digest = hashlib.sha256()
    size = 0
    while chunk := process.stdout.read(CHUNK_SIZE):
        size += len(chunk)
        digest.update(chunk)

    error = process.stderr.read().decode("utf-8", errors="replace").strip()
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(
            f"7z failed while reading {member} (exit {return_code}): {error}"
        )

    return size, digest.hexdigest()


def check_item(label: str, actual: tuple[int, str], expected: dict) -> bool:
    actual_size, actual_hash = actual
    expected_size = expected["size"]
    expected_hash = expected["sha256"]
    matches = actual_size == expected_size and actual_hash == expected_hash
    status = "OK" if matches else "FAIL"
    print(f"[{status}] {label}")
    if not matches:
        print(f"  size:   {actual_size} (expected {expected_size})")
        print(f"  sha256: {actual_hash}")
        print(f"  expect: {expected_hash}")
    return matches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the local original SRWZ ISO without extracting it."
    )
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--skip-full-iso",
        action="store_true",
        help="Verify only key files inside the ISO.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    iso_path = args.iso.resolve()
    manifest_path = args.manifest.resolve()

    if shutil.which("7z") is None:
        print("error: 7z is required but was not found in PATH", file=sys.stderr)
        return 2
    if not iso_path.is_file():
        print(f"error: ISO not found: {iso_path}", file=sys.stderr)
        return 2
    if not manifest_path.is_file():
        print(f"error: manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    with manifest_path.open(encoding="utf-8") as source:
        manifest = json.load(source)

    success = True
    disc = manifest["disc"]
    if not args.skip_full_iso:
        success &= check_item(
            iso_path.name,
            sha256_file(iso_path),
            {"size": disc["file_size"], "sha256": disc["sha256"]},
        )

    for item in manifest["key_files"]:
        success &= check_item(
            item["path"],
            sha256_iso_member(iso_path, item["path"]),
            item,
        )

    if success:
        print("Original disc baseline verified.")
        return 0

    print("Original disc baseline verification failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
