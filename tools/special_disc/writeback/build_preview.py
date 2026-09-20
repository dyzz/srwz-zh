"""Assemble the SP preview disc: migrated components first, then the Chinese images.

Components are applied in order, each built on the bytes the previous one
produced (checked by hash): the Chinese font (install_font.py), the executable
UI strings and suspend messages (migrate_slps_text.py) and the battle subtitles
(migrate_srvc.py). Then every finished picture is mapped back to its own
palette (the original index is kept wherever the colour is unchanged, and every
originally transparent pixel keeps its index), or, where PALETTES names one,
written with the new palette made for it; it is stored in the picture's layout
(linear, GS-swizzled PSMT8 or row-major PSMT4), and its stream is re-encoded
with the production Rust codec. Streams that fit keep their slot. VT1 streams
that grow are re-laid inside the window between the first and the last edited
chunk (the window end stays fixed; unedited chunks move with their full
original bytes) and the SLPS VT1 offset table entries are updated.

Outputs (work/build/special-disc/preview/):
  archives/<member>      patched archive copies
  SLPS_259.20            executable
  sp-image-preview.iso   SP disc copy with the members written in place
  manifest.json          component chain, per-picture checks, stream sizes
The finished ISO and its manifest are also copied to build/iso/special-disc/preview/.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.codec import decode_production, reencode_changed_suffix  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.tim2 import parse_tim2  # noqa: E402
from srwz.psmt4 import swizzle_psmt4, unswizzle_psmt4  # noqa: E402
from srwz.tim2_writeback import _csm1_palette_offset, swizzle_psmt8, unswizzle_psmt8  # noqa: E402

KIT = ROOT / "config/assets/special-disc/preview"
ISO = ROOT / "rom/Super Robot Taisen Z - Special Disc [J].iso"
LOCKS = ROOT / "config/products/special-disc/disc-inventory.json"
OUT = ROOT / "work/build/special-disc/preview"
BUILD = ROOT / "build/iso/special-disc/preview"  # where the playable copy is picked up
# Components built before the pictures, in order; each one names the member bytes it started from.
COMPONENTS = [
    ROOT / "work/build/special-disc/components/font",  # install_font.py: VT1 chunks 2-3 and two table entries
    ROOT / "work/build/special-disc/components/text",  # migrate_slps_text.py: executable UI strings, suspend messages
    ROOT / "work/build/special-disc/components/srvc",  # migrate_srvc.py: battle subtitles (BTL/SRVC.BIN)
    ROOT / "work/build/special-disc/components/compdata",  # migrate_compdata.py: names, weapons, abilities (COMPDATA.BN)
    ROOT / "work/build/special-disc/components/library",  # migrate_library.py: encyclopedia (MTVZKN*) and their tables
    ROOT / "work/build/special-disc/components/nisv",  # migrate_nisv.py: tutorial, strategy Q&A, squad names (NISVDATA)
    ROOT / "work/build/special-disc/components/names",  # migrate_names.py: demo speaker names (OP/ST), map names
    ROOT / "work/build/special-disc/components/flow",  # migrate_flow.py: scenario-chart overviews and titles (STAGE chunk 0)
    ROOT / "work/build/special-disc/components/textures",  # migrate_textures.py: reusable textures and heading layout
    ROOT / "work/build/special-disc/components/exe-patches",  # migrate_exe_patches.py: width measurement and alignments
    ROOT / "work/build/special-disc/components/system-text",  # write_system_text.py: SD system text (exe, COMPDATA, tickers)
]
EXE = "SLPS_259.20"
TABLES = {"DATA/VT1.BIN": 0x353790, "AID_DATA/AIDDATA.BIN": 0x37D510,
          "DATA/HSFC.BIN": 0x3AE8A0, "DATA/NISVDATA.BIN": 0x384A00}

# (archive, stream offset, TIM2 offset in the decoded stream, picture, palette bank, layout, source, label)
EDITS = [
    ("DATA/VT1.BIN", 0xBA047F0, 0, 0, 0, "swizzled", "vt1-16-title-menu/final-zh-indexes.npy", "VT1 #156 标题菜单按钮"),
    ("DATA/VT1.BIN", 0xBB26400, 0, 0, 0, "swizzled", "vt1-30-extra-stage-menu/final-zh-indexes.npy", "VT1 #171 额外关卡按钮"),
    ("DATA/VT1.BIN", 0xBBFA510, 0, 0, 0, "swizzled", "vt1-53-battle-viewer-menu/final-zh-indexes.npy", "VT1 #185 战斗鉴赏按钮"),
    ("DATA/VT1.BIN", 0xBB7E2A0, 0, 0, 0, "linear", "heading-plate/final-VT1-173.png", "VT1 #173 额外关卡标题"),
    ("DATA/VT1.BIN", 0xBBA5020, 0, 0, 0, "linear", "heading-plate/final-VT1-175.png", "VT1 #175 剧情模式标题"),
    ("DATA/VT1.BIN", 0xBBDB7D0, 0, 0, 0, "linear", "heading-plate/final-VT1-180.png", "VT1 #180 挑战模式标题"),
    ("DATA/VT1.BIN", 0xBC35BC0, 0, 0, 0, "linear", "heading-plate/final-VT1-187.png", "VT1 #187 战斗鉴赏标题"),
    *[("AID_DATA/AIDDATA.BIN", 0xC5F0, 287856, k, k, "swizzled", f"aid-banner-{k + 1}/final-zh.png", f"AIDDATA 块2 横幅 {k + 1}")
      for k in range(5)],
    ("AID_DATA/AIDDATA.BIN", 0xC5F0, 948592, 0, 0, "swizzled", "heading-plate/final-AIDDATA-块2.png", "AIDDATA 块2 特别剧场标题"),
    ("DATA/HSFC.BIN", 0x13D0, 0x104A0, 0, 0, "linear", "hsfc-chart-title-z/final-zh-indexes.npy", "HSFC #105 剧情流程 Z"),
    ("DATA/HSFC.BIN", 0x13D0, 0x81DE0, 0, 0, "linear", "hsfc-chart-title-sp/final-zh.png", "HSFC #110 剧情流程 Special Disc"),
    ("DATA/NISVDATA.BIN", 0x49400, 0x30, 0, 0, "swizzled", "nisv-sound-select-title/final-zh.png", "NISV #128 音乐选择"),
    ("DATA/VT1.BIN", 0xBAFBC70, 0, 0, 0, "psmt4", "vt1-28-logo/final-zh-p0.npy", "VT1 #162 标题 logo 特别篇"),
    ("DATA/VT1.BIN", 0xBAFBC70, 0, 1, 1, "psmt4", "vt1-28-logo/final-zh-p1.npy", "VT1 #162 标题 logo 光晕层"),
]


# Pictures whose indexes come with a new 256-colour palette (RGBA, alpha 0 or 255), written to their CLUT:
# the button atlases are drawn whole from the user's plate (render_buttons.py).
PALETTES = {f"{slug}/final-zh-indexes.npy": f"{slug}/final-zh-palette.npy"
            for slug in ("vt1-16-title-menu", "vt1-30-extra-stage-menu", "vt1-53-battle-viewer-menu")}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_member(members, locks, name):
    m = members[name]
    with ISO.open("rb") as f:
        f.seek(m.extent_lba * 2048)
        data = f.read(m.size)
    assert sha256(data) == locks[name], f"{name} lock drift"
    return data


def offsets(exe: bytes, start: int, size: int) -> list[int]:
    values, pos = [], start
    while True:
        v = struct.unpack_from("<I", exe, pos)[0]
        values.append(v)
        pos += 4
        if v == size:
            return values


def palette_rgba(decoded: bytes, tim2_offset: int, picture: int, bank: int) -> np.ndarray:
    t = parse_tim2(decoded[tim2_offset:])
    q = t.pictures[picture]
    owner = q if q.clut_size else next(p for p in t.pictures[:picture][::-1] if p.clut_size)
    a = tim2_offset + owner.offset + owner.header_size + owner.image_size
    if q.image_type == 4:
        # 4 bpp: one CSM1 CLUT of 16-colour banks, the bank chosen per picture
        clut = decoded[a:a + owner.clut_size]
        entries = [_csm1_palette_offset(bank * 16 + n) for n in range(16)]
    else:
        clut = decoded[a:a + owner.clut_size][bank * 1024:(bank + 1) * 1024]
        assert len(clut) == 1024
        entries = [_csm1_palette_offset(n) for n in range(256)]
    out = np.zeros((len(entries), 4), np.int32)
    for n, entry in enumerate(entries):
        c = clut[entry * 4:][:4]
        out[n] = (c[0], c[1], c[2], min(255, c[3] * 2))
    return out


def write_palette(decoded: bytearray, tim2_offset: int, picture: int, bank: int, colours: np.ndarray) -> None:
    """Store a new 256-colour palette (alpha 0 or 255 as palette_rgba reads it) in a PSMT8 picture's CLUT."""
    t = parse_tim2(bytes(decoded[tim2_offset:]))
    q = t.pictures[picture]
    assert q.image_type == 5 and q.clut_size >= (bank + 1) * 1024 and colours.shape == (256, 4)
    a = tim2_offset + q.offset + q.header_size + q.image_size + bank * 1024
    for n, (r, g, b, alpha) in enumerate(colours.tolist()):
        assert alpha in (0, 255)
        entry = a + _csm1_palette_offset(n) * 4
        decoded[entry:entry + 4] = bytes((r, g, b, 0x80 if alpha == 255 else 0))
    assert (palette_rgba(bytes(decoded), tim2_offset, picture, bank) == colours).all()

def target_indexes(source: Path, current: np.ndarray, palette: np.ndarray):
    """Finished image -> palette indexes, keeping original indexes where nothing changed."""
    if source.suffix == ".npy":
        out = np.load(source).astype(np.uint8)
        assert out.shape == current.shape, (source, out.shape, current.shape)
        was, after = palette[current], palette[out]
        # a picture given as indexes may move ink, so alpha changes are reported, not forbidden
        return out, dict(mode="indexes", changed_pixels=int((out != current).sum()),
                         alpha_changed=int(((after[..., 3] == 0) != (was[..., 3] == 0)).sum()))
    rgba = np.asarray(Image.open(source).convert("RGBA")).astype(np.int32)
    assert rgba.shape[:2] == current.shape, (source, rgba.shape, current.shape)
    was = palette[current]
    transparent_before = was[..., 3] == 0
    out = current.copy()
    changed = (rgba != was).any(-1) & ~transparent_before
    lookup = {}
    for n in range(255, -1, -1):
        lookup[tuple(palette[n])] = n
    nearest = 0
    for y, x in zip(*np.where(changed)):
        key = tuple(rgba[y, x])
        if key in lookup:
            out[y, x] = lookup[key]
            continue
        # e.g. a semi-transparent pixel given an opaque colour: nearest entry with the same alpha
        same_alpha = np.where(palette[:, 3] == was[y, x, 3])[0]
        dist = ((palette[same_alpha, :3] - rgba[y, x, :3]) ** 2).sum(1)
        out[y, x] = same_alpha[int(dist.argmin())]
        nearest += 1
    after = palette[out]
    report = dict(mode="png", changed_pixels=int((out != current).sum()), nearest_colour_pixels=nearest,
                  transparent_kept=int(transparent_before.sum()),
                  alpha_changed=int(((after[..., 3] == 0) != transparent_before).sum()),
                  png_pixels_not_reproduced=int(((after != rgba).any(-1) & ~transparent_before).sum()))
    return out, report


def align16(n: int) -> int:
    return (n + 15) // 16 * 16


def main() -> None:
    snapshot = json.loads((ROOT / "config/assets/special-disc/preview.json").read_text())
    for asset in snapshot["files"]:
        path = KIT / asset["path"]
        assert sha256(path.read_bytes()) == asset["sha256"], f"preview asset drift: {path}"
    locks = {m["path"]: m["sha256"] for m in json.loads(LOCKS.read_text())["sp"]["members"]}
    members = member_map(scan_iso9660(ISO))
    # Earlier components are the base. Each must have started from exactly the bytes the one
    # before it produced (or the disc), so the chain cannot silently skip or reorder a step.
    # The font component moves VT1 chunks 2 and 3, disjoint from every picture edit here.
    chain: dict[str, tuple[Path, str]] = {}
    used = []
    for component in COMPONENTS:
        if not (component / "report.json").exists():
            continue
        report = json.loads((component / "report.json").read_text())
        for name, digest in report["files"].items():
            started = report.get("base_files", {}).get(name) or report["original_files"][name]
            assert report["original_files"][name] == locks[name], f"{component.name}: built on another disc"
            assert started == chain.get(name, (None, locks[name]))[1], f"{component.name}: not built on the current {name}"
            chain[name] = (component, digest)
        used.append(dict(component=str(component.relative_to(ROOT)), files=report["files"]))

    def base_member(name: str) -> bytearray:
        if name in chain:
            component, digest = chain[name]
            data = (component / name).read_bytes()
            assert sha256(data) == digest, f"{name}: {component.name} drift"
            return bytearray(data)
        return bytearray(read_member(members, locks, name))

    exe = base_member(EXE)
    archives = {name: base_member(name) for name in {e[0] for e in EDITS}}
    # members a component changed that no picture edit touches go to the disc as they are
    extras = {name: base_member(name) for name in chain if name not in archives and name != EXE}
    manifest = dict(iso=str(ISO.relative_to(ROOT)), pictures=[], streams=[], relocated={}, components=used)
    by_stream = {}
    for edit in EDITS:
        by_stream.setdefault((edit[0], edit[1]), []).append(edit)
    encoded_streams = {}
    for (name, stream_offset), edits in by_stream.items():
        data = archives[name]
        table = offsets(exe, TABLES[name], len(data))
        assert stream_offset in table, f"{name} {stream_offset:#x} is not a stream start"
        slot_end = table[table.index(stream_offset) + 1]
        original = decode_production(bytes(data[stream_offset:slot_end]))
        decoded = bytearray(original.output)
        for _name, _off, tim2_offset, picture, bank, layout, source, label in edits:
            t = parse_tim2(bytes(decoded[tim2_offset:]))
            q = t.pictures[picture]
            assert q.image_type == (4 if layout == "psmt4" else 5) and q.mipmap_count == 1, label
            a = tim2_offset + q.offset + q.header_size
            stored = bytes(decoded[a:a + q.image_size])
            if layout == "psmt4":
                logical = unswizzle_psmt4(stored, q.width, q.height, row_major_pages=True)
            elif layout == "swizzled":
                logical = unswizzle_psmt8(stored, q.width, q.height)
            else:
                logical = stored
            current = np.frombuffer(logical, np.uint8).reshape(q.height, q.width)
            palette = palette_rgba(bytes(decoded), tim2_offset, picture, bank)
            new, check = target_indexes(KIT / source, current, palette)
            assert new.max() < len(palette), label
            if source in PALETTES:
                colours = np.load(KIT / PALETTES[source]).astype(np.int32)
                was_clear, now_clear = palette[current][..., 3] == 0, colours[new][..., 3] == 0
                assert (was_clear == now_clear).all(), f"{label}: the new palette changes transparency"
                write_palette(decoded, tim2_offset, picture, bank, colours)
                check = dict(mode="indexes+palette", changed_pixels=check["changed_pixels"], alpha_changed=0,
                             palette_entries_changed=int((colours != palette).any(1).sum()),
                             palette_sha256=sha256((KIT / PALETTES[source]).read_bytes()))
            logical_new = new.astype(np.uint8).tobytes()
            if layout == "psmt4":
                stored_new = swizzle_psmt4(logical_new, q.width, q.height, row_major_pages=True)
                assert unswizzle_psmt4(stored_new, q.width, q.height, row_major_pages=True) == logical_new
            elif layout == "swizzled":
                stored_new = swizzle_psmt8(logical_new, q.width, q.height)
                assert unswizzle_psmt8(stored_new, q.width, q.height) == logical_new
            else:
                stored_new = logical_new
            decoded[a:a + q.image_size] = stored_new
            manifest["pictures"].append(dict(label=label, archive=name, stream_offset=hex(stream_offset),
                                             tim2_offset=hex(tim2_offset), picture=picture, bank=bank, layout=layout,
                                             source=source, source_sha256=sha256((KIT / source).read_bytes()),
                                             size=[q.width, q.height], **check))
        encoded = reencode_changed_suffix(bytes(data[stream_offset:slot_end]), bytes(decoded),
                                          strategy="rust-maximum", original_result=original)
        slot = slot_end - stream_offset
        encoded_streams[(name, stream_offset)] = (encoded, bytes(decoded))
        manifest["streams"].append(dict(archive=name, chunk=table.index(stream_offset), offset=hex(stream_offset),
                                        slot=slot, original_consumed=original.consumed, encoded=len(encoded),
                                        fits_in_place=len(encoded) <= slot, headroom=slot - len(encoded)))

    for name, data in archives.items():
        table = offsets(exe, TABLES[name], len(data))
        edited = {table.index(off): enc for (arch, off), enc in encoded_streams.items() if arch == name}
        if all(len(enc[0]) <= table[i + 1] - table[i] for i, enc in edited.items()):
            for i, (enc, _dec) in edited.items():
                slot = table[i + 1] - table[i]
                data[table[i]:table[i + 1]] = enc + bytes(slot - len(enc))
            continue
        # Re-lay the chunks between the first and last edited chunk; the window end stays fixed.
        assert name == "DATA/VT1.BIN", f"{name}: a stream does not fit and relocation is only prepared for VT1"
        first, last = min(edited), max(edited)
        window_end = table[last + 1]
        pieces, starts, cursor = [], {}, table[first]
        for i in range(first, last + 1):
            starts[i] = cursor
            if i in edited:
                blob = edited[i][0]
                blob = blob + bytes(align16(len(blob)) - len(blob))
            else:
                blob = bytes(data[table[i]:table[i + 1]])
            pieces.append(blob)
            cursor += len(blob)
        if cursor > window_end:
            raise SystemExit(f"{name}: chunks {first}-{last} need {cursor - window_end} more bytes than their window")
        region = b"".join(pieces)
        region += bytes(window_end - table[first] - len(region))  # spare room becomes padding of the last chunk
        data[table[first]:window_end] = region
        moved = {}
        for i in range(first + 1, last + 1):
            if starts[i] != table[i]:
                struct.pack_into("<I", exe, TABLES[name] + 4 * i, starts[i])
                moved[i] = dict(old=hex(table[i]), new=hex(starts[i]))
        manifest["relocated"][name] = dict(window=[first, last + 1], spare=window_end - cursor,
                                           table_offset=hex(TABLES[name]), moved_entries=moved)
    # Verify every edited stream through the (possibly updated) tables.
    for name, data in archives.items():
        table = offsets(exe, TABLES[name], len(data))
        for (arch, off), (enc, dec) in encoded_streams.items():
            if arch != name:
                continue
            i = [k for k, v in enumerate(offsets(read_member(members, locks, EXE), TABLES[name], len(data))) if v == off][0]
            got = decode_production(bytes(data[table[i]:table[i + 1]]))
            assert got.output == dec, (name, i)
        if name in manifest["relocated"]:
            original_data = read_member(members, locks, name)
            original_table = offsets(read_member(members, locks, EXE), TABLES[name], len(data))
            first, end = manifest["relocated"][name]["window"]
            for i in range(first, end):
                if any(arch == name and off == original_table[i] for (arch, off) in encoded_streams):
                    continue
                before = original_data[original_table[i]:original_table[i + 1]]
                after = bytes(data[table[i]:table[i] + len(before)])
                assert before == after, (name, i)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in list(archives.items()) + list(extras.items()):
        path = OUT / "archives" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(data))
    (OUT / EXE).write_bytes(bytes(exe))
    iso_out = OUT / "sp-image-preview.iso"
    shutil.copyfile(ISO, iso_out)
    with iso_out.open("r+b") as f:
        for name, data in list(archives.items()) + list(extras.items()) + [(EXE, exe)]:
            m = members[name]
            assert len(data) == m.size
            f.seek(m.extent_lba * 2048)
            f.write(bytes(data))
    manifest["files"] = {name: dict(sha256=sha256(bytes(data)), original_sha256=locks[name])
                         for name, data in list(archives.items()) + list(extras.items()) + [(EXE, exe)]}
    manifest["preview_iso"] = str(iso_out.relative_to(ROOT))
    BUILD.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(iso_out, BUILD / iso_out.name)
    manifest["build_copy"] = str((BUILD / iso_out.name).relative_to(ROOT))
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    shutil.copyfile(OUT / "manifest.json", BUILD / "manifest.json")
    print(json.dumps({k: manifest[k] for k in ("streams", "relocated", "files", "preview_iso")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
