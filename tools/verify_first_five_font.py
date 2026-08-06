#!/usr/bin/env python3
"""Verify the first-five font baseline without coupling it to an ISO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.font import GLYPH_SIZE, sha256_bytes
from srwz.font_profile import FontProfileError, load_font_profile
from srwz.font_source import FontSourceError, font_source_metadata, load_font_lock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT_ROOT / "config/fonts/first-five-font.json"
PROPOSAL = PROJECT_ROOT / "work/writeback/first-five-codebook-proposal.json"
REPORT = PROJECT_ROOT / "work/build/first-five/components/font-validation.json"
COMPONENT_ROOT = PROJECT_ROOT / "work/build/first-five/components"
MANIFEST = PROJECT_ROOT / "manifests/first-five-font-validation.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--refresh-manifest", action="store_true")
    return parser.parse_args()


def _read_json(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read JSON: {path}") from error
    if not isinstance(document, dict):
        raise SystemExit(f"JSON root is not an object: {path}")
    return document


def _file_lock(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "size": len(data),
        "sha256": sha256_bytes(data),
    }


def build_manifest() -> dict:
    proposal = _read_json(PROPOSAL)
    report = _read_json(REPORT)
    try:
        profile = load_font_profile(PROJECT_ROOT, CONFIG)
        font_lock = load_font_lock(PROJECT_ROOT / profile["font_lock"])
    except (FontProfileError, FontSourceError) as error:
        raise SystemExit(str(error)) from error
    if proposal.get("status") != "static_proposal_not_runtime_verified":
        raise SystemExit("first-five proposal status is invalid")
    if report.get("status") != "offline_font_validated_runtime_not_tested":
        raise SystemExit("first-five font report status is invalid")
    if proposal.get("font_source") != font_source_metadata(font_lock):
        raise SystemExit("first-five proposal font source drift")
    if proposal.get("font_flavor") != profile["font_flavor"]:
        raise SystemExit("first-five proposal font flavor drift")
    if report.get("font_source") != proposal.get("font_source"):
        raise SystemExit("first-five component font source drift")
    if report.get("font_flavor") != proposal.get("font_flavor"):
        raise SystemExit("first-five component font flavor drift")
    if report.get("assignment_count") != len(proposal.get("assignments", [])):
        raise SystemExit("first-five assignment count drift")
    empty_sha256 = sha256_bytes(bytes(GLYPH_SIZE))
    empty_characters = [
        assignment["character"]
        for assignment in proposal["assignments"]
        if not assignment["character"].isspace()
        and assignment["raster"]["packed_glyph_sha256"] == empty_sha256
    ]
    if empty_characters:
        raise SystemExit(
            "first-five proposal contains empty visible glyphs: "
            + "".join(empty_characters)
        )
    outputs = {}
    for label, relative in (
        ("slps", "SLPS_258.87"),
        ("vt1", "DATA/VT1.BIN"),
    ):
        path = COMPONENT_ROOT / relative
        locked = _file_lock(path)
        if locked["size"] != report["outputs"][label]["size"] or (
            locked["sha256"] != report["outputs"][label]["sha256"]
        ):
            raise SystemExit(f"first-five {label} output drift")
        outputs[label] = locked
    archive = report["archive"]
    if (
        archive["source_size"] != archive["output_size"]
        or not archive["offset_reread_exact"]
    ):
        raise SystemExit("first-five VT1 fixed-size contract failed")
    return {
        "schema_version": 1,
        "status": "offline_first_five_font_validated_runtime_pending",
        "scope": (
            "First-five font proposal and fixed-size SLPS/VT1 component only. "
            "This manifest does not build an ISO or claim runtime rendering."
        ),
        "inputs": {
            "config": _file_lock(CONFIG),
            "font_flavor": profile["font_flavor"],
        },
        "proposal": {
            **_file_lock(PROPOSAL),
            "proposal_id": proposal["proposal_id"],
            "assignment_count": len(proposal["assignments"]),
        },
        "font_component": {
            "report": _file_lock(REPORT),
            "font_source": report["font_source"],
            "font_flavor": report["font_flavor"],
            "assignment_count": report["assignment_count"],
            "changed_glyph_count": report["changed_glyph_count"],
            "font": report["font"],
            "archive": report["archive"],
            "outputs": outputs,
        },
        "acceptance": {
            "font_source_and_flavor_exact": True,
            "visible_glyph_rasters_nonempty": True,
            "codec_round_trip_exact": True,
            "vt1_size_unchanged": True,
            "offset_reread_exact": True,
            "runtime": "pending",
        },
    }


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    report = build_manifest()
    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        status = "refreshed"
    else:
        if _read_json(manifest_path) != report:
            raise SystemExit("first-five font manifest drift")
        status = "verified"
    print(f"first-five font manifest {status}: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
