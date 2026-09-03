#!/usr/bin/env python3
"""Build a stage-001-only capacity canary and patch an isolated test ISO."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from srwz.chinese_layout import fit_chinese_dialogue_layout
from srwz.codec import decode_production as decode, reencode_changed_suffix
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.stage import STAGE_BASE_ADDRESS, parse_stage, read_stage_function_addresses
from srwz.text import (
    PreparedTextEncoder,
    decode_text,
    load_text_table,
    original_fullwidth_ascii_overrides,
)
from srwz.writers import (
    _table_with_overrides,
    encode_stage_message,
    repack_stage_texts_in_place,
)

from build_story_component import (
    DEFAULT_CONFIG,
    PROJECT_ROOT,
    _entry_translations,
    _json,
    _load_overrides,
    _locked_file,
    _project_path,
    _read_iso_member,
    _speaker_translations,
)


STAGE_INDEX = 1
CANARY_DIALOGUE_COUNT = 50
CANARY_MARKER = "测试测试"
CANARY_RUNTIME_SCENE_PREFIX = "story/001/dialogue/02.01/"
DEFAULT_BASE_ISO = (
    PROJECT_ROOT / "build/iso/zh-release-full-story/srwz-zh-current.iso"
)
DEFAULT_OUTPUT_ISO = (
    PROJECT_ROOT / "build/iso/stage-canary-001/srwz-zh-stage-001-canary.iso"
)
DEFAULT_REPORT = PROJECT_ROOT / "work/build/stage-canary-001/canary-validation.json"


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_output_path(path: Path, prefix: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(prefix.resolve())
    except ValueError as error:
        raise SystemExit(f"canary output must stay under {prefix}: {resolved}") from error
    return resolved


def _inject_canary_marker(translation: str) -> str:
    """Put the stress marker inside the visible dialogue punctuation."""

    if translation.startswith("“"):
        return "“" + CANARY_MARKER + translation[1:]
    if translation.startswith("（"):
        return "（" + CANARY_MARKER + translation[1:]
    return CANARY_MARKER + translation


def _payload_contract(
    data: bytes,
    entry,
    table,
    overrides: dict[str, int],
    speaker_replacements: dict[int, str],
    replacement: str,
) -> dict:
    speaker = decode_text(data, entry.text_offset, table, stop_at_newline=True)
    if speaker.terminator == "newline":
        message = decode_text(data, speaker.end, table)
        translated_speaker = speaker_replacements.get(entry.speaker_id, speaker.text)
        prefix = PreparedTextEncoder(table, overrides).encode(translated_speaker) + b"\n"
        source_end = message.end
    else:
        message = speaker
        prefix = b""
        source_end = speaker.end
    strict_end = min(len(data), (source_end + 15) & ~15)
    if any(data[source_end:strict_end]):
        strict_end = source_end
    payload = prefix + encode_stage_message(
        table,
        overrides,
        entry_id=entry.entry_id,
        source_text=message.text,
        replacement=replacement,
        terminate=True,
    )
    return {
        "entry_id": entry.entry_id,
        "source_text_offset": entry.text_offset,
        "source_payload_size": source_end - entry.text_offset,
        "strict_slot_size": strict_end - entry.text_offset,
        "translated_payload_size": len(payload),
        "strict_slot_delta": len(payload) - (strict_end - entry.text_offset),
        "translation": replacement,
    }


def build_canary(
    config_path: Path,
    base_iso_path: Path,
    output_iso_path: Path,
    report_path: Path,
    *,
    force: bool,
) -> dict:
    config_path = config_path.resolve()
    config = _json(config_path)
    source = config["source"]
    _slps_path, source_slps = _locked_file(source["slps"], label="source SLPS")
    stage_path, source_stage = _locked_file(source["stage"], label="source STAGE")
    table_path, _ = _locked_file(source["text_table"], label="source text table")
    codebook_path, _ = _locked_file(source["base_codebook"], label="base codebook")
    source_hb = _read_iso_member(_project_path(source["iso"]), source["hb"])

    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member=source["hb"]["member"],
        table_start=30320,
        table_end=31144,
    )
    offsets = read_executable_archive_offsets(source_hb, offset_spec, len(source_stage))
    source_chunks = [
        source_stage[offsets[index] : offsets[index + 1]]
        for index in range(len(offsets) - 1)
    ]
    decoded = decode(source_chunks[STAGE_INDEX])
    stage_name = decoded.output[0x30:0x50].split(b"\0", 1)[0]
    if stage_name != b"stg_001.bin":
        raise SystemExit(f"stage-001 header drift: {stage_name!r}")

    functions = read_stage_function_addresses(source_slps)
    table = load_text_table(table_path)
    parsed = parse_stage(
        decoded.output,
        table,
        stage_index=STAGE_INDEX,
        function_address=functions[STAGE_INDEX],
    )
    translations = config["translations"]
    dialogue_path = _project_path(
        str(translations["dialogue_root"]) + "/stage-001.json"
    )
    dialogue = _entry_translations(dialogue_path, {STAGE_INDEX})
    ordered_dialogue_entries = [
        entry
        for entry in parsed.entries
        if entry.kind == "dialogue"
        and entry.entry_id.startswith(CANARY_RUNTIME_SCENE_PREFIX)
        and dialogue.get(entry.entry_id, "").startswith(("“", "（"))
    ]
    canary_entries = ordered_dialogue_entries[:CANARY_DIALOGUE_COUNT]
    if len(canary_entries) != CANARY_DIALOGUE_COUNT:
        raise SystemExit(
            "stage-001 does not contain enough dialogue for the stress canary"
        )
    canary_entry_ids = [entry.entry_id for entry in canary_entries]
    if len(canary_entry_ids) != len(set(canary_entry_ids)):
        raise SystemExit("stage-001 stress canary dialogue IDs are duplicated")
    missing_canary_ids = sorted(set(canary_entry_ids) - set(dialogue))
    if missing_canary_ids:
        raise SystemExit(
            f"stage-001 stress canary corpus entries are missing: {missing_canary_ids}"
        )

    fitted_corpus_dialogue = {
        entry_id: fit_chinese_dialogue_layout(
            translation,
            stage_keyword_links="《" in next(
                entry.text for entry in parsed.entries if entry.entry_id == entry_id
            ),
        ).text
        for entry_id, translation in dialogue.items()
    }
    stressed_dialogue = dict(dialogue)
    for entry_id in canary_entry_ids:
        stressed_dialogue[entry_id] = _inject_canary_marker(dialogue[entry_id])
    fitted_dialogue = {
        entry_id: fit_chinese_dialogue_layout(
            translation,
            stage_keyword_links="《" in next(
                entry.text for entry in parsed.entries if entry.entry_id == entry_id
            ),
        ).text
        for entry_id, translation in stressed_dialogue.items()
    }
    for entry_id in canary_entry_ids:
        if CANARY_MARKER not in fitted_dialogue[entry_id]:
            raise SystemExit(
                f"stage-001 stress marker was lost during layout: {entry_id}"
            )

    conditions = _entry_translations(
        _project_path(translations["conditions"]),
        {STAGE_INDEX},
    )
    stage_conditions = {
        entry_id: translation
        for entry_id, translation in conditions.items()
        if int(entry_id.split("/")[1]) == STAGE_INDEX
    }
    speakers = _speaker_translations(
        _project_path(translations["speakers"]),
        {STAGE_INDEX},
    )[STAGE_INDEX]
    overrides, _ = _load_overrides(
        _project_path(config["font"]["proposal"]),
        _project_path(config["font"]["allocation_registry"]),
        codebook_path,
    )
    overrides.update(original_fullwidth_ascii_overrides(table))

    entries = {entry.entry_id: entry for entry in parsed.entries}
    corpus_contracts = [
        _payload_contract(
            decoded.output,
            entries[entry_id],
            table,
            overrides,
            speakers,
            fitted_corpus_dialogue[entry_id],
        )
        for entry_id in canary_entry_ids
    ]
    canary_contracts = [
        _payload_contract(
            decoded.output,
            entries[entry_id],
            table,
            overrides,
            speakers,
            fitted_dialogue[entry_id],
        )
        for entry_id in canary_entry_ids
    ]
    corpus_contracts_by_id = {
        contract["entry_id"]: contract for contract in corpus_contracts
    }
    total_added_payload_bytes = 0
    for contract in canary_contracts:
        corpus_contract = corpus_contracts_by_id[contract["entry_id"]]
        contract["corpus_translation"] = corpus_contract["translation"]
        contract["corpus_translated_payload_size"] = corpus_contract[
            "translated_payload_size"
        ]
        contract["corpus_strict_slot_delta"] = corpus_contract[
            "strict_slot_delta"
        ]
        contract["added_payload_bytes"] = (
            contract["translated_payload_size"]
            - corpus_contract["translated_payload_size"]
        )
        total_added_payload_bytes += contract["added_payload_bytes"]
    if total_added_payload_bytes < CANARY_DIALOGUE_COUNT * 8:
        raise SystemExit(
            "stage-001 stress canary did not add the expected payload pressure"
        )
    stress_cross_slot_count = sum(
        contract["strict_slot_delta"] > 0 for contract in canary_contracts
    )
    if stress_cross_slot_count <= 0:
        raise SystemExit("stage-001 stress canary does not cross any source slots")

    write = repack_stage_texts_in_place(
        decoded.output,
        table,
        stage_index=STAGE_INDEX,
        function_address=functions[STAGE_INDEX],
        replacements={**fitted_dialogue, **stage_conditions},
        speaker_replacements=speakers,
        overrides=overrides,
    )
    allocations = {item.entry_id: item for item in write.allocations}
    for contract in canary_contracts:
        allocation = allocations[contract["entry_id"]]
        contract["source_pointer_offset"] = entries[contract["entry_id"]].pointer_offset
        contract["output_text_offset"] = allocation.arena_offset
        contract["output_pointer_address"] = STAGE_BASE_ADDRESS + allocation.arena_offset
        contract["pointer_relocated"] = (
            allocation.arena_offset != entries[contract["entry_id"]].text_offset
        )
    relocated_canary_count = sum(
        contract["pointer_relocated"] for contract in canary_contracts
    )
    if relocated_canary_count <= 0:
        raise SystemExit("stage-001 stress canary did not relocate any target pointers")

    codec = config["codec"]
    encoded = reencode_changed_suffix(
        source_chunks[STAGE_INDEX],
        write.data,
        strategy="rust-fit",
        min_match_length=codec["min_match_length"],
        max_match_chain=codec["max_match_chain"],
        lazy_matching=False,
        max_output_size=len(source_chunks[STAGE_INDEX]),
        original_result=decoded,
    )
    output_chunk = encoded + bytes(len(source_chunks[STAGE_INDEX]) - len(encoded))
    candidate_stage = bytearray(source_stage)
    candidate_stage[offsets[STAGE_INDEX] : offsets[STAGE_INDEX + 1]] = output_chunk
    candidate_stage = bytes(candidate_stage)
    for index in range(len(source_chunks)):
        if index == STAGE_INDEX:
            continue
        if candidate_stage[offsets[index] : offsets[index + 1]] != source_chunks[index]:
            raise SystemExit(f"non-canary STAGE chunk changed: {index}")
    reread = parse_stage(
        decode(output_chunk).output,
        _table_with_overrides(table, overrides),
        stage_index=STAGE_INDEX,
        function_address=functions[STAGE_INDEX],
    )
    reread_text = {entry.entry_id: entry.text for entry in reread.entries}
    for contract in canary_contracts:
        if reread_text.get(contract["entry_id"]) != contract["translation"]:
            raise SystemExit(f"canary reread mismatch: {contract['entry_id']}")
    following_dialogue = ordered_dialogue_entries[CANARY_DIALOGUE_COUNT]
    if (
        reread_text.get(following_dialogue.entry_id)
        != fitted_corpus_dialogue[following_dialogue.entry_id]
    ):
        raise SystemExit("dialogue following the stage-001 stress range changed")

    base_iso_path = base_iso_path.resolve()
    output_iso_path = _require_output_path(
        output_iso_path,
        PROJECT_ROOT / "build/iso/stage-canary-001",
    )
    report_path = _require_output_path(
        report_path,
        PROJECT_ROOT / "work/build/stage-canary-001",
    )
    if base_iso_path == output_iso_path:
        raise SystemExit("refusing to overwrite the base ISO")
    if not base_iso_path.is_file():
        raise SystemExit(f"base ISO is missing: {base_iso_path}")
    if output_iso_path.exists() and not force:
        raise SystemExit(f"candidate ISO exists; use --force: {output_iso_path}")

    base_image = scan_iso9660(base_iso_path)
    stage_member = member_map(base_image).get("DATA/STAGE.BIN")
    if stage_member is None or stage_member.size != len(candidate_stage):
        raise SystemExit("base ISO STAGE member identity drift")
    output_iso_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base_iso_path, output_iso_path)
    with output_iso_path.open("r+b") as output:
        output.seek(stage_member.extent_lba * SECTOR_SIZE)
        output.write(candidate_stage)
        output.flush()
    output_image = scan_iso9660(output_iso_path)
    output_stage_member = member_map(output_image).get("DATA/STAGE.BIN")
    if (
        output_stage_member is None
        or output_stage_member.extent_lba != stage_member.extent_lba
        or output_stage_member.size != stage_member.size
    ):
        raise SystemExit("candidate ISO STAGE layout drift")
    with output_iso_path.open("rb") as output:
        output.seek(output_stage_member.extent_lba * SECTOR_SIZE)
        installed_stage = output.read(output_stage_member.size)
    if installed_stage != candidate_stage:
        raise SystemExit("candidate ISO STAGE exact readback mismatch")

    report = {
        "schema_version": 1,
        "status": "stage_001_capacity_canary_static_validated_runtime_pending",
        "stage_index": STAGE_INDEX,
        "stage_header": stage_name.decode("ascii"),
        "rollback_contract": {
            "automatic_untyped_alias_rewrite": False,
            "source_zero_slack_capped_at_next_16_byte_boundary": True,
            "non_canary_stage_chunks_byte_exact_to_original": True,
        },
        "stress_profile": {
            "marker": CANARY_MARKER,
            "selection": "first_50_spoken_or_parenthetical_dialogue_entries_in_02.01",
            "runtime_scene_prefix": CANARY_RUNTIME_SCENE_PREFIX,
            "target_count": len(canary_contracts),
            "total_added_payload_bytes": total_added_payload_bytes,
            "corpus_cross_slot_count": sum(
                contract["strict_slot_delta"] > 0
                for contract in corpus_contracts
            ),
            "stress_cross_slot_count": stress_cross_slot_count,
            "relocated_target_count": relocated_canary_count,
            "following_dialogue_id": following_dialogue.entry_id,
            "following_dialogue_exact": True,
        },
        "canary_entries": canary_contracts,
        "stage": {
            "source_path": str(stage_path.relative_to(PROJECT_ROOT)),
            "source_sha256": _sha256_bytes(source_stage),
            "candidate_sha256": _sha256_bytes(candidate_stage),
            "chunk_source_size": len(source_chunks[STAGE_INDEX]),
            "chunk_encoded_size": len(encoded),
            "chunk_compressed_headroom": len(source_chunks[STAGE_INDEX]) - len(encoded),
            "decoded_size_preserved": len(write.data) == len(decoded.output),
            "archive_size_preserved": len(candidate_stage) == len(source_stage),
        },
        "base_iso": {
            "path": str(base_iso_path.relative_to(PROJECT_ROOT)),
            "size": base_iso_path.stat().st_size,
            "sha256": _sha256_path(base_iso_path),
        },
        "candidate_iso": {
            "path": str(output_iso_path.relative_to(PROJECT_ROOT)),
            "size": output_iso_path.stat().st_size,
            "sha256": _sha256_path(output_iso_path),
            "stage_extent_lba": stage_member.extent_lba,
            "stage_exact_readback": True,
        },
        "runtime_acceptance": "pending",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--base-iso", type=Path, default=DEFAULT_BASE_ISO)
    parser.add_argument("--output-iso", type=Path, default=DEFAULT_OUTPUT_ISO)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_canary(
        args.config,
        args.base_iso,
        args.output_iso,
        args.report,
        force=args.force,
    )
    print(
        "stage-001 canary:",
        f"stage={report['stage']['candidate_sha256']}",
        f"iso={report['candidate_iso']['sha256']}",
        "runtime=pending",
    )
    print(f"report: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
