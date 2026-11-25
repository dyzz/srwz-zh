"""Generate a boot-time widescreen PNACH for a retail or multilingual SRW Z ISO."""

import argparse
import functools
import operator
import struct
import subprocess
import tempfile
from pathlib import Path

from build import EDITIONS, branch, dual, graphics_layout, reserve, symbols

HD_TEXTURE_BYTES = 2 * 236800
HD_RESERVATION = (4096 + HD_TEXTURE_BYTES + 4095) & ~4095

SERIAL = {"original": "SLPS-25887", "best": "SLPS-73270", "sp": "SLPS-25920"}
VERIFIED_CRCS = {
    "original": (0x321C5C3B, 0x8A8885C2, 0x78F618C4),
    "best": (0x10A7E29A, 0x18DDFE30),
    "sp": (0x9D06B913, 0x78625DBB),
}


def generate(edition, iso, output, *, bitmap=False, hd=False):
    data = dual.Disc(iso).read(EDITIONS[edition].exe)
    crc = functools.reduce(
        operator.xor,
        (v for (v,) in struct.iter_unpack("<I", data[: len(data) // 4 * 4])),
        0,
    )
    # Region-specific overlays in other releases can replace the same RAM after boot.
    if crc not in VERIFIED_CRCS[edition]:
        raise ValueError(f"unsupported {edition} ELF CRC {crc:08X}")
    elf = dual.Elf(data)
    bitmap = bitmap or hd
    base, writes = reserve(elf, edition, HD_RESERVATION if hd else 40960 if bitmap else 4096)
    defs, hooks, expected = graphics_layout(edition)
    display = defs["DISPLAY_RETURN"] - 8
    if any(elf.word(addr) != word for addr, word in expected.items()):
        raise ValueError("source does not match the original graphics hooks")
    src = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "wide.inc").write_text(
            "".join(f".equ {k},{v:#x}\n" for k, v in defs.items())
        )

        def run(tool, *args):
            return subprocess.check_output(
                ["mipsel-linux-gnu-" + tool, *map(str, args)], cwd=work
            )

        run(
            "as",
            "-EL",
            "-mips3",
            "-mabi=o64",
            "--fatal-warnings",
            "--defsym",
            "PNACH=1",
            *(["--defsym", "BITMAP_BEZEL=1"] if bitmap else []),
            *(["--defsym", "HD_TEXTURE=1"] if hd else []),
            "-I",
            src,
            "-o",
            "wide.o",
            src / "viewport.S",
        )
        run(
            "ld",
            "-EL",
            f"-Ttext={base:#x}",
            "-e",
            hex(base),
            "-o",
            "wide.elf",
            "wide.o",
        )
        run("objcopy", "-O", "binary", "-j", ".text", "wide.elf", "wide.bin")
        payload = (work / "wide.bin").read_bytes()
        sy = symbols(run("nm", "wide.elf").decode())
    if bitmap and sy["bitmap_pixels"] != base + 4096:
        raise ValueError("unexpected bitmap start")
    if len(payload) > 4096:
        raise ValueError("widescreen payload exceeds the heap reservation")
    lines = [
        f"gametitle=Super Robot Taisen Z ({edition})",
        "[Widescreen 16:9]",
        "gsaspectratio=16:9",
        "description=Wide tactical view and scene-aware side panels. Enable before boot. Cold boot after changes.",
    ]

    def write(addr, value):
        lines.append(f"patch=0,EE,{addr:08X},word,{value:08X}")

    shapes = sy["bezel_shapes"]
    shape_count = (sy["bezel_shapes_end"] - shapes) // 7
    shapes_end = shapes + 7 * shape_count
    for i, (word,) in enumerate(struct.iter_unpack("<I", payload)):
        addr = base + 4 * i
        if addr == sy["bezel_palette"]:
            lines.extend(
                [
                    "",
                    "// BEZEL PALETTE: edit the next 11 values as 00BBGGRR.",
                    "// Both sides share these colors. Keep addresses and leading zeros.",
                ]
            )
        if shapes <= addr < shapes_end:
            # Seven bytes per row. Emit byte writes so edits never straddle two shapes.
            if addr == shapes:
                lines.extend(
                    [
                        "",
                        "// BEZEL SHAPES: each row is a left-hand trapezoid, mirrored on the right.",
                        "// Byte order: palette offset (00,04,...,28), Y top/bottom, left/right at top, left/right at bottom.",
                        "// Coordinates are hex: X 00..50, Y 00..E0. To hide a row, set its bottom Y equal to its top Y.",
                    ]
                )
                for row in range(shapes, shapes_end, 7):
                    lines.append(f"// Shape {(row - shapes) // 7 + 1}")
                    for column in range(7):
                        offset = row + column
                        lines.append(
                            f"patch=0,EE,{offset:08X},byte,{payload[offset - base]:02X}"
                        )
                for pad in range(shapes_end, (shapes_end + 3) & ~3):
                    lines.append(f"patch=0,EE,{pad:08X},byte,{payload[pad - base]:02X}")
            continue
        write(addr, word)
    writes.update(
        {addr: branch(sy[label], link) for addr, (label, link) in hooks.items()}
    )
    writes[display + 4] = 0
    lines.append("// Heap reservation and graphics hook sites.")
    for addr, word in sorted(writes.items()):
        write(addr, word)
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{SERIAL[edition]}_{crc:08X}.pnach"
    path.write_text("\n".join(lines) + "\n")
    print(path)
    if bitmap:
        return sy["bitmap_pixels"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edition", choices=SERIAL)
    parser.add_argument("iso", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--bitmap-template", action="store_true")
    args = parser.parse_args()
    address = generate(args.edition, args.iso, args.output, bitmap=args.bitmap_template)
    if address is not None:
        print(f"{address:08X}")
