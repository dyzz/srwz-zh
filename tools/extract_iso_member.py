#!/usr/bin/env python3
"""Extract selected files from the local ISO through 7z.

The command never scans for ROMs and never has a default that extracts the
whole disc. Callers must name every desired ISO member explicitly.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = PROJECT_ROOT / "rom" / "srwz.iso"
DEFAULT_OUTPUT = PROJECT_ROOT / "work" / "disc"


def safe_member_path(member: str) -> PurePosixPath:
    normalized = PurePosixPath(member.replace("\\", "/"))
    if normalized.is_absolute() or not normalized.parts:
        raise ValueError(f"ISO member must be relative: {member!r}")
    if any(part in ("", ".", "..") for part in normalized.parts):
        raise ValueError(f"unsafe ISO member path: {member!r}")
    return normalized


def extract_member(
    iso_path: Path,
    member: str,
    output_root: Path,
    *,
    force: bool = False,
) -> Path:
    relative = safe_member_path(member)
    target = output_root.joinpath(*relative.parts)
    if target.exists() and not force:
        raise FileExistsError(f"refusing to replace existing file: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".partial",
            dir=target.parent,
            delete=False,
        ) as output:
            temporary = Path(output.name)
            process = subprocess.run(
                [
                    "7z",
                    "x",
                    "-so",
                    "-bso0",
                    "-bsp0",
                    str(iso_path),
                    relative.as_posix(),
                ],
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
            )
        if process.returncode != 0:
            error = process.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"7z failed while extracting {relative} "
                f"(exit {process.returncode}): {error}"
            )
        temporary.replace(target)
        return target
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract explicitly selected files from the local SRWZ ISO."
    )
    parser.add_argument("members", nargs="+", help="ISO paths such as DATA/STAGE.BIN")
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    iso_path = args.iso.resolve()
    output_root = args.output.resolve()
    if shutil.which("7z") is None:
        print("error: 7z is required but was not found in PATH", file=sys.stderr)
        return 2
    if not iso_path.is_file():
        print(f"error: ISO not found: {iso_path}", file=sys.stderr)
        return 2

    try:
        for member in args.members:
            target = extract_member(
                iso_path,
                member,
                output_root,
                force=args.force,
            )
            print(target)
    except (FileExistsError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
