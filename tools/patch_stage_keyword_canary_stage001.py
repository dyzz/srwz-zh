#!/usr/bin/env python3
"""Rebuild only female Stage 1 inside the isolated keyword-link canary.

The stage is always rebuilt from the locked retail STAGE/HB/SLPS resources
and the current committed-style Chinese corpus.  The existing canary is only
the destination image; it is never used as a source for the decoded stage.
No other STAGE slot or ISO member is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
for import_root in (PROJECT_ROOT, TOOLS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tools.build_story_component import (  # noqa: E402
    _entry_translations,
    _json,
    _load_overrides,
    _locked_file,
    _project_path,
    _read_iso_member,
    _speaker_translations,
)
from srwz.codec import decode_production as decode, reencode_changed_suffix  # noqa: E402
from srwz.font import sha256_bytes  # noqa: E402
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660  # noqa: E402
from srwz.iso_layout import (  # noqa: E402
    ExecutableOffsetSpec,
    read_executable_archive_offsets,
)
from srwz.stage import read_stage_function_addresses  # noqa: E402
from srwz.text import load_text_table, original_fullwidth_ascii_overrides  # noqa: E402
from srwz.writers import repack_stage_texts_in_place  # noqa: E402


STAGE_INDEX = 1
DEFAULT_ISO = (
    PROJECT_ROOT
    / "build/iso/keyword-link-canary/srwz-zh-keyword-link-stage001.iso"
)
DEFAULT_CONFIG = PROJECT_ROOT / "config/story-component.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, default=DEFAULT_ISO)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    iso_path = args.iso.resolve()
    if not iso_path.is_file():
        raise SystemExit(f"keyword canary ISO does not exist: {iso_path}")
    config_path = args.config.resolve()
    config = _json(config_path)
    if config.get("profile_id") != "srwz-zh-story-component-v1":
        raise SystemExit("unexpected story-component profile")

    source = config["source"]
    _slps_path, source_slps = _locked_file(source["slps"], label="source SLPS")
    _stage_path, source_stage = _locked_file(
        source["stage"],
        label="source STAGE",
    )
    table_path, _table_payload = _locked_file(
        source["text_table"],
        label="source text table",
    )
    codebook_path, _codebook_payload = _locked_file(
        source["base_codebook"],
        label="base codebook",
    )
    source_hb = _read_iso_member(_project_path(source["iso"]), source["hb"])
    offset_spec = ExecutableOffsetSpec(
        name="HEDBDY/HB.BIN STAGE offsets",
        member=source["hb"]["member"],
        table_start=30320,
        table_end=31144,
    )
    offsets = read_executable_archive_offsets(
        source_hb,
        offset_spec,
        len(source_stage),
    )
    stage_start, stage_end = offsets[STAGE_INDEX : STAGE_INDEX + 2]
    source_slot = source_stage[stage_start:stage_end]
    decoded = decode(source_slot)
    if any(source_slot[decoded.consumed :]):
        raise SystemExit("retail Stage 1 has nonzero compressed padding")

    translations = config["translations"]
    dialogue_path = _project_path(
        translations["dialogue_root"] + f"/stage-{STAGE_INDEX:03d}.json"
    )
    dialogue = _entry_translations(dialogue_path, {STAGE_INDEX})
    conditions = _entry_translations(
        _project_path(translations["conditions"]),
        {STAGE_INDEX},
    )
    speakers = _speaker_translations(
        _project_path(translations["speakers"]),
        {STAGE_INDEX},
    )[STAGE_INDEX]

    font = config["font"]
    proposal_path = _project_path(font["proposal"])
    allocation_path = _project_path(font["allocation_registry"])
    overrides, _proposal = _load_overrides(
        proposal_path,
        allocation_path,
        codebook_path,
    )
    table = load_text_table(table_path)
    overrides.update(original_fullwidth_ascii_overrides(table))
    write = repack_stage_texts_in_place(
        decoded.output,
        table,
        stage_index=STAGE_INDEX,
        function_address=read_stage_function_addresses(source_slps)[STAGE_INDEX],
        replacements={**dialogue, **conditions},
        speaker_replacements=speakers,
        overrides=overrides,
    )
    codec = config["codec"]
    encoded = reencode_changed_suffix(
        source_slot,
        write.data,
        strategy="rust-fit",
        min_match_length=int(codec["min_match_length"]),
        max_match_chain=int(codec["max_match_chain"]),
        lazy_matching=False,
        max_output_size=len(source_slot),
        original_result=decoded,
    )
    output_slot = encoded + bytes(len(source_slot) - len(encoded))
    reread = decode(output_slot)
    if reread.output != write.data or any(output_slot[reread.consumed :]):
        raise SystemExit("rebuilt Stage 1 compressed reread failed")

    members = member_map(scan_iso9660(iso_path))
    stage_member = members.get("DATA/STAGE.BIN")
    if stage_member is None:
        raise SystemExit("keyword canary ISO has no DATA/STAGE.BIN")
    if stage_member.size != len(source_stage):
        raise SystemExit("keyword canary STAGE member size drift")
    absolute_start = stage_member.extent_lba * SECTOR_SIZE + stage_start
    with iso_path.open("rb") as source_file:
        source_file.seek(absolute_start)
        current_slot = source_file.read(len(output_slot))
    if len(current_slot) != len(output_slot):
        raise SystemExit("short keyword canary Stage 1 read")

    before_sha256 = _sha256_file(iso_path)
    changed = current_slot != output_slot
    if changed:
        with iso_path.open("r+b") as target:
            target.seek(absolute_start)
            if target.read(len(current_slot)) != current_slot:
                raise SystemExit("keyword canary Stage 1 changed during preparation")
            target.seek(absolute_start)
            target.write(output_slot)
            target.flush()
            os.fsync(target.fileno())
    after_sha256 = _sha256_file(iso_path)
    print(
        json.dumps(
            {
                "schema_version": 1,
                "iso": str(iso_path.relative_to(PROJECT_ROOT)),
                "stage_index": STAGE_INDEX,
                "changed": changed,
                "before_sha256": before_sha256,
                "after_sha256": after_sha256,
                "member": "DATA/STAGE.BIN",
                "slot_start": stage_start,
                "slot_end": stage_end,
                "slot_size": len(source_slot),
                "source_encoded_size": decoded.consumed,
                "output_encoded_size": len(encoded),
                "headroom": len(source_slot) - len(encoded),
                "decoded_sha256": sha256_bytes(write.data),
                "dialogue_count": len(dialogue),
                "condition_count": len(conditions),
                "speaker_count": len(speakers),
                "codec": "rust-fit",
                "round_trip_exact": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
