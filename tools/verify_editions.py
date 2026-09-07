#!/usr/bin/env python3
"""Check edition batch/ISO/readback bindings, not a replacement gameplay test."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from srwz.edition import BuildContext, EditionError, json_bytes, load_json, load_release_profiles, project_path
from srwz.release_inputs import sha256_file, verify_files


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def verify_batch(root: Path, manifest: Path) -> dict:
    root = root.resolve()
    batch = load_json(manifest)
    if batch.get("status") != "requested_editions_static_validated_runtime_pending":
        raise EditionError("edition batch is incomplete or failed")
    source_path = project_path(root, batch["input_snapshot"], "work/build/shared")
    snapshot = load_json(source_path)
    digest = hashlib.sha256(json_bytes(snapshot["files"])).hexdigest()
    if digest != batch["input_digest"] or digest != snapshot["input_digest"]:
        raise EditionError("edition batch input identity mismatch")
    if source_path != project_path(root, f"work/build/shared/{digest}/inputs.json", "work/build/shared"):
        raise EditionError("snapshot directory does not match its digest")
    verify_files(source_path.parent / "project", snapshot["files"])
    requested = tuple(batch["requested_editions"])
    profiles = load_release_profiles(source_path.parent / "project", batch["release_config"], requested)
    if [r["edition_id"] for r in batch["results"]] != list(requested):
        raise EditionError("edition results are missing, duplicated or reordered")
    for profile, result in zip(profiles, batch["results"]):
        profile.require_supported()
        context = BuildContext(root, profile, digest)
        if (result["input_digest"] != digest or result["edition_contract_sha256"] != profile.contract_sha256
                or result["source_iso_sha256"] != profile.source_iso.sha256
                or result["adapter"] != profile.adapter
                or result["status"] != "edition_iso_static_validated_runtime_pending"):
            raise EditionError("cross-edition or cross-input result binding")
        output = project_path(root, result["output"]["path"], "build/iso")
        if (output != context.output_iso or output.stat().st_size != result["output"]["size"]
                or sha256_file(output) != result["output"]["sha256"]):
            raise EditionError("edition output is missing, stale or misbound")
        proof = project_path(root, result["readback"]["path"], context.project_root.relative_to(root).as_posix())
        if sha256_file(proof) != result["readback"]["sha256"]:
            raise EditionError("edition semantic readback receipt drift")
        readback = load_json(proof)
        expected_status = {"original": "full_story_final_iso_static_content_readback_passed", "best": "best_final_iso_static_content_readback_passed"}[profile.edition_id]
        if (readback["status"] != expected_status
                or readback["iso"]["sha256"] != result["output"]["sha256"]
                or readback["iso"]["size"] != result["output"]["size"]):
            raise EditionError("semantic readback belongs to a different ISO")
        if profile.edition_id == "best":
            frontend = result["shared_frontend"]
            if (frontend["edition"] != "original" or frontend["input_digest"] != digest
                    or readback["input_digest"] != digest or readback["source_iso_sha256"] != profile.source_iso.sha256):
                raise EditionError("BEST shared frontend/source binding mismatch")
            component = readback["component_readback"]
            component_path = project_path(context.project_root, component["path"], "work/build/best-current")
            if sha256_file(component_path) != component["sha256"]:
                raise EditionError("BEST component readback drift")
            component_proof = load_json(component_path)
            if component_proof["input_digest"] != digest or component_proof["status"] != "best_components_semantic_readback_passed":
                raise EditionError("BEST component/input binding mismatch")
    if "best" in requested and "original" in requested:
        results = {r["edition_id"]: r for r in batch["results"]}
        shared = results["best"]["shared_frontend"]
        if (shared["readback_sha256"] != results["original"]["readback"]["sha256"]
                or shared["iso_sha256"] != results["original"]["output"]["sha256"]):
            raise EditionError("dual outputs do not share the same frontend")
    return {"status": "edition_batch_receipt_integrity_passed", "input_digest": digest,
            "verified_editions": list(requested), "both_editions": set(requested) == {"original", "best"},
            "runtime": "not_tested", "scope": "input snapshot and existing semantic-readback receipts bound to actual ISO bytes"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest = args.manifest if args.manifest.is_absolute() else PROJECT_ROOT / args.manifest
        print(json.dumps(verify_batch(PROJECT_ROOT, manifest), ensure_ascii=False, indent=2))
        return 0
    except (EditionError, OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
