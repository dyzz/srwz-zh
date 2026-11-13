#!/usr/bin/env python3
"""Fetch the pinned PS2 Tremor source into the ignored work/ tree.

The music player links against Tremor (Xiph's fixed-point Vorbis decoder) in
the PS2 flavour published as citronalco/ps2-libtremor.  Tremor is not vendored
here: this script clones the pinned commit so `--tremor-source` has a
reproducible default instead of a path that only exists on one machine.

    python3 tools/special_disc/vocal_bgm/bootstrap_tremor.py

Prints the checkout path on success; `--print-path` prints it without
network access when the checkout is already present and verified.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCK_FILE = Path(__file__).resolve().parent / "upstream.lock.json"


class BootstrapError(RuntimeError):
    """The pinned Tremor source could not be prepared exactly."""


def load_pin() -> dict:
    with LOCK_FILE.open(encoding="utf-8") as source:
        pin = json.load(source).get("tremor", {})
    for key in ("repository", "commit", "source_dir"):
        if not pin.get(key):
            raise BootstrapError(f"upstream.lock.json: tremor is missing {key!r}")
    if len(pin["commit"]) != 40 or not all(
        c in "0123456789abcdef" for c in pin["commit"]
    ):
        raise BootstrapError("commit must be a full 40-character SHA-1")
    return pin


def checkout_dir(pin: dict) -> Path:
    path = (PROJECT_ROOT / pin["source_dir"]).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise BootstrapError(
            f"source_dir escapes the project root: {pin['source_dir']}"
        ) from exc
    return path


def run(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        [str(part) for part in command],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def head_commit(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    try:
        return run(["git", "rev-parse", "HEAD"], cwd=path)
    except subprocess.CalledProcessError:
        return None


def is_clean(path: Path) -> bool:
    return run(["git", "status", "--porcelain"], cwd=path) == ""


def verify(path: Path, pin: dict) -> None:
    """Confirm the checkout is exactly the pinned, unmodified commit."""
    head = head_commit(path)
    if head != pin["commit"]:
        raise BootstrapError(
            f"{path} is at {head or 'no commit'}, expected {pin['commit']}"
        )
    if not is_clean(path):
        raise BootstrapError(f"{path} has local modifications")
    missing = [name for name in pin.get("expect_files", []) if not (path / name).is_file()]
    if missing:
        raise BootstrapError(f"{path} is missing {', '.join(missing)}")


def fetch(path: Path, pin: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        if path.exists() and any(path.iterdir()):
            raise BootstrapError(f"{path} exists and is not a git checkout")
        print(f"[..] cloning {pin['repository']}")
        run(["git", "clone", "--quiet", pin["repository"], path])
    run(["git", "fetch", "--quiet", "origin", pin["commit"]], cwd=path)
    run(["git", "checkout", "--quiet", "--force", pin["commit"]], cwd=path)
    run(["git", "clean", "-qfdx"], cwd=path)


def ensure_tremor(*, offline: bool = False) -> Path:
    """Return the pinned Tremor checkout, fetching it unless offline."""
    pin = load_pin()
    path = checkout_dir(pin)
    try:
        verify(path, pin)
        return path
    except BootstrapError:
        if offline:
            raise
    fetch(path, pin)
    verify(path, pin)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-path",
        action="store_true",
        help="verify an existing checkout and print it, without network access",
    )
    args = parser.parse_args()
    try:
        path = ensure_tremor(offline=args.print_path)
    except BootstrapError as error:
        print(f"[!!] {error}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as error:
        print(f"[!!] {' '.join(error.cmd)} failed:\n{error.stderr}", file=sys.stderr)
        return 2
    if not args.print_path:
        pin = load_pin()
        print(f"[OK] Tremor at pinned commit {pin['commit']}")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
