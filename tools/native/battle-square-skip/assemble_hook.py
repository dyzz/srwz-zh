#!/usr/bin/env python3
"""Assemble the square-skip hook for each edition and print/refresh its contract bytes.

Development-only: the production build consumes the assembled hex stored in
config/full-story-components.json and never runs an assembler.  Requires
mipsel-linux-gnu-as and mipsel-linux-gnu-objcopy (Homebrew: mipsel-linux-gnu-binutils).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().with_name("skip_hook.s")
CONFIG = PROJECT_ROOT / "config/full-story-components.json"
SYMBOLS = (
    "CAVE", "DATA", "PAD_HELD", "PAD_TRIG", "CTX", "WORLD", "CURSOR", "ACTION_INDEX",
    "FN_WORLD_STEP", "FN_SPRITE_DRAW", "FN_SE_RESUME", "FN_FLIP",
)


def assemble(symbols: dict[str, str]) -> bytes:
    gas = shutil.which("mipsel-linux-gnu-as")
    objcopy = shutil.which("mipsel-linux-gnu-objcopy")
    if gas is None or objcopy is None:
        raise SystemExit("mipsel-linux-gnu-as / objcopy not found")
    with tempfile.TemporaryDirectory() as tmp:
        obj = Path(tmp) / "hook.o"
        binary = Path(tmp) / "hook.bin"
        command = [gas, "-EL", "-mips3"]
        for name in SYMBOLS:
            command += ["--defsym", f"{name}={int(symbols[name], 0)}"]
        command += ["-o", str(obj), str(SOURCE)]
        subprocess.run(command, check=True)
        subprocess.run([objcopy, "-O", "binary", "-j", ".text", str(obj), str(binary)], check=True)
        return binary.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="store assembled bytes into the config")
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    section = config["battle_square_skip"]
    changed = False
    for edition, contract in section["editions"].items():
        blob = assemble(contract["symbols"])
        digest = hashlib.sha256(blob).hexdigest()
        current = contract.get("hook_sha256")
        print(f"{edition}: {len(blob)} bytes sha256 {digest} ({'matches' if current == digest else 'DIFFERS from'} config)")
        if args.write and current != digest:
            contract["hook_hex"] = blob.hex()
            contract["hook_sha256"] = digest
            changed = True
    if changed:
        CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("config updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
