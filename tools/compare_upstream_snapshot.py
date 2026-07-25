#!/usr/bin/env python3
"""Compare the vendored Python snapshot with a local upstream checkout."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = PROJECT_ROOT / "vendor" / "upstream-python"
DEFAULT_UPSTREAM = PROJECT_ROOT.parent
DEFAULT_LOCK = PROJECT_ROOT / "config" / "upstream.lock.json"
SELECTION_NAME = "selection.json"
SNAPSHOT_ONLY = {Path("README.md"), Path(SELECTION_NAME)}


def is_tracked_snapshot_file(path: Path, snapshot: Path) -> bool:
    relative = path.relative_to(snapshot)
    return (
        path.is_file()
        and relative not in SNAPSHOT_ONLY
        and "__pycache__" not in relative.parts
        and path.suffix != ".pyc"
    )


def current_commit(repository: Path) -> str | None:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return process.stdout.strip() if process.returncode == 0 else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare vendored upstream Python files byte-for-byte."
    )
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--upstream", type=Path, default=DEFAULT_UPSTREAM)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = args.snapshot.resolve()
    upstream = args.upstream.resolve()
    lock_path = args.lock.resolve()

    if not snapshot.is_dir():
        print(f"error: snapshot not found: {snapshot}", file=sys.stderr)
        return 2
    if not upstream.is_dir():
        print(f"error: upstream checkout not found: {upstream}", file=sys.stderr)
        return 2

    with lock_path.open(encoding="utf-8") as source:
        lock = json.load(source)
    pinned_commit = lock["commit"]

    selection_path = snapshot / SELECTION_NAME
    if not selection_path.is_file():
        print(f"error: selection manifest not found: {selection_path}", file=sys.stderr)
        return 2
    with selection_path.open(encoding="utf-8") as source:
        selection = json.load(source)
    if selection.get("upstream_commit") != pinned_commit:
        print(
            "error: selection manifest and upstream lock use different commits",
            file=sys.stderr,
        )
        return 2

    selected_paths = {
        Path(item["path"]) for item in selection.get("selected_files", [])
    }
    if not selected_paths:
        print("error: selection manifest contains no files", file=sys.stderr)
        return 2

    checkout_commit = current_commit(upstream)
    if checkout_commit != pinned_commit:
        print(
            f"[WARN] upstream HEAD is {checkout_commit or 'unknown'}, "
            f"snapshot is pinned to {pinned_commit}"
        )

    snapshot_paths = {
        path.relative_to(snapshot)
        for path in snapshot.rglob("*")
        if is_tracked_snapshot_file(path, snapshot)
    }
    undeclared = sorted(snapshot_paths - selected_paths)
    absent = sorted(selected_paths - snapshot_paths)

    identical = 0
    modified: list[Path] = []
    missing: list[Path] = []
    for relative in sorted(selected_paths & snapshot_paths):
        snapshot_file = snapshot / relative
        upstream_file = upstream / relative
        if not upstream_file.is_file():
            missing.append(relative)
        elif snapshot_file.read_bytes() != upstream_file.read_bytes():
            modified.append(relative)
        else:
            identical += 1

    print(f"selected: {len(selected_paths)}")
    print(f"identical: {identical}")
    for relative in absent:
        print(f"missing snapshot: {relative}")
    for relative in undeclared:
        print(f"undeclared snapshot file: {relative}")
    for relative in missing:
        print(f"missing upstream: {relative}")
    for relative in modified:
        print(f"modified: {relative}")

    if absent or undeclared or missing or modified:
        return 1
    print("Upstream Python snapshot matches the local checkout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
