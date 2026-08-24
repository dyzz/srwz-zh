#!/usr/bin/env python3
"""Build and statically validate the current SRWZ Chinese PS2 DVD image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from srwz.iso_config import (
        IsoBuildError,
        expected_shift_segments,
        load_config,
        validate_directory_contract as _validate_directory_contract,
    )
    from srwz.iso9660 import (
        SECTOR_SIZE,
        Iso9660Error,
        extent_order,
        member_manifest_sha256,
        member_map,
        pcsx2_v263_image_type,
        scan_iso9660,
        sha256_member,
    )
except ModuleNotFoundError:
    from tools.srwz.iso_config import (
        IsoBuildError,
        expected_shift_segments,
        load_config,
        validate_directory_contract as _validate_directory_contract,
    )
    from tools.srwz.iso9660 import (
        SECTOR_SIZE,
        Iso9660Error,
        extent_order,
        member_manifest_sha256,
        member_map,
        pcsx2_v263_image_type,
        scan_iso9660,
        sha256_member,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config" / "iso" / "zh-release-current-build.json"
)
HASH_CHUNK_SIZE = 4 * 1024 * 1024
BOOT_LOGO_SIZE = 12 * 2048


def validate_directory_contract(config: dict) -> None:
    """Keep the builder import surface while sharing one validator."""

    _validate_directory_contract(config)


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(HASH_CHUNK_SIZE):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()

def resolve_project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise IsoBuildError(f"path escapes project root: {value}") from exc
    return path


def verify_file(path: Path, expected_size: int, expected_sha256: str) -> None:
    if not path.is_file():
        raise IsoBuildError(f"missing required file: {path}")
    actual_size, actual_sha256 = sha256_file(path)
    if actual_size != expected_size:
        raise IsoBuildError(
            f"{path} size {actual_size}, expected {expected_size}"
        )
    if actual_sha256 != expected_sha256:
        raise IsoBuildError(
            f"{path} SHA-256 {actual_sha256}, expected {expected_sha256}"
        )


def validate_current_component_inputs(config: dict, manifest: dict) -> dict:
    """Reject a working ISO assembled from a stale component receipt."""

    if config.get("require_current_component_input_binding") is not True:
        return {"enforced": False}
    if config.get("release_tag") is not None:
        raise IsoBuildError(
            "current component input binding is only valid for a working profile"
        )
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise IsoBuildError("component validation manifest has no input locks")

    verified_paths: dict[Path, tuple[int, str]] = {}
    for label, lock in inputs.items():
        if not isinstance(lock, dict):
            raise IsoBuildError(f"component input lock is invalid: {label}")
        raw_path = lock.get("path")
        expected_size = lock.get("size")
        expected_sha256 = lock.get("sha256")
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or expected_size < 0
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise IsoBuildError(f"component input lock is invalid: {label}")
        path = resolve_project_path(raw_path)
        identity = (expected_size, expected_sha256)
        previous = verified_paths.get(path)
        if previous is not None:
            if previous != identity:
                raise IsoBuildError(
                    f"component input has conflicting locks: {raw_path}"
                )
            continue
        verified_paths[path] = identity
        try:
            verify_file(path, expected_size, expected_sha256)
        except IsoBuildError as error:
            raise IsoBuildError(
                f"component input drift requires a component rebuild: {label}"
            ) from error
    return {
        "enforced": True,
        "input_lock_count": len(inputs),
        "unique_input_path_count": len(verified_paths),
        "all_component_inputs_current": True,
    }


def validate_component_output_binding(config: dict) -> dict:
    """Bind every ISO replacement to one validated component manifest."""

    if config.get("require_component_output_binding") is not True:
        return {"enforced": False}
    manifest_reference = config.get("component_validation_manifest")
    required_status = config.get("component_required_status")
    if (
        not isinstance(manifest_reference, str)
        or not manifest_reference
        or not isinstance(required_status, str)
        or not required_status
    ):
        raise IsoBuildError("component output binding contract is incomplete")
    manifest_path = resolve_project_path(manifest_reference)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IsoBuildError(
            f"cannot load component validation manifest: {manifest_reference}"
        ) from error
    outputs = manifest.get("outputs")
    if manifest.get("status") != required_status or not isinstance(
        outputs, dict
    ):
        raise IsoBuildError("component validation manifest identity drift")
    current_inputs = validate_current_component_inputs(config, manifest)
    replacement_members = {
        replacement["member"] for replacement in config["replacements"]
    }
    if replacement_members != set(outputs):
        raise IsoBuildError(
            "replacement member set differs from component manifest"
        )
    for replacement in config["replacements"]:
        member = replacement["member"]
        lock = outputs.get(member)
        if not isinstance(lock, dict) or any(
            replacement.get(field) != lock.get(field)
            for field in ("size", "sha256")
        ):
            raise IsoBuildError(
                f"replacement differs from component manifest: {member}"
            )
        if replacement.get("source") != lock.get("path"):
            raise IsoBuildError(
                f"replacement path differs from component manifest: {member}"
            )
    return {
        "enforced": True,
        "manifest": manifest_reference,
        "status": required_status,
        "replacement_count": len(config["replacements"]),
        "all_replacements_match_component_outputs": True,
        "current_inputs": current_inputs,
    }


def refresh_component_output_locks(config: dict) -> int:
    """Refresh a non-release working profile from its validated components."""

    if config.get("release_tag") is not None:
        raise IsoBuildError("refusing to refresh output locks in a release profile")
    if config.get("require_component_output_binding") is not True:
        raise IsoBuildError("working lock refresh requires component binding")
    manifest_reference = config.get("component_validation_manifest")
    manifest_path = resolve_project_path(manifest_reference)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IsoBuildError(
            f"cannot load component validation manifest: {manifest_reference}"
        ) from error
    outputs = manifest.get("outputs")
    if (
        manifest.get("status") != config.get("component_required_status")
        or not isinstance(outputs, dict)
    ):
        raise IsoBuildError("component validation manifest identity drift")
    replacements = config.get("replacements")
    if not isinstance(replacements, list) or {
        item.get("member") for item in replacements if isinstance(item, dict)
    } != set(outputs):
        raise IsoBuildError("replacement member set differs from component manifest")
    for replacement in replacements:
        member = replacement["member"]
        lock = outputs.get(member)
        if (
            not isinstance(lock, dict)
            or replacement.get("source") != lock.get("path")
            or not isinstance(lock.get("size"), int)
            or not isinstance(lock.get("sha256"), str)
        ):
            raise IsoBuildError(
                f"replacement path differs from component manifest: {member}"
            )
        replacement["size"] = lock["size"]
        replacement["sha256"] = lock["sha256"]
    config["output"].pop("expected_sha256", None)
    config["output"].pop("expected_member_manifest_sha256", None)
    return len(replacements)


def validate_replacement_sector_budget(config: dict, source_image) -> dict:
    """Fail before rebuilding when a fixed-LBA profile outgrows a member."""

    enforced = config["layout"].get(
        "preserve_original_member_sector_allocations",
        False,
    )
    if not enforced:
        return {"enforced": False}

    shift_segments = expected_shift_segments(config)
    if any(shift_sectors != 0 for _, shift_sectors in shift_segments):
        raise IsoBuildError(
            "fixed member-sector allocation requires zero LBA shift segments"
        )
    if config["output"].get("expected_size") != config["source_iso"]["size"]:
        raise IsoBuildError(
            "fixed member-sector allocation requires output size to equal "
            "the source ISO size"
        )

    source_members = member_map(source_image)
    entries = []
    for replacement in config["replacements"]:
        path = replacement["member"]
        source_member = source_members.get(path)
        if source_member is None:
            raise IsoBuildError(
                f"replacement member is absent from the source ISO: {path}"
            )
        candidate_size = replacement.get("size")
        if (
            not isinstance(candidate_size, int)
            or isinstance(candidate_size, bool)
            or candidate_size < 0
        ):
            raise IsoBuildError(f"replacement size is invalid: {path}")
        source_sectors = (source_member.size + SECTOR_SIZE - 1) // SECTOR_SIZE
        candidate_sectors = (candidate_size + SECTOR_SIZE - 1) // SECTOR_SIZE
        if candidate_sectors > source_sectors:
            raise IsoBuildError(
                f"replacement exceeds original member sectors: {path} "
                f"needs {candidate_sectors}, source has {source_sectors}"
            )
        entries.append(
            {
                "member": path,
                "source_size": source_member.size,
                "candidate_size": candidate_size,
                "source_sectors": source_sectors,
                "candidate_sectors": candidate_sectors,
                "within_original_member_sectors": True,
            }
        )

    return {
        "enforced": True,
        "sector_size": SECTOR_SIZE,
        "all_shift_segments_zero": True,
        "output_size_equals_source_iso": True,
        "all_replacements_within_original_member_sectors": True,
        "entries": entries,
    }


def resolve_tool(tool_config: dict) -> str:
    default_path = resolve_project_path(tool_config["default_path"])
    candidates = [default_path]
    path_candidate = shutil.which(tool_config["executable"])
    if path_candidate is not None:
        candidates.append(Path(path_candidate))

    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise IsoBuildError(
            f"{tool_config['executable']} {tool_config['version']} is "
            "required; run: python3 tools/bootstrap_mkps2iso.py"
        )

    process = subprocess.run(
        [str(executable), "--help"],
        capture_output=True,
        text=True,
    )
    output = process.stdout + process.stderr
    first_line = next(
        (line.strip() for line in output.splitlines() if line.strip()),
        "",
    )
    if first_line != tool_config["version_line"]:
        raise IsoBuildError(
            f"{executable} version line {first_line!r}, expected "
            f"{tool_config['version_line']!r}"
        )
    return str(executable)


def tree_file_map(root: Path) -> dict[str, Path]:
    files = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.casefold() == "boot_logo.raw":
            continue
        normalized = relative.upper()
        if normalized in files:
            raise IsoBuildError(
                f"case-insensitive duplicate in extracted tree: {relative}"
            )
        files[normalized] = path
    return files


def _sanitize_dump_xml(path: Path, volume_id: str) -> None:
    raw = path.read_bytes()
    pattern = re.compile(rb'(\svolume=")[^"]*(")')
    replacement = volume_id.encode("ascii")
    raw, count = pattern.subn(
        lambda match: match.group(1) + replacement + match.group(2),
        raw,
        count=1,
    )
    if count != 1:
        raise IsoBuildError("dumps2iso XML has no unique volume attribute")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IsoBuildError(
            "dumps2iso XML remains non-UTF-8 after volume sanitization"
        ) from exc
    path.write_text(text, encoding="utf-8")


def extract_original_layout(
    dumper: str,
    iso_path: Path,
    original_tree: Path,
    base_xml: Path,
    expected_paths: set[str],
    *,
    volume_id: str,
    refresh: bool,
) -> None:
    if refresh:
        if original_tree.exists():
            shutil.rmtree(original_tree)
        if base_xml.exists():
            base_xml.unlink()

    logo = original_tree / "boot_logo.raw"
    if original_tree.exists() or base_xml.exists():
        if not original_tree.is_dir() or not base_xml.is_file():
            raise IsoBuildError(
                "partial mkps2iso extraction cache; rerun with "
                "--refresh-extraction"
            )
        actual_paths = set(tree_file_map(original_tree))
        if actual_paths != expected_paths:
            raise IsoBuildError(
                "cached mkps2iso extraction has a different member set; "
                "rerun with --refresh-extraction"
            )
        if not logo.is_file() or logo.stat().st_size != BOOT_LOGO_SIZE:
            raise IsoBuildError(
                "cached boot_logo.raw is missing or has the wrong size"
            )
        _sanitize_dump_xml(base_xml, volume_id)
        print(f"[OK] reuse mkps2iso extraction: {original_tree}")
        return

    original_tree.parent.mkdir(parents=True, exist_ok=True)
    base_xml.parent.mkdir(parents=True, exist_ok=True)
    command = [
        dumper,
        "-L",
        "-o",
        str(original_tree),
        "-x",
        str(base_xml),
        str(iso_path),
    ]
    print(f"[BUILD] extracting original PS2 layout to {original_tree}")
    process = subprocess.run(
        command,
        capture_output=True,
    )
    if process.returncode != 0:
        details = (process.stdout + process.stderr).decode(
            "utf-8",
            errors="replace",
        )
        raise IsoBuildError(
            f"dumps2iso failed ({process.returncode}): "
            f"{details.strip()}"
        )
    _sanitize_dump_xml(base_xml, volume_id)

    actual_paths = set(tree_file_map(original_tree))
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        raise IsoBuildError(
            f"extracted member set mismatch; missing={missing}, extra={extra}"
        )
    if not logo.is_file() or logo.stat().st_size != BOOT_LOGO_SIZE:
        raise IsoBuildError("dumps2iso did not produce a 24 KiB boot logo")
    print(f"[OK] extracted member set: {len(actual_paths)} files")


def verify_extracted_members(source_image, original_tree: Path) -> None:
    extracted = tree_file_map(original_tree)
    for member in source_image.members:
        path = extracted[member.path.upper()]
        size, digest = sha256_file(path)
        if size != member.size or digest != sha256_member(
            source_image.path,
            member,
        ):
            raise IsoBuildError(
                f"extracted member differs from original ISO: {member.path}"
            )
    print(f"[OK] extracted bytes: {len(source_image.members)} members exact")


def hardlink_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, copy_function=os.link)


def install_replacements(config: dict, staging_tree: Path) -> dict[str, Path]:
    staged_paths = tree_file_map(staging_tree)
    replacements = {}
    for item in config["replacements"]:
        source = resolve_project_path(item["source"])
        verify_file(source, item["size"], item["sha256"])
        target = staged_paths.get(item["member"].upper())
        if target is None:
            raise IsoBuildError(f"replacement member is absent: {item['member']}")
        old_stat = target.stat()
        target.unlink()
        shutil.copyfile(source, target)
        os.utime(target, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        replacements[item["member"]] = source
        print(f"[OK] staged replacement: {item['member']}")
    return replacements


def write_build_xml(
    base_xml: Path,
    build_xml: Path,
    staging_tree: Path,
    volume_id: str,
    member_lbas: dict[str, int] | None = None,
) -> None:
    text = base_xml.read_text(encoding="utf-8")
    text, source_count = re.subn(
        r'(<directory_tree\s+source=")[^"]*(")',
        lambda match: (
            match.group(1) + staging_tree.as_posix() + match.group(2)
        ),
        text,
        count=1,
    )
    text, logo_count = re.subn(
        r'(<logo\s+file=")[^"]*(")',
        lambda match: (
            match.group(1)
            + (staging_tree / "boot_logo.raw").as_posix()
            + match.group(2)
        ),
        text,
        count=1,
    )
    text, volume_count = re.subn(
        r'(\svolume=")[^"]*(")',
        lambda match: match.group(1) + volume_id + match.group(2),
        text,
        count=1,
    )
    if (source_count, logo_count, volume_count) != (1, 1, 1):
        raise IsoBuildError(
            "mkps2iso XML source/logo/volume rewrite was not unique"
        )
    if member_lbas is not None:
        text = _pin_xml_file_lbas(text, member_lbas)
    build_xml.parent.mkdir(parents=True, exist_ok=True)
    build_xml.write_text(text, encoding="utf-8")


def _xml_file_member_paths(text: str) -> list[str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise IsoBuildError("mkps2iso XML is malformed") from exc
    directory_tree = root.find(".//directory_tree")
    if directory_tree is None:
        raise IsoBuildError("mkps2iso XML has no directory_tree element")

    paths: list[str] = []

    def walk(element: ET.Element, prefix: tuple[str, ...]) -> None:
        for child in element:
            tag = child.tag.casefold()
            if tag == "file":
                name = child.get("name")
                if not name:
                    raise IsoBuildError("mkps2iso XML file has no name")
                paths.append("/".join((*prefix, name)).upper())
            elif tag == "dir":
                name = child.get("name")
                if not name:
                    raise IsoBuildError("mkps2iso XML dir has no name")
                walk(child, (*prefix, name))

    walk(directory_tree, ())
    if len(paths) != len(set(paths)):
        raise IsoBuildError("mkps2iso XML contains duplicate file paths")
    return paths


def _pin_xml_file_lbas(text: str, member_lbas: dict[str, int]) -> str:
    """Force logical members to their intended LBAs without padding them."""

    normalized_lbas = {
        path.upper(): int(lba) for path, lba in member_lbas.items()
    }
    paths = _xml_file_member_paths(text)
    if set(paths) != set(normalized_lbas):
        missing = sorted(set(normalized_lbas) - set(paths))
        extra = sorted(set(paths) - set(normalized_lbas))
        raise IsoBuildError(
            "mkps2iso XML member set differs while pinning LBAs; "
            f"missing={missing}, extra={extra}"
        )
    if any(lba <= 0 for lba in normalized_lbas.values()):
        raise IsoBuildError("mkps2iso member LBAs must be positive")

    path_index = 0

    def pin(match: re.Match[str]) -> str:
        nonlocal path_index
        path = paths[path_index]
        path_index += 1
        tag = match.group(0)
        lba = normalized_lbas[path]
        if re.search(r'\soffs="[^"]*"', tag):
            tag, count = re.subn(
                r'(\soffs=")[^"]*(")',
                lambda offset_match: (
                    offset_match.group(1)
                    + str(lba)
                    + offset_match.group(2)
                ),
                tag,
                count=1,
            )
            if count != 1:
                raise IsoBuildError(f"could not replace XML LBA for {path}")
            return tag
        suffix = "/>" if tag.endswith("/>") else ">"
        return tag[: -len(suffix)] + f' offs="{lba}"' + suffix

    text, count = re.subn(r"<file\b[^>]*?/?>", pin, text)
    if count != len(paths) or path_index != len(paths):
        raise IsoBuildError("mkps2iso XML file/LBA rewrite count differs")
    return text


def run_mkps2iso(
    executable: str,
    build_xml: Path,
    output_path: Path,
    lba_log: Path,
) -> list[str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lba_log.parent.mkdir(parents=True, exist_ok=True)
    command = [
        executable,
        "-q",
        "-y",
        "-l",
        str(lba_log),
        "-o",
        str(output_path),
        str(build_xml),
    ]
    print(f"[BUILD] writing {output_path}")
    process = subprocess.run(command, capture_output=True, text=True)
    output = (process.stdout + process.stderr).strip()
    if output:
        print(output)
    if process.returncode != 0:
        raise IsoBuildError(f"mkps2iso failed with exit {process.returncode}")
    return command


def sha256_7z_member(seven_zip: str, image: Path, member: str) -> str:
    process = subprocess.Popen(
        [seven_zip, "e", "-so", str(image), member],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    digest = hashlib.sha256()
    while chunk := process.stdout.read(HASH_CHUNK_SIZE):
        digest.update(chunk)
    stderr = process.stderr.read().decode("utf-8", errors="replace")
    returncode = process.wait()
    if returncode != 0:
        raise IsoBuildError(
            f"7z UDF read failed for {member} ({returncode}): "
            f"{stderr.strip()}"
        )
    return digest.hexdigest()


def validate_output(
    config: dict,
    source_image,
    output_path: Path,
) -> dict:
    output_image = scan_iso9660(output_path)
    source_members = member_map(source_image)
    output_members = member_map(output_image)
    if set(source_members) != set(output_members):
        raise IsoBuildError("output ISO member paths differ from the original")
    if extent_order(source_image) != extent_order(output_image):
        raise IsoBuildError("output ISO member data order differs from the original")

    expected_root_size = config["output"]["expected_root_directory_size"]
    if output_image.root_directory_size != expected_root_size:
        raise IsoBuildError(
            f"output root-directory size {output_image.root_directory_size}, "
            f"expected {expected_root_size}"
        )
    output_media_type = pcsx2_v263_image_type(
        output_image.root_directory_size
    )
    expected_media_type = config["output"]["expected_pcsx2_v263_image_type"]
    if output_media_type != expected_media_type:
        raise IsoBuildError(
            f"PCSX2 v2.6.3 would classify output as {output_media_type}, "
            f"expected {expected_media_type}"
        )
    if (
        output_image.udf_volume_recognition_sequence
        != config["output"]["expected_udf_volume_recognition_sequence"]
    ):
        raise IsoBuildError("output UDF volume recognition sequence changed")

    shift_segments = expected_shift_segments(config)
    segment_by_member = dict(shift_segments)
    found_segments = []
    current_shift = 0
    shifted_members = []
    prefix_members = []
    for path in extent_order(source_image):
        if path in segment_by_member:
            current_shift = segment_by_member[path]
            found_segments.append(path)
        expected_lba = source_members[path].extent_lba + current_shift
        if output_members[path].extent_lba != expected_lba:
            raise IsoBuildError(
                f"unexpected output LBA for {path}: "
                f"{output_members[path].extent_lba}, expected {expected_lba}"
            )
        (shifted_members if current_shift else prefix_members).append(path)
    expected_segment_members = tuple(
        first_member for first_member, _ in shift_segments
    )
    if tuple(found_segments) != expected_segment_members:
        missing = [
            first_member
            for first_member in expected_segment_members
            if first_member not in found_segments
        ]
        raise IsoBuildError(f"shift segment members not found: {missing}")

    replacement_config = {
        item["member"]: item for item in config["replacements"]
    }
    unchanged_count = 0
    replacements = []
    semantic_entries = []
    system_cnf_exact = False
    for path in extent_order(source_image):
        source_member = source_members[path]
        output_member = output_members[path]
        output_hash = sha256_member(output_path, output_member)
        semantic_entries.append((path, output_member.size, output_hash))
        replacement = replacement_config.get(path)
        if replacement is not None:
            if output_member.size != replacement["size"]:
                raise IsoBuildError(f"replacement size mismatch: {path}")
            if output_hash != replacement["sha256"]:
                raise IsoBuildError(f"replacement SHA-256 mismatch: {path}")
            replacements.append(
                {
                    "member": path,
                    "size": output_member.size,
                    "sha256": output_hash,
                    "extent_lba": output_member.extent_lba,
                }
            )
            continue

        source_hash = sha256_member(source_image.path, source_member)
        if output_member.size != source_member.size or output_hash != source_hash:
            raise IsoBuildError(f"unchanged member differs: {path}")
        unchanged_count += 1
        if path == "SYSTEM.CNF":
            system_cnf_exact = True

    if not system_cnf_exact:
        raise IsoBuildError("SYSTEM.CNF was not verified byte-exact")

    seven_zip = shutil.which("7z")
    if seven_zip is None:
        raise IsoBuildError("7z is required for independent UDF reads")
    udf_hashes = {}
    for path in config["acceptance"]["udf_verify_members"]:
        expected_hash = (
            replacement_config[path]["sha256"]
            if path in replacement_config
            else sha256_member(source_image.path, source_members[path])
        )
        actual_hash = sha256_7z_member(seven_zip, output_path, path)
        if actual_hash != expected_hash:
            raise IsoBuildError(f"independent UDF bytes differ: {path}")
        udf_hashes[path] = actual_hash

    member_manifest_hash = member_manifest_sha256(semantic_entries)
    expected_member_manifest_hash = config["output"].get(
        "expected_member_manifest_sha256"
    )
    if (
        expected_member_manifest_hash is not None
        and member_manifest_hash != expected_member_manifest_hash
    ):
        raise IsoBuildError(
            f"member manifest SHA-256 {member_manifest_hash}, expected "
            f"{expected_member_manifest_hash}"
        )

    output_size, output_sha256 = sha256_file(output_path)
    expected_size = config["output"].get("expected_size")
    expected_sha256 = config["output"].get("expected_sha256")
    if expected_size is not None and output_size != expected_size:
        raise IsoBuildError(
            f"output size {output_size}, expected {expected_size}"
        )
    if expected_sha256 is not None and output_sha256 != expected_sha256:
        raise IsoBuildError(
            f"output SHA-256 {output_sha256}, expected {expected_sha256}"
        )

    return {
        "schema_version": 2,
        "status": "static_iso_validated_runtime_evidence_separate",
        "source_iso": {
            "size": source_image.path.stat().st_size,
            "sha256": config["source_iso"]["sha256"],
            "member_count": len(source_image.members),
            "root_directory_size": source_image.root_directory_size,
            "pcsx2_v263_image_type": pcsx2_v263_image_type(
                source_image.root_directory_size
            ),
            "udf_volume_recognition_sequence": (
                source_image.udf_volume_recognition_sequence
            ),
        },
        "output_iso": {
            "path": output_path.relative_to(PROJECT_ROOT).as_posix(),
            "size": output_size,
            "sha256": output_sha256,
            "member_count": len(output_image.members),
            "iso9660_system_id": output_image.system_id,
            "iso9660_volume_id": output_image.volume_id,
            "root_directory_size": output_image.root_directory_size,
            "pcsx2_v263_image_type": output_media_type,
            "udf_volume_recognition_sequence": (
                output_image.udf_volume_recognition_sequence
            ),
            "byte_reproducible": config["output"]["byte_reproducible"],
        },
        "layout": {
            "member_paths_exact": True,
            "member_order_exact": True,
            "unchanged_member_count": unchanged_count,
            "unchanged_member_bytes_exact": True,
            "replacement_bytes_exact": True,
            "system_cnf_exact": True,
            "member_manifest_sha256": member_manifest_hash,
            "semantic_reproducible": True,
            "lba_prefix_preserved_through": prefix_members[-1],
            "shifted_member_count": len(shifted_members),
            "shift_sectors": (
                shift_segments[0][1]
                if len(shift_segments) == 1
                else None
            ),
            "shift_segments": [
                {
                    "first_member": first_member,
                    "shift_sectors": shift_sectors,
                }
                for first_member, shift_sectors in shift_segments
            ],
        },
        "independent_udf_reads": udf_hashes,
        "replacements": replacements,
        "runtime_acceptance": "not tested by ISO builder",
        "runtime_evidence_manifest": config.get(
            "runtime_evidence_manifest"
        ),
        "emulator_executed_by_builder": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build and statically validate the current SRWZ Chinese PS2 DVD."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--refresh-extraction",
        action="store_true",
        help="Recreate the cached original layout under work/ with dumps2iso.",
    )
    parser.add_argument(
        "--refresh-output-locks",
        action="store_true",
        help=(
            "For a non-release working profile, bind replacements to the "
            "current validated component manifest and record the newly "
            "validated ISO/member-manifest hashes."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config_path = args.config.resolve()
        config = load_config(config_path)
        if args.refresh_output_locks:
            refreshed_count = refresh_component_output_locks(config)
            print(
                "[refresh] working replacement locks:",
                f"{refreshed_count} members",
            )
        component_binding = validate_component_output_binding(config)
        if component_binding["enforced"]:
            print(
                "[OK] component manifest binding: "
                f"{component_binding['replacement_count']} replacements"
            )
            current_inputs = component_binding["current_inputs"]
            if current_inputs["enforced"]:
                print(
                    "[OK] component manifest live inputs: "
                    f"{current_inputs['input_lock_count']} locks"
                )
        source_iso = resolve_project_path(config["source_iso"]["path"])
        verify_file(
            source_iso,
            config["source_iso"]["size"],
            config["source_iso"]["sha256"],
        )
        print("[OK] original ISO baseline")

        source_image = scan_iso9660(source_iso)
        if len(source_image.members) != config["source_iso"]["member_count"]:
            raise IsoBuildError("original ISO member count changed")
        if source_image.system_id != config["source_iso"]["iso9660_system_id"]:
            raise IsoBuildError("original ISO system ID changed")
        if (
            source_image.udf_volume_recognition_sequence
            != config["source_iso"]["udf_volume_recognition_sequence"]
        ):
            raise IsoBuildError(
                "original ISO UDF volume recognition sequence changed"
            )
        print(
            f"[OK] original PS2 DVD layout: "
            f"{len(source_image.members)} members, "
            f"UDF {source_image.udf_volume_recognition_sequence}"
        )

        sector_budget = validate_replacement_sector_budget(
            config,
            source_image,
        )
        if sector_budget["enforced"]:
            print(
                "[OK] fixed-LBA sector budget: every replacement stays "
                "within its original member sectors"
            )

        mkps2iso = resolve_tool(config["toolchain"]["mkps2iso"])
        dumps2iso = resolve_tool(config["toolchain"]["dumps2iso"])
        print(
            f"[OK] mkps2iso toolchain {config['toolchain']['version']} "
            f"({config['toolchain']['commit'][:12]})"
        )

        original_tree = resolve_project_path(
            config["workspace"]["original_tree"]
        )
        staging_tree = resolve_project_path(
            config["workspace"]["staging_tree"]
        )
        base_xml = resolve_project_path(config["workspace"]["base_xml"])
        build_xml = resolve_project_path(config["workspace"]["build_xml"])
        lba_log = resolve_project_path(config["workspace"]["lba_log"])
        expected_paths = set(member_map(source_image))
        extract_original_layout(
            dumps2iso,
            source_iso,
            original_tree,
            base_xml,
            expected_paths,
            volume_id=config["layout"]["volume_id"],
            refresh=args.refresh_extraction,
        )
        verify_extracted_members(source_image, original_tree)

        hardlink_tree(original_tree, staging_tree)
        install_replacements(config, staging_tree)
        shift_by_member = dict(expected_shift_segments(config))
        current_shift = 0
        pinned_lbas = {}
        for member_path in extent_order(source_image):
            if member_path in shift_by_member:
                current_shift = shift_by_member[member_path]
            pinned_lbas[member_path] = (
                member_map(source_image)[member_path].extent_lba
                + current_shift
            )
        write_build_xml(
            base_xml,
            build_xml,
            staging_tree,
            config["layout"]["volume_id"],
            pinned_lbas,
        )

        output_path = resolve_project_path(config["output"]["path"])
        command = run_mkps2iso(
            mkps2iso,
            build_xml,
            output_path,
            lba_log,
        )
        report = validate_output(config, source_image, output_path)
        report["component_binding"] = component_binding
        report["sector_budget"] = sector_budget
        report["builder"] = {
            "name": "mkps2iso",
            "version": config["toolchain"]["version"],
            "repository": config["toolchain"]["repository"],
            "tag": config["toolchain"]["tag"],
            "commit": config["toolchain"]["commit"],
            "license_spdx": config["toolchain"]["license_spdx"],
            "command": [
                str(Path(value).relative_to(PROJECT_ROOT))
                if value.startswith(str(PROJECT_ROOT))
                else value
                for value in command
            ],
        }

        report_path = resolve_project_path(config["output"]["report"])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if args.refresh_output_locks:
            config["output"]["expected_sha256"] = report["output_iso"]["sha256"]
            config["output"]["expected_member_manifest_sha256"] = report["layout"][
                "member_manifest_sha256"
            ]
            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"[refresh] working ISO locks: {config_path}")
        print(
            f"[OK] ISO: {report['output_iso']['size']} bytes, "
            f"SHA-256 {report['output_iso']['sha256']}"
        )
        print(
            "[OK] PCSX2 v2.6.3 media type: "
            f"{report['output_iso']['pcsx2_v263_image_type']}"
        )
        print(f"[OK] report: {report_path}")
        print("[BOUNDARY] builder does not execute PCSX2; runtime evidence is separate")
        return 0
    except (IsoBuildError, Iso9660Error, OSError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
