#!/usr/bin/env python3
"""Build the complete translated STAGE/HB component with the Rust codec."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Mapping

from srwz.codec import decode_production as decode, reencode_changed_suffix
from srwz.diagnostics import require_work_output
from srwz.font import sha256_bytes
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.stage import parse_stage, read_stage_function_addresses
from srwz.text import (
    load_text_table,
    normalize_original_fullwidth_ascii,
    original_fullwidth_ascii_overrides,
)
from srwz.writeback import rebuild_aligned_archive
from srwz.writers import (
    build_executable_offset_patch_plan,
    repack_stage_texts_in_place,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/story-component.json"
_STAGE_NAME = re.compile(r"stage-(\d{3})\.json$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build every committed story translation into fixed-size "
            "STAGE.BIN and HB.BIN components."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help=(
            "Compress independent STAGE chunks concurrently; use 1 for the "
            "serial reference path (default: 4)."
        ),
    )
    return parser.parse_args()


def _project_path(reference: str) -> Path:
    path = Path(reference)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise SystemExit(f"unsupported JSON contract: {path}")
    return document


def _locked_file(reference: Mapping[str, object], *, label: str) -> tuple[Path, bytes]:
    path = _project_path(str(reference.get("path", "")))
    payload = path.read_bytes()
    if (
        reference.get("size") != len(payload)
        or reference.get("sha256") != sha256_bytes(payload)
    ):
        raise SystemExit(f"{label} size or SHA-256 drift")
    return path, payload


def _keyword_spans(text: str, *, label: str) -> tuple[str, ...]:
    spans = []
    opened_at = None
    for index, character in enumerate(text):
        if character == "《":
            if opened_at is not None:
                raise SystemExit(f"{label} has nested runtime-keyword marker")
            opened_at = index
        elif character == "》":
            if opened_at is None or index == opened_at + 1:
                raise SystemExit(f"{label} has malformed runtime-keyword marker")
            spans.append(text[opened_at + 1 : index])
            opened_at = None
    if opened_at is not None:
        raise SystemExit(f"{label} has an unterminated runtime-keyword marker")
    return tuple(spans)


def _runtime_keyword_catalog(reference: Mapping[str, object]) -> dict[str, str]:
    path, payload = _locked_file(reference, label="runtime-keyword catalog")
    document = json.loads(payload.decode("utf-8"))
    if (
        document.get("schema_version") != 1
        or document.get("profile_id") != "srwz-stage-runtime-keywords-v1"
        or document.get("status") != "approved"
        or not isinstance(document.get("entries"), list)
        or len(document["entries"]) != 52
    ):
        raise SystemExit("runtime-keyword catalog identity drift")
    by_source = {}
    indices = set()
    for row in document["entries"]:
        source = row.get("source_term")
        translation = row.get("translation")
        source_hash = row.get("source_text_sha256")
        index = row.get("entry_index")
        if (
            not isinstance(source, str)
            or not source
            or not isinstance(translation, str)
            or not translation
            or source_hash != hashlib.sha256(source.encode("utf-8")).hexdigest()
            or not isinstance(index, int)
            or index in indices
            or source in by_source
        ):
            raise SystemExit("runtime-keyword catalog row drift")
        indices.add(index)
        by_source[source] = translation
    if indices != set(range(52)):
        raise SystemExit("runtime-keyword catalog slots must be exactly 0..51")
    return by_source


def _validate_runtime_keywords(
    source_text: str,
    translated_text: str,
    catalog: Mapping[str, str],
    *,
    label: str,
) -> int:
    source_spans = _keyword_spans(source_text, label=f"{label} source")
    translated_spans = _keyword_spans(
        translated_text, label=f"{label} translation"
    )
    if len(source_spans) != len(translated_spans):
        raise SystemExit(
            f"{label} runtime-keyword span-count drift: "
            f"source={len(source_spans)} translation={len(translated_spans)}"
        )
    for span_index, (source, translated) in enumerate(
        zip(source_spans, translated_spans)
    ):
        expected = catalog.get(source)
        if expected is None:
            raise SystemExit(
                f"{label} runtime-keyword source is not cataloged: {source!r}"
            )
        if translated != expected:
            raise SystemExit(
                f"{label} runtime-keyword mismatch at span {span_index}: "
                f"source={source!r} expected={expected!r} actual={translated!r}"
            )
    return len(source_spans)


def _read_iso_member(iso_path: Path, reference: Mapping[str, object]) -> bytes:
    member_name = reference.get("member")
    if not isinstance(member_name, str) or not member_name:
        raise SystemExit("source HB member is invalid")
    member = member_map(scan_iso9660(iso_path)).get(member_name)
    if member is None:
        raise SystemExit(f"source ISO has no {member_name}")
    with iso_path.open("rb") as source:
        source.seek(member.extent_lba * SECTOR_SIZE)
        payload = source.read(member.size)
    if (
        len(payload) != reference.get("size")
        or sha256_bytes(payload) != reference.get("sha256")
    ):
        raise SystemExit("source HB size or SHA-256 drift")
    return payload


def _stage_files(reference: Mapping[str, object]) -> dict[int, Path]:
    root = _project_path(str(reference.get("dialogue_root", "")))
    result = {}
    for path in sorted(root.glob("stage-*.json")):
        match = _STAGE_NAME.fullmatch(path.name)
        if match is None:
            continue
        stage = int(match.group(1))
        if stage in result:
            raise SystemExit(f"duplicate story stage: {stage:03d}")
        result[stage] = path
    indices = sorted(result)
    indices_sha256 = sha256_bytes(
        json.dumps(indices, separators=(",", ":")).encode("utf-8")
    )
    if (
        len(indices) != reference.get("expected_stage_count")
        or indices_sha256 != reference.get("expected_stage_indices_sha256")
    ):
        raise SystemExit("committed story-stage selection drift")
    return result


def _entry_translations(path: Path, stages: set[int] | None = None) -> dict[str, str]:
    document = _json(path)
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise SystemExit(f"translation entries are invalid: {path}")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit(f"translation entry is invalid: {path}")
        entry_id = entry.get("id")
        translation = entry.get("translation")
        if not isinstance(entry_id, str) or not isinstance(translation, str):
            raise SystemExit(f"translation entry fields are invalid: {path}")
        if stages is not None and int(entry_id.split("/")[1]) not in stages:
            continue
        result[entry_id] = normalize_original_fullwidth_ascii(translation)
    return result


def _speaker_translations(path: Path, stages: set[int]) -> dict[int, dict[int, str]]:
    document = _json(path)
    result = {stage: {} for stage in stages}
    for entry in document.get("entries", []):
        parts = entry["id"].split("/")
        stage = int(parts[1])
        if stage in result:
            result[stage][int(parts[-1])] = normalize_original_fullwidth_ascii(
                entry["translation"]
            )
    return result


def _load_overrides(
    proposal_path: Path,
    allocation_registry_path: Path,
    base_codebook_path: Path,
) -> tuple[dict[str, int], dict]:
    base = _json(base_codebook_path)
    proposal = _json(proposal_path)
    if proposal.get("allocation_registry", {}).get("sha256") != _sha256(
        allocation_registry_path
    ):
        raise SystemExit("codebook proposal allocation registry drift")
    assignments = [*base["assignments"], *proposal["assignments"]]
    # STAGE dialogue consumes ordinary visible glyphs through the two-byte
    # renderer path. Keep every canonical punctuation assignment here too:
    # a raw one-byte character such as ``~`` shifts the following double-byte
    # Chinese stream until the next newline and produces mixed/noisy glyphs.
    # Runtime substitutions are still emitted byte-exact by ``encode_text``
    # before these overrides are consulted. Stock Latin and digit codes are
    # restored below through ``original_fullwidth_ascii_overrides``.
    overrides = {
        assignment["character"]: int(assignment["code"], 16)
        for assignment in assignments
    }
    aliases = {
        assignment["character"]: int(assignment["code"], 16)
        for assignment in proposal.get("surface_alias_assignments", [])
    }
    alias_report = proposal.get("surface_safe_aliases", {})
    conditional = {
        assignment["character"]
        for assignment in proposal["assignments"]
        if 0x8140 <= int(assignment["code"], 16) < 0x889F
    }
    unaliased = conditional - set(aliases)
    if (
        not set(aliases) <= conditional
        or alias_report.get("assignment_count") != len(aliases)
        or alias_report.get("conditional_primary_assignment_count")
        != len(conditional)
        or alias_report.get("unaliased_conditional_assignment_count")
        != len(unaliased)
        or alias_report.get("all_selected_assignments") is not (not unaliased)
        or any(0x8140 <= code < 0x889F for code in aliases.values())
    ):
        raise SystemExit("global safe-alias proposal contract failed")
    overrides.update(aliases)
    return overrides, proposal


def build(
    config_path: Path,
    *,
    workers: int = 4,
) -> tuple[dict[Path, bytes], dict]:
    if workers <= 0:
        raise SystemExit("story component workers must be positive")
    config = _json(config_path)
    if config.get("profile_id") != "srwz-zh-story-component-v1":
        raise SystemExit("story component profile identity drift")
    source = config["source"]
    slps_path, source_slps = _locked_file(source["slps"], label="source SLPS")
    stage_path, source_stage = _locked_file(source["stage"], label="source STAGE")
    table_path, _table_payload = _locked_file(
        source["text_table"], label="source text table"
    )
    codebook_path, _codebook_payload = _locked_file(
        source["base_codebook"], label="base codebook"
    )
    iso_path = _project_path(source["iso"])
    source_hb = _read_iso_member(iso_path, source["hb"])

    translations = config["translations"]
    stage_files = _stage_files(translations)
    stages = set(stage_files)
    conditions_path = _project_path(translations["conditions"])
    speakers_path = _project_path(translations["speakers"])
    conditions = _entry_translations(conditions_path, stages)
    speakers = _speaker_translations(speakers_path, stages)
    dialogue = {
        stage: _entry_translations(path, {stage})
        for stage, path in stage_files.items()
    }
    keyword_catalog = _runtime_keyword_catalog(translations["runtime_keywords"])

    font = config["font"]
    proposal_path = _project_path(font["proposal"])
    allocation_path = _project_path(font["allocation_registry"])
    if font.get("all_safe_aliases") is not True:
        raise SystemExit("story component must use every safe font alias")
    overrides, proposal = _load_overrides(
        proposal_path,
        allocation_path,
        codebook_path,
    )
    table = load_text_table(table_path)
    overrides.update(original_fullwidth_ascii_overrides(table))

    codec = config["codec"]
    if (
        codec.get("strategy") != "rust-fit"
        or codec.get("min_match_length") != 2
        or not isinstance(codec.get("max_match_chain"), int)
        or codec["max_match_chain"] <= 0
        or codec.get("lazy_matching") is not False
        or codec.get("preserve_stage_layout") is not True
    ):
        raise SystemExit("story component must use the Rust fit-to-budget profile")

    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member=source["hb"]["member"],
        table_start=30320,
        table_end=31144,
    )
    offsets = read_executable_archive_offsets(source_hb, offset_spec, len(source_stage))
    if offsets[0] != 0 or offsets[-1] != len(source_stage):
        raise SystemExit("source HB/STAGE offsets do not cover STAGE.BIN")
    functions = read_stage_function_addresses(source_slps)
    source_chunks = [
        source_stage[offsets[index] : offsets[index + 1]]
        for index in range(len(offsets) - 1)
    ]
    missing = []
    for stage_index in sorted(set(range(len(source_chunks))) - stages):
        source_output = decode(source_chunks[stage_index]).output
        if parse_stage(
            source_output,
            table,
            stage_index=stage_index,
            function_address=functions[stage_index],
        ).dialogue_count:
            missing.append(stage_index)
    if missing:
        raise SystemExit(
            "story corpus does not cover every source dialogue STAGE: "
            f"missing={missing}, unexpected=[]"
        )

    def build_stage(stage: int) -> tuple[int, bytes, dict]:
        decoded = decode(source_chunks[stage])
        parsed_source = parse_stage(
            decoded.output,
            table,
            stage_index=stage,
            function_address=functions[stage],
        )
        runtime_keyword_link_count = 0
        runtime_keyword_source_hashes = set()
        for entry in parsed_source.entries:
            if entry.kind != "dialogue" or "《" not in entry.text:
                continue
            translated = dialogue[stage].get(entry.entry_id)
            if translated is None:
                raise SystemExit(
                    f"missing translated runtime-keyword entry: {entry.entry_id}"
                )
            runtime_keyword_link_count += _validate_runtime_keywords(
                entry.text,
                translated,
                keyword_catalog,
                label=entry.entry_id,
            )
            runtime_keyword_source_hashes.update(
                hashlib.sha256(term.encode("utf-8")).hexdigest()
                for term in _keyword_spans(
                    entry.text, label=f"{entry.entry_id} source"
                )
            )
        stage_conditions = {
            entry_id: translation
            for entry_id, translation in conditions.items()
            if int(entry_id.split("/")[1]) == stage
        }
        replacements = {**dialogue[stage], **stage_conditions}
        write = repack_stage_texts_in_place(
            decoded.output,
            table,
            stage_index=stage,
            function_address=functions[stage],
            replacements=replacements,
            speaker_replacements=speakers[stage],
            overrides=overrides,
        )
        if write.source_dialogue_count <= 0:
            raise SystemExit(
                "story corpus includes a STAGE without source dialogue: "
                f"{stage:03d}"
            )
        encoded = reencode_changed_suffix(
            source_chunks[stage],
            write.data,
            strategy="rust-fit",
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=False,
            max_output_size=len(source_chunks[stage]),
            original_result=decoded,
        )
        output_chunk = encoded + bytes(len(source_chunks[stage]) - len(encoded))
        return stage, output_chunk, {
            **write.to_metadata(),
            "dialogue_count": len(dialogue[stage]),
            "condition_count": len(stage_conditions),
            "speaker_count": len(speakers[stage]),
            "runtime_keyword_link_count": runtime_keyword_link_count,
            "runtime_keyword_source_hashes": sorted(
                runtime_keyword_source_hashes
            ),
            "runtime_keyword_links_exact": True,
            "source_encoded_size": decoded.consumed,
            "output_encoded_size": len(encoded),
            "source_chunk_size": len(source_chunks[stage]),
            "output_chunk_size": len(output_chunk),
            "chunk_span_preserved": True,
            "output_encoded_sha256": sha256_bytes(encoded),
            "codec_strategy": "rust-fit",
            "codec_options": {
                "min_match_length": codec["min_match_length"],
                "max_match_chain": codec["max_match_chain"],
                "lazy_matching": False,
            },
            "codec_round_trip_exact": True,
            "translated_reread_exact": True,
        }

    ordered_stages = sorted(stages)
    if workers == 1:
        built_stages = map(build_stage, ordered_stages)
        executor = None
    else:
        executor = ThreadPoolExecutor(
            max_workers=min(workers, len(ordered_stages)),
            thread_name_prefix="srwz-stage",
        )
        built_stages = executor.map(build_stage, ordered_stages)
    output_chunks = list(source_chunks)
    stage_reports = []
    try:
        for stage, output_chunk, stage_report in built_stages:
            output_chunks[stage] = output_chunk
            stage_reports.append(stage_report)
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    runtime_keyword_link_count = sum(
        item["runtime_keyword_link_count"] for item in stage_reports
    )
    runtime_keyword_source_hashes = sorted(
        {
            source_hash
            for item in stage_reports
            for source_hash in item["runtime_keyword_source_hashes"]
        }
    )
    if (
        runtime_keyword_link_count
        != translations.get("expected_runtime_keyword_link_count")
        or len(runtime_keyword_source_hashes)
        != translations.get("expected_runtime_keyword_source_count")
    ):
        raise SystemExit(
            "runtime-keyword coverage drift: "
            f"links={runtime_keyword_link_count} "
            f"sources={len(runtime_keyword_source_hashes)}"
        )

    rebuilt_stage, rebuilt_offsets = rebuild_aligned_archive(output_chunks, alignment=16)
    if tuple(rebuilt_offsets) != tuple(offsets):
        raise SystemExit("fixed-size STAGE layout drift")
    plan = build_executable_offset_patch_plan(
        source_hb,
        offset_spec,
        rebuilt_offsets,
        source_name=source["hb"]["member"],
    )
    rebuilt_hb = plan.apply(source_hb)
    if read_executable_archive_offsets(
        rebuilt_hb, offset_spec, len(rebuilt_stage)
    ) != rebuilt_offsets:
        raise SystemExit("rebuilt HB offset reread mismatch")

    output_root = require_work_output(
        _project_path(config["outputs"]["component_root"]), WORK_ROOT
    )
    outputs = {
        output_root / "DATA/STAGE.BIN": rebuilt_stage,
        output_root / "HEDBDY/HB.BIN": rebuilt_hb,
    }
    report = {
        "schema_version": 1,
        "status": "offline_components_validated_runtime_not_tested",
        "profile_id": config["profile_id"],
        "inputs": {
            "config": {"path": str(config_path.relative_to(PROJECT_ROOT)), "sha256": _sha256(config_path)},
            "source_slps": {"path": str(slps_path.relative_to(PROJECT_ROOT)), "sha256": sha256_bytes(source_slps)},
            "source_stage": {"path": str(stage_path.relative_to(PROJECT_ROOT)), "sha256": sha256_bytes(source_stage)},
            "source_hb": {"member": source["hb"]["member"], "sha256": sha256_bytes(source_hb)},
            "text_table": {"path": str(table_path.relative_to(PROJECT_ROOT)), "sha256": _sha256(table_path)},
            "base_codebook": {"path": str(codebook_path.relative_to(PROJECT_ROOT)), "sha256": _sha256(codebook_path)},
            "proposal": {"path": str(proposal_path.relative_to(PROJECT_ROOT)), "sha256": _sha256(proposal_path)},
            "allocation_registry": {"path": str(allocation_path.relative_to(PROJECT_ROOT)), "sha256": _sha256(allocation_path)},
            "conditions": {"path": str(conditions_path.relative_to(PROJECT_ROOT)), "sha256": _sha256(conditions_path)},
            "speakers": {"path": str(speakers_path.relative_to(PROJECT_ROOT)), "sha256": _sha256(speakers_path)},
            "runtime_keywords": {
                "path": translations["runtime_keywords"]["path"],
                "sha256": translations["runtime_keywords"]["sha256"],
            },
        },
        "stage_indices": sorted(stages),
        "codebook_proposal": str(proposal_path.relative_to(PROJECT_ROOT)),
        "codebook_assignment_count": len(overrides),
        "surface_safe_alias_characters": "",
        "all_safe_aliases": True,
        "safe_alias_assignment_count": len(proposal.get("surface_alias_assignments", [])),
        "unaliased_conditional_localized_assignment_count": proposal.get("surface_safe_aliases", {}).get("unaliased_conditional_assignment_count"),
        "stages": stage_reports,
        "outputs": {
            "stage": {"size": len(rebuilt_stage), "sha256": sha256_bytes(rebuilt_stage)},
            "hb": {"size": len(rebuilt_hb), "sha256": sha256_bytes(rebuilt_hb)},
        },
        "minimum_compressed_chunk_headroom": min(
            item["source_chunk_size"] - item["output_encoded_size"]
            for item in stage_reports
        ),
        "unchanged_chunk_count": len(output_chunks) - len(stages),
        "stage_layout_preserved": True,
        "source_dialogue_stage_coverage_exact": True,
        "hb_offset_reread_exact": True,
        "runtime_keyword_link_count": runtime_keyword_link_count,
        "runtime_keyword_source_count": len(runtime_keyword_source_hashes),
        "runtime_keyword_source_hashes": runtime_keyword_source_hashes,
        "runtime_keyword_links_exact": all(
            item["runtime_keyword_links_exact"] for item in stage_reports
        ),
        "runtime_acceptance": "not tested",
    }
    return outputs, report


def main() -> int:
    args = parse_args()
    config_path = args.config.resolve()
    outputs, report = build(config_path, workers=args.workers)
    report_path = next(iter(outputs)).parents[1] / "component-validation.json"
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    for path, payload in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "story component:",
        f"stages={len(report['stage_indices'])}",
        f"records={sum(item['allocation_count'] for item in report['stages'])}",
        f"headroom={report['minimum_compressed_chunk_headroom']}",
        "codec=rust-fit",
        "runtime=pending",
    )
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
