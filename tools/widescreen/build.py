"""Build an ISO with optional widescreen output from a multilingual Z disc, preserving its other features."""

import argparse
import json
import hashlib
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from build_builtin_cheats import symbols  # noqa: E402
from special_disc.vocal_bgm.build_image import make_header_room  # noqa: E402
from special_disc.iso_relocation import append_members, verify_relocation  # noqa: E402
from zh_hant import assemble_dual as dual  # noqa: E402
from zh_hant.editions import EDITIONS, edition_inc  # noqa: E402

# Map-camera update call, its original callee, terrain and unit projection X,
# DISPLAY2 register write, and optional segment in the unused pre-subtitle gap.
LAYOUT = {
    "original": (
        0x14489C,
        0x140030,
        0x524F40,
        0x594220,
        0x10CB50,
        (0x78DC00, 0x790000),
    ),
    "best": (0x14489C, 0x140030, 0x525740, 0x594A20, 0x10CB50, (0x78DC00, 0x790000)),
    "sp": (0x145BCC, 0x140AE0, 0x5A41F0, 0x61BD10, 0x10CAE0, None),
}


def branch(address, link=True):
    return (0x0C000000 if link else 0x08000000) | (address >> 2)


def check_variants(source, params, spans):
    # Both regional patch streams are applied after boot. Reject a write into
    # either hook site or the new program before producing any output.
    with source.open("rb") as stream:
        for prefix in ("PATCH", "PATCH2"):
            stream.seek(params[prefix + "_LBA"] * 2048)
            data = stream.read(params[prefix + "_SECTORS"] * 2048)
            if data[:4] != b"ZHTP":
                raise ValueError("language build refers to the wrong patch extents")
            rows, count = struct.unpack_from("<II", data, 8)
            pos = 32 + rows * 12
            for _ in range(count):
                addr, size = struct.unpack_from("<II", data, pos)
                if any(addr < end and addr + size > start for start, end in spans):
                    raise ValueError(
                        f"regional write overlaps widescreen code at {addr:#x}"
                    )
                pos += 8 + size + (-size % 4)


def graphics_layout(edition):
    map_call, update, terrain, unit, display, _ = LAYOUT[edition]
    hud_call, hud_submit, hud_chain, hud_arena = {
        "original": (0x1434F0, 0x135FD0, 0x523908, 0x49A6D0),
        "best": (0x1434F0, 0x135FD0, 0x524108, 0x49AED0),
        "sp": (0x1447F0, 0x136960, 0x5A2B88, 0x519950),
    }[edition]
    command, unit_menu, compass_vector = {
        "original": (0x35253C, 0x35131C, 0x3F99C0),
        "best": (0x352B3C, 0x35191C, 0x3FA140),
        "sp": (0x377A5C, 0x37697C, 0x4542F0),
    }[edition]
    defs = dict(
        MOVIE_PIXELS={"original": 0x59BF88, "best": 0x59C788, "sp": 0x624E88}[edition],
        COMPASS_VECTOR=compass_vector,
        HUD_CHAIN=hud_chain,
        HUD_ARENA=hud_arena,
        HUD_SUBMIT=hud_submit,
        REPORT_OBJECT={"original": 0x6D5D68, "best": 0x6D6568, "sp": 0x762998}[edition],
        TERRAIN_X=terrain,
        UNIT_X=unit,
        PROJECTION_UPDATE=update,
        DISPLAY_RETURN=display + 8,
    )
    hooks = {command: ("right_menu", True), unit_menu: ("right_menu", True),
             map_call: ("map_projection", True), hud_call: ("hud_submit", True),
             display: ("display_output", False)}
    checks = {
        command: 0x0320F809,
        unit_menu: 0x0320F809,
        command + 4: 0x0200282D,
        unit_menu + 4: 0x0200282D,
        hud_call: branch(hud_submit),
        map_call: branch(update),
        display: 0xFCA30000,
        display + 4: 0xDE020020,
    }
    return defs, hooks, checks


def reserve(elf, edition, size_bytes):
    # These two native heap setup paths and the image-end pointer must agree.
    if edition == "sp":
        second, pointer = 0x1410F4, 0x44E734
    else:
        second = 0x140644
        pointer = 0x3F4734 if edition == "best" else 0x3F3FB4
    pairs = [(0x1001D0, 0x1001D8), (second, second + 12)]
    base = elf.word(pointer)
    stock = {"original": 0x789D00, "best": 0x78A500, "sp": 0x81C600}[edition]
    if base not in (stock, 0x8C0000 if edition == "sp" else 0x7A0000):
        raise ValueError(f"unsupported heap boundary {base:#x}")
    if any(
        v < base + size_bytes and v + size > base for _, _, v, _, _, size, _, _ in elf.loads
    ):
        raise ValueError("payload overlaps a loaded segment")
    end = base + size_bytes
    writes = {pointer: end}
    for hi, lo in pairs:
        upper, lower = elf.word(hi), elf.word(lo)
        if upper >> 16 != 0x3C04 or lower >> 16 != 0x2484:
            raise ValueError("unrecognized heap initializer")
        old = ((upper & 65535) << 16) + struct.unpack(
            "<h", struct.pack("<H", lower & 65535)
        )[0]
        if old != base and not (edition == "sp" and old == base - 65536):
            raise ValueError("inconsistent heap boundary")
        # Keep initialization (including the SP scratch area) above the payload.
        writes[hi] = 0x3C040000 | ((end + 32768) >> 16)
        writes[lo] = 0x24840000 | (end & 65535)
    if edition == "sp" and base != stock:
        writes[pointer] = end + 65536
    return base, writes


def build(edition, source, output, work, lang_build, *, replace=False):
    if output.exists() and not replace:
        raise FileExistsError(output)
    if source.resolve() == output.resolve():
        raise ValueError("widescreen output aliases the input disc")
    ed = EDITIONS[edition]
    _, _, _, _, display, extra = LAYOUT[edition]
    start, end = extra or ed.cave
    disc = dual.Disc(source)
    elf = dual.Elf(disc.read(ed.exe))
    old = symbols((lang_build / "symbols.txt").read_text())
    code = (lang_build / "hook.bin").read_bytes()
    if elf.get(ed.cave[0], len(code)) != code:
        raise ValueError("language build differs from the input disc")
    defs, graphics_hooks, checks = graphics_layout(edition)
    pixels = Path(__file__).with_name("default-bezel.rgbx").read_bytes()
    if len(pixels) != 2 * 40 * 112 * 4:
        raise ValueError("expected two 40x112 RGBX bezel panels")
    # The emulator's Auto mode can recognize this disc even when new artwork
    # changes its ELF CRC. Keep the versioned descriptor at the heap boundary.
    descriptor_tag = b"SRWZAR01"
    descriptor_size = len(descriptor_tag) + 8
    segment_base, heap_writes = reserve(elf, edition, descriptor_size + len(pixels))
    pixel_base = segment_base + descriptor_size
    defs.update(BITMAP_BEZEL=1, BUILTIN_BITMAP=pixel_base)
    compass_vector = defs["COMPASS_VECTOR"]
    if elf.get(compass_vector, 12) != struct.pack("<3f", 2.6, -88.55, -129):
        raise ValueError("unexpected compass origin")
    if edition == "sp":
        # Expand into the verified blank file padding before the last program,
        # and into its 512-byte virtual gap for the settings and graphics code.
        phoff = struct.unpack_from("<I", elf.b, 28)[0]
        stride, count = struct.unpack_from("<HH", elf.b, 42)
        headers = (phoff + stride * i for i in range(count))
        (entry,) = (
            h for h in headers
            if struct.unpack_from("<I", elf.b, h)[0] == 1
            and struct.unpack_from("<I", elf.b, h + 8)[0] == start
        )
        _, off, va, _, size, mem, _, align = struct.unpack_from("<8I", elf.b, entry)
        grow = 512
        other_loads = [segment for segment in elf.loads if segment[2] != va]
        if (
            size != mem or va + size != end or off + size != len(elf.b)
            or off < grow or grow % max(align, 1) or any(elf.b[off - grow : off])
            or any(v < end + grow and va < v + m for _, _, v, _, _, m, _, _ in other_loads)
            or any(f < off and off - grow < f + n for _, f, _, _, n, _, _, _ in other_loads)
        ):
            raise ValueError("unexpected SP program boundaries")
        elf.b[off - grow : off + size] = elf.b[off : off + size] + bytes(grow)
        struct.pack_into("<I", elf.b, entry + 4, off - grow)
        struct.pack_into("<II", elf.b, entry + 16, size + grow, size + grow)
        elf = dual.Elf(elf.b)
        end += grow
    checks.update({
        ed.boot_site[0]: branch(old["lang_hook"]),
        ed.title_site[0]: branch(old["title_hook"]),
    })
    for addr, word in checks.items():
        if elf.word(addr) != word:
            raise ValueError(f"unexpected instruction at {addr:#x}")
    work.mkdir(parents=True, exist_ok=True)
    params = {
        k: int(v, 0)
        for k, v in re.findall(
            r"\.equ\s+(\w+),\s*(\w+)", (lang_build / "params.inc").read_text()
        )
    }
    protected = [(a, a + 4) for a in (*checks, *heap_writes)]
    protected.extend([(segment_base, pixel_base + len(pixels)), (start, end),
                      (compass_vector, compass_vector + 4)])
    check_variants(source, params, protected)
    if extra:
        defs["SHARED_LANG"] = old["lang"]  # existing cheat and language consumers
    (work / "wide.inc").write_text(
        "".join(f".equ {k},{v:#x}\n" for k, v in defs.items())
    )
    (work / "edition.inc").write_text(edition_inc(ed))
    books = {
        k: TOOLS.parent / "config" / folder / "zh-release-font-assignments.json"
        for k, folder in [("sc", "encoding"), ("tc", "zh-hant/encoding")]
    }
    dual.MESSAGES = dual.panel_messages(params["LANGS"])
    (work / "messages.inc").write_text(dual.codebook_messages(books))
    lines = []
    for lang, path in books.items():
        codes = dict(dual.STOCK_CODES)
        ledger = json.loads(path.read_text())
        for group in (
            "primary_assignments",
            "surface_alias_assignments",
            "source_compatibility_assignments",
        ):
            for row in ledger[group]:
                codes.setdefault(row["character"], row["code"])
        items = [
            (f"aspect_label_{lang}", "画面比例：" if lang == "sc" else "畫面比例：")
        ]
        if lang == "sc":
            items += [("aspect_classic", "４：３　"), ("aspect_wide", "１６：９")]
        for label, text in items:
            raw = b"".join(
                bytes.fromhex(codes[c]) if c in codes else c.encode("cp932")
                for c in text
            )
            lines.append(f"{label}: .byte " + ",".join(map(str, raw + b"\0")))
    (work / "aspect_text.inc").write_text("\n".join(lines) + "\n")

    def tool(name, *args):
        return subprocess.check_output(
            ["mipsel-linux-gnu-" + name, *map(str, args)], text=True
        )

    asm = Path(__file__).with_name("viewport.S")
    tool(
        "as",
        "-EL",
        "-mips3",
        "-mabi=o64",
        "--fatal-warnings",
        "-I",
        work,
        "-I",
        lang_build,
        "-I",
        TOOLS / "zh_hant",
        "-I",
        asm.parent,
        "-o",
        work / "wide.o",
        asm,
    )
    tool(
        "ld",
        "-EL",
        f"-Ttext={start:#x}",
        "-e",
        "lang_hook",
        "-o",
        work / "wide.elf",
        work / "wide.o",
    )
    tool("objcopy", "-O", "binary", "-j", ".text", work / "wide.elf", work / "wide.bin")
    sy = symbols(tool("nm", work / "wide.elf"))
    payload = (work / "wide.bin").read_bytes()
    if len(payload) > end - start:
        raise ValueError("payload exceeds reserved RAM")
    if extra:
        # Move the file backing of the Latin segment to the ELF tail. Its VA and
        # existing data stay identical; no spare program-header slot is needed.
        ph = struct.unpack_from("<I", elf.b, 28)[0]
        count = struct.unpack_from("<H", elf.b, 44)[0]
        headers = [ph + i * 32 for i in range(count)]

        def owns_language_program(header):
            kind, _, address, _, length, *_ = struct.unpack_from("<8I", elf.b, header)
            return kind == 1 and address <= ed.cave[0] < address + length

        (head,) = [header for header in headers if owns_language_program(header)]
        _, off, va, _, size, memsize, _, align = struct.unpack_from("<8I", elf.b, head)
        if (
            size != memsize
            or va + size > start
            or any(
                v != va and v < start + len(payload) and va < v + m
                for _, _, v, _, _, m, *_ in elf.loads
            )
        ):
            raise ValueError("no room after Latin segment")
        newoff = len(elf.b) + (va - len(elf.b)) % max(4096, align)
        olddata = elf.b[off : off + size]
        elf.b.extend(
            bytes(newoff - len(elf.b)) + olddata + bytes(start - va - size) + payload
        )
        struct.pack_into("<I", elf.b, head + 4, newoff)
        struct.pack_into(
            "<II",
            elf.b,
            head + 16,
            start - va + len(payload),
            start - va + len(payload),
        )
        elf = dual.Elf(elf.b)
    elf.put(start, payload)
    writes = dict(heap_writes)
    writes[display + 4] = 0
    for addr, label, link in [
        (ed.boot_site[0], "lang_hook", True),
        (ed.title_site[0], "title_hook", True),
        *((addr, *target) for addr, target in graphics_hooks.items()),
    ]:
        writes[addr] = branch(sy[label], link)
    for address, word in writes.items():
        elf.putw(address, word)
    ph = struct.unpack_from("<I", elf.b, 28)[0]
    count = struct.unpack_from("<H", elf.b, 44)[0]
    headers = [struct.unpack_from("<8I", elf.b, ph + 32 * i) for i in range(count)]
    image, _ = make_header_room(elf.b, ph, count, headers)
    segment = descriptor_tag + struct.pack("<II", sy["wide_enabled"], 0) + pixels
    offset = len(image) + (segment_base - len(image)) % 4096
    image.extend(bytes(offset - len(image)) + segment)
    struct.pack_into("<8I", image, ph + 32 * count, 1, offset, segment_base,
                     segment_base, len(segment), len(segment), 4, 64)
    struct.pack_into("<H", image, 44, count + 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staged = Path(temp) / "image.iso"
        subprocess.run(["cp", "-c", source, staged], check=True)
        members = {ed.exe: bytes(image)}
        proof = append_members(
            staged, disc.m, members,
            allowed_udf={ed.exe, "EFF/VEFF2DX.BIN"} if extra else None,
            catalog_policy="inherit",
        )
        verify_relocation(staged, disc.m, members, proof)
        final = dual.Disc(staged)
        final_elf = dual.Elf(final.read(ed.exe))
        words = {hex(address): final_elf.word(address) for address in writes}
        if any(words[hex(address)] != value for address, value in writes.items()):
            raise ValueError("widescreen ELF readback mismatch")
        default = final_elf.word(sy["wide_enabled"])
        if default != 0:
            raise ValueError("unexpected widescreen default")
        member = "EFF/VEFF2DX.BIN"
        effect = final.read(member)
        if effect != disc.read(member):
            raise ValueError(f"{member} differs from input")
        report = {"edition": edition, "input": dual.disc_identity(source),
                  "output": dual.disc_identity(staged), "elf_words": words,
                  "wide_enabled": {"address": sy["wide_enabled"], "default": default},
                  "members": {member: {"size": len(effect), "sha256": hashlib.sha256(effect).hexdigest()}}}
        receipt = Path(temp) / "verified.json"
        receipt.write_text(json.dumps(report, indent=2) + "\n")
        dual.publish(staged, output, receipt, output.with_suffix(".receipt.json"))
    (work / "symbols.json").write_text(json.dumps(sy, indent=2))
    print(output)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("edition", choices=LAYOUT)
    for name in ("source", "output", "work"):
        p.add_argument(name, type=Path)
    p.add_argument("--language-build", type=Path)
    p.add_argument("--replace", action="store_true", help="replace a previous candidate after verifying the new disc")
    args = p.parse_args()
    build(
        args.edition,
        args.source,
        args.output,
        args.work,
        args.language_build
        or TOOLS.parent / "build/multilang" / ("assemble-" + args.edition),
        replace=args.replace,
    )
