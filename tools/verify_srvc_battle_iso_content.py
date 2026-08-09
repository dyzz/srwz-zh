#!/usr/bin/env python3
"""Independently reread every indexed SRVC battle subtitle from the final ISO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.archive import sha256_file
from srwz.font import sha256_bytes
from srwz.image_export import parse_seg_offsets
from srwz.srvc import parse_srvc_archive, parse_srvc_archive_with_layout
from srwz.text import (
    control_notation_tokens,
    load_text_table,
    original_fullwidth_ascii_overrides,
)
from srwz.text import project_runtime_text_table

from verify_full_story_iso_content import TEXT_TABLE, load_overrides, read_members


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO = PROJECT_ROOT / "build/iso/zh-release-full-story/srwz-zh-release-full-story-r13.iso"
DEFAULT_COMPONENT_MANIFEST = PROJECT_ROOT / "manifests/full-story-components-validation.json"
DEFAULT_COMPONENT_CONFIG = PROJECT_ROOT / "config/full-story-components.json"
DEFAULT_ISO_CONFIG = PROJECT_ROOT / "config/iso/zh-release-full-story-build.json"
DEFAULT_PROPOSAL = PROJECT_ROOT / "work/writeback/zh-release-codebook-proposal.json"
DEFAULT_REPORT = PROJECT_ROOT / "work/verification/zh-release-srvc-battle-content.json"
DEFAULT_MANIFEST = PROJECT_ROOT / "manifests/zh-release-srvc-battle-iso-content-validation.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--component-manifest", type=Path, default=DEFAULT_COMPONENT_MANIFEST)
    parser.add_argument("--component-config", type=Path, default=DEFAULT_COMPONENT_CONFIG)
    parser.add_argument("--iso-config", type=Path, default=DEFAULT_ISO_CONFIG)
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def control_signature(text: str) -> tuple[tuple[str, str], ...]:
    return tuple((token.kind, token.text) for token in control_notation_tokens(text))


def locked_bytes(reference: dict, label: str) -> tuple[Path, bytes]:
    path = PROJECT_ROOT / reference["path"]
    data = path.read_bytes()
    if len(data) != reference["size"] or sha256_bytes(data) != reference["sha256"]:
        raise SystemExit(f"{label} lock drift")
    return path, data


def main() -> int:
    args = parse_args()
    iso_path = project_path(args.iso)
    component_path = project_path(args.component_manifest)
    component_config_path = project_path(args.component_config)
    iso_config_path = project_path(args.iso_config)
    proposal_path = project_path(args.proposal)
    report_path = project_path(args.report)
    manifest_path = project_path(args.manifest)
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")

    component = json.loads(component_path.read_text(encoding="utf-8"))
    component_config = json.loads(component_config_path.read_text(encoding="utf-8"))
    iso_config = json.loads(iso_config_path.read_text(encoding="utf-8"))
    if component.get("status") != iso_config.get("component_required_status"):
        raise SystemExit("component manifest status mismatch")
    output_locks = component.get("outputs")
    if not isinstance(output_locks, dict):
        raise SystemExit("component output locks are missing")
    members = read_members(iso_path, tuple(output_locks))
    for member, data in members.items():
        lock = output_locks[member]
        if len(data) != lock["size"] or sha256_bytes(data) != lock["sha256"]:
            raise SystemExit(f"final ISO component mismatch: {member}")

    iso_size = iso_path.stat().st_size
    iso_sha256 = sha256_file(iso_path)
    if (
        iso_size != iso_config["output"]["expected_size"]
        or iso_sha256 != iso_config["output"]["expected_sha256"]
    ):
        raise SystemExit("final ISO lock mismatch")

    reference = component_config["srvc_battle_text"]
    _corpus_path, corpus_data = locked_bytes(reference["corpus"], "SRVC corpus")
    _bin_path, source_bin = locked_bytes(reference["original_bin"], "original SRVC.BIN")
    _seg_path, source_seg = locked_bytes(reference["original_seg"], "original SRVC.SEG")
    corpus = json.loads(corpus_data.decode("utf-8"))
    source_table = load_text_table(TEXT_TABLE)
    primary, aliases, _proposal = load_overrides(proposal_path)
    output_table = project_runtime_text_table(source_table, primary)
    output_table = project_runtime_text_table(output_table, aliases)
    output_table = project_runtime_text_table(
        output_table, original_fullwidth_ascii_overrides(source_table)
    )

    output_bin = members["BTL/SRVC.BIN"]
    output_seg = members["BTL/SRVC.SEG"]
    offsets = parse_seg_offsets(source_seg, len(source_bin))
    source_chunks = parse_srvc_archive(source_bin, offsets, source_table)
    output_chunks = parse_srvc_archive_with_layout(
        output_bin, offsets, source_chunks, output_table
    )

    first_records = {}
    occurrence_counts = {}
    for chunk in source_chunks:
        for record in chunk.records:
            first_records.setdefault(record.text, record)
            occurrence_counts[record.text] = occurrence_counts.get(record.text, 0) + 1
    ordered_sources = sorted(
        first_records,
        key=lambda text: (first_records[text].archive_text_start, text),
    )
    entries = corpus["entries"]
    translations = {}
    for index, (source_text, entry) in enumerate(zip(ordered_sources, entries)):
        entry_id = f"battle:{index:05d}"
        if (
            entry["id"] != entry_id
            or entry["source_text_sha256"] != sha256_bytes(source_text.encode("utf-8"))
            or entry["occurrence_count"] != occurrence_counts[source_text]
            or entry["translation"].count("\\n") != source_text.count("\\n")
            or "\n" in entry["translation"]
            or control_signature(entry["translation"]) != control_signature(source_text)
        ):
            raise SystemExit(f"SRVC corpus/readback binding drift: {entry_id}")
        translations[source_text] = entry["translation"]

    readback_count = 0
    metadata_exact = True
    source_tail_exact = True
    zero_chunks_exact = True
    for source_chunk, output_chunk in zip(source_chunks, output_chunks):
        metadata_exact &= [record.metadata for record in source_chunk.records] == [
            record.metadata for record in output_chunk.records
        ]
        if not source_chunk.records:
            zero_chunks_exact &= source_bin[
                source_chunk.archive_start : source_chunk.archive_end
            ] == output_bin[source_chunk.archive_start : source_chunk.archive_end]
            continue
        tail_start = source_chunk.archive_start + source_chunk.indexed_text_end
        source_tail_exact &= source_bin[tail_start : source_chunk.archive_end] == output_bin[
            tail_start : source_chunk.archive_end
        ]
        for source_record, output_record in zip(source_chunk.records, output_chunk.records):
            if output_record.text != translations[source_record.text]:
                raise SystemExit(
                    f"SRVC final ISO translated reread mismatch: "
                    f"{source_record.chunk_index}/{source_record.record_index}"
                )
            readback_count += 1

    expected = reference["expected"]
    checks = {
        "iso_hash_exact": True,
        "all_component_members_exact": True,
        "srvc_bin_size_preserved": len(output_bin) == len(source_bin),
        "srvc_seg_byte_exact": output_seg == source_seg,
        "chunk_count_exact": len(output_chunks) == expected["chunk_count"],
        "indexed_record_count_exact": readback_count == expected["record_count"],
        "unique_text_count_exact": len(translations) == expected["unique_text_count"],
        "translated_reread_exact": readback_count == corpus["record_count"],
        "metadata_byte_exact": metadata_exact,
        "original_unindexed_tails_byte_exact": source_tail_exact,
        "zero_record_chunks_byte_exact": zero_chunks_exact,
        "control_tokens_preserved": True,
    }
    report = {
        "schema_version": 1,
        "status": "srvc_battle_text_final_iso_static_readback_passed",
        "scope": (
            "Independent final-ISO readback of every indexed BTL/SRVC battle "
            "subtitle; gameplay runtime is separate."
        ),
        "iso": {
            "path": str(iso_path.relative_to(PROJECT_ROOT)),
            "size": iso_size,
            "sha256": iso_sha256,
        },
        "component_manifest": str(component_path.relative_to(PROJECT_ROOT)),
        "srvc": {
            "bin_size": len(output_bin),
            "bin_sha256": sha256_bytes(output_bin),
            "seg_size": len(output_seg),
            "seg_sha256": sha256_bytes(output_seg),
            "chunk_count": len(output_chunks),
            "indexed_chunk_count": sum(bool(chunk.records) for chunk in output_chunks),
            "zero_record_chunk_count": sum(not chunk.records for chunk in output_chunks),
            "record_count": readback_count,
            "unique_text_count": len(translations),
            "unindexed_tail_bytes_at_original_offsets": expected["unindexed_tail_bytes"],
        },
        "checks": checks,
        "runtime": {
            "status": "not_tested",
            "reason": (
                "Fresh new-game and load-game STAGE entry plus a voiced battle "
                "subtitle have not been captured for this exact ISO."
            ),
        },
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise SystemExit(f"SRVC final ISO checks failed: {failed!r}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest_status = "refreshed"
    else:
        if json.loads(manifest_path.read_text(encoding="utf-8")) != report:
            raise SystemExit("SRVC final ISO content manifest drift")
        manifest_status = "verified"
    print(
        "SRVC final ISO readback:",
        f"unique={len(translations)}",
        f"records={readback_count}",
        f"chunks={len(output_chunks)}",
        "status=passed",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
