#!/usr/bin/env python3
"""Explicitly freeze existing, reviewed ISO title pixels. Never rasterizes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from srwz.archive import sha256_file
from srwz.codec import decode_production
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.stage_title_graphics import unpack_linear_4bpp
from srwz.stage_title_snapshot import STATUS, freeze_indexes, load_frozen_titles
from srwz.tim2 import scan_tim2


ROOT = Path(__file__).resolve().parents[1]


def read_vt1(iso: Path) -> bytes:
    member = member_map(scan_iso9660(iso))["DATA/VT1.BIN"]
    with iso.open("rb") as source:
        source.seek(member.extent_lba * SECTOR_SIZE)
        data = source.read(member.size)
    if len(data) != member.size:
        raise ValueError("short VT1 read from reviewed ISO")
    return data


def file_lock(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)), "size": path.stat().st_size,
            "sha256": sha256_file(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refreeze", action="store_true", required=True,
                        help="explicitly replace the snapshot and update its configuration lock")
    parser.add_argument("--iso", type=Path, required=True)
    parser.add_argument("--iso-config", type=Path, default=ROOT / "config/iso/zh-release-current-build.json")
    parser.add_argument("--component-manifest", type=Path, default=ROOT / "manifests/full-story-library-components-validation.json")
    parser.add_argument("--config", type=Path, default=ROOT / "config/full-story-components.json")
    parser.add_argument("--output", type=Path, default=ROOT / "config/assets/stage-title-graphics-indexed-snapshot.json")
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text())
    graphics = config["full_stage_titles"]["graphics"]
    report = json.loads(args.component_manifest.read_text())
    graphic_report = report["stage_titles"]["graphics"]
    iso_config = json.loads(args.iso_config.read_text())
    iso_hash = sha256_file(args.iso)
    if iso_hash != iso_config["output"]["expected_sha256"]:
        raise ValueError("reviewed ISO identity does not match its locked build configuration")
    vt1 = read_vt1(args.iso)
    vt1_hash = hashlib.sha256(vt1).hexdigest()
    if vt1_hash != report["outputs"]["DATA/VT1.BIN"]["sha256"]:
        raise ValueError("reviewed ISO VT1 differs from the component manifest")
    titles = []
    for title in graphic_report["titles"]:
        stored = vt1[title["stored_start"]:title["stored_end"]]
        decoded = decode_production(stored)
        records = scan_tim2(decoded.output)
        if len(records) != 1 or len(records[0].pictures) != 1 or any(stored[decoded.consumed:]):
            raise ValueError("reviewed stage-title stream layout drift")
        picture = records[0].pictures[0]
        start = picture.offset + picture.header_size
        packed = decoded.output[start:start + picture.image_size]
        if hashlib.sha256(unpack_linear_4bpp(packed)).hexdigest() != title["output_indexes_sha256"]:
            raise ValueError(f"reviewed stage-title pixel drift: {title['entry_id']}")
        titles.append({**title, "packed_indexes": freeze_indexes(packed),
                       "output_stored_sha256": hashlib.sha256(stored).hexdigest()})
    snapshot = {
        "schema_version": 1,
        "status": STATUS,
        "update_policy": "explicit_refreeze_from_reviewed_iso_only",
        "raster_policy": graphics["raster"],
        "provenance": {"iso_sha256": iso_hash, "iso_size": args.iso.stat().st_size,
                       "vt1_sha256": vt1_hash,
                       "component_manifest": file_lock(args.component_manifest.resolve())},
        "output_group_sha256": hashlib.sha256(vt1[graphic_report["group_start"]:graphic_report["group_end"]]).hexdigest(),
        "titles": titles,
    }
    corpus = json.loads((ROOT / config["full_stage_titles"]["stage_names"]["path"]).read_text())
    load_frozen_titles(snapshot, corpus["entries"][:107], graphics["raster"])
    output = args.output.resolve()
    # Resolve the repository-relative reference before writing anything.
    output.relative_to(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    graphics["render_policy"] = {
        "production_source": "locked_indexed_snapshot",
        "normal_build_rasterization": False,
        "snapshot_update": "explicit_refreeze_from_reviewed_iso_only",
    }
    graphics["frozen_snapshot"] = file_lock(output)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    print(f"Frozen {len(titles)} existing title index planes; rasterization=disabled")
    print(f"snapshot: {output.relative_to(ROOT)}")
    print(f"reviewed ISO: {iso_hash}")


if __name__ == "__main__":
    main()
