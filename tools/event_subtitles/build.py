"""Build an isolated subtitled candidate from an already assembled Original/Best image.

The production builds apply the same transform inside ``tools/build_editions.py``
after each edition's native assembly; this wrapper exists for isolated runtime
experiments and never writes a production path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.iso9660 import member_map, scan_iso9660
from event_subtitles.apply import ARCHIVE, apply_event_subtitles, load_profile, patch, verify_subtitle_members  # noqa: F401
from special_disc.event_gallery.udf import relocate  # noqa: F401  (re-exported for tests)
from special_disc.iso_relocation import (append_members, patch_catalog_tolerant as patch_catalog,  # noqa: F401
                                         verify_relocation, verify_untouched)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(edition, source, output, out):
    profile = load_profile(edition)
    source, output, out = source.resolve(), output.resolve(), out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not output.is_relative_to(ROOT / "work/iso") or output == source:
        raise ValueError("Use an isolated work/iso candidate")
    before = member_map(scan_iso9660(source))

    def read(name):
        member = before[name]
        with source.open("rb") as f:
            f.seek(member.extent_lba * 2048)
            return f.read(member.size)

    result = apply_event_subtitles(edition, read(profile["elf_member"]), read(ARCHIVE), workdir=out, profile=profile)
    (out / "subtitled.elf").write_bytes(result["members"][profile["elf_member"]])
    working = output.with_suffix(".building.iso")
    working.unlink(missing_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["/bin/cp", "-c", str(source), str(working)], check=True)
    relocation = append_members(working, before, result["members"],
                                allowed_udf={profile["elf_member"], ARCHIVE}, catalog_policy="inherit")
    readback = verify_relocation(working, before, result["members"], relocation)
    untouched = verify_untouched(source, working, relocation["touched_spans"])
    members = verify_subtitle_members(result["members"][profile["elf_member"]], result["members"][ARCHIVE],
                                      profile, result["receipt"])
    working.replace(output)
    receipt = {"edition": edition, "source": str(source), "candidate": str(output),
               "elf_sha256": sha(result["members"][profile["elf_member"]]),
               "subtitles": result["receipt"], "relocation": relocation, "relocation_readback": readback,
               "untouched_base_bytes": untouched, "member_readback": members,
               "runtime_validation": "pending separate native map validation"}
    (out / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"edition": edition, "candidate": str(output), "elf_sha256": receipt["elf_sha256"]},
                     ensure_ascii=False))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=["original", "best"], required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workdir", type=Path)
    args = parser.parse_args()
    edition = args.edition
    config = load_profile(edition)
    build(edition, args.source or ROOT / config["input"],
          args.output or ROOT / f"work/iso/event-subtitles-{edition}-candidate.iso",
          args.workdir or ROOT / f"work/build/event-subtitles-{edition}-candidate")
