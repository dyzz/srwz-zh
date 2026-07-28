"""Select and build fixed-span P0 SLPS and COMPDATA localization slices."""

from __future__ import annotations

import hashlib
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping

from .codec import decode, reencode_changed_suffix
from .corpus import text_sha256
from .font import decode_vt1_font_segment, sha256_bytes
from .menu import MenuParseResult, parse_menu_file
from .text import decode_text, encode_text, load_text_table
from .ui_inventory import expand_scene_entries, load_scene_config
from .writers import replace_menu_texts_in_place


class UiMenuError(ValueError):
    """The fixed-span UI menu selection or component has drifted."""


_FIXED_SELECTION_POLICY = {
    "accept_exact_no_op_entries": True,
    "require_every_target": True,
    "require_all_shared_target_owners_for_writes": True,
    "require_identical_shared_payload": True,
    "require_payload_with_terminator_within_original_consumed_size": True,
    "pointer_write_policy": "forbidden",
}


def _json_object(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UiMenuError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(document, dict):
        raise UiMenuError(f"JSON root must be an object: {path}")
    return document


def _project_path(project_root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise UiMenuError("project path must be a non-empty string")
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise UiMenuError(f"path escapes project root: {relative}") from error
    return path


def _hash_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _validate_fixed_selection_policy(
    config: Mapping[str, object],
    *,
    source_file: str,
) -> None:
    policy = config.get("selection_policy")
    expected = {
        "source_file": source_file,
        **_FIXED_SELECTION_POLICY,
    }
    if policy != expected:
        raise UiMenuError(
            f"{source_file} fixed-span selection policy is unsupported or incomplete"
        )


def _load_hashed_path(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> Path:
    path = _project_path(project_root, reference.get("path"))
    if _hash_file(path) != reference.get("sha256"):
        raise UiMenuError(f"{label} SHA-256 drift")
    return path


def load_ui_font_overrides(
    project_root: Path,
    config: Mapping[str, object],
    font_manifest: Mapping[str, object],
) -> tuple[dict[str, int], dict]:
    base_path = _load_hashed_path(
        project_root,
        config["base_codebook"],
        label="base codebook",
    )
    proposal_reference = font_manifest.get("proposal")
    if not isinstance(proposal_reference, dict):
        raise UiMenuError("UI font manifest has no proposal")
    proposal_path = _project_path(
        project_root,
        proposal_reference.get("path"),
    )
    if _hash_file(proposal_path) != proposal_reference.get("sha256"):
        raise UiMenuError("UI font proposal SHA-256 drift")
    assignments = [
        *_json_object(base_path).get("assignments", []),
        *_json_object(proposal_path).get("assignments", []),
    ]
    overrides = {}
    codes = {}
    for assignment in assignments:
        if not isinstance(assignment, dict):
            raise UiMenuError("malformed UI codebook assignment")
        character = assignment.get("character")
        code = assignment.get("code")
        if (
            not isinstance(character, str)
            or len(character) != 1
            or not isinstance(code, str)
        ):
            raise UiMenuError("malformed UI codebook assignment")
        value = int(code, 16)
        previous_code = overrides.setdefault(character, value)
        previous_character = codes.setdefault(value, character)
        if previous_code != value or previous_character != character:
            raise UiMenuError("UI codebook assignment collision")
    return overrides, {
        "base_codebook": {
            "path": str(base_path.relative_to(project_root.resolve())),
            "sha256": _hash_file(base_path),
        },
        "proposal": {
            "path": str(proposal_path.relative_to(project_root.resolve())),
            "sha256": _hash_file(proposal_path),
        },
        "override_count": len(overrides),
    }


def _load_menu_descriptor(
    project_root: Path,
    reference: Mapping[str, object],
) -> tuple[Path, dict]:
    path = _load_hashed_path(
        project_root,
        reference,
        label="menu descriptor",
    )
    try:
        descriptors = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise UiMenuError("menu descriptor JSON is invalid") from error
    if not isinstance(descriptors, list):
        raise UiMenuError("menu descriptor root must be a list")
    matches = [
        descriptor
        for descriptor in descriptors
        if isinstance(descriptor, dict)
        and descriptor.get("friendly_name") == reference.get("friendly_name")
    ]
    if len(matches) != 1:
        raise UiMenuError("menu descriptor friendly_name is not unique")
    return path, matches[0]


def _selected_p0_entries_for_prefix(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    entry_prefix: str,
    count_key: str,
) -> tuple[dict[str, dict], dict]:
    path = _load_hashed_path(
        project_root,
        reference,
        label="UI scene inventory",
    )
    config = load_scene_config(path)
    if config["inventory_id"] != reference.get("inventory_id"):
        raise UiMenuError("UI scene inventory ID drift")
    priorities = reference.get("priorities")
    if not isinstance(priorities, list) or not priorities:
        raise UiMenuError("UI menu priorities are invalid")
    all_entries = {}
    selected_entries = {}
    scene_ids = []
    for scene in config["scenes"]:
        if scene["priority"] not in priorities:
            continue
        scene_ids.append(scene["scene_id"])
        for entry in expand_scene_entries(project_root, scene):
            entry_id = entry["id"]
            previous = all_entries.setdefault(entry_id, entry)
            if previous != entry:
                raise UiMenuError(f"UI decision differs for {entry_id}")
            if entry_id.startswith(entry_prefix):
                selected_entries[entry_id] = entry
    return selected_entries, {
        "path": str(path.relative_to(project_root.resolve())),
        "sha256": _hash_file(path),
        "inventory_id": config["inventory_id"],
        "priorities": priorities,
        "scene_ids": scene_ids,
        "p0_unique_entry_count": len(all_entries),
        count_key: len(selected_entries),
    }


def _selected_p0_entries(
    project_root: Path,
    reference: Mapping[str, object],
) -> tuple[dict[str, dict], dict]:
    return _selected_p0_entries_for_prefix(
        project_root,
        reference,
        entry_prefix="menu/SLPS/",
        count_key="p0_slps_entry_count",
    )


def _selection_hash(
    selected_ids: set[str],
    payloads: Mapping[str, bytes],
    parsed_entries: Mapping[str, object],
) -> str:
    digest = hashlib.sha256()
    for entry_id in sorted(selected_ids):
        row = {
            "id": entry_id,
            "payload_sha256": sha256_bytes(payloads[entry_id]),
            "target_offsets": sorted(set(parsed_entries[entry_id].target_offsets)),
        }
        digest.update(
            json.dumps(
                row,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def select_fixed_menu_replacements(
    source: bytes,
    parsed: MenuParseResult,
    table,
    *,
    p0_entries: Mapping[str, Mapping[str, object]],
    overrides: Mapping[str, int],
) -> tuple[dict[str, str], tuple[dict, ...], dict]:
    """Select the maximal closed P0 subset that fits every source span."""

    entries = {entry.entry_id: entry for entry in parsed.entries}
    missing_ids = sorted(set(p0_entries) - set(entries))
    if missing_ids:
        raise UiMenuError(f"P0 menu IDs are absent from parser: {missing_ids!r}")
    target_owners: defaultdict[int, set[str]] = defaultdict(set)
    for entry in parsed.entries:
        for target_offset in set(entry.target_offsets):
            target_owners[target_offset].add(entry.entry_id)

    payloads = {}
    reasons = {}
    details = {}
    selected = set()
    for entry_id, decision in p0_entries.items():
        entry = entries[entry_id]
        translation = decision.get("translation")
        if not isinstance(translation, str):
            raise UiMenuError(f"{entry_id} translation is not text")
        if text_sha256(entry.text) != decision.get("source_text_sha256"):
            raise UiMenuError(f"{entry_id} source text hash drift")
        payload = encode_text(
            translation,
            table,
            overrides=overrides,
            terminate=True,
        )
        payloads[entry_id] = payload
        targets = sorted(set(entry.target_offsets))
        if not targets:
            reasons[entry_id] = "no_target"
            details[entry_id] = {
                "payload_size": len(payload),
                "minimum_capacity": 0,
            }
            continue
        capacities = []
        for target_offset in targets:
            decoded = decode_text(source, target_offset, table)
            if decoded.text != entry.text:
                raise UiMenuError(f"{entry_id} source target preimage drift")
            capacities.append(decoded.consumed)
        minimum_capacity = min(capacities)
        details[entry_id] = {
            "payload_size": len(payload),
            "minimum_capacity": minimum_capacity,
        }
        if len(payload) > minimum_capacity:
            reasons[entry_id] = "overflow"
            continue
        selected.add(entry_id)

    changed = True
    while changed:
        changed = False
        for entry_id in sorted(selected):
            for target_offset in set(entries[entry_id].target_offsets):
                owners = target_owners[target_offset]
                if not owners <= selected:
                    selected.remove(entry_id)
                    reasons[entry_id] = "shared_unselected"
                    changed = True
                    break
                if len({payloads[owner] for owner in owners}) != 1:
                    selected.remove(entry_id)
                    reasons[entry_id] = "shared_conflict"
                    changed = True
                    break

    replacements = {
        entry_id: p0_entries[entry_id]["translation"] for entry_id in sorted(selected)
    }
    excluded = tuple(
        {
            "entry_id": entry_id,
            "reason": reasons[entry_id],
            **details[entry_id],
        }
        for entry_id in sorted(set(p0_entries) - selected)
    )
    selected_targets = {
        target for entry_id in selected for target in entries[entry_id].target_offsets
    }
    reason_counts = Counter(item["reason"] for item in excluded)
    return (
        replacements,
        excluded,
        {
            "selected_entry_count": len(selected),
            "selected_target_count": len(selected_targets),
            "selection_sha256": _selection_hash(
                selected,
                payloads,
                entries,
            ),
            "excluded_entry_count": len(excluded),
            "excluded_reason_counts": dict(sorted(reason_counts.items())),
        },
    )


def select_fixed_slps_replacements(
    source: bytes,
    parsed: MenuParseResult,
    table,
    *,
    p0_entries: Mapping[str, Mapping[str, object]],
    overrides: Mapping[str, int],
) -> tuple[dict[str, str], tuple[dict, ...], dict]:
    """Backward-compatible name for the generic fixed menu selector."""

    return select_fixed_menu_replacements(
        source,
        parsed,
        table,
        p0_entries=p0_entries,
        overrides=overrides,
    )


def _partition_noop_entries(
    source: bytes,
    parsed: MenuParseResult,
    table,
    *,
    decisions: Mapping[str, Mapping[str, object]],
    overrides: Mapping[str, int],
) -> tuple[dict[str, Mapping[str, object]], tuple[str, ...]]:
    entries = {entry.entry_id: entry for entry in parsed.entries}
    actionable = {}
    noops = []
    for entry_id, decision in decisions.items():
        entry = entries.get(entry_id)
        if entry is None:
            raise UiMenuError(f"P0 menu ID is absent from parser: {entry_id}")
        translation = decision.get("translation")
        if not isinstance(translation, str):
            raise UiMenuError(f"{entry_id} translation is not text")
        if text_sha256(entry.text) != decision.get("source_text_sha256"):
            raise UiMenuError(f"{entry_id} source text hash drift")
        payload = encode_text(
            translation,
            table,
            overrides=overrides,
            terminate=True,
        )
        exact = bool(entry.target_offsets)
        for target_offset in set(entry.target_offsets):
            decoded = decode_text(source, target_offset, table)
            if decoded.text != entry.text:
                raise UiMenuError(f"{entry_id} source target preimage drift")
            if len(payload) > decoded.consumed:
                exact = False
                break
            before = source[target_offset : target_offset + decoded.consumed]
            after = payload + bytes(decoded.consumed - len(payload))
            if before != after:
                exact = False
                break
        if exact:
            noops.append(entry_id)
        else:
            actionable[entry_id] = decision
    return actionable, tuple(sorted(noops))


def _changed_offsets(before: bytes, after: bytes) -> list[int]:
    if len(before) != len(after):
        raise UiMenuError("fixed-span component changed decoded size")
    return [
        offset
        for offset, (source_byte, output_byte) in enumerate(zip(before, after))
        if source_byte != output_byte
    ]


def _difference_range_count(offsets: list[int]) -> int:
    count = 0
    previous = None
    for offset in offsets:
        if previous is None or offset != previous + 1:
            count += 1
        previous = offset
    return count


def _menu_pointer_sites(
    data: bytes,
    parsed: MenuParseResult,
) -> set[int]:
    sites = set()
    for entry in parsed.entries:
        target_addresses = {
            parsed.base_offset + target for target in entry.target_offsets
        }
        for pointer_offset in entry.pointer_offsets:
            if (
                0 <= pointer_offset <= len(data) - 4
                and struct.unpack_from("<I", data, pointer_offset)[0]
                in target_addresses
            ):
                sites.update(range(pointer_offset, pointer_offset + 4))
        for address in (*entry.embedded_hi, *entry.embedded_lo):
            offset = address - parsed.base_offset
            if not 0 <= offset <= len(data) - 2:
                raise UiMenuError("embedded pointer site is outside source")
            sites.update(range(offset, offset + 2))
    return sites


def _verify_fixed_span_differences(
    source: bytes,
    output: bytes,
    parsed: MenuParseResult,
    targets,
) -> list[int]:
    allowed_offsets = set()
    for target in targets:
        allowed_offsets.update(
            range(
                target.target_offset,
                target.target_offset + target.capacity,
            )
        )
    changed_offsets = _changed_offsets(source, output)
    if any(offset not in allowed_offsets for offset in changed_offsets):
        raise UiMenuError("fixed menu component changed bytes outside text targets")
    pointer_sites = _menu_pointer_sites(source, parsed)
    if any(source[offset] != output[offset] for offset in pointer_sites):
        raise UiMenuError("fixed menu component modified a pointer instruction byte")
    return changed_offsets


def build_fixed_slps_component(
    project_root: Path,
    config_path: Path,
) -> tuple[bytes, dict]:
    """Build and independently reparse the fixed-span P0 SLPS component."""

    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiMenuError("unsupported UI menu writeback schema")
    _validate_fixed_selection_policy(config, source_file="SLPS")
    font_reference = config.get("font_candidate")
    if not isinstance(font_reference, dict):
        raise UiMenuError("UI menu profile has no font_candidate")
    font_manifest_path = _project_path(
        project_root,
        font_reference.get("manifest"),
    )
    if _hash_file(font_manifest_path) != font_reference.get("sha256"):
        raise UiMenuError("UI font candidate manifest SHA-256 drift")
    font_manifest = _json_object(font_manifest_path)
    if font_manifest.get("status") != (
        "offline_font_and_p0_renderer_coverage_passed_runtime_pending"
    ):
        raise UiMenuError("UI font candidate status is invalid")

    source_slps_path = _project_path(
        project_root,
        font_reference.get("source_slps"),
    )
    source_vt1_path = _project_path(
        project_root,
        font_reference.get("source_vt1"),
    )
    source_slps = source_slps_path.read_bytes()
    source_vt1 = source_vt1_path.read_bytes()
    if (
        sha256_bytes(source_slps)
        != font_manifest["font_component"]["outputs"]["slps"]["sha256"]
    ):
        raise UiMenuError("UI font SLPS source hash drift")
    if (
        sha256_bytes(source_vt1)
        != font_manifest["font_component"]["outputs"]["vt1"]["sha256"]
    ):
        raise UiMenuError("UI font VT1 source hash drift")

    descriptor_path, descriptor = _load_menu_descriptor(
        project_root,
        config["menu_descriptor"],
    )
    text_table_path = _load_hashed_path(
        project_root,
        config["text_table"],
        label="text table",
    )
    table = load_text_table(text_table_path)
    parsed = parse_menu_file(source_slps, descriptor, table)
    p0_entries, scene_report = _selected_p0_entries(
        project_root,
        config["scene_inventory"],
    )
    overrides, codebook_report = load_ui_font_overrides(
        project_root,
        config,
        font_manifest,
    )
    actionable_entries, no_op_entry_ids = _partition_noop_entries(
        source_slps,
        parsed,
        table,
        decisions=p0_entries,
        overrides=overrides,
    )
    replacements, excluded, writable_selection = select_fixed_menu_replacements(
        source_slps,
        parsed,
        table,
        p0_entries=actionable_entries,
        overrides=overrides,
    )
    selection = {
        "p0_entry_count": len(p0_entries),
        "no_op_entry_count": len(no_op_entry_ids),
        "no_op_entry_ids": list(no_op_entry_ids),
        "selected_write_entry_count": writable_selection["selected_entry_count"],
        "selected_write_target_count": writable_selection["selected_target_count"],
        "fixed_covered_entry_count": (
            len(no_op_entry_ids) + writable_selection["selected_entry_count"]
        ),
        "selection_sha256": writable_selection["selection_sha256"],
        "excluded_entry_count": writable_selection["excluded_entry_count"],
        "excluded_reason_counts": writable_selection["excluded_reason_counts"],
    }
    ratchet = config.get("ratchet")
    if not isinstance(ratchet, dict):
        raise UiMenuError("UI menu profile has no ratchet")
    checks = {
        "p0_unique_entry_count": (
            scene_report["p0_unique_entry_count"] == ratchet["p0_unique_entry_count"]
        ),
        "p0_slps_entry_count": (
            scene_report["p0_slps_entry_count"] == ratchet["p0_slps_entry_count"]
        ),
        "no_op_entry_count": (
            selection["no_op_entry_count"] == ratchet["no_op_entry_count"]
        ),
        "selected_write_entry_count": (
            selection["selected_write_entry_count"]
            == ratchet["selected_write_entry_count"]
        ),
        "selected_write_target_count": (
            selection["selected_write_target_count"]
            == ratchet["selected_write_target_count"]
        ),
        "fixed_covered_entry_count": (
            selection["fixed_covered_entry_count"]
            == ratchet["fixed_covered_entry_count"]
        ),
        "excluded_overflow_entry_count": (
            selection["excluded_reason_counts"].get("overflow", 0)
            == ratchet["excluded_overflow_entry_count"]
        ),
        "excluded_other_entry_count": (
            sum(
                count
                for reason, count in selection["excluded_reason_counts"].items()
                if reason != "overflow"
            )
            == ratchet["excluded_other_entry_count"]
        ),
    }
    if not all(checks.values()):
        raise UiMenuError(f"UI fixed SLPS ratchet failed: {checks}")

    result = replace_menu_texts_in_place(
        source_slps,
        parsed,
        table,
        replacements=replacements,
        overrides=overrides,
        source_name="ui-p0 font SLPS_258.87",
    )
    output = result.data

    changed_offsets = _verify_fixed_span_differences(
        source_slps,
        output,
        parsed,
        result.targets,
    )

    source_font_hash = sha256_bytes(
        decode_vt1_font_segment(source_slps, source_vt1).decoded
    )
    output_font_hash = sha256_bytes(decode_vt1_font_segment(output, source_vt1).decoded)
    if source_font_hash != output_font_hash:
        raise UiMenuError("UI fixed SLPS changed the decoded font component")

    difference_ranges = _difference_range_count(changed_offsets)
    report = {
        "schema_version": 1,
        "status": "fixed_slps_component_validated_iso_runtime_pending",
        "profile_id": config["profile_id"],
        "scope": config["scope"],
        "inputs": {
            "config": {
                "path": str(config_path.relative_to(project_root.resolve())),
                "sha256": _hash_file(config_path),
            },
            "font_manifest": {
                "path": str(font_manifest_path.relative_to(project_root.resolve())),
                "sha256": _hash_file(font_manifest_path),
            },
            "source_slps": {
                "path": str(source_slps_path.relative_to(project_root.resolve())),
                "size": len(source_slps),
                "sha256": sha256_bytes(source_slps),
            },
            "source_vt1": {
                "path": str(source_vt1_path.relative_to(project_root.resolve())),
                "size": len(source_vt1),
                "sha256": sha256_bytes(source_vt1),
            },
            "scene_inventory": scene_report,
            "menu_descriptor": {
                "path": str(descriptor_path.relative_to(project_root.resolve())),
                "sha256": _hash_file(descriptor_path),
                "friendly_name": parsed.friendly_name,
                "parsed_entry_count": len(parsed.entries),
            },
            "text_table": {
                "path": str(text_table_path.relative_to(project_root.resolve())),
                "sha256": _hash_file(text_table_path),
            },
            "codebook": codebook_report,
        },
        "selection": selection,
        "excluded": list(excluded),
        "write": {
            "entry_count": result.entry_count,
            "target_count": len(result.targets),
            "payload_size": sum(target.payload_size for target in result.targets),
            "owned_capacity": sum(target.capacity for target in result.targets),
            "target_metadata_sha256": sha256_bytes(
                json.dumps(
                    [target.to_metadata() for target in result.targets],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            "patch_plan_metadata_sha256": sha256_bytes(
                json.dumps(
                    result.patch_plan.to_metadata(),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            "pointer_write_count": 0,
            "pointer_bytes_unchanged": True,
            "non_target_bytes_unchanged": True,
            "target_reparse_exact": True,
        },
        "component": {
            "size": len(output),
            "sha256": sha256_bytes(output),
            "changed_byte_count": len(changed_offsets),
            "difference_range_count": difference_ranges,
            "source_font_decoded_sha256": source_font_hash,
            "output_font_decoded_sha256": output_font_hash,
            "font_decoded_unchanged": True,
        },
        "ratchet": {
            "expected": ratchet,
            "checks": checks,
            "passed": True,
        },
        "remaining_work": {
            "growing_slps_entry_count": len(excluded),
            "out_of_scope_compdata_p0_entry_count": (
                scene_report["p0_unique_entry_count"]
                - scene_report["p0_slps_entry_count"]
            ),
            "requires_registered_pool_or_other_allocation": [
                item["entry_id"] for item in excluded
            ],
        },
        "runtime": {
            "status": "not_tested",
            "reason": (
                "This is an isolated SLPS component. It has not been "
                "combined with VT1, title assets, COMPDATA, STAGE or an "
                "exact ISO."
            ),
        },
    }
    return output, report


def build_fixed_compdata_component(
    project_root: Path,
    config_path: Path,
) -> tuple[bytes, dict]:
    """Build and independently decode the fixed-span P0 COMPDATA member."""

    config = _json_object(config_path)
    if config.get("schema_version") != 1:
        raise UiMenuError("unsupported UI menu writeback schema")
    _validate_fixed_selection_policy(config, source_file="Compdata")

    font_reference = config.get("font_candidate")
    if not isinstance(font_reference, dict):
        raise UiMenuError("UI menu profile has no font_candidate")
    font_manifest_path = _project_path(
        project_root,
        font_reference.get("manifest"),
    )
    if _hash_file(font_manifest_path) != font_reference.get("sha256"):
        raise UiMenuError("UI font candidate manifest SHA-256 drift")
    font_manifest = _json_object(font_manifest_path)
    if font_manifest.get("status") != (
        "offline_font_and_p0_renderer_coverage_passed_runtime_pending"
    ):
        raise UiMenuError("UI font candidate status is invalid")
    overrides, codebook_report = load_ui_font_overrides(
        project_root,
        config,
        font_manifest,
    )

    source_reference = config.get("source_member")
    if not isinstance(source_reference, dict):
        raise UiMenuError("UI COMPDATA profile has no source_member")
    source_path = _load_hashed_path(
        project_root,
        source_reference,
        label="COMPDATA source member",
    )
    source_member = source_path.read_bytes()
    if len(source_member) != source_reference.get("size"):
        raise UiMenuError("COMPDATA source member size drift")
    decoded_result = decode(source_member)
    source_decoded = decoded_result.output
    if decoded_result.consumed != len(source_member):
        raise UiMenuError("COMPDATA source has trailing bytes")
    if (
        len(source_decoded) != source_reference.get("decoded_size")
        or sha256_bytes(source_decoded) != source_reference.get("decoded_sha256")
        or decoded_result.flags != source_reference.get("flags")
    ):
        raise UiMenuError("COMPDATA decoded source drift")

    descriptor_path, descriptor = _load_menu_descriptor(
        project_root,
        config["menu_descriptor"],
    )
    text_table_path = _load_hashed_path(
        project_root,
        config["text_table"],
        label="text table",
    )
    table = load_text_table(text_table_path)
    parsed = parse_menu_file(source_decoded, descriptor, table)
    p0_entries, scene_report = _selected_p0_entries_for_prefix(
        project_root,
        config["scene_inventory"],
        entry_prefix="menu/Compdata/",
        count_key="p0_compdata_entry_count",
    )
    actionable_entries, no_op_entry_ids = _partition_noop_entries(
        source_decoded,
        parsed,
        table,
        decisions=p0_entries,
        overrides=overrides,
    )
    replacements, excluded, writable_selection = select_fixed_menu_replacements(
        source_decoded,
        parsed,
        table,
        p0_entries=actionable_entries,
        overrides=overrides,
    )
    selection = {
        "p0_entry_count": len(p0_entries),
        "no_op_entry_count": len(no_op_entry_ids),
        "no_op_entry_ids": list(no_op_entry_ids),
        "selected_write_entry_count": writable_selection["selected_entry_count"],
        "selected_write_target_count": writable_selection["selected_target_count"],
        "fixed_covered_entry_count": (
            len(no_op_entry_ids) + writable_selection["selected_entry_count"]
        ),
        "selection_sha256": writable_selection["selection_sha256"],
        "excluded_entry_count": writable_selection["excluded_entry_count"],
        "excluded_reason_counts": writable_selection["excluded_reason_counts"],
    }

    ratchet = config.get("ratchet")
    if not isinstance(ratchet, dict):
        raise UiMenuError("UI COMPDATA profile has no ratchet")
    checks = {
        "p0_unique_entry_count": (
            scene_report["p0_unique_entry_count"] == ratchet["p0_unique_entry_count"]
        ),
        "p0_compdata_entry_count": (
            scene_report["p0_compdata_entry_count"]
            == ratchet["p0_compdata_entry_count"]
        ),
        "no_op_entry_count": (
            selection["no_op_entry_count"] == ratchet["no_op_entry_count"]
        ),
        "selected_write_entry_count": (
            selection["selected_write_entry_count"]
            == ratchet["selected_write_entry_count"]
        ),
        "selected_write_target_count": (
            selection["selected_write_target_count"]
            == ratchet["selected_write_target_count"]
        ),
        "fixed_covered_entry_count": (
            selection["fixed_covered_entry_count"]
            == ratchet["fixed_covered_entry_count"]
        ),
        "excluded_overflow_entry_count": (
            selection["excluded_reason_counts"].get("overflow", 0)
            == ratchet["excluded_overflow_entry_count"]
        ),
        "excluded_other_entry_count": (
            sum(
                count
                for reason, count in selection["excluded_reason_counts"].items()
                if reason != "overflow"
            )
            == ratchet["excluded_other_entry_count"]
        ),
    }
    if not all(checks.values()):
        raise UiMenuError(f"UI fixed COMPDATA ratchet failed: {checks}")

    result = replace_menu_texts_in_place(
        source_decoded,
        parsed,
        table,
        replacements=replacements,
        overrides=overrides,
        source_name="original decoded DATA/COMPDATA.BN",
    )
    output_decoded = result.data
    changed_offsets = _verify_fixed_span_differences(
        source_decoded,
        output_decoded,
        parsed,
        result.targets,
    )

    codec_config = config.get("codec")
    if not isinstance(codec_config, dict):
        raise UiMenuError("UI COMPDATA profile has no codec policy")
    if codec_config.get("mode") != "preserve-prefix-reencode-suffix":
        raise UiMenuError("unsupported UI COMPDATA codec mode")
    output_member = reencode_changed_suffix(
        source_member,
        output_decoded,
        strategy=codec_config["strategy"],
        min_match_length=codec_config["min_match_length"],
        max_match_chain=codec_config["max_match_chain"],
        lazy_matching=codec_config["lazy_matching"],
    )
    output_decoded_result = decode(output_member)
    if (
        output_decoded_result.consumed != len(output_member)
        or output_decoded_result.output != output_decoded
        or output_decoded_result.flags != decoded_result.flags
    ):
        raise UiMenuError("rebuilt COMPDATA member fails codec round-trip")
    compressed_common_prefix = next(
        (
            offset
            for offset, (before, after) in enumerate(zip(source_member, output_member))
            if before != after
        ),
        min(len(source_member), len(output_member)),
    )
    if compressed_common_prefix < ratchet["minimum_preserved_compressed_prefix"]:
        raise UiMenuError("COMPDATA preserved compressed prefix regressed")

    pointer_site_count = len(_menu_pointer_sites(source_decoded, parsed))
    report = {
        "schema_version": 1,
        "status": "fixed_compdata_component_validated_iso_runtime_pending",
        "profile_id": config["profile_id"],
        "scope": config["scope"],
        "inputs": {
            "config": {
                "path": str(config_path.relative_to(project_root.resolve())),
                "sha256": _hash_file(config_path),
            },
            "font_manifest": {
                "path": str(font_manifest_path.relative_to(project_root.resolve())),
                "sha256": _hash_file(font_manifest_path),
            },
            "source_member": {
                "path": str(source_path.relative_to(project_root.resolve())),
                "size": len(source_member),
                "sha256": sha256_bytes(source_member),
                "decoded_size": len(source_decoded),
                "decoded_sha256": sha256_bytes(source_decoded),
                "flags": decoded_result.flags,
                "fully_consumed": True,
            },
            "scene_inventory": scene_report,
            "menu_descriptor": {
                "path": str(descriptor_path.relative_to(project_root.resolve())),
                "sha256": _hash_file(descriptor_path),
                "friendly_name": parsed.friendly_name,
                "parsed_entry_count": len(parsed.entries),
            },
            "text_table": {
                "path": str(text_table_path.relative_to(project_root.resolve())),
                "sha256": _hash_file(text_table_path),
            },
            "codebook": codebook_report,
        },
        "selection": selection,
        "excluded": list(excluded),
        "write": {
            "entry_count": result.entry_count,
            "target_count": len(result.targets),
            "payload_size": sum(target.payload_size for target in result.targets),
            "owned_capacity": sum(target.capacity for target in result.targets),
            "target_metadata_sha256": sha256_bytes(
                json.dumps(
                    [target.to_metadata() for target in result.targets],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            "patch_plan_metadata_sha256": sha256_bytes(
                json.dumps(
                    result.patch_plan.to_metadata(),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            "pointer_write_count": 0,
            "pointer_site_byte_count": pointer_site_count,
            "pointer_bytes_unchanged": True,
            "non_target_bytes_unchanged": True,
            "target_reparse_exact": True,
        },
        "decoded_component": {
            "size": len(output_decoded),
            "source_sha256": sha256_bytes(source_decoded),
            "output_sha256": sha256_bytes(output_decoded),
            "changed_byte_count": len(changed_offsets),
            "difference_range_count": _difference_range_count(changed_offsets),
        },
        "compressed_component": {
            "source_size": len(source_member),
            "output_size": len(output_member),
            "size_delta": len(output_member) - len(source_member),
            "source_sha256": sha256_bytes(source_member),
            "output_sha256": sha256_bytes(output_member),
            "strategy": codec_config["strategy"],
            "min_match_length": codec_config["min_match_length"],
            "max_match_chain": codec_config["max_match_chain"],
            "lazy_matching": codec_config["lazy_matching"],
            "preserved_prefix_size": compressed_common_prefix,
            "flags_preserved": True,
            "decoded_round_trip_exact": True,
            "fully_consumed": True,
        },
        "ratchet": {
            "expected": ratchet,
            "checks": checks,
            "passed": True,
        },
        "remaining_work": {
            "growing_compdata_entry_count": len(excluded),
            "requires_registered_pool_or_other_allocation": [
                item["entry_id"] for item in excluded
            ],
        },
        "runtime": {
            "status": "not_tested",
            "reason": (
                "This is an isolated COMPDATA member. It has not been "
                "combined with the UI font, SLPS, title assets, STAGE "
                "or an exact ISO."
            ),
        },
    }
    return output_member, report


__all__ = [
    "UiMenuError",
    "build_fixed_compdata_component",
    "build_fixed_slps_component",
    "load_ui_font_overrides",
    "select_fixed_menu_replacements",
    "select_fixed_slps_replacements",
]
