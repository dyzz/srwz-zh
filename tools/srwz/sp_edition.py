"""Locked native SP baseline dependencies and final full-text readback checks."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .edition import EditionError, FileIdentity, load_json, project_path
from .iso9660 import member_map, scan_iso9660
from .release_inputs import sha256_file


def locked_sp_inputs(root: Path) -> tuple[str, ...]:
    config = load_json(root / "config/editions/sp/inputs.json")
    if (config.get("schema_version") != 1 or
            config.get("policy") != "locked_sp_baseline_and_font_inputs_with_current_corpus_rebuild"):
        raise EditionError("SP baseline input policy drift")
    paths = []
    for row in config["files"]:
        lock = FileIdentity.parse(row)
        if not lock.path.startswith(("work/", "config/editorial/special-disc/")) or lock.path in paths:
            raise EditionError("invalid or duplicate SP dependency path")
        path = project_path(root, lock.path)
        if ((root / lock.path).is_symlink() or not path.is_file() or
                path.stat().st_size != lock.size or sha256_file(path) != lock.sha256):
            raise EditionError(f"SP locked dependency missing or changed: {lock.path}")
        paths.append(lock.path)
    if not paths:
        raise EditionError("SP baseline inputs are empty")
    return tuple(paths)


def validate_sp_readback(root: Path, proof: dict) -> None:
    if proof.get("status") != "all_current_draft_text_written_static_verified_runtime_pending":
        raise EditionError("SP full-text build did not pass static readback")
    iso = project_path(root, proof["iso"]["path"], "build/iso/special-disc")
    if iso.stat().st_size != proof["iso"]["size"] or sha256_file(iso) != proof["iso"]["sha256"]:
        raise EditionError("SP readback ISO identity mismatch")
    if proof["coverage"]["pending_targets"] or proof["coverage"]["unassigned_display_characters"]:
        raise EditionError("SP corpus or font coverage incomplete")
    independent = proof["independent_readback"]
    independent_path = project_path(root, independent["path"], "work/build/special-disc/full-text")
    if sha256_file(independent_path) != independent["sha256"]:
        raise EditionError("SP independent readback receipt drift")
    semantic = load_json(independent_path)
    if (semantic["status"] != "all_bound_text_reread_from_final_iso" or semantic["iso"] != proof["iso"]
            or not semantic["component_hashes_verified"]):
        raise EditionError("SP independent readback ISO binding mismatch")
    for path, digest in proof["components"].items():
        if sha256_file(project_path(root, path, "work/build/special-disc/full-text")) != digest:
            raise EditionError("SP component receipt drift")
    members = member_map(scan_iso9660(iso))
    with iso.open("rb") as stream:
        for name, digest in proof["files"].items():
            member = members[name]
            stream.seek(member.extent_lba * 2048)
            if hashlib.sha256(stream.read(member.size)).hexdigest() != digest:
                raise EditionError(f"SP final member readback drift: {name}")
