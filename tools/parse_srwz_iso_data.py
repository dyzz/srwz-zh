#!/usr/bin/env python3
"""Parse all localization-relevant SRWZ ISO data and compare upstream XML."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from srwz.archive import (
    ArchiveLayoutError,
    load_offset_layout,
    slice_archive,
    verify_archive,
)
from srwz.codec import decode
from srwz.codec_contract import SrwzCodecError
from srwz.diagnostics import require_work_output
from srwz.iso_layout import (
    CORE_ARCHIVE_SPECS,
    IsoLayoutError,
    read_executable_archive_offsets,
)
from srwz.menu import MenuParseError, parse_menu_file
from srwz.reference import (
    compare_signatures,
    menu_reference_signature,
    story_reference_signature,
    summary_reference_signature,
)
from srwz.stage import (
    StageParseError,
    parse_stage,
    read_stage_function_addresses,
)
from srwz.summary import SummaryParseError, parse_summary
from srwz.text import SrwzTextError, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_DISC_ROOT = WORK_ROOT / "disc"
DEFAULT_REFERENCE_ROOT = PROJECT_ROOT.parent / "2_translated"
DEFAULT_OUTPUT = WORK_ROOT / "parsed" / "srwz-data.json"
DEFAULT_STAGE_LAYOUT = PROJECT_ROOT / "config" / "stage-offsets.json"
DEFAULT_MENU_CONFIG = (
    PROJECT_ROOT
    / "vendor"
    / "upstream-python"
    / "project"
    / "menu_files.json"
)
DEFAULT_TEXT_TABLE = (
    PROJECT_ROOT
    / "vendor"
    / "upstream-python"
    / "project"
    / "tbl_all.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse SLPS, COMPDATA, STAGE, MTV_PROS and VT1 metadata without "
            "running upstream binaries."
        )
    )
    parser.add_argument("--disc-root", type=Path, default=DEFAULT_DISC_ROOT)
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=DEFAULT_REFERENCE_ROOT,
    )
    parser.add_argument("--no-reference", action="store_true")
    parser.add_argument("--stage-layout", type=Path, default=DEFAULT_STAGE_LAYOUT)
    parser.add_argument("--menu-config", type=Path, default=DEFAULT_MENU_CONFIG)
    parser.add_argument("--text-table", type=Path, default=DEFAULT_TEXT_TABLE)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stream_metadata(data: bytes, result) -> dict:
    trailing = data[result.consumed:]
    return {
        "slice_size": len(data),
        "slice_sha256": sha256_bytes(data),
        "declared_size": result.declared_size,
        "flags": result.flags,
        "header_size": result.header_size,
        "metadata": dict(result.metadata),
        "consumed": result.consumed,
        "padding": len(trailing),
        "padding_all_zero": all(byte == 0 for byte in trailing),
        "decoded_sha256": sha256_bytes(result.output),
    }


def _menu_signature(result) -> tuple:
    return tuple(
        (
            entry.section,
            entry.text,
            entry.pointer_offsets,
            entry.embedded_hi,
            entry.embedded_lo,
        )
        for entry in result.entries
    )


def _story_signature(result) -> tuple:
    return tuple(
        (
            entry.kind,
            entry.section,
            entry.text,
            entry.pointer_offset,
            entry.speaker_id,
        )
        for entry in result.entries
    )


def _summary_signature(result) -> tuple:
    return tuple(
        (entry.text, entry.text_offset)
        for entry in result.entries
    )


def _collection_comparison(
    actual,
    references,
    actual_signature,
    reference_signature,
) -> dict:
    actual_ids = set(actual)
    reference_ids = set(references)
    files = []
    for identifier in sorted(actual_ids & reference_ids):
        comparison = compare_signatures(
            actual_signature(actual[identifier]),
            reference_signature(references[identifier]),
        )
        files.append({"id": identifier, **comparison})
    missing_references = sorted(actual_ids - reference_ids)
    missing_actual = sorted(reference_ids - actual_ids)
    differing_entries = sum(
        item["differing_entry_count"] for item in files
    )
    exact_count = sum(item["exact"] for item in files)
    return {
        "actual_file_count": len(actual_ids),
        "reference_file_count": len(reference_ids),
        "compared_file_count": len(files),
        "exact_file_count": exact_count,
        "differing_entry_count": differing_entries,
        "missing_reference_ids": missing_references,
        "missing_actual_ids": missing_actual,
        "exact": (
            exact_count == len(files)
            and not missing_references
            and not missing_actual
        ),
        "files": files,
    }


def _reference_set_metadata(folder: Path) -> dict:
    files = sorted(folder.glob("*.xml"))
    digest = hashlib.sha256()
    total_size = 0
    for path in files:
        data = path.read_bytes()
        total_size += len(data)
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(hashlib.sha256(data).digest())
    return {
        "file_count": len(files),
        "total_size": total_size,
        "aggregate_sha256": digest.hexdigest(),
    }


def _reference_comparison(reference_root: Path, menus, stages, summaries) -> dict:
    menu_paths = {
        path.stem: path
        for path in (reference_root / "menu").glob("*.xml")
    }
    story_paths = {
        int(path.stem): path
        for path in (reference_root / "story").glob("*.xml")
    }
    summary_paths = {
        int(path.stem): path
        for path in (reference_root / "summary").glob("*.xml")
    }
    menu_comparison = _collection_comparison(
        menus,
        menu_paths,
        _menu_signature,
        menu_reference_signature,
    )
    story_comparison = _collection_comparison(
        stages,
        story_paths,
        _story_signature,
        story_reference_signature,
    )
    summary_comparison = _collection_comparison(
        summaries,
        summary_paths,
        _summary_signature,
        summary_reference_signature,
    )
    return {
        "status": "compared",
        "reference_root": str(reference_root),
        "reference_sets": {
            "menu": _reference_set_metadata(reference_root / "menu"),
            "story": _reference_set_metadata(reference_root / "story"),
            "summary": _reference_set_metadata(reference_root / "summary"),
        },
        "exact": all(
            comparison["exact"]
            for comparison in (
                menu_comparison,
                story_comparison,
                summary_comparison,
            )
        ),
        "menu": menu_comparison,
        "story": story_comparison,
        "summary": summary_comparison,
    }


def _vt1_inventory(executable: bytes, data: bytes) -> dict:
    spec = CORE_ARCHIVE_SPECS["VT1.BIN"]
    offsets = read_executable_archive_offsets(
        executable,
        spec,
        len(data),
    )
    segments = []
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        segment = data[start:end]
        row = {
            "index": index,
            "start": start,
            "end": end,
            "size": len(segment),
            "sha256": sha256_bytes(segment),
        }
        try:
            result = decode(segment)
            trailing = segment[result.consumed:]
            row["codec"] = {
                "classification": (
                    "compressed_stream"
                    if all(byte == 0 for byte in trailing)
                    else "stream_prefix_with_nonzero_tail"
                ),
                **stream_metadata(segment, result),
            }
        except SrwzCodecError as error:
            row["codec"] = {
                "classification": "not_decoded_as_stream",
                "error": str(error),
                "error_offset": error.offset,
            }
        segments.append(row)

    font_segment = segments[2]
    if font_segment["codec"]["classification"] != "compressed_stream":
        raise IsoLayoutError("VT1 font segment 2 is not a complete codec stream")
    return {
        "member": spec.member,
        "size": len(data),
        "sha256": sha256_bytes(data),
        "offsets": list(offsets),
        "segment_count": len(segments),
        "font_segment_index": 2,
        "segments": segments,
    }


def main() -> int:
    args = parse_args()
    disc_root = args.disc_root.resolve()
    reference_root = args.reference_root.resolve()

    try:
        output_path = require_work_output(args.json_output, WORK_ROOT)
        if output_path.exists() and not args.force:
            raise FileExistsError(
                f"refusing to replace existing parse output: {output_path}"
            )

        paths = {
            "SLPS_258.87": disc_root / "SLPS_258.87",
            "COMPDATA.BN": disc_root / "DATA" / "COMPDATA.BN",
            "STAGE.BIN": disc_root / "DATA" / "STAGE.BIN",
            "MTV_PROS.BIN": disc_root / "DATA" / "MTV_PROS.BIN",
            "VT1.BIN": disc_root / "DATA" / "VT1.BIN",
        }
        missing = [str(path) for path in paths.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "missing extracted ISO members: " + ", ".join(missing)
            )

        source_data = {
            name: path.read_bytes()
            for name, path in paths.items()
        }
        executable = source_data["SLPS_258.87"]
        table = load_text_table(args.text_table.resolve())
        menu_descriptors = json.loads(
            args.menu_config.resolve().read_text(encoding="utf-8")
        )

        compdata_stream = source_data["COMPDATA.BN"]
        compdata_decoded = decode(compdata_stream)
        menu_sources = {
            "SLPS": executable,
            "Compdata": compdata_decoded.output,
        }
        menus = {}
        for descriptor in menu_descriptors:
            friendly_name = descriptor["friendly_name"]
            menus[friendly_name] = parse_menu_file(
                menu_sources[friendly_name],
                descriptor,
                table,
            )

        stage_layout = load_offset_layout(args.stage_layout.resolve())
        verify_archive(paths["STAGE.BIN"], stage_layout)
        functions = read_stage_function_addresses(executable)
        if len(functions) < stage_layout.chunk_count:
            raise ValueError(
                "stage function table has fewer entries than STAGE.BIN"
            )
        stage_inventory = []
        text_stages = {}
        for index, chunk in enumerate(
            slice_archive(source_data["STAGE.BIN"], stage_layout)
        ):
            decoded = decode(chunk)
            parsed = parse_stage(
                decoded.output,
                table,
                stage_index=index,
                function_address=functions[index],
            )
            stage_inventory.append(
                {
                    "index": index,
                    "codec": stream_metadata(chunk, decoded),
                    "entry_count": len(parsed.entries),
                    "speaker_count": parsed.speaker_count,
                    "condition_count": parsed.condition_count,
                    "dialogue_count": parsed.dialogue_count,
                    "section_count": parsed.section_count,
                    "unknown_code_count": parsed.unknown_code_count,
                }
            )
            if parsed.entries:
                text_stages[index] = parsed

        mtv_data = source_data["MTV_PROS.BIN"]
        mtv_offsets = read_executable_archive_offsets(
            executable,
            CORE_ARCHIVE_SPECS["MTV_PROS.BIN"],
            len(mtv_data),
        )
        summary_inventory = []
        text_summaries = {}
        for index, (start, end) in enumerate(
            zip(mtv_offsets, mtv_offsets[1:])
        ):
            chunk = mtv_data[start:end]
            decoded = decode(chunk)
            parsed = parse_summary(
                decoded.output,
                table,
                chunk_index=index,
            )
            summary_inventory.append(
                {
                    "index": index,
                    "start": start,
                    "end": end,
                    "codec": stream_metadata(chunk, decoded),
                    "section_count": parsed.section_count,
                    "entry_count": len(parsed.entries),
                    "unknown_code_count": parsed.unknown_code_count,
                }
            )
            if parsed.entries:
                text_summaries[index] = parsed

        vt1 = _vt1_inventory(executable, source_data["VT1.BIN"])

        stable_ids = [
            entry.entry_id
            for result in menus.values()
            for entry in result.entries
        ]
        stable_ids.extend(
            entry.entry_id
            for result in text_stages.values()
            for entry in result.entries
        )
        stable_ids.extend(
            entry.entry_id
            for result in text_summaries.values()
            for entry in result.entries
        )
        if len(stable_ids) != len(set(stable_ids)):
            raise ValueError("parsed localization entry IDs are not unique")

        if args.no_reference:
            comparison = {"status": "not_requested", "exact": None}
        else:
            comparison = _reference_comparison(
                reference_root,
                menus,
                text_stages,
                text_summaries,
            )

        document = {
            "schema_version": 1,
            "content_policy": (
                "Ignored local parse output containing original Japanese text; "
                "do not commit this file."
            ),
            "sources": {
                name: {
                    "path": str(paths[name]),
                    "size": len(data),
                    "sha256": sha256_bytes(data),
                }
                for name, data in source_data.items()
            },
            "configuration": {
                "stage_layout": str(args.stage_layout.resolve()),
                "menu_config": str(args.menu_config.resolve()),
                "text_table": str(args.text_table.resolve()),
                "menu_config_sha256": sha256_bytes(
                    args.menu_config.resolve().read_bytes()
                ),
                "text_table_sha256": sha256_bytes(
                    args.text_table.resolve().read_bytes()
                ),
            },
            "archives": {
                "COMPDATA.BN": {
                    "codec": stream_metadata(
                        compdata_stream,
                        compdata_decoded,
                    )
                },
                "STAGE.BIN": {
                    "chunk_count": len(stage_inventory),
                    "text_stage_count": len(text_stages),
                    "stages": stage_inventory,
                },
                "MTV_PROS.BIN": {
                    "offsets": list(mtv_offsets),
                    "chunk_count": len(summary_inventory),
                    "text_chunk_count": len(text_summaries),
                    "chunks": summary_inventory,
                },
                "VT1.BIN": vt1,
            },
            "parsed": {
                "menu": [
                    menus[name].to_mapping()
                    for name in sorted(menus)
                ],
                "story": [
                    text_stages[index].to_mapping()
                    for index in sorted(text_stages)
                ],
                "summary": [
                    text_summaries[index].to_mapping()
                    for index in sorted(text_summaries)
                ],
            },
            "totals": {
                "menu_files": len(menus),
                "menu_entries": sum(
                    len(result.entries) for result in menus.values()
                ),
                "stage_chunks": len(stage_inventory),
                "story_files": len(text_stages),
                "story_entries": sum(
                    len(result.entries) for result in text_stages.values()
                ),
                "summary_chunks": len(summary_inventory),
                "summary_files": len(text_summaries),
                "summary_entries": sum(
                    len(result.entries)
                    for result in text_summaries.values()
                ),
                "unknown_text_codes": (
                    sum(result.unknown_code_count for result in menus.values())
                    + sum(
                        result.unknown_code_count
                        for result in text_stages.values()
                    )
                    + sum(
                        result.unknown_code_count
                        for result in text_summaries.values()
                    )
                ),
                "stable_id_count": len(stable_ids),
            },
            "comparison": comparison,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    except (
        ArchiveLayoutError,
        FileExistsError,
        FileNotFoundError,
        IsoLayoutError,
        MenuParseError,
        OSError,
        SrwzCodecError,
        SrwzTextError,
        StageParseError,
        SummaryParseError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"parsed: menus={document['totals']['menu_entries']} "
        f"story={document['totals']['story_entries']} "
        f"summary={document['totals']['summary_entries']} "
        f"unknown_codes={document['totals']['unknown_text_codes']}"
    )
    print(
        f"archives: stage={document['totals']['stage_chunks']} "
        f"story_files={document['totals']['story_files']} "
        f"mtv_pros={document['totals']['summary_chunks']} "
        f"vt1={vt1['segment_count']}"
    )
    if comparison["status"] == "compared":
        print(
            f"upstream comparison: exact={comparison['exact']} "
            f"menu={comparison['menu']['exact_file_count']}/"
            f"{comparison['menu']['reference_file_count']} "
            f"story={comparison['story']['exact_file_count']}/"
            f"{comparison['story']['reference_file_count']} "
            f"summary={comparison['summary']['exact_file_count']}/"
            f"{comparison['summary']['reference_file_count']}"
        )
    print(f"json: {output_path}")
    return 0 if comparison.get("exact") is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
