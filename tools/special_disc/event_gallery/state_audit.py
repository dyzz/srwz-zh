#!/usr/bin/env python3
"""Record which RAM values a gallery row changes, and which survive leaving it.

Dumps EE RAM on the list, during the scene and back on the list, then groups the
differences into ranges and marks those covered by gallery_state_regions.
Run on the headless ARMSX2 runner:

    python3 tools/special_disc/event_gallery/state_audit.py ISO CARD ROW OUT.json \\
        [--mode circle|triangle] [--exit-frame N]
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.srwz.armsx2_runtime import Armsx2Session  # noqa: E402

CONTROL = 0x763A50  # gallery list controller pointer
RECORD = 0x61DEB8  # current script record, 0 back on the list
SPAN = (0x400000, 0x640000)  # game state; above it is heap, below it code
GAP = 32
NAV = ["run 1800","press start 3","run 200","press circle 3","run 200","press cross 3","run 180","press down 3","press circle 3","run 240","press up 3","run 30","press circle 3","run 140"]  # title to the gallery list
# Rewritten every frame or per draw: GS packets, clocks, pad and sound queues.
NOISE = ((0x4EE900, 0x4F4000), (0x51A000, 0x5A0000))


def regions(source: str) -> list[tuple[int, int]]:
    block = source.split("gallery_state_regions:")[1].split(".word 0,0")[0]
    return [(int(a, 16), int(b, 0)) for a, b in re.findall(r"\.word (0x[0-9a-f]+),(0x[0-9a-f]+|\d+)", block)]


def ranges(before: bytes, after: bytes) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start = last = None
    for address in range(*SPAN):
        if before[address] == after[address] or any(a <= address < b for a, b in NOISE):
            continue
        if start is None:
            start = last = address
        elif address - last > GAP:
            out.append((start, last + 1))
            start = last = address
        else:
            last = address
    if start is not None:
        out.append((start, last + 1))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("iso", type=Path)
    parser.add_argument("card", type=Path)
    parser.add_argument("row", type=int)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", default="circle", choices=("circle", "triangle"))
    parser.add_argument("--exit-frame", type=int, default=280)
    args = parser.parse_args()
    restored = regions((ROOT / "tools/special_disc/event_gallery/runtime.S").read_text())
    with tempfile.TemporaryDirectory() as tmp, Armsx2Session(args.iso, args.card, tmp) as vm:
        for command in NAV:
            vm.cmd(command)

        def dump(name: str) -> bytes:
            path = Path(tmp) / f"{name}.bin"
            vm.cmd(f"dump 0 33554432 {path}")
            return path.read_bytes()

        word = lambda ram, a: struct.unpack_from("<I", ram, a)[0]
        ram = dump("list")
        control = word(ram, CONTROL)
        page, line = divmod(args.row, 11)
        for _ in range(page):
            vm.cmd("press right 3")
            vm.cmd("run 40")
        for _ in range(line):
            vm.cmd("press down 3")
            vm.cmd("run 8")
        vm.cmd("run 10")
        base = dump("base")
        vm.cmd(f"press {args.mode} 1")
        vm.cmd(f"run {args.exit_frame}")
        during = dump("during")
        vm.cmd("press start 3")
        vm.cmd("run 240")
        after = dump("after")
    assert control and word(after, RECORD) == 0, "scene did not return to the list"
    covered = lambda a, b: any(s <= a and b <= s + n for s, n in restored)
    show = lambda ram, a, b: ram[a:min(b, a + 16)].hex()
    report = {
        "row": args.row, "mode": args.mode, "exit_frame": args.exit_frame, "span": [hex(v) for v in SPAN],
        "changed_during_scene": [
            {"start": hex(a), "bytes": b - a, "list": show(base, a, b), "scene": show(during, a, b),
             "in_state_regions": covered(a, b)} for a, b in ranges(base, during)],
        "left_changed_after_exit": [
            {"start": hex(a), "bytes": b - a, "list": show(base, a, b), "after": show(after, a, b),
             "in_state_regions": covered(a, b)} for a, b in ranges(base, after)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(len(report["changed_during_scene"]), "ranges changed;", len(report["left_changed_after_exit"]), "left after exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
