#!/usr/bin/env python3
"""Build exactly one incremental UI ISO and discard full-disc work trees."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping

try:
    from srwz.font import GLYPH_COUNT, GLYPH_SIZE, decode_vt1_font_segment
    from srwz.iso_config import load_config
except ModuleNotFoundError:
    from tools.srwz.font import (
        GLYPH_COUNT,
        GLYPH_SIZE,
        decode_vt1_font_segment,
    )
    from tools.srwz.iso_config import load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHAIN = PROJECT_ROOT / "config/iso/ui-incremental-chain.json"


class SingleIsoCandidateError(ValueError):
    """The single-candidate ISO workflow contract was violated."""


def _project_path(
    project_root: Path,
    raw: object,
    *,
    prefix: str,
    context: str,
) -> Path:
    if not isinstance(raw, str) or not raw:
        raise SingleIsoCandidateError(f"{context} must be a non-empty path")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise SingleIsoCandidateError(f"{context} must be project-relative")
    try:
        relative.relative_to(prefix)
    except ValueError as error:
        raise SingleIsoCandidateError(
            f"{context} must be under {prefix}/"
        ) from error
    return (project_root / relative).resolve()


def load_selected_step(chain_path: Path, step_id: str) -> Mapping[str, object]:
    try:
        chain = json.loads(chain_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SingleIsoCandidateError(
            f"cannot load incremental chain: {error}"
        ) from error
    if chain.get("schema_version") != 1:
        raise SingleIsoCandidateError("unsupported incremental chain schema")
    matches = [
        step
        for step in chain.get("steps", [])
        if isinstance(step, dict) and step.get("step_id") == step_id
    ]
    if len(matches) != 1:
        raise SingleIsoCandidateError(
            f"incremental step must exist exactly once: {step_id}"
        )
    return matches[0]


def generated_iso_paths(project_root: Path) -> tuple[Path, ...]:
    output_root = project_root / "build/iso"
    if not output_root.exists():
        return ()
    return tuple(sorted(output_root.rglob("*.iso")))


def validate_slps_vt1_pair(
    project_root: Path,
    step: Mapping[str, object],
) -> Mapping[str, object] | None:
    """Reject a VT1 archive paired with an incompatible SLPS offset table."""

    component_sources = step.get("component_sources")
    if not isinstance(component_sources, dict):
        return None
    slps_raw = component_sources.get("SLPS_258.87")
    vt1_raw = component_sources.get("DATA/VT1.BIN")
    if slps_raw is None or vt1_raw is None:
        return None
    slps_path = _project_path(
        project_root,
        slps_raw,
        prefix="work/build",
        context="selected step SLPS source",
    )
    vt1_path = _project_path(
        project_root,
        vt1_raw,
        prefix="work/build",
        context="selected step VT1 source",
    )
    try:
        decoded = decode_vt1_font_segment(
            slps_path.read_bytes(),
            vt1_path.read_bytes(),
        )
    except (OSError, ValueError) as error:
        raise SingleIsoCandidateError(
            "selected step pairs DATA/VT1.BIN with an incompatible "
            f"SLPS_258.87 offset table: {error}"
        ) from error
    expected_size = GLYPH_COUNT * GLYPH_SIZE
    if len(decoded.decoded) != expected_size:
        raise SingleIsoCandidateError(
            "selected step VT1 font decoded to an unexpected size: "
            f"{len(decoded.decoded)} != {expected_size}"
        )
    return {
        "slps": slps_path,
        "vt1": vt1_path,
        "decoded_size": len(decoded.decoded),
        "compressed_size": decoded.compressed_size,
    }


def remove_existing_isos(
    project_root: Path,
    *,
    replace_existing: bool,
) -> tuple[Path, ...]:
    existing = generated_iso_paths(project_root)
    if existing and not replace_existing:
        relative = ", ".join(
            path.relative_to(project_root).as_posix() for path in existing
        )
        raise SingleIsoCandidateError(
            "generated ISO already exists; validate it or rerun with "
            f"--replace-existing: {relative}"
        )
    for path in existing:
        path.unlink()
    return existing


def cleanup_full_disc_workspaces(
    project_root: Path,
    build_config: Mapping[str, object],
) -> tuple[Path, ...]:
    workspace = build_config.get("workspace")
    if not isinstance(workspace, dict):
        raise SingleIsoCandidateError("ISO config has no workspace object")
    removed = []
    for field, expected_name in (
        ("original_tree", "original"),
        ("staging_tree", "staging"),
    ):
        path = _project_path(
            project_root,
            workspace.get(field),
            prefix="work/build",
            context=f"workspace {field}",
        )
        if path.name != expected_name or path.parent.name != "iso":
            raise SingleIsoCandidateError(
                f"unsafe full-disc workspace path: {path}"
            )
        if path.exists():
            shutil.rmtree(path)
            removed.append(path)
    return tuple(removed)


def _run(command: list[str]) -> None:
    process = subprocess.run(command, cwd=PROJECT_ROOT)
    if process.returncode != 0:
        raise SingleIsoCandidateError(
            f"command failed with exit {process.returncode}: "
            + " ".join(command)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build one incremental UI ISO, retain no other ISO, and remove "
            "the generated original/staging full-disc trees."
        )
    )
    parser.add_argument("--chain", type=Path, default=DEFAULT_CHAIN)
    parser.add_argument("--step-id", required=True)
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Delete the currently retained generated ISO before building.",
    )
    parser.add_argument(
        "--refresh-extraction",
        action="store_true",
        help="Forward a fresh extraction request to the ISO builder.",
    )
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Keep original/staging trees for debugging instead of pruning.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_path: Path | None = None
    build_config: Mapping[str, object] | None = None
    succeeded = False
    try:
        step = load_selected_step(args.chain.resolve(), args.step_id)
        pairing = validate_slps_vt1_pair(PROJECT_ROOT, step)
        if pairing is not None:
            print(
                "[OK] SLPS/VT1 compatibility: "
                f"{pairing['decoded_size']} decoded font bytes"
            )
        build_config_path = _project_path(
            PROJECT_ROOT,
            step.get("build_config"),
            prefix="config/iso",
            context="selected step build config",
        )
        build_config = load_config(build_config_path)
        target_path = _project_path(
            PROJECT_ROOT,
            build_config["output"]["path"],
            prefix="build/iso",
            context="selected step output ISO",
        )
        removed_isos = remove_existing_isos(
            PROJECT_ROOT,
            replace_existing=args.replace_existing,
        )
        for path in removed_isos:
            print(
                "[PRUNE] prior ISO: "
                f"{path.relative_to(PROJECT_ROOT).as_posix()}"
            )

        if step.get("materialization") == "copy_locked_components":
            _run(
                [
                    sys.executable,
                    str(
                        PROJECT_ROOT
                        / "tools/prepare_ui_iso_incremental_chain.py"
                    ),
                    "--config",
                    str(args.chain.resolve()),
                    "--step-id",
                    args.step_id,
                ]
            )
        elif step.get("materialization") != "existing_profile":
            raise SingleIsoCandidateError(
                "selected step has an unsupported materialization mode"
            )

        command = [
            sys.executable,
            str(PROJECT_ROOT / "tools/build_canary_iso.py"),
            "--config",
            str(build_config_path),
        ]
        original_tree = _project_path(
            PROJECT_ROOT,
            build_config["workspace"]["original_tree"],
            prefix="work/build",
            context="selected step original tree",
        )
        if args.refresh_extraction or not original_tree.is_dir():
            command.append("--refresh-extraction")
        _run(command)

        remaining = generated_iso_paths(PROJECT_ROOT)
        if remaining != (target_path,):
            raise SingleIsoCandidateError(
                "single-candidate invariant failed after build"
            )
        if not args.keep_workspace:
            removed = cleanup_full_disc_workspaces(
                PROJECT_ROOT,
                build_config,
            )
            for path in removed:
                print(
                    "[PRUNE] full-disc workspace: "
                    f"{path.relative_to(PROJECT_ROOT).as_posix()}"
                )
        succeeded = True
        print(
            "[OK] only retained ISO: "
            f"{target_path.relative_to(PROJECT_ROOT).as_posix()}"
        )
        return 0
    except (
        OSError,
        KeyError,
        SingleIsoCandidateError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        if not succeeded and target_path is not None and target_path.exists():
            target_path.unlink()
            print(
                "[PRUNE] incomplete ISO: "
                f"{target_path.relative_to(PROJECT_ROOT).as_posix()}"
            )
        if (
            not succeeded
            and not args.keep_workspace
            and build_config is not None
        ):
            try:
                removed = cleanup_full_disc_workspaces(
                    PROJECT_ROOT,
                    build_config,
                )
                for path in removed:
                    print(
                        "[PRUNE] full-disc workspace: "
                        f"{path.relative_to(PROJECT_ROOT).as_posix()}"
                    )
            except (OSError, SingleIsoCandidateError) as error:
                print(f"cleanup error: {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
