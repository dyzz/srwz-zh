#!/usr/bin/env python3
"""Refreeze owner-discovered fixed STAGE formation-name occurrences."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.srwz.codec import decode_production as decode  # noqa: E402
from tools.srwz.iso_layout import read_executable_archive_offsets  # noqa: E402
from tools.srwz.stage_formations import (  # noqa: E402
    STAGE_OFFSET_SPEC,
    FormationCell,
    FormationGroup,
    build_locked_formation_inventory,
    discover_owned_stage_formation_names,
    load_locked_stage_default_formations,
)
from tools.srwz.text import load_text_table  # noqa: E402


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_lock(path: Path, data: bytes) -> dict[str, object]:
    try:
        display_path = path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        display_path = str(path.resolve())
    return {
        "path": display_path,
        "size": len(data),
        "sha256": _sha256(data),
    }


def _decoded_chunks(stage: bytes, hb: bytes) -> dict[int, bytes]:
    offsets = read_executable_archive_offsets(hb, STAGE_OFFSET_SPEC, len(stage))
    result = {}
    for stage_index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        decoded = decode(stage[start:end])
        if any(stage[start + decoded.consumed : end]):
            raise ValueError(f"STAGE {stage_index} has nonzero archive padding")
        result[stage_index] = decoded.output
    return result


def _cell_key(
    group: FormationGroup,
    cell: FormationCell,
) -> tuple[int, int, int, str]:
    return (
        group.stage_index,
        cell.offset,
        group.slot_size,
        cell.source_text,
    )


def refreeze(
    *,
    original_stage_path: Path,
    current_stage_path: Path,
    hb_path: Path,
    corpus_path: Path,
    inventory_path: Path,
    table_path: Path,
) -> dict[str, object]:
    original_stage = original_stage_path.read_bytes()
    current_stage = current_stage_path.read_bytes()
    hb = hb_path.read_bytes()
    corpus_data = corpus_path.read_bytes()
    inventory_document = json.loads(inventory_path.read_text(encoding="utf-8"))
    corpus_document = json.loads(corpus_data.decode("utf-8"))
    translations = corpus_document.get("translations_by_source_text")
    if not isinstance(translations, dict) or not translations:
        raise ValueError("default formation corpus is invalid")
    if len(original_stage) != len(current_stage):
        raise ValueError("current STAGE size differs from original STAGE")

    table = load_text_table(table_path)
    existing = list(
        load_locked_stage_default_formations(
            original_stage,
            hb,
            table,
            inventory_document,
        )
    )
    original_owned = discover_owned_stage_formation_names(
        original_stage,
        hb,
        table,
    )
    current_owned = discover_owned_stage_formation_names(
        original_stage,
        hb,
        table,
        owner_stage=current_stage,
    )
    current_keys = {
        _cell_key(group, cell)
        for group in current_owned
        for cell in group.cells
    }
    original_chunks = _decoded_chunks(original_stage, hb)
    current_chunks = _decoded_chunks(current_stage, hb)

    occupied = {
        (group.stage_index, cell.offset): group.slot_size
        for group in existing
        for cell in group.cells
    }
    additions_by_group: dict[tuple[int, str], list[FormationCell]] = {}
    for group in original_owned:
        original = original_chunks[group.stage_index]
        current = current_chunks[group.stage_index]
        for cell in group.cells:
            position = (group.stage_index, cell.offset)
            if position in occupied or cell.source_text not in translations:
                continue
            if _cell_key(group, cell) not in current_keys:
                continue
            slot_end = cell.offset + group.slot_size
            if original[cell.offset:slot_end] != current[cell.offset:slot_end]:
                continue
            additions_by_group.setdefault(
                (group.stage_index, group.layout), []
            ).append(cell)
            occupied[position] = group.slot_size

    existing_packed_keys = {
        (group.stage_index, group.layout): index
        for index, group in enumerate(existing)
        if group.layout.startswith(("packed8-", "pointer8-"))
    }
    new_groups_by_stage: dict[int, list[FormationGroup]] = {}
    for key, cells in sorted(additions_by_group.items()):
        stage_index, layout = key
        ordered_cells = tuple(sorted(cells, key=lambda cell: cell.offset))
        if key in existing_packed_keys:
            index = existing_packed_keys[key]
            prior = existing[index]
            existing[index] = replace(
                prior,
                cells=tuple(
                    sorted(
                        (*prior.cells, *ordered_cells),
                        key=lambda cell: cell.offset,
                    )
                ),
            )
        else:
            template = next(
                group
                for group in original_owned
                if group.stage_index == stage_index and group.layout == layout
            )
            new_groups_by_stage.setdefault(stage_index, []).append(
                replace(template, cells=ordered_cells)
            )

    merged: list[FormationGroup] = []
    for stage_index in sorted(
        {group.stage_index for group in existing} | set(new_groups_by_stage)
    ):
        merged.extend(
            group for group in existing if group.stage_index == stage_index
        )
        merged.extend(
            sorted(
                new_groups_by_stage.get(stage_index, ()),
                key=lambda group: (group.layout, group.cells[0].offset),
            )
        )
    groups = tuple(merged)
    locked_sources = {
        cell.source_text for group in groups for cell in group.cells
    }
    if locked_sources != set(translations):
        raise ValueError(
            "corpus and refrozen inventory source coverage differ: "
            f"missing={sorted(set(translations) - locked_sources)!r} "
            f"extra={sorted(locked_sources - set(translations))!r}"
        )

    output = build_locked_formation_inventory(groups)
    output.update(
        {
            "source_stage": _file_lock(original_stage_path, original_stage),
            "source_current_stage": _file_lock(
                current_stage_path, current_stage
            ),
            "source_hb": _file_lock(hb_path, hb),
            "source_corpus": _file_lock(corpus_path, corpus_data),
        }
    )
    inventory_path.write_text(
        json.dumps(
            output,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "prior_group_count": len(existing),
        "added_group_count": len(groups) - len(existing),
        "added_entry_count": sum(len(cells) for cells in additions_by_group.values()),
        **output["expected"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--original-stage",
        type=Path,
        default=PROJECT_ROOT / "work/disc/DATA/STAGE.BIN",
    )
    parser.add_argument(
        "--current-stage",
        type=Path,
        default=(
            PROJECT_ROOT
            / "work/build/zh-release-full-story/components/DATA/STAGE.BIN"
        ),
    )
    parser.add_argument(
        "--hb",
        type=Path,
        default=(
            PROJECT_ROOT
            / "work/build/zh-release-full-story/components/HEDBDY/HB.BIN"
        ),
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=PROJECT_ROOT / "corpus/zh/menu/stage-default-formations.json",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=PROJECT_ROOT / "config/stage-default-formation-inventory.json",
    )
    parser.add_argument(
        "--table",
        type=Path,
        default=(
            PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
        ),
    )
    args = parser.parse_args()
    report = refreeze(
        original_stage_path=args.original_stage,
        current_stage_path=args.current_stage,
        hb_path=args.hb,
        corpus_path=args.corpus,
        inventory_path=args.inventory,
        table_path=args.table,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
