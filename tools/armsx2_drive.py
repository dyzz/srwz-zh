#!/usr/bin/env python3
"""Interactive ARMSX2 driver: drop-in for lrps2_drive.py, backed by pcsx2-srwzrunner.

Same positional arguments as lrps2_drive.py, with any arm64 Python (no arch -x86_64):
  python3 tools/armsx2_drive.py ISO CARD OUTDIR SOCK [--renderer sw|metal] [--upscale N]

The runner then serves SOCK until 'quit'. Commands (one per line; every reply ends
with 'OK frame=N' or 'ERR ...'):
  run N / press BTN [N] / hold BTN / release BTN
  shot NAME             OUTDIR/NAME.png, reports size and mean luma
  mem ADDR LEN          hex of EE RAM (ADDR hex)
  dump ADDR LEN PATH    raw EE RAM bytes to PATH (use instead of 'mem 0 33554432')
  poke ADDR HEX
  watch ADDR LEN / unwatch   per-frame change report
  state NAME / load NAME     OUTDIR/NAME.p2s (or an absolute path)
  vram PATH             GS local memory (4 MB) to PATH (hardware renderers read back first)
  perf N                run N frames, report wall-clock fps
  trace ADDR [name=N] [REG:LEN | @ADDR:LEN ...] [stack]
                        log every time the EE reaches ADDR: all GPRs, LEN bytes read
                        through REG (e.g. a1:96) or at an absolute address (e.g.
                        @70000060:2 in scratchpad), optional call stack. Runs under
                        the JIT; frames stay byte-identical.
  untrace [ADDR] / traces / tracedump PATH (JSON lines; clears the pending hits)
  storewatch ADDR LEN [dma] / unstorewatch
                        report writes into the range: EE stores with PC/RA/stack (EE
                        interpreter, ~30 fps) and SIF0/fromSPR/fromIPU DMA. 'dma' keeps
                        the JIT and reports DMA only. Hits print after each run and
                        append to OUTDIR/store-hits.jsonl. The interpreter counts
                        cycles a little differently, so frames shot while it runs can
                        differ by a few pixels from a JIT run (still repeatable).
  audio start / audio stop PATH
                        record the SPU2 mix silently: PATH (.wav, 16-bit stereo,
                        48 kHz) plus PATH.keys.jsonl with every voice key-on/off
                        (frame, sample, start/loop address, pitch, ADSR, volume)
  video start PATH / video stop / video status
                        record advanced frames + SPU2 audio to H.264/AAC MP4;
                        requires ffmpeg on PATH. Relative PATH is under OUTDIR,
                        .mp4 appended if absent; spaces allowed. No overwrite.
                        Retains .audio.wav, .json, .keys.jsonl, .ffmpeg.log.
                        Native refresh rate, 4:3 display; no host waiting time.
                        Audio commands and load are blocked while recording;
                        display mode changes abort. Quit finalizes recording.
  voices [all]          SPU2 voices that are playing (phase, envelope, addresses)

For scripted runs, prefer tools/srwz/armsx2_runtime.Armsx2Session. For the text the
game draws (every glyph with its screen position), arm
tools/srwz/armsx2_text_probe.trace_commands(edition) and read the tracedump with
tools/armsx2_text_rows.py.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from srwz.armsx2_runtime import RENDERERS, RUNNER_DIR, Armsx2RuntimeError, prepare_session_data, runner_argv
except ModuleNotFoundError:
    from tools.srwz.armsx2_runtime import RENDERERS, RUNNER_DIR, Armsx2RuntimeError, prepare_session_data, runner_argv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("iso", type=Path)
    parser.add_argument("card", type=Path)
    parser.add_argument("outdir", type=Path)
    parser.add_argument("socket")
    parser.add_argument("--renderer", choices=RENDERERS, default="sw")
    parser.add_argument("--upscale", type=int, default=1)
    args = parser.parse_args()

    runner = RUNNER_DIR / "pcsx2-srwzrunner"
    if not runner.is_file():
        print(f"runner not built: {runner}", file=sys.stderr)
        return 1
    outdir = args.outdir.resolve()
    try:
        bios = prepare_session_data(outdir)
        argv = runner_argv(
            args.iso.resolve(), args.card.resolve(), outdir, args.socket,
            bios=bios, renderer=args.renderer, upscale=args.upscale,
        )
    except Armsx2RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    sys.stdout.flush()
    os.execv(argv[0], argv)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
