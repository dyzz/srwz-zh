#!/usr/bin/env python3
"""Compose the validated full-story and reviewed LIBRARY component receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FULL = PROJECT_ROOT / "manifests/full-story-components-validation.json"
DEFAULT_LIBRARY = PROJECT_ROOT / "manifests/library-v0.2-reviewed-validation.json"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "manifests/full-story-library-components-validation.json"
)
INTEGRATED_COMPONENT_ROOT = PROJECT_ROOT / "work/build/zh-release-full-story/components"
FULL_STATUS = "integrated_global_zh_release_components_validated_runtime_pending"
LIBRARY_STATUS = "library_v0.2_reviewed_components_static_validated"
OUTPUT_STATUS = (
    "integrated_global_zh_release_library_components_validated_runtime_pending"
)
SHARED_OUTPUT_MEMBERS = {"DATA/NISVDATA.BIN"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", type=Path, default=DEFAULT_FULL)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load(path: Path) -> dict:
    document = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise SystemExit(f"unsupported component manifest: {path}")
    return document


def file_lock(path: Path) -> dict[str, object]:
    data = path.resolve().read_bytes()
    return {
        "path": str(path.resolve().relative_to(PROJECT_ROOT)),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> int:
    args = parse_args()
    full_path = args.full.resolve()
    library_path = args.library.resolve()
    full = load(full_path)
    library = load(library_path)
    if full.get("status") != FULL_STATUS:
        raise SystemExit("full-story component status drift")
    if (
        library.get("status") != LIBRARY_STATUS
        or library.get("release_eligible") is not True
        or not all(library.get("acceptance", {}).values())
    ):
        raise SystemExit("reviewed LIBRARY component acceptance is incomplete")
    full_outputs = full.get("outputs")
    library_outputs = library.get("outputs")
    if not isinstance(full_outputs, dict) or not isinstance(library_outputs, dict):
        raise SystemExit("component outputs are malformed")
    overlap = set(full_outputs) & set(library_outputs)
    if overlap - SHARED_OUTPUT_MEMBERS:
        raise SystemExit(f"component output ownership overlap: {sorted(overlap)}")
    if "DATA/NISVDATA.BIN" in overlap:
        full_runtime_menu = full.get("runtime_library_menu")
        library_runtime_menu = library.get("runtime_library_menu")
        full_sound_select = (
            full_runtime_menu.get("sound_select")
            if isinstance(full_runtime_menu, dict)
            else None
        )
        library_sound_select = (
            library_runtime_menu.get("sound_select")
            if isinstance(library_runtime_menu, dict)
            else None
        )
        if (
            not isinstance(full_runtime_menu, dict)
            or not isinstance(library_runtime_menu, dict)
            or not isinstance(full_sound_select, dict)
            or not isinstance(library_sound_select, dict)
            or full_runtime_menu.get("output_logical_indexes_sha256")
            != library_runtime_menu.get("output_logical_indexes_sha256")
            or full_runtime_menu.get("render_snapshot")
            != library_runtime_menu.get("render_snapshot")
            or full_sound_select.get("output_logical_indexes_sha256")
            != library_sound_select.get("output_logical_indexes_sha256")
            or full_sound_select.get("render_snapshot")
            != library_sound_select.get("render_snapshot")
            or full_sound_select.get("labels")
            != library_sound_select.get("labels")
            or full_sound_select.get("sound_select_title_written") is not True
            or library_sound_select.get("sound_select_title_written") is not True
            or full_runtime_menu.get("all_six_labels_written") is not True
            or library_runtime_menu.get("all_six_labels_written") is not True
        ):
            raise SystemExit("shared NISVDATA runtime menu composition drift")

    full_unlock = full.get("sound_select_default_unlock")
    library_unlock = library.get("sound_select_default_unlock")
    if (
        not isinstance(full_unlock, dict)
        or not isinstance(library_unlock, dict)
        or full_unlock.get("virtual_address")
        != library_unlock.get("virtual_address")
        or full_unlock.get("file_offset") != library_unlock.get("file_offset")
        or full_unlock.get("original_instruction_hex")
        != library_unlock.get("original_instruction_hex")
        or full_unlock.get("replacement_instruction_hex")
        != library_unlock.get("replacement_instruction_hex")
        or full_unlock.get("metadata") != library_unlock.get("metadata")
        or full_unlock.get("instruction_replacement_exact") is not True
        or library_unlock.get("instruction_replacement_exact") is not True
        or library_unlock.get("full_story_component_owns_writeback") is not True
    ):
        raise SystemExit("sound-select default-unlock composition drift")

    installed_library_outputs = {}
    for member, lock in library_outputs.items():
        if member in overlap:
            continue
        if not isinstance(lock, dict):
            raise SystemExit(f"invalid LIBRARY output lock: {member}")
        source = PROJECT_ROOT / str(lock.get("path"))
        data = source.read_bytes()
        if (
            len(data) != lock.get("size")
            or hashlib.sha256(data).hexdigest() != lock.get("sha256")
        ):
            raise SystemExit(f"LIBRARY output drift: {member}")
        target = INTEGRATED_COMPONENT_ROOT / member
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
        installed_library_outputs[member] = file_lock(target)

    combined = deepcopy(full)
    combined["status"] = OUTPUT_STATUS
    combined["profile_id"] = "srwz-global-zh-release-library-integrated-v1"
    combined["scope"] = (
        str(full.get("scope", "")).rstrip(".")
        + ", plus the reviewed v0.2 robot, character and keyword encyclopedia members."
    )
    combined.setdefault("inputs", {})["library_component_manifest"] = file_lock(
        library_path
    )
    combined["library"] = {
        "status": library["status"],
        "profile_id": library["profile_id"],
        "release_eligible": library["release_eligible"],
        "translation": deepcopy(library["translation"]),
        "library_menu": deepcopy(library["library_menu"]),
        "runtime_library_menu": deepcopy(
            library.get("runtime_library_menu")
        ),
        "sound_select_default_unlock": deepcopy(
            library.get("sound_select_default_unlock")
        ),
        "legacy_jtim_restoration": deepcopy(
            library.get("legacy_jtim_restoration")
        ),
        "archives": deepcopy(library["archives"]),
        "acceptance": deepcopy(library["acceptance"]),
    }
    combined["outputs"] = {**full_outputs, **installed_library_outputs}
    combined.setdefault("acceptance", {})[
        "reviewed_library_components_reread_exact"
    ] = all(library["acceptance"].values())
    combined["runtime"] = {
        "status": "not_tested",
        "reason": (
            "Static component proof only; fresh PCSX2 entry-flow evidence for "
            "the exact ISO remains separate."
        ),
        "required_library_flows": deepcopy(
            library.get("runtime", {}).get("required_flows", [])
        ),
    }
    if len(combined["outputs"]) != 20 or not all(
        combined["acceptance"].values()
    ):
        raise SystemExit("combined component acceptance failed")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print(
        f"combined components: outputs={len(combined['outputs'])} "
        f"library_texts={library['translation']['unique_text_count']} "
        f"status={OUTPUT_STATUS}"
    )
    print(output.relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
