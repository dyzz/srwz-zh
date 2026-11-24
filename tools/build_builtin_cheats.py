"""Build a separate Original multilingual disc with a session-only native cheat menu."""

import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

from special_disc.iso_relocation import append_members, verify_relocation
from zh_hant.assemble_dual import Disc, Elf, STOCK_CODES
from zh_hant.editions import ORIGINAL, edition_inc

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tools/builtin_cheats"
BASE = 0x78C700  # end of Latin segment; event subtitles start at 0x790000
SITES = {
    0x35886C: ("report_text", 0x0C04F168),
    0x141CA4: ("cheat_home", 0x0C061224),
    0x141B54: ("cheat_map", 0x0C04FDF8),
    0x14314C: ("cheat_tick", 0x0C0F89B0),
    0x253980: ("money_reward", 0x8C830004, 0x00711821),
    0x253B10: ("pp_reward", 0x30E7FFFF, 0x30A9FFFF),
    0x289704: ("cost_apply", 0x90E20002, 0x0C09DDF8),
    0x35DF84: ("cost_list", 0x90C30066, 0xA6A30006),
    0x37F324: ("cost_check", 0x90420066, 0x0062082A),
}


def symbols(text):
    return {
        parts[2]: int(parts[0], 16)
        for line in text.splitlines()
        if len(parts := line.split()) == 3
    }


def messages():
    out = []
    localized = {
        "sc": (
            "encoding",
            "金手指",
            "机师",
            "资金",
            "获取",
            "保持最大",
            "左右切换",
            "确认",
            "取消",
        ),
        "tc": (
            "zh-hant/encoding",
            "金手指",
            "機師",
            "資金",
            "獲取",
            "保持最大",
            "左右切換",
            "確認",
            "取消",
        ),
    }
    for key, (
        folder,
        title,
        pilot,
        cash,
        gain,
        maximum,
        switch,
        ok,
        cancel,
    ) in localized.items():
        ledger = json.loads(
            (ROOT / "config" / folder / "zh-release-font-assignments.json").read_text()
        )
        codes = dict(STOCK_CODES)
        for group in (
            "primary_assignments",
            "surface_alias_assignments",
            "source_compatibility_assignments",
        ):
            for row in ledger[group]:
                codes.setdefault(row["character"], row["code"])
        strings = [
            title,
            cash,
            pilot + "ＰＰ",
            "精神指令",
            "普通",
            gain + "×４",
            maximum,
            "免消耗",
            "　　" + switch + "　　　" + ok + "　　　" + cancel,
            "ＳＥＬＥＣＴ　" + title,
        ]
        for i, text in enumerate(strings):
            raw = b"".join(
                char.encode("ascii")
                if char.isascii()
                else bytes.fromhex(codes[char])
                if char in codes
                else char.encode("cp932")
                for char in text
            )
            if i == 8:
                template = b"\x82\x50\n\x82\x51\n\x82\x52\n" + raw + b"\0"
                out.append(f"template_{key}: .byte " + ",".join(map(str, template)))
            out.append(f"str_{key}_{i}: .byte " + ",".join(map(str, raw + b"\0")))
        out += [
            ".align 2",
            f"words_{key}: .word "
            + ",".join(f"str_{key}_{i}" for i in range(len(strings))),
        ]
    return "\n".join(out) + "\n"


def grow_latin_segment(elf, payload):
    ph = struct.unpack_from("<I", elf.b, 28)[0]
    count = struct.unpack_from("<H", elf.b, 44)[0]
    latin, subtitle = ph + (count - 2) * 32, ph + (count - 1) * 32
    _, off, addr, _, size, memsize, _, _ = struct.unpack_from("<8I", elf.b, latin)
    _, next_off, next_addr, *_ = struct.unpack_from("<8I", elf.b, subtitle)
    if (
        addr != 0x789E00
        or addr + size != BASE
        or size != memsize
        or next_off != off + size
        or next_addr != 0x790000
    ):
        raise ValueError("unsupported executable segment layout")
    payload += bytes(-len(payload) % 128)
    if BASE + len(payload) > next_addr:
        raise ValueError("native menu overlaps subtitles")
    elf.b[next_off:next_off] = payload
    struct.pack_into("<II", elf.b, latin + 16, size + len(payload), size + len(payload))
    struct.pack_into("<I", elf.b, subtitle + 4, next_off + len(payload))


def build(source, output, work, lang_work):
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    disc = Disc(source)
    elf = Elf(disc.read(ORIGINAL.exe))
    lang = symbols((lang_work / "symbols.txt").read_text())
    original_hook = (lang_work / "hook.bin").read_bytes()
    if elf.get(ORIGINAL.cave[0], len(original_hook)) != original_hook:
        raise ValueError("language hook symbols do not match the source disc")
    sites = SITES
    # The Traditional boot records must leave the new hooks intact.
    receipt = json.loads(source.with_suffix(".receipt.json").read_text())
    with source.open("rb") as f:
        for variant in (receipt, receipt["hk"]):
            patch = variant["patch"]
            f.seek(patch["lba"] * 2048)
            raw = f.read(patch["bytes"])
            if raw[:4] != b"ZHTP":
                raise ValueError("invalid language patch")
            rows, records = struct.unpack_from("<II", raw, 8)
            pos = 32 + 12 * rows
            for _ in range(records):
                address, size = struct.unpack_from("<II", raw, pos)
                if any(
                    address < a + 4 * (len(spec) - 1) and a < address + size
                    for a, spec in sites.items()
                ):
                    raise ValueError(
                        f"language record overlaps game hook at {address:#x}"
                    )
                pos += 8 + size + (-size % 4)
    work.mkdir(parents=True, exist_ok=True)
    imports = {
        "LANG_TITLE": "title_hook",
        "LANG_DIALOG": "dlg_state",
        "LANG_ID": "lang",
        "LANG_ICON": "draw_icon",
        "LANG_SET": "set_msg",
        "LANG_RESTORE": "restore_msg",
    }
    (work / "language.inc").write_text(
        "".join(f".equ {name},{lang[sym]:#x}\n" for name, sym in imports.items())
    )
    (work / "edition.inc").write_text(edition_inc(ORIGINAL))
    (work / "cheat_text.inc").write_text(messages())

    def tool(name, *args):
        return subprocess.check_output(
            ["mipsel-linux-gnu-" + name, *map(str, args)], text=True
        )

    tool(
        "as",
        "-EL",
        "-mips3",
        "-mabi=o64",
        "--fatal-warnings",
        "-I",
        work,
        "-I",
        SRC,
        "-o",
        work / "menu.o",
        SRC / "menu.S",
    )
    tool(
        "ld",
        "-EL",
        f"-Ttext={BASE:#x}",
        "-e",
        "cheat_home",
        "-o",
        work / "menu.elf",
        work / "menu.o",
    )
    tool("objcopy", "-O", "binary", "-j", ".text", work / "menu.elf", work / "menu.bin")
    syms = symbols(tool("nm", work / "menu.elf"))
    for addr, (label, *expected) in sites.items():
        if [elf.word(addr + i * 4) for i in range(len(expected))] != expected:
            raise ValueError(f"incompatible instruction at {addr:#x}")
        call = len(expected) == 1
        elf.putw(addr, (0x0C000000 if call else 0x08000000) | (syms[label] >> 2))
        if not call:
            elf.putw(addr + 4, 0)
    payload = (work / "menu.bin").read_bytes()
    grow_latin_segment(elf, payload)
    if Elf(elf.b).get(BASE, len(payload)) != payload:
        raise ValueError("ELF payload readback failed")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staged = Path(temp) / "disc.iso"
        subprocess.run(["cp", "-c", source, staged], check=True)
        members = {ORIGINAL.exe: bytes(elf.b)}
        relocation = append_members(
            staged,
            disc.m,
            members,
            allowed_udf={ORIGINAL.exe, "EFF/VEFF2DX.BIN"},
            catalog_policy="inherit",
        )
        verify_relocation(staged, disc.m, members, relocation)
        os.link(staged, output)
    (work / "symbols.json").write_text(json.dumps(syms, indent=2))
    (work / "relocation.json").write_text(json.dumps(relocation, indent=2))
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "output", "work"):
        parser.add_argument(name, type=Path)
    parser.add_argument(
        "--language-build",
        type=Path,
        default=ROOT / "build/multilang/assemble-original",
    )
    args = parser.parse_args()
    build(args.source, args.output, args.work, args.language_build)
