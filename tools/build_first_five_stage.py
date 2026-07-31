#!/usr/bin/env python3
"""Build an offline first-five-stage STAGE/HB component candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.archive import load_offset_layout
from srwz.codec import decode, reencode_changed_suffix
from srwz.font import sha256_bytes
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.stage import parse_stage, read_stage_function_addresses
from srwz.text import TextTable, load_text_table
from srwz.writeback import rebuild_aligned_archive
from srwz.writers import (
    build_executable_offset_patch_plan,
    repack_stage_texts_in_place,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
TEXT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
PROPOSAL = WORK_ROOT / "writeback/first-five-codebook-proposal.json"
ALLOCATION_REGISTRY = (
    PROJECT_ROOT / "config/encoding/first-five-allocations.json"
)
OUTPUT_ROOT = WORK_ROOT / "build/first-five/components"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--stages",
        default="1-5",
        help="Comma-separated stage indices or inclusive ranges (default: 1-5).",
    )
    parser.add_argument(
        "--strategy",
        choices=("greedy", "literal", "rust-maximum"),
        default="rust-maximum",
        help=(
            "Changed-suffix encoding strategy: greedy, literal or the "
            "repository-owned Rust maximum parser "
            "(default: rust-maximum)."
        ),
    )
    parser.add_argument(
        "--min-match-length",
        type=int,
        default=2,
        help="Encoder minimum match length (default: 2).",
    )
    parser.add_argument(
        "--max-match-chain",
        type=int,
        default=1024,
        help="Encoder candidate-chain limit (default: 1024).",
    )
    parser.add_argument(
        "--lazy-matching",
        action="store_true",
        help="Prefer a longer match at the next byte when beneficial.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
        help="Component output directory (default: first-five production path).",
    )
    parser.add_argument(
        "--preserve-stage-layout",
        action="store_true",
        help=(
            "Require every rebuilt stream to fit its original aligned chunk "
            "and pad it back to the original span, preserving all STAGE/HB "
            "offsets and the ISO member size."
        ),
    )
    return parser.parse_args()


def _stage_indices(value: str) -> set[int]:
    stages: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            raise SystemExit("empty item in --stages")
        if "-" in item:
            first_text, last_text = item.split("-", 1)
            first = int(first_text)
            last = int(last_text)
            if first > last:
                raise SystemExit(f"descending stage range: {item}")
            stages.update(range(first, last + 1))
        else:
            stages.add(int(item))
    if not stages or min(stages) < 1 or max(stages) > 204:
        raise SystemExit("--stages must select indices from 1 through 204")
    return stages


def _translations(path: Path, stages: set[int]) -> dict[str, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        entry["id"]: entry["translation"]
        for entry in document["entries"]
        if int(entry["id"].split("/")[1]) in stages
    }


def _speaker_translations(stages: set[int]) -> dict[int, dict[int, str]]:
    document = json.loads(
        (PROJECT_ROOT / "corpus/zh/story-speakers.json").read_text(
            encoding="utf-8"
        )
    )
    result = {stage: {} for stage in stages}
    for entry in document["entries"]:
        parts = entry["id"].split("/")
        stage = int(parts[1])
        if stage in stages:
            result[stage][int(parts[-1])] = entry["translation"]
    return result


def _load_overrides() -> dict[str, int]:
    base = json.loads(
        (PROJECT_ROOT / "config/encoding/codebook.json").read_text(
            encoding="utf-8"
        )
    )
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    if proposal.get("allocation_registry", {}).get("sha256") != (
        sha256_bytes(ALLOCATION_REGISTRY.read_bytes())
    ):
        raise SystemExit("codebook proposal allocation registry drift")
    assignments = [*base["assignments"], *proposal["assignments"]]
    return {
        assignment["character"]: int(assignment["code"], 16)
        for assignment in assignments
    }


def _augmented_table(table: TextTable, overrides: dict[str, int]) -> TextTable:
    return TextTable(
        characters={
            **table.characters,
            **{code: character for character, code in overrides.items()},
        },
        tags=table.tags,
    )


def _read_member(iso_path: Path, member_path: str) -> bytes:
    image = scan_iso9660(iso_path)
    member = member_map(image).get(member_path)
    if member is None:
        raise SystemExit(f"source ISO has no {member_path}")
    with iso_path.open("rb") as source:
        source.seek(member.extent_lba * SECTOR_SIZE)
        data = source.read(member.size)
    if len(data) != member.size:
        raise SystemExit(f"short ISO member read: {member_path}")
    return data


def main() -> int:
    args = parse_args()
    stages = _stage_indices(args.stages)
    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root
    report_path = output_root / "component-validation.json"
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    if not PROPOSAL.is_file():
        raise SystemExit(
            "missing codebook proposal; run audit_first_five_writeback.py"
        )

    config = json.loads(
        (PROJECT_ROOT / "config/canary/complete-content.json").read_text(
            encoding="utf-8"
        )
    )
    inputs = config["inputs"]
    table = load_text_table(TEXT_TABLE)
    overrides = _load_overrides()
    output_table = _augmented_table(table, overrides)
    source_stage = (PROJECT_ROOT / inputs["stage"]["path"]).read_bytes()
    layout = load_offset_layout(
        PROJECT_ROOT / inputs["stage_layout"]
    )
    if (
        len(source_stage) != inputs["stage"]["size"]
        or sha256_bytes(source_stage) != inputs["stage"]["sha256"]
        or tuple(layout.offsets)[-1] != len(source_stage)
    ):
        raise SystemExit("source STAGE baseline mismatch")
    source_slps = (PROJECT_ROOT / inputs["slps"]["path"]).read_bytes()
    functions = read_stage_function_addresses(source_slps)
    source_iso = PROJECT_ROOT / inputs["source_iso"]["path"]
    source_hb = _read_member(source_iso, inputs["hb"]["member"])
    if (
        len(source_hb) != inputs["hb"]["size"]
        or sha256_bytes(source_hb) != inputs["hb"]["sha256"]
    ):
        raise SystemExit("source HB baseline mismatch")

    dialogue_by_stage = {
        stage: _translations(
            PROJECT_ROOT
            / f"corpus/zh/story-dialogue/stage-{stage:03d}.json",
            {stage},
        )
        for stage in stages
    }
    conditions = _translations(
        PROJECT_ROOT / "corpus/zh/story-conditions.json",
        stages,
    )
    speakers = _speaker_translations(stages)
    source_chunks = [
        source_stage[layout.offsets[index]:layout.offsets[index + 1]]
        for index in range(len(layout.offsets) - 1)
    ]
    output_chunks = list(source_chunks)
    stage_reports = []
    for stage in sorted(stages):
        decoded = decode(source_chunks[stage])
        replacements = {
            **dialogue_by_stage[stage],
            **{
                entry_id: translation
                for entry_id, translation in conditions.items()
                if int(entry_id.split("/")[1]) == stage
            },
        }
        write = repack_stage_texts_in_place(
            decoded.output,
            table,
            stage_index=stage,
            function_address=functions[stage],
            replacements=replacements,
            speaker_replacements=speakers[stage],
            overrides=overrides,
        )
        encoded = reencode_changed_suffix(
            source_chunks[stage],
            write.data,
            strategy=args.strategy,
            min_match_length=args.min_match_length,
            max_match_chain=args.max_match_chain,
            lazy_matching=args.lazy_matching,
        )
        round_trip = decode(encoded)
        if round_trip.output != write.data or round_trip.consumed != len(encoded):
            raise SystemExit(f"stage {stage:03d} codec round-trip mismatch")
        reparsed = parse_stage(
            round_trip.output,
            output_table,
            stage_index=stage,
            function_address=functions[stage],
        )
        actual = {entry.entry_id: entry.text for entry in reparsed.entries}
        if any(actual.get(key) != value for key, value in replacements.items()):
            raise SystemExit(f"stage {stage:03d} translated reread mismatch")
        if args.preserve_stage_layout:
            source_chunk_size = len(source_chunks[stage])
            if len(encoded) > source_chunk_size:
                raise SystemExit(
                    f"stage {stage:03d} encoded stream exceeds its fixed "
                    f"chunk: {len(encoded)} > {source_chunk_size}"
                )
            output_chunks[stage] = encoded + bytes(
                source_chunk_size - len(encoded)
            )
        else:
            output_chunks[stage] = encoded
        stage_reports.append(
            {
                **write.to_metadata(),
                "dialogue_count": len(dialogue_by_stage[stage]),
                "condition_count": len(replacements) - len(dialogue_by_stage[stage]),
                "speaker_count": len(speakers[stage]),
                "source_encoded_size": decoded.consumed,
                "output_encoded_size": len(encoded),
                "source_chunk_size": len(source_chunks[stage]),
                "output_chunk_size": len(output_chunks[stage]),
                "chunk_span_preserved": (
                    len(output_chunks[stage]) == len(source_chunks[stage])
                ),
                "output_encoded_sha256": sha256_bytes(encoded),
                "codec_strategy": (
                    f"preserved_prefix_{args.strategy}_suffix"
                ),
                "codec_options": {
                    "min_match_length": args.min_match_length,
                    "max_match_chain": args.max_match_chain,
                    "lazy_matching": args.lazy_matching,
                },
                "codec_round_trip_exact": True,
                "translated_reread_exact": True,
            }
        )

    rebuilt_stage, rebuilt_offsets = rebuild_aligned_archive(
        output_chunks,
        alignment=16,
    )
    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member=inputs["hb"]["member"],
        table_start=30320,
        table_end=31144,
    )
    source_offsets = read_executable_archive_offsets(
        source_hb,
        offset_spec,
        len(source_stage),
    )
    if source_offsets != tuple(layout.offsets):
        raise SystemExit("source HB/STAGE offsets mismatch")
    plan = build_executable_offset_patch_plan(
        source_hb,
        offset_spec,
        rebuilt_offsets,
        source_name=inputs["hb"]["member"],
    )
    rebuilt_hb = plan.apply(source_hb)
    if read_executable_archive_offsets(
        rebuilt_hb,
        offset_spec,
        len(rebuilt_stage),
    ) != rebuilt_offsets:
        raise SystemExit("rebuilt HB offset reread mismatch")

    report = {
        "schema_version": 1,
        "status": "offline_components_validated_runtime_not_tested",
        "stage_indices": sorted(stages),
        "codebook_proposal": str(PROPOSAL),
        "codebook_assignment_count": len(overrides),
        "stages": stage_reports,
        "outputs": {
            "stage": {
                "size": len(rebuilt_stage),
                "sha256": sha256_bytes(rebuilt_stage),
            },
            "hb": {
                "size": len(rebuilt_hb),
                "sha256": sha256_bytes(rebuilt_hb),
            },
        },
        "unchanged_chunk_count": len(output_chunks) - len(stages),
        "stage_layout_preserved": (
            tuple(rebuilt_offsets) == tuple(layout.offsets)
        ),
        "hb_offset_reread_exact": True,
        "runtime_acceptance": "not tested",
    }
    outputs = {
        output_root / "DATA/STAGE.BIN": rebuilt_stage,
        output_root / "HEDBDY/HB.BIN": rebuilt_hb,
    }
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "first-five STAGE:",
        f"records={sum(item['allocation_count'] for item in stage_reports)}",
        f"size={len(source_stage)}->{len(rebuilt_stage)}",
        "HB reread=exact",
    )
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
