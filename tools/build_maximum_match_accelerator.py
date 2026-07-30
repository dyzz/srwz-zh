#!/usr/bin/env python3
"""Build the optional native accelerator for maximum match discovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path

from srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
SOURCE = PROJECT_ROOT / "tools/native/srwz_maximum_match.c"
OUTPUT_ROOT = WORK_ROOT / "toolchain/srwz-maximum-match"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cc", default="clang")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    compiler = shutil.which(args.cc)
    if compiler is None:
        raise SystemExit(f"C compiler not found: {args.cc}")
    system = platform.system()
    if system == "Darwin":
        filename = "libsrwz_maximum_match.dylib"
        link_flags = ["-dynamiclib"]
    elif system == "Linux":
        filename = "libsrwz_maximum_match.so"
        link_flags = ["-shared", "-fPIC"]
    else:
        raise SystemExit(f"unsupported host for accelerator: {system}")

    output_root = require_work_output(OUTPUT_ROOT.resolve(), WORK_ROOT)
    library = output_root / filename
    report = output_root / "build.json"
    if (library.exists() or report.exists()) and not args.force:
        raise SystemExit(f"output exists; use --force: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    command = [
        compiler,
        "-std=c11",
        "-O3",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pthread",
        *link_flags,
        str(SOURCE),
        "-o",
        str(library),
    ]
    subprocess.run(command, check=True, cwd=PROJECT_ROOT)
    document = {
        "schema_version": 1,
        "source": {
            "path": str(SOURCE.relative_to(PROJECT_ROOT)),
            "sha256": sha256_file(SOURCE),
        },
        "compiler": {
            "path": compiler,
            "version": subprocess.run(
                [compiler, "--version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()[0],
        },
        "command": [
            (
                str(Path(value).resolve().relative_to(PROJECT_ROOT))
                if value.startswith(str(PROJECT_ROOT))
                else value
            )
            for value in command
        ],
        "library": {
            "path": str(library.relative_to(PROJECT_ROOT)),
            "size": library.stat().st_size,
            "sha256": sha256_file(library),
        },
    }
    report.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"maximum match accelerator: {library}")
    print(f"sha256: {document['library']['sha256']}")
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
