#!/usr/bin/env python3
"""Build the complete translated STAGE/HB component with the Rust codec."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Mapping

from srwz.codec import decode_production as decode, reencode_changed_suffix
from srwz.diagnostics import require_work_output
from srwz.font import sha256_bytes
from srwz.release_font_policy import DEFAULT_WIDTH_CLASS, allocation_width_class
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.stage import (
    STAGE_BASE_ADDRESS,
    parse_stage,
    read_stage_function_addresses,
)
from srwz.story_quotes import evaluate_story_quote
from srwz.text import (
    decode_text,
    encode_text,
    load_text_table,
    normalize_original_fullwidth_ascii,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
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
TICKER_RUNTIME_POINTER_MIN = 0x00750000
TICKER_RUNTIME_POINTER_MAX = 0x0076FFFF
Z_REPORT_RECORD_SIGNATURE = (0x00000006, 0xFFFFFFFF, 0xFFFFFFFF)


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


def _load_story_tickers(
    reference: Mapping[str, object],
) -> tuple[Path, dict[str, dict]]:
    path = _project_path(str(reference.get("path", "")))
    if (
        not path.is_file()
        or path.stat().st_size != reference.get("size")
        or _sha256(path) != reference.get("sha256")
    ):
        raise SystemExit("story ticker corpus size or SHA-256 drift")
    document = _json(path)
    entries = document.get("entries")
    if (
        document.get("batch_id") != "v1-story-tickers"
        or not isinstance(entries, list)
        or len(entries) != reference.get("expected_entry_count")
    ):
        raise SystemExit("story ticker corpus identity or entry count drift")

    inventory = document.get("inventory")
    if inventory != {
        "selection_authority": "structural_stage_scan",
        "decoded_alignment": 4,
        "prefix_ff_bytes": 6,
        "prefix_payload_bytes": 4,
        "prefix_payload_kinds": ["zero", "runtime_pointer"],
        "runtime_pointer_min": f"0x{TICKER_RUNTIME_POINTER_MIN:08X}",
        "runtime_pointer_max": f"0x{TICKER_RUNTIME_POINTER_MAX:08X}",
        "slot_allocation_size": 140,
    }:
        raise SystemExit("story ticker inventory contract is invalid")

    by_source: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("story ticker entry is malformed")
        entry_id = entry.get("id")
        source_text = entry.get("source_text")
        translation = entry.get("translation")
        glossary_refs = entry.get("glossary_refs")
        if (
            not isinstance(entry_id, str)
            or not entry_id
            or not isinstance(source_text, str)
            or not source_text
            or entry.get("source_text_sha256")
            != sha256_bytes(source_text.encode("utf-8"))
            or not isinstance(translation, str)
            or not translation
            or entry.get("editorial_status") != "reviewed"
            or not isinstance(glossary_refs, list)
            or not glossary_refs
            or any(not isinstance(item, str) or not item for item in glossary_refs)
            or "targets" in entry
        ):
            raise SystemExit(f"story ticker decision is invalid: {entry_id!r}")
        if source_text in by_source:
            raise SystemExit(f"duplicate story ticker source: {source_text!r}")
        normalized_source = normalize_original_fullwidth_ascii(source_text)
        normalized_translation = normalize_original_fullwidth_ascii(translation)
        source_ascii = Counter(re.findall(r"[A-Za-z0-9]+", normalized_source))
        translated_ascii = Counter(
            re.findall(r"[A-Za-z0-9]+", normalized_translation)
        )
        if any(translated_ascii[token] < count for token, count in source_ascii.items()):
            raise SystemExit(
                f"story ticker visible Latin/digit drift: {entry_id!r}"
            )
        by_source[source_text] = {
            "entry_id": entry_id,
            "source_text": source_text,
            "source_text_sha256": entry["source_text_sha256"],
            "translation": normalized_translation,
        }
    return path, by_source


def _load_z_reports(
    reference: Mapping[str, object],
) -> tuple[Path, dict[str, dict]]:
    """Load every reviewed non-dialogue string owned by a Z Report record."""

    path = _project_path(str(reference.get("path", "")))
    if (
        not path.is_file()
        or path.stat().st_size != reference.get("size")
        or _sha256(path) != reference.get("sha256")
    ):
        raise SystemExit("Z Report corpus size or SHA-256 drift")
    document = _json(path)
    entries = document.get("entries")
    if (
        document.get("batch_id") != "v1-stage-z-reports"
        or not isinstance(entries, list)
        or len(entries) != reference.get("expected_entry_count")
        or document.get("inventory")
        != {
            "selection_authority": "z_report_record_signature",
            "record_signature": [
                "0x00000006",
                "0xFFFFFFFF",
                "0xFFFFFFFF",
                "<absolute_text_pointer>",
            ],
            "slot_ownership": "nul_terminated_source_span_only",
        }
    ):
        raise SystemExit("Z Report corpus identity or inventory contract drift")

    by_source: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("Z Report entry is malformed")
        entry_id = entry.get("id")
        source_text = entry.get("source_text")
        translation = entry.get("translation")
        if (
            not isinstance(entry_id, str)
            or not entry_id
            or not isinstance(source_text, str)
            or not source_text
            or entry.get("source_text_sha256")
            != sha256_bytes(source_text.encode("utf-8"))
            or not isinstance(translation, str)
            or not translation
            or entry.get("editorial_status") != "reviewed"
            or not isinstance(entry.get("glossary_refs"), list)
            or not entry["glossary_refs"]
            or source_text in by_source
        ):
            raise SystemExit(f"Z Report decision is invalid: {entry_id!r}")
        by_source[source_text] = {
            "entry_id": entry_id,
            "source_text": source_text,
            "source_text_sha256": entry["source_text_sha256"],
            "translation": normalize_original_fullwidth_ascii(translation),
        }
    return path, by_source


def _discover_z_reports(
    source_chunks: list[bytes],
    table,
    entries_by_source: Mapping[str, dict],
    reference: Mapping[str, object],
) -> tuple[dict[int, list[dict]], dict]:
    """Inventory every text slot owned by the locked Z Report record shape."""

    by_stage: dict[int, list[dict]] = {}
    inventory = []
    unknown_sources = set()
    for stage_index, source_chunk in enumerate(source_chunks):
        data = decode(source_chunk).output
        for record_offset in range(0, len(data) - 15, 4):
            if (
                struct.unpack_from("<III", data, record_offset)
                != Z_REPORT_RECORD_SIGNATURE
            ):
                continue
            text_pointer = struct.unpack_from("<I", data, record_offset + 12)[0]
            offset = text_pointer - STAGE_BASE_ADDRESS
            if not 0 <= offset < len(data):
                # The first three words can occur coincidentally in unrelated
                # data.  A Z Report owner also requires an absolute pointer
                # into this decoded STAGE chunk.
                continue
            try:
                source = decode_text(
                    data,
                    offset,
                    table,
                    end=min(len(data), offset + 256),
                )
            except Exception as error:
                raise SystemExit(
                    "Z Report record text could not be decoded: "
                    f"stage={stage_index} record=0x{record_offset:X} "
                    f"offset=0x{offset:X}"
                ) from error
            if (
                source.terminator != "nul"
                or source.unknown_code_count
                or not source.text
            ):
                raise SystemExit(
                    "Z Report record text is not an exact known NUL string: "
                    f"stage={stage_index} record=0x{record_offset:X} "
                    f"offset=0x{offset:X}"
                )
            entry = entries_by_source.get(source.text)
            if entry is None:
                unknown_sources.add(source.text)
                continue
            target = {
                **entry,
                "record_offset": record_offset,
                "text_pointer": text_pointer,
                "decoded_offset": offset,
                "source_slot_size": source.consumed,
            }
            by_stage.setdefault(stage_index, []).append(target)
            inventory.append(
                {
                    "stage_index": stage_index,
                    "record_offset": record_offset,
                    "text_pointer": text_pointer,
                    "decoded_offset": offset,
                    "source_slot_size": source.consumed,
                    "source_text": source.text,
                    "source_text_sha256": entry["source_text_sha256"],
                }
            )
    if unknown_sources:
        raise SystemExit(
            "unregistered structural Z Report sources: "
            + repr(sorted(unknown_sources))
        )
    discovered_sources = {
        target["source_text"]
        for targets in by_stage.values()
        for target in targets
    }
    missing_sources = sorted(set(entries_by_source) - discovered_sources)
    inventory.sort(key=lambda item: (item["stage_index"], item["decoded_offset"]))
    inventory_sha256 = sha256_bytes(
        json.dumps(
            inventory,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if (
        missing_sources
        or len(discovered_sources) != reference.get("expected_entry_count")
        or len(inventory) != reference.get("expected_target_count")
        or len(by_stage) != reference.get("expected_stage_count")
        or inventory_sha256 != reference.get("expected_inventory_sha256")
    ):
        raise SystemExit(
            "Z Report structural inventory drift: "
            f"entries={len(discovered_sources)} targets={len(inventory)} "
            f"stages={len(by_stage)} missing={missing_sources} "
            f"sha256={inventory_sha256}"
        )
    return by_stage, {
        "entry_count": len(discovered_sources),
        "target_count": len(inventory),
        "stage_count": len(by_stage),
        "stage_indices": sorted(by_stage),
        "inventory_sha256": inventory_sha256,
        "structural_slots_exact": True,
    }


def _write_z_reports(
    data: bytes,
    table,
    *,
    stage_index: int,
    targets: list[dict],
    overrides: Mapping[str, int],
) -> tuple[bytes, dict]:
    """Rewrite only each source string's exact NUL-terminated allocation."""

    if not targets:
        return data, {
            "z_report_count": 0,
            "z_report_changed_byte_count": 0,
            "z_report_source_hashes": [],
            "z_report_fixed_slots_exact": True,
            "z_report_translated_reread_exact": True,
        }
    runtime_table = project_runtime_text_table(table, overrides)
    output = bytearray(data)
    owned_indexes = set()
    readbacks = []
    source_hashes = set()
    for target in targets:
        offset = target["decoded_offset"]
        slot_size = target["source_slot_size"]
        end = offset + slot_size
        source = decode_text(data, offset, table, end=end)
        if (
            source.terminator != "nul"
            or source.end != end
            or source.text != target["source_text"]
            or sha256_bytes(source.text.encode("utf-8"))
            != target["source_text_sha256"]
        ):
            raise SystemExit(
                "Z Report source preimage drift: "
                f"{target['entry_id']} stage={stage_index} offset=0x{offset:X}"
            )
        payload = encode_text(
            target["translation"],
            table,
            overrides=overrides,
            terminate=True,
        )
        if len(payload) > slot_size:
            raise SystemExit(
                "Z Report replacement exceeds fixed slot: "
                f"{target['entry_id']} encoded={len(payload)} slot={slot_size}"
            )
        current_indexes = set(range(offset, end))
        if current_indexes & owned_indexes:
            raise SystemExit("Z Report fixed slots overlap")
        owned_indexes.update(current_indexes)
        output[offset:end] = payload + bytes(slot_size - len(payload))
        readbacks.append((target, len(payload)))
        source_hashes.add(target["source_text_sha256"])

    rebuilt = bytes(output)
    if any(
        before != after and index not in owned_indexes
        for index, (before, after) in enumerate(zip(data, rebuilt))
    ):
        raise SystemExit("Z Report write escaped its fixed slots")
    for target, payload_size in readbacks:
        reread = decode_text(
            rebuilt,
            target["decoded_offset"],
            runtime_table,
            end=target["decoded_offset"] + payload_size,
        )
        if (
            reread.terminator != "nul"
            or reread.end != target["decoded_offset"] + payload_size
            or reread.text != target["translation"]
        ):
            raise SystemExit(
                f"Z Report translated reread mismatch: {target['entry_id']}"
            )
    return rebuilt, {
        "z_report_count": len(targets),
        "z_report_changed_byte_count": sum(
            before != after for before, after in zip(data, rebuilt)
        ),
        "z_report_source_hashes": sorted(source_hashes),
        "z_report_fixed_slots_exact": True,
        "z_report_translated_reread_exact": True,
    }


def _discover_story_tickers(
    source_chunks: list[bytes],
    table,
    entries_by_source: Mapping[str, dict],
    reference: Mapping[str, object],
) -> tuple[dict[int, list[dict]], dict]:
    """Discover every fixed 140-byte bazaar ticker slot in STAGE.BIN.

    The ticker is not part of the ordinary dialogue pointer graph.  Each
    occurrence is nevertheless identified by a stable decoded layout: a
    four-byte-aligned string follows six 0xFF bytes and a four-byte payload.
    Most payloads are zero, while eight slots store a runtime pointer there.
    The NUL-terminated text plus zero padding occupies exactly 140 bytes.
    Scan the full archive so pointer-prefixed and ticker-only stage chunks
    cannot escape coverage.
    """

    by_stage: dict[int, list[dict]] = {}
    inventory = []
    unknown_sources = set()
    allocation_size = 140
    japanese = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
    for stage_index, source_chunk in enumerate(source_chunks):
        data = decode(source_chunk).output
        for offset in range(12, len(data), 4):
            if offset + allocation_size > len(data):
                continue
            if data[offset - 10 : offset - 4] != b"\xFF" * 6:
                continue
            try:
                source = decode_text(
                    data,
                    offset,
                    table,
                    end=offset + allocation_size,
                )
            except Exception:
                continue
            if (
                source.terminator != "nul"
                or source.unknown_code_count
                or not japanese.search(source.text)
                or any(data[source.end : offset + allocation_size])
                or (
                    offset + allocation_size < len(data)
                    and data[offset + allocation_size] == 0
                )
            ):
                continue
            prefix_word = int.from_bytes(
                data[offset - 4 : offset], byteorder="little"
            )
            if prefix_word == 0:
                prefix_kind = "zero"
            elif (
                TICKER_RUNTIME_POINTER_MIN
                <= prefix_word
                <= TICKER_RUNTIME_POINTER_MAX
            ):
                prefix_kind = "runtime_pointer"
            else:
                raise SystemExit(
                    "story ticker candidate has an unknown prefix payload: "
                    f"stage={stage_index} offset=0x{offset:X} "
                    f"value=0x{prefix_word:08X}"
                )
            entry = entries_by_source.get(source.text)
            if entry is None:
                unknown_sources.add(source.text)
                continue
            target = {
                **entry,
                "decoded_offset": offset,
                "source_slot_size": source.consumed,
                "slot_prefix_kind": prefix_kind,
                "slot_prefix_word": prefix_word,
            }
            by_stage.setdefault(stage_index, []).append(target)
            inventory.append(
                {
                    "stage_index": stage_index,
                    "decoded_offset": offset,
                    "source_slot_size": source.consumed,
                    "source_text_sha256": entry["source_text_sha256"],
                    "slot_prefix_kind": prefix_kind,
                    "slot_prefix_word": prefix_word,
                }
            )
    if unknown_sources:
        raise SystemExit(
            "unregistered structural story ticker sources: "
            + repr(sorted(unknown_sources))
        )
    discovered_sources = {
        target["source_text"]
        for targets in by_stage.values()
        for target in targets
    }
    missing_sources = sorted(set(entries_by_source) - discovered_sources)
    inventory.sort(key=lambda item: (item["stage_index"], item["decoded_offset"]))
    inventory_sha256 = sha256_bytes(
        json.dumps(
            inventory,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if (
        missing_sources
        or len(discovered_sources) != reference.get("expected_entry_count")
        or len(inventory) != reference.get("expected_target_count")
        or len(by_stage) != reference.get("expected_stage_count")
        or inventory_sha256 != reference.get("expected_inventory_sha256")
        or any(len(targets) != 1 for targets in by_stage.values())
    ):
        raise SystemExit(
            "story ticker structural inventory drift: "
            f"entries={len(discovered_sources)} targets={len(inventory)} "
            f"stages={len(by_stage)} missing={missing_sources} "
            f"sha256={inventory_sha256}"
        )
    return by_stage, {
        "entry_count": len(discovered_sources),
        "target_count": len(inventory),
        "stage_count": len(by_stage),
        "stage_indices": sorted(by_stage),
        "prefix_kind_counts": dict(
            sorted(Counter(item["slot_prefix_kind"] for item in inventory).items())
        ),
        "inventory_sha256": inventory_sha256,
        "structural_slots_exact": True,
    }


def _write_story_tickers(
    data: bytes,
    table,
    *,
    stage_index: int,
    targets: list[dict],
    overrides: Mapping[str, int],
) -> tuple[bytes, dict]:
    if not targets:
        return data, {
            "story_ticker_count": 0,
            "story_ticker_changed_byte_count": 0,
            "story_ticker_source_hashes": [],
            "story_ticker_fixed_slots_exact": True,
            "story_ticker_translated_reread_exact": True,
        }

    runtime_table = project_runtime_text_table(table, overrides)
    output = bytearray(data)
    owned_indexes = set()
    readbacks = []
    source_hashes = set()
    for target in targets:
        offset = target["decoded_offset"]
        slot_size = target["source_slot_size"]
        end = offset + slot_size
        if end > len(data):
            raise SystemExit(
                f"story ticker slot exceeds stage {stage_index} decoded data"
            )
        source = decode_text(data, offset, table, end=end)
        if (
            source.terminator != "nul"
            or source.end != end
            or source.text != target["source_text"]
            or sha256_bytes(source.text.encode("utf-8"))
            != target["source_text_sha256"]
        ):
            raise SystemExit(
                f"story ticker source preimage drift: "
                f"{target['entry_id']} stage={stage_index} offset=0x{offset:X}"
            )
        payload = encode_text(
            target["translation"],
            table,
            overrides=overrides,
            terminate=True,
        )
        if len(payload) > slot_size:
            raise SystemExit(
                f"story ticker replacement exceeds fixed slot: "
                f"{target['entry_id']} encoded={len(payload)} slot={slot_size}"
            )
        current_indexes = set(range(offset, end))
        if current_indexes & owned_indexes:
            raise SystemExit("story ticker fixed slots overlap")
        owned_indexes.update(current_indexes)
        output[offset:end] = payload + bytes(slot_size - len(payload))
        readbacks.append((target, len(payload)))
        source_hashes.add(target["source_text_sha256"])

    rebuilt = bytes(output)
    if any(
        before != after and index not in owned_indexes
        for index, (before, after) in enumerate(zip(data, rebuilt))
    ):
        raise SystemExit("story ticker write escaped its fixed slots")
    for target, payload_size in readbacks:
        reread = decode_text(
            rebuilt,
            target["decoded_offset"],
            runtime_table,
            end=target["decoded_offset"] + payload_size,
        )
        if (
            reread.terminator != "nul"
            or reread.end != target["decoded_offset"] + payload_size
            or reread.text != target["translation"]
        ):
            raise SystemExit(
                f"story ticker translated reread mismatch: "
                f"{target['entry_id']} stage={stage_index}"
            )
    return rebuilt, {
        "story_ticker_count": len(targets),
        "story_ticker_changed_byte_count": sum(
            before != after for before, after in zip(data, rebuilt)
        ),
        "story_ticker_source_hashes": sorted(source_hashes),
        "story_ticker_fixed_slots_exact": True,
        "story_ticker_translated_reread_exact": True,
    }


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
    special = {
        assignment["character"]
        for assignment in proposal["assignments"]
        if allocation_width_class(int(assignment["code"], 16))
        != DEFAULT_WIDTH_CLASS
    }
    unaliased = conditional - set(aliases)
    unaliased_special = special - set(aliases)
    if (
        not set(aliases) <= special
        or alias_report.get("assignment_count") != len(aliases)
        or alias_report.get("conditional_primary_assignment_count")
        != len(conditional)
        or alias_report.get("unaliased_conditional_assignment_count")
        != len(unaliased)
        or alias_report.get("all_selected_assignments") is not (not unaliased)
        or alias_report.get("special_primary_assignment_count") != len(special)
        or alias_report.get("unaliased_special_assignment_count")
        != len(unaliased_special)
        or any(
            allocation_width_class(code) != DEFAULT_WIDTH_CLASS
            for code in aliases.values()
        )
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
    tickers_path, ticker_entries_by_source = _load_story_tickers(
        translations["tickers"]
    )
    z_reports_path, z_report_entries_by_source = _load_z_reports(
        translations["z_reports"]
    )
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
    tickers_by_stage, ticker_inventory = _discover_story_tickers(
        source_chunks,
        table,
        ticker_entries_by_source,
        translations["tickers"],
    )
    z_reports_by_stage, z_report_inventory = _discover_z_reports(
        source_chunks,
        table,
        z_report_entries_by_source,
        translations["z_reports"],
    )
    tutorial_binding = translations.get("tutorial_binding")
    if tutorial_binding != {
        "stage_names": {"185": "stg_500.bin", "186": "stg_501.bin"},
        "dialogue_counts": {"185": 407, "186": 431},
        "expected_total_dialogue_count": 838,
    }:
        raise SystemExit("tutorial STAGE binding contract drift")
    tutorial_source_names = {}
    for raw_stage, expected_name in tutorial_binding["stage_names"].items():
        stage_index = int(raw_stage)
        decoded_stage = decode(source_chunks[stage_index]).output
        raw_name = decoded_stage[0x30:0x50].split(b"\0", 1)[0]
        try:
            source_name = raw_name.decode("ascii")
        except UnicodeDecodeError as error:
            raise SystemExit("tutorial STAGE header is not ASCII") from error
        if source_name != expected_name:
            raise SystemExit(
                f"tutorial STAGE binding drift: {stage_index}={source_name!r}"
            )
        tutorial_source_names[raw_stage] = source_name
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
        quote_style_counts = Counter()
        source_speakers = {
            entry.speaker_id: entry.text
            for entry in parsed_source.entries
            if entry.kind == "speaker"
        }
        for entry in parsed_source.entries:
            if entry.kind != "dialogue":
                continue
            translated = dialogue[stage].get(entry.entry_id)
            if translated is None:
                raise SystemExit(
                    f"missing translated dialogue entry: {entry.entry_id}"
                )
            has_keyword_links = "《" in entry.text
            verdict = evaluate_story_quote(
                entry.text,
                translated,
                source_speakers[entry.speaker_id],
                has_keyword_links=has_keyword_links,
            )
            quote_style_counts[verdict.expected] += 1
            if not verdict.exact:
                raise SystemExit(
                    f"{entry.entry_id} dialogue outer punctuation mismatch: "
                    f"expected={verdict.expected} actual={verdict.actual}"
                )
            if has_keyword_links:
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
        source_conditions = {
            entry.entry_id: entry.text
            for entry in parsed_source.entries
            if entry.kind == "condition"
        }
        for entry_id, translation in stage_conditions.items():
            source_text = source_conditions.get(entry_id)
            if source_text is None:
                raise SystemExit(
                    f"condition source entry is absent: {entry_id}"
                )
            # In STAGE victory/defeat conditions, a raw ASCII colon is not
            # punctuation: the runtime replaces it with a scenario-dependent
            # pilot name.  Fullwidth punctuation looks similar in the corpus
            # but disables that substitution on screen.
            if (
                translation.count(":") != source_text.count(":")
                or (":" in source_text and "：" in translation)
            ):
                raise SystemExit(
                    "condition runtime-name placeholder drift: "
                    f"{entry_id} source={source_text!r} "
                    f"translation={translation!r}"
                )
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
        stage_data, ticker_report = _write_story_tickers(
            write.data,
            table,
            stage_index=stage,
            targets=tickers_by_stage.get(stage, []),
            overrides=overrides,
        )
        stage_data, z_report_report = _write_z_reports(
            stage_data,
            table,
            stage_index=stage,
            targets=z_reports_by_stage.get(stage, []),
            overrides=overrides,
        )
        if write.source_dialogue_count <= 0:
            raise SystemExit(
                "story corpus includes a STAGE without source dialogue: "
                f"{stage:03d}"
            )
        encoded = reencode_changed_suffix(
            source_chunks[stage],
            stage_data,
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
            **ticker_report,
            **z_report_report,
            "dialogue_count": len(dialogue[stage]),
            "condition_count": len(stage_conditions),
            "condition_runtime_name_placeholder_count": sum(
                translation.count(":")
                for translation in stage_conditions.values()
            ),
            "speaker_count": len(speakers[stage]),
            "runtime_keyword_link_count": runtime_keyword_link_count,
            "runtime_keyword_source_hashes": sorted(
                runtime_keyword_source_hashes
            ),
            "runtime_keyword_links_exact": True,
            "dialogue_quote_style_counts": dict(sorted(quote_style_counts.items())),
            "dialogue_outer_punctuation_exact": True,
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

    def build_auxiliary_only_stage(stage: int) -> tuple[int, bytes, dict]:
        decoded = decode(source_chunks[stage])
        stage_data, ticker_report = _write_story_tickers(
            decoded.output,
            table,
            stage_index=stage,
            targets=tickers_by_stage.get(stage, []),
            overrides=overrides,
        )
        stage_data, z_report_report = _write_z_reports(
            stage_data,
            table,
            stage_index=stage,
            targets=z_reports_by_stage.get(stage, []),
            overrides=overrides,
        )
        encoded = reencode_changed_suffix(
            source_chunks[stage],
            stage_data,
            strategy="rust-fit",
            min_match_length=codec["min_match_length"],
            max_match_chain=codec["max_match_chain"],
            lazy_matching=False,
            max_output_size=len(source_chunks[stage]),
            original_result=decoded,
        )
        output_chunk = encoded + bytes(len(source_chunks[stage]) - len(encoded))
        return stage, output_chunk, {
            **ticker_report,
            **z_report_report,
            "stage_index": stage,
            "source_encoded_size": decoded.consumed,
            "output_encoded_size": len(encoded),
            "source_chunk_size": len(source_chunks[stage]),
            "output_chunk_size": len(output_chunk),
            "chunk_span_preserved": True,
            "output_encoded_sha256": sha256_bytes(encoded),
            "codec_strategy": "rust-fit",
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

    auxiliary_stages = set(tickers_by_stage) | set(z_reports_by_stage)
    auxiliary_only_stage_reports = []
    for stage in sorted(auxiliary_stages - stages):
        stage, output_chunk, stage_report = build_auxiliary_only_stage(stage)
        output_chunks[stage] = output_chunk
        auxiliary_only_stage_reports.append(stage_report)

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
    all_auxiliary_reports = [*stage_reports, *auxiliary_only_stage_reports]
    all_ticker_reports = all_auxiliary_reports
    story_ticker_count = sum(
        item["story_ticker_count"] for item in all_ticker_reports
    )
    story_ticker_source_hashes = sorted(
        {
            source_hash
            for item in all_ticker_reports
            for source_hash in item["story_ticker_source_hashes"]
        }
    )
    if (
        story_ticker_count
        != translations["tickers"].get("expected_target_count")
        or len(story_ticker_source_hashes)
        != translations["tickers"].get("expected_entry_count")
    ):
        raise SystemExit(
            "story ticker build coverage drift: "
            f"targets={story_ticker_count} "
            f"entries={len(story_ticker_source_hashes)}"
        )
    z_report_count = sum(
        item["z_report_count"] for item in all_auxiliary_reports
    )
    z_report_source_hashes = sorted(
        {
            source_hash
            for item in all_auxiliary_reports
            for source_hash in item["z_report_source_hashes"]
        }
    )
    if (
        z_report_count
        != translations["z_reports"].get("expected_target_count")
        or len(z_report_source_hashes)
        != translations["z_reports"].get("expected_entry_count")
    ):
        raise SystemExit(
            "Z Report build coverage drift: "
            f"targets={z_report_count} entries={len(z_report_source_hashes)}"
        )
    tutorial_stage_reports = {
        str(item["stage_index"]): item
        for item in stage_reports
        if item["stage_index"] in {185, 186}
    }
    if (
        set(tutorial_stage_reports) != {"185", "186"}
        or {
            stage: item["dialogue_count"]
            for stage, item in tutorial_stage_reports.items()
        }
        != tutorial_binding["dialogue_counts"]
        or sum(
            item["dialogue_count"] for item in tutorial_stage_reports.values()
        )
        != tutorial_binding["expected_total_dialogue_count"]
        or not all(
            item["translated_reread_exact"]
            for item in tutorial_stage_reports.values()
        )
    ):
        raise SystemExit("tutorial translated STAGE coverage drift")
    dialogue_quote_style_counts = Counter()
    for item in stage_reports:
        dialogue_quote_style_counts.update(item["dialogue_quote_style_counts"])
    expected_quote_styles = translations.get("expected_dialogue_quote_styles")
    if (
        sum(dialogue_quote_style_counts.values())
        != translations.get("expected_dialogue_entry_count")
        or dict(sorted(dialogue_quote_style_counts.items()))
        != expected_quote_styles
    ):
        raise SystemExit(
            "dialogue outer-punctuation coverage drift: "
            f"expected={expected_quote_styles} "
            f"actual={dict(sorted(dialogue_quote_style_counts.items()))}"
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
            "tickers": {
                "path": str(tickers_path.relative_to(PROJECT_ROOT)),
                "size": tickers_path.stat().st_size,
                "sha256": _sha256(tickers_path),
            },
            "z_reports": {
                "path": str(z_reports_path.relative_to(PROJECT_ROOT)),
                "size": z_reports_path.stat().st_size,
                "sha256": _sha256(z_reports_path),
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
        "auxiliary_only_stages": auxiliary_only_stage_reports,
        "ticker_only_stages": [
            item
            for item in auxiliary_only_stage_reports
            if item["story_ticker_count"]
        ],
        "outputs": {
            "stage": {"size": len(rebuilt_stage), "sha256": sha256_bytes(rebuilt_stage)},
            "hb": {"size": len(rebuilt_hb), "sha256": sha256_bytes(rebuilt_hb)},
        },
        "minimum_compressed_chunk_headroom": min(
            item["source_chunk_size"] - item["output_encoded_size"]
            for item in stage_reports
        ),
        "unchanged_chunk_count": len(output_chunks)
        - len(stages | auxiliary_stages),
        "stage_layout_preserved": True,
        "source_dialogue_stage_coverage_exact": True,
        "hb_offset_reread_exact": True,
        "runtime_keyword_link_count": runtime_keyword_link_count,
        "runtime_keyword_source_count": len(runtime_keyword_source_hashes),
        "runtime_keyword_source_hashes": runtime_keyword_source_hashes,
        "runtime_keyword_links_exact": all(
            item["runtime_keyword_links_exact"] for item in stage_reports
        ),
        "story_ticker_count": story_ticker_count,
        "story_ticker_source_count": len(story_ticker_source_hashes),
        "story_ticker_source_hashes": story_ticker_source_hashes,
        "story_ticker_stage_count": ticker_inventory["stage_count"],
        "story_ticker_stage_indices": ticker_inventory["stage_indices"],
        "story_ticker_prefix_kind_counts": ticker_inventory[
            "prefix_kind_counts"
        ],
        "story_ticker_inventory_sha256": ticker_inventory[
            "inventory_sha256"
        ],
        "story_ticker_structural_slots_exact": ticker_inventory[
            "structural_slots_exact"
        ],
        "story_ticker_fixed_slots_exact": all(
            item["story_ticker_fixed_slots_exact"]
            for item in all_ticker_reports
        ),
        "story_ticker_translated_reread_exact": all(
            item["story_ticker_translated_reread_exact"]
            for item in all_ticker_reports
        ),
        "z_report_count": z_report_count,
        "z_report_source_count": len(z_report_source_hashes),
        "z_report_source_hashes": z_report_source_hashes,
        "z_report_stage_count": z_report_inventory["stage_count"],
        "z_report_stage_indices": z_report_inventory["stage_indices"],
        "z_report_inventory_sha256": z_report_inventory[
            "inventory_sha256"
        ],
        "z_report_structural_slots_exact": z_report_inventory[
            "structural_slots_exact"
        ],
        "z_report_fixed_slots_exact": all(
            item["z_report_fixed_slots_exact"]
            for item in all_auxiliary_reports
        ),
        "z_report_translated_reread_exact": all(
            item["z_report_translated_reread_exact"]
            for item in all_auxiliary_reports
        ),
        "tutorial_binding": {
            "stage_names": tutorial_source_names,
            "dialogue_counts": tutorial_binding["dialogue_counts"],
            "total_dialogue_count": tutorial_binding[
                "expected_total_dialogue_count"
            ],
            "source_stage_headers_exact": True,
            "translated_stage_reread_exact": True,
            "alternate_mtv_prop_text_owner_ruled_out": True,
        },
        "dialogue_quote_style_counts": dict(
            sorted(dialogue_quote_style_counts.items())
        ),
        "dialogue_outer_punctuation_exact": all(
            item["dialogue_outer_punctuation_exact"] for item in stage_reports
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
