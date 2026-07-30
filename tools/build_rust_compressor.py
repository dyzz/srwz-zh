#!/usr/bin/env python3
"""Build the repository-owned clean-room Rust SRWZ compressor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from srwz.diagnostics import require_work_output


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
CRATE_ROOT = PROJECT_ROOT / "tools/native/srwz-codec-rs"
OUTPUT_ROOT = WORK_ROOT / "toolchain/srwz-compressor-rs"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cargo = shutil.which(args.cargo)
    if cargo is None:
        raise SystemExit(f"Cargo not found: {args.cargo}")
    rustc = shutil.which("rustc")
    if rustc is None:
        raise SystemExit("rustc not found")

    output_root = require_work_output(OUTPUT_ROOT.resolve(), WORK_ROOT)
    target_root = output_root / "target"
    binary = target_root / "release/srwz-compress"
    report = output_root / "build.json"
    if (binary.exists() or report.exists()) and not args.force:
        raise SystemExit(f"output exists; use --force: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    command = [
        cargo,
        "build",
        "--release",
        "--locked",
        "--manifest-path",
        str(CRATE_ROOT / "Cargo.toml"),
    ]
    environment = os.environ.copy()
    environment["CARGO_TARGET_DIR"] = str(target_root)
    subprocess.run(
        command,
        check=True,
        cwd=PROJECT_ROOT,
        env=environment,
    )
    if not binary.is_file():
        raise SystemExit(f"Cargo did not produce expected binary: {binary}")

    source_paths = [
        CRATE_ROOT / "Cargo.toml",
        CRATE_ROOT / "Cargo.lock",
        CRATE_ROOT / "src/lib.rs",
        CRATE_ROOT / "src/main.rs",
    ]
    document = {
        "schema_version": 1,
        "implementation": "clean-room Rust SRWZ compressor",
        "sources": [
            {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in source_paths
        ],
        "toolchain": {
            "cargo_path": cargo,
            "cargo_version": subprocess.run(
                [cargo, "--version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
            "rustc_version": subprocess.run(
                [rustc, "--version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
        },
        "binary": {
            "path": str(binary.relative_to(PROJECT_ROOT)),
            "size": binary.stat().st_size,
            "sha256": sha256_file(binary),
        },
    }
    report.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Rust compressor: {binary}")
    print(f"sha256: {document['binary']['sha256']}")
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
