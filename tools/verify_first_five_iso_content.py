#!/usr/bin/env python3
"""Re-read and verify the first-five Chinese texts from the final ISO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.archive import sha256_file
from srwz.codec import decode
from srwz.font import sha256_bytes
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.stage import parse_stage, read_stage_function_addresses
from srwz.text import TextTable, load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = PROJECT_ROOT / "build/iso/first-five/srwz-first-five.iso"
DEFAULT_REPORT = (
    PROJECT_ROOT / "work/verification/first-five-iso-content.json"
)
BUILD_CONFIG = PROJECT_ROOT / "config/iso/first-five-build.json"
COMPONENT_REPORT = (
    PROJECT_ROOT / "work/build/first-five/components/component-validation.json"
)
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
BASE_CODEBOOK = PROJECT_ROOT / "config/encoding/codebook.json"
CODEBOOK_PROPOSAL = (
    PROJECT_ROOT / "work/writeback/first-five-codebook-proposal.json"
)
STAGES = (1, 2, 3, 4, 5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_translations(path: Path, stages: set[int]) -> dict[str, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["id"]: entry["translation"]
        for entry in document["entries"]
        if int(entry["id"].split("/")[1]) in stages
    }


def load_overrides() -> dict[str, int]:
    base = json.loads(BASE_CODEBOOK.read_text(encoding="utf-8"))
    proposal = json.loads(CODEBOOK_PROPOSAL.read_text(encoding="utf-8"))
    assignments = [*base["assignments"], *proposal["assignments"]]
    return {
        assignment["character"]: int(assignment["code"], 16)
        for assignment in assignments
    }


def augmented_table(table: TextTable, overrides: dict[str, int]) -> TextTable:
    return TextTable(
        characters={
            **table.characters,
            **{code: character for character, code in overrides.items()},
        },
        tags=table.tags,
    )


def read_members(iso_path: Path, paths: tuple[str, ...]) -> dict[str, bytes]:
    image = scan_iso9660(iso_path)
    members = member_map(image)
    missing = sorted(set(paths) - set(members))
    if missing:
        raise SystemExit(f"final ISO is missing members: {missing!r}")
    result = {}
    with iso_path.open("rb") as source:
        for path in paths:
            member = members[path]
            source.seek(member.extent_lba * SECTOR_SIZE)
            data = source.read(member.size)
            if len(data) != member.size:
                raise SystemExit(f"short final ISO member read: {path}")
            result[path] = data
    return result


def main() -> int:
    args = parse_args()
    iso_path = project_path(args.iso)
    report_path = project_path(args.report)
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")

    config = json.loads(BUILD_CONFIG.read_text(encoding="utf-8"))
    component = json.loads(COMPONENT_REPORT.read_text(encoding="utf-8"))
    expected_replacements = {
        item["member"]: item for item in config["replacements"]
    }
    required_members = (
        "SLPS_258.87",
        "HEDBDY/HB.BIN",
        "DATA/STAGE.BIN",
    )
    members = read_members(iso_path, required_members)
    for member_path, data in members.items():
        expected = expected_replacements[member_path]
        if (
            len(data) != expected["size"]
            or sha256_bytes(data) != expected["sha256"]
        ):
            raise SystemExit(
                f"final ISO replacement mismatch: {member_path}"
            )

    slps = members["SLPS_258.87"]
    hb = members["HEDBDY/HB.BIN"]
    stage_archive = members["DATA/STAGE.BIN"]
    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member="HEDBDY/HB.BIN",
        table_start=30320,
        table_end=31144,
    )
    offsets = read_executable_archive_offsets(
        hb,
        offset_spec,
        len(stage_archive),
    )
    if len(offsets) != 206 or offsets[-1] != len(stage_archive):
        raise SystemExit("final ISO HB/STAGE layout mismatch")

    table = augmented_table(load_text_table(TEXT_TABLE), load_overrides())
    functions = read_stage_function_addresses(slps)
    conditions = load_translations(
        PROJECT_ROOT / "corpus/zh/story-conditions.json",
        set(STAGES),
    )
    speakers = load_translations(
        PROJECT_ROOT / "corpus/zh/story-speakers.json",
        set(STAGES),
    )
    component_stages = {
        item["stage_index"]: item for item in component["stages"]
    }

    stage_reports = []
    total_entries = 0
    for stage in STAGES:
        dialogue = load_translations(
            PROJECT_ROOT
            / f"corpus/zh/story-dialogue/stage-{stage:03d}.json",
            {stage},
        )
        expected_texts = {
            **dialogue,
            **{
                entry_id: translation
                for entry_id, translation in conditions.items()
                if int(entry_id.split("/")[1]) == stage
            },
            **{
                entry_id: translation
                for entry_id, translation in speakers.items()
                if int(entry_id.split("/")[1]) == stage
            },
        }
        chunk = stage_archive[offsets[stage]:offsets[stage + 1]]
        decoded = decode(chunk)
        expected_stage = component_stages[stage]
        encoded = chunk[:decoded.consumed]
        padding = chunk[decoded.consumed:]
        if any(padding):
            raise SystemExit(f"stage {stage:03d} has non-zero archive padding")
        if (
            decoded.consumed != expected_stage["output_encoded_size"]
            or sha256_bytes(encoded)
            != expected_stage["output_encoded_sha256"]
            or len(decoded.output) != expected_stage["output_size"]
        ):
            raise SystemExit(f"stage {stage:03d} codec metadata mismatch")

        parsed = parse_stage(
            decoded.output,
            table,
            stage_index=stage,
            function_address=functions[stage],
        )
        actual_texts = {
            entry.entry_id: entry.text for entry in parsed.entries
        }
        if actual_texts != expected_texts:
            missing = sorted(set(expected_texts) - set(actual_texts))
            extra = sorted(set(actual_texts) - set(expected_texts))
            wrong = sorted(
                entry_id
                for entry_id in set(expected_texts) & set(actual_texts)
                if expected_texts[entry_id] != actual_texts[entry_id]
            )
            raise SystemExit(
                f"stage {stage:03d} translated text mismatch: "
                f"missing={missing[:3]!r}, extra={extra[:3]!r}, "
                f"wrong={wrong[:3]!r}"
            )
        if parsed.unknown_code_count:
            raise SystemExit(
                f"stage {stage:03d} has "
                f"{parsed.unknown_code_count} unknown codes"
            )

        total_entries += len(expected_texts)
        stage_reports.append(
            {
                "stage_index": stage,
                "archive_offset": offsets[stage],
                "archive_next_offset": offsets[stage + 1],
                "encoded_size": decoded.consumed,
                "encoded_sha256": sha256_bytes(encoded),
                "padding_size": len(padding),
                "padding_all_zero": True,
                "decoded_size": len(decoded.output),
                "decoded_sha256": sha256_bytes(decoded.output),
                "dialogue_count": len(dialogue),
                "condition_count": sum(
                    entry_id.startswith(
                        f"story/{stage:03d}/condition/"
                    )
                    for entry_id in expected_texts
                ),
                "speaker_count": sum(
                    entry_id.startswith(f"story/{stage:03d}/speaker/")
                    for entry_id in expected_texts
                ),
                "translation_entry_count": len(expected_texts),
                "entry_id_set_exact": True,
                "translated_text_exact": True,
                "unknown_code_count": 0,
            }
        )

    output = config["output"]
    iso_size = iso_path.stat().st_size
    iso_sha256 = sha256_file(iso_path)
    report = {
        "schema_version": 1,
        "status": "passed",
        "scope": (
            "Independent final-ISO readback of stages 001-005; "
            "this is not a five-battle gameplay playthrough."
        ),
        "iso": {
            "path": str(iso_path.relative_to(PROJECT_ROOT)),
            "size": iso_size,
            "sha256": iso_sha256,
        },
        "stage_indices": list(STAGES),
        "stage_count": len(STAGES),
        "translation_entry_count": total_entries,
        "members": {
            path: {
                "size": len(data),
                "sha256": sha256_bytes(data),
                "replacement_exact": True,
            }
            for path, data in members.items()
        },
        "hb_offset_count": len(offsets),
        "hb_offset_reread_exact": True,
        "stages": stage_reports,
        "checks": {
            "iso_size": iso_size
            == config["source_iso"]["size"]
            == output.get("expected_size", iso_size),
            "replacement_members_exact": True,
            "hb_stage_offsets_valid": True,
            "encoded_streams_exact": True,
            "decoded_sizes_exact": True,
            "archive_padding_zero": True,
            "entry_id_sets_exact": True,
            "dialogue_conditions_speakers_exact": True,
            "unknown_code_count_zero": True,
        },
        "runtime_acceptance": (
            "static final-ISO content readback; runtime evidence is separate"
        ),
    }
    expected_iso_sha = (
        PROJECT_ROOT / output["report"]
    )
    if expected_iso_sha.is_file():
        iso_report = json.loads(expected_iso_sha.read_text(encoding="utf-8"))
        if (
            report["iso"]["size"] != iso_report["output_iso"]["size"]
            or report["iso"]["sha256"]
            != iso_report["output_iso"]["sha256"]
        ):
            raise SystemExit("final ISO image hash mismatch")
    if not all(report["checks"].values()):
        failed = [
            name for name, passed in report["checks"].items() if not passed
        ]
        raise SystemExit(f"final ISO content checks failed: {failed!r}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "first-five final ISO readback:",
        f"stages={len(STAGES)}",
        f"translations={total_entries}",
        "status=passed",
    )
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
