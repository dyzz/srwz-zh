"""Build an isolated event-gallery candidate ISO from an already assembled SP image.

The production SP build applies the same transform inside
``special_disc/writeback/build_full_text.py``; this wrapper exists for isolated
runtime experiments on a finished image. It never writes the production path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.iso9660 import member_map, scan_iso9660
from special_disc.event_gallery.apply import MEMBERS, apply_event_gallery, load_config, verify_gallery_members
from special_disc.iso_relocation import append_members, verify_relocation


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(source, output, outdir, config_path):
    source, output, outdir = source.resolve(), output.resolve(), outdir.resolve()
    if source == output or output == (ROOT / "build/iso/special-disc/sp-current.iso").resolve():
        raise ValueError("The event gallery must use a separate candidate ISO")
    if (ROOT / "rom").resolve() in output.parents:
        raise ValueError("Original disc images are immutable build inputs")
    working = output.with_name(output.name + ".building")
    outdir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    before = member_map(scan_iso9660(source))

    def read_member(path):
        member = before[path]
        with source.open("rb") as f:
            f.seek(member.extent_lba * 2048)
            return f.read(member.size)

    inputs = {name: read_member(name) for name in MEMBERS}
    result = apply_event_gallery(inputs[MEMBERS[0]], inputs[MEMBERS[1]], inputs[MEMBERS[2]],
                                 config=load_config(config_path), workdir=outdir)
    (outdir / "gallery.elf").write_bytes(result["members"][MEMBERS[0]])
    subprocess.run(["/bin/cp", "-c", str(source), str(working)], check=True)
    relocation = append_members(working, before, result["members"])
    verification = verify_relocation(working, before, result["members"], relocation)
    readback = verify_gallery_members(result["members"][MEMBERS[0]], result["members"][MEMBERS[2]], result["receipt"])
    working.replace(output)
    receipt = {"source": str(source), "candidate": str(output), "source_sha256": None,
               "source_elf_sha256": sha(inputs[MEMBERS[0]]), "elf_sha256": sha(result["members"][MEMBERS[0]]),
               "relocation": relocation, "relocation_readback": verification, "gallery_readback": readback,
               "gallery": result["receipt"],
               "runtime_acceptance": "Separate cold-start emulator evidence required"}
    (outdir / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"candidate": str(output), "receipt": str(outdir / "receipt.json"),
                      "elf_sha256": receipt["elf_sha256"]}, ensure_ascii=False))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "build/iso/special-disc/sp-current.iso")
    parser.add_argument("--output", type=Path, default=ROOT / "work/iso/sp-event-gallery-zh.iso")
    parser.add_argument("--workdir", type=Path, default=ROOT / "work/build/sp-event-gallery")
    parser.add_argument("--config", type=Path, default=ROOT / "config/products/special-disc/event-gallery.json")
    args = parser.parse_args()
    build(args.source, args.output, args.workdir, args.config)
