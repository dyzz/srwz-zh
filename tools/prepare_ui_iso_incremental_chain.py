#!/usr/bin/env python3
"""Materialize locked component inputs for incremental UI ISO builds."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from srwz.iso_config import load_config
from srwz.pcsx2_boot_smoke import sha256_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/iso/ui-incremental-chain.json"


def project_path(raw: str, prefix: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe project path: {raw}")
    relative.relative_to(prefix)
    return (PROJECT_ROOT / relative).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--step-id")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    chain = json.loads(args.config.read_text(encoding="utf-8"))
    selected = [
        step
        for step in chain["steps"]
        if (
            step.get("materialization") == "copy_locked_components"
            and (args.step_id is None or step["step_id"] == args.step_id)
        )
    ]
    if args.step_id is not None and not selected:
        raise SystemExit(
            f"unknown or non-copy step-id: {args.step_id}"
        )
    copied = 0
    exact = 0
    for step in selected:
        build_config_path = project_path(
            step["build_config"],
            "config/iso",
        )
        build_config = load_config(build_config_path)
        sources = step["component_sources"]
        for replacement in build_config["replacements"]:
            member = replacement["member"]
            source = project_path(sources[member], "work/build")
            destination = project_path(
                replacement["source"],
                "work/build",
            )
            if (
                source.stat().st_size != replacement["size"]
                or sha256_file(source) != replacement["sha256"]
            ):
                raise SystemExit(f"source lock drift: {source}")
            if destination.exists():
                destination_exact = (
                    destination.stat().st_size == replacement["size"]
                    and sha256_file(destination) == replacement["sha256"]
                )
                if destination_exact:
                    exact += 1
                    continue
                if not args.force:
                    raise SystemExit(
                        f"destination drift; use --force: {destination}"
                    )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied += 1
    print(f"incremental component inputs copied: {copied}")
    print(f"incremental component inputs already exact: {exact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
