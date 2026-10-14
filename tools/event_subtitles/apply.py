"""Add captions to the native Original/Best map effects as a pure member transform.

Inputs are the edition's fully assembled executable and effect archive; outputs
are the subtitled members plus a receipt binding every input hash. No ISO is
touched here: the caller relocates the two grown members (``special_disc.iso_relocation``).
No gallery, stage script, map or audio member changes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.codec import decode_production
from srwz.iso9660 import member_map, scan_iso9660
from special_disc.event_gallery.apply import caption_quad
from special_disc.event_gallery.subtitles import build_many as build_caption_many, records, vram_limit_for

ARCHIVE = "EFF/VEFF2DX.BIN"
FONT_REL = "work/font-source/harmonyos-sans-sc-1.0/HarmonyOS_Sans_SC_Regular.ttf"
SP_CAPTIONS = "config/products/special-disc/event-subtitles.json"
MAIN_CAPTIONS = "config/event-subtitles/main-only-captions.json"
PROFILE_NAMES = {
    "SCREEN_EFFECT_ENABLED": "screen_effect_enabled", "EFFECT_POOL": "effect_pool", "DRAW_QUAD": "draw_quad",
    "NATIVE_POLL": "poll", "FRAME_INFO": "frame_info", "FRAME_PARITY": "frame_parity", "WAIT_GIF": "wait_gif",
    "FLUSH_CACHE": "flush_cache", "PAYLOAD_BASE": "payload_base",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_profile(edition: str, root: Path = ROOT) -> dict:
    if edition not in ("original", "best"):
        raise ValueError("event subtitles exist for original and best only")
    return json.loads((root / f"config/event-subtitles/{edition}.json").read_text(encoding="utf-8"))


def load_captions(root: Path = ROOT) -> list[dict]:
    sp = json.loads((root / SP_CAPTIONS).read_text(encoding="utf-8"))["captions"]
    extra = json.loads((root / MAIN_CAPTIONS).read_text(encoding="utf-8"))["captions"]
    return sp + extra


def patch(elf: bytearray, address: int, expected: bytes, replacement: bytes, base: int = 0xFE580) -> None:
    offset = address - base
    if elf[offset:offset + len(expected)] != expected:
        raise ValueError(f"Instruction preimage mismatch at {address:#x}")
    if len(expected) != len(replacement):
        raise ValueError("Instruction patch must retain its original length")
    elf[offset:offset + len(expected)] = replacement


def assemble_runtime(profile: dict, out: Path) -> bytes:
    inc = [f".equ {name}, {profile[key]:#x}" for name, key in PROFILE_NAMES.items()]
    inc.append(f".equ PACKET_BASE, {profile['payload_base'] + 0x8000:#x}")
    (out / "profile.inc").write_text("\n".join(inc) + "\n")
    source = Path(__file__).with_name("runtime.S")
    steps = [("as", ["-EL", "-mips3", "-I", str(out), "-o", str(out / "runtime.o"), str(source)]),
             ("ld", ["-EL", f"-Ttext={profile['payload_base']:#x}", "-e", "caption_final_draw",
                     "-o", str(out / "runtime.elf"), str(out / "runtime.o")]),
             ("objcopy", ["-O", "binary", "-j", ".text", str(out / "runtime.elf"), str(out / "runtime.bin")])]
    for tool, arguments in steps:
        binary = shutil.which("mipsel-linux-gnu-" + tool)
        if not binary:
            raise ValueError("MIPS binutils unavailable")
        subprocess.run([binary, *arguments], check=True)
    code = (out / "runtime.bin").read_bytes()
    if len(code) >= 0x1C00:
        raise ValueError("caption runtime overlaps its animation header")
    return code


def _heap_words(profile: dict) -> dict[str, tuple[bytes, bytes]]:
    """Executable words that move the native allocator start past the payload."""
    end = profile["payload_base"] + profile["payload_size"]
    hi, low = (end + 0x8000) >> 16, end & 0xFFFF
    old_hi, old_lo = (profile["heap_end"] + 0x8000) >> 16, profile["heap_end"] & 0xFFFF
    words = {}
    for key in ("heap_init_hi", "map_heap_hi"):
        words[key] = (struct.pack("<I", (15 << 26) | (4 << 16) | old_hi), struct.pack("<I", (15 << 26) | (4 << 16) | hi))
    for key in ("heap_init_lo", "map_heap_lo"):
        words[key] = (struct.pack("<I", 0x24840000 | old_lo), struct.pack("<I", 0x24840000 | low))
    words["heap_literal"] = (struct.pack("<I", profile["heap_end"]), struct.pack("<I", end))
    return words


def _hook_words(profile: dict) -> dict[str, tuple[bytes, bytes]]:
    jal = lambda target: struct.pack("<I", 0x0C000000 | (target >> 2))
    return {"final_draw_hook": (jal(profile["poll"]), jal(profile["payload_base"] + 0xA00)),
            "feedback_hook": (jal(profile["frame_info"]), jal(profile["payload_base"] + 0xE00))}


def apply_event_subtitles(edition: str, elf: bytes, veff: bytes, *, workdir: Path, font: Path | None = None,
                          root: Path = ROOT, profile: dict | None = None) -> dict:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    profile = load_profile(edition, root) if profile is None else profile
    font = root / FONT_REL if font is None else Path(font)
    if not font.is_file():
        raise ValueError(f"caption font missing: {font}")
    base = profile["elf_file_base"]
    out = bytearray(elf)
    original_elf = bytes(elf)
    count = profile["archive_offset_count"]
    offsets = struct.unpack_from(f"<{count}I", out, profile["offset_table"])
    if offsets[0] != 0 or offsets[-1] != len(veff) or not all(a < b for a, b in zip(offsets, offsets[1:])):
        raise ValueError("effect archive offset table does not describe the input archive")
    captions = load_captions(root)
    replacements, receipts, jobs = {}, [], []
    for effect in sorted({c["effect"] for c in captions}):
        chunk = effect + 1
        start, end = offsets[chunk:chunk + 2]
        decoded = decode_production(veff[start:end])
        raw = decoded.output
        if struct.unpack_from("<I", out, profile["size_table"] + chunk * 4)[0] != len(raw):
            raise ValueError(f"effect decoded-size table drift for chunk {chunk}")
        compression = {"flags": decoded.flags, "header_unknown_1": decoded.metadata.get("header_unknown_1", 0)}
        if "header_unknown_0" in decoded.metadata:
            compression["header_unknown_0"] = decoded.metadata["header_unknown_0"]
        lines = [c for c in captions if c["effect"] == effect]
        jobs.append((effect, chunk, raw, lines, compression))
    built = build_caption_many((raw, lines, font, workdir / f"effect-{effect}", compression, vram_limit_for(effect))
                               for effect, chunk, raw, lines, compression in jobs)
    for (effect, chunk, raw, lines, compression), (new, packed, receipt) in zip(jobs, built):
        if effect == 257 and receipt["texture"]["native_vram_end_block"] > 0x3D00:
            raise ValueError("feedback backup overlaps scene textures")
        replacements[chunk] = (new, packed)
        receipt.update(effect=effect, chunk=chunk, decoded_sha256=sha(new), packed_sha256=sha(packed),
                       source_voice_table_sha256=sha(records(raw)[-1]))
        receipts.append(receipt)
        struct.pack_into("<I", out, profile["size_table"] + chunk * 4, len(new))
    updated, new_offsets = bytearray(), [0]
    for index, (a, b) in enumerate(zip(offsets, offsets[1:])):
        if index in replacements:
            data = replacements[index][1]
            updated += data + bytes((-len(data)) % 16)
        else:
            updated += veff[a:b]
        new_offsets.append(len(updated))
    struct.pack_into(f"<{count}I", out, profile["offset_table"], *new_offsets)

    payload = bytearray(profile["payload_size"])
    code = assemble_runtime(profile, workdir)
    payload[:len(code)] = code
    payload[0x1C00:0x1C10] = bytes((3,)) + bytes(15)
    animation = caption_quad()
    payload[0x1C10:0x1C10 + len(animation)] = animation
    table, extra_table = bytearray(), bytearray()
    for receipt in receipts:
        draw = receipt["runtime_draw"]
        tail = draw["palette_byte"] | ((draw["picture"] << 2 | draw["group"]) << 8)
        for index, caption in enumerate(c for c in captions if c["effect"] == receipt["effect"]):
            row = struct.pack("<5I", receipt["effect"], caption["start_frame"], caption["end_frame"],
                              index * draw["row_height"] | draw["width"] << 16, tail)
            if caption.get("edition_extra"):
                extra_table += row
            else:
                table += row
    table += extra_table + struct.pack("<5I", 0xFFFFFFFF, 0, 0, 0, 0)
    if len(table) >= 0x1000:
        raise ValueError("caption table exceeds its reserved block")
    payload[0x5800:0x5800 + len(table)] = table
    # runtime.S builds its GIF packets at PACKET_BASE (payload + 0x8000) every frame.
    if any(payload[0x8000:0x9000]):
        raise ValueError("caption payload overlaps the per-frame GIF packet buffer")

    for key, (expected, replacement) in {**_hook_words(profile), **_heap_words(profile)}.items():
        patch(out, profile[key], expected, replacement, base)
    ph = struct.unpack_from("<I", out, 28)[0]
    phsize, num = struct.unpack_from("<HH", out, 42)
    if phsize != 32 or num != 209 or ph + (num + 1) * 32 > 0x1A80 or any(out[ph + num * 32:ph + (num + 1) * 32]):
        raise ValueError("executable program header layout changed; caption segment cannot be added")
    for index in range(num):
        segment = struct.unpack_from("<8I", out, ph + index * 32)
        if segment[0] == 1 and segment[5] and segment[2] + segment[5] > profile["payload_base"]:
            raise ValueError("private payload overlaps a native overlay segment")
    out += bytes((-len(out)) % 0x1000)
    position = len(out)
    struct.pack_into("<8I", out, ph + num * 32, 1, position, profile["payload_base"], profile["payload_base"],
                     len(payload), len(payload), 7, 16)
    struct.pack_into("<H", out, 44, num + 1)
    out += payload
    elf_out, veff_out = bytes(out), bytes(updated)
    profile_path = root / f"config/event-subtitles/{edition}.json"
    receipt = {
        "edition": edition,
        "profile": {"path": f"config/event-subtitles/{edition}.json", "sha256": sha(profile_path.read_bytes())},
        "caption_sources": {SP_CAPTIONS: sha((root / SP_CAPTIONS).read_bytes()),
                            MAIN_CAPTIONS: sha((root / MAIN_CAPTIONS).read_bytes())},
        "font": {"path": FONT_REL, "sha256": sha(font.read_bytes())},
        "source_files": {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in
                         (Path(__file__), Path(__file__).with_name("runtime.S"))},
        "input_elf_sha256": sha(original_elf), "elf_sha256": sha(elf_out),
        "input_veff_sha256": sha(veff), "veff_sha256": sha(veff_out),
        "caption_count": len(captions), "effects": sorted({c["effect"] for c in captions}),
        "payload": {"address": hex(profile["payload_base"]), "offset": position, "size": len(payload)},
        "veff": {"source_bytes": len(veff), "bytes": len(veff_out), "offsets": new_offsets,
                 "edited_chunks": sorted(replacements), "unmodified_effect_chunks_preserved": True},
        "subtitles": receipts,
        "all_stage_scripts_maps_and_audio_members_unchanged": True,
        "gallery_menu_or_scene_driver_added": False,
    }
    (workdir / "subtitles-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return {"members": {profile["elf_member"]: elf_out, ARCHIVE: veff_out}, "replacements": replacements,
            "offsets": new_offsets, "receipt": receipt, "profile": profile}


def verify_subtitle_members(elf: bytes, veff: bytes, profile: dict, receipt: dict) -> dict:
    """Independent readback of hooks, allocator words, payload segment and subtitled chunks."""
    base = profile["elf_file_base"]
    for key, (_, replacement) in {**_hook_words(profile), **_heap_words(profile)}.items():
        offset = profile[key] - base
        if elf[offset:offset + len(replacement)] != replacement:
            raise AssertionError(f"caption executable word missing: {key}")
    ph = struct.unpack_from("<I", elf, 28)[0]
    num = struct.unpack_from("<H", elf, 44)[0]
    segment = struct.unpack_from("<8I", elf, ph + (num - 1) * 32)
    payload = receipt["payload"]
    if num != 210 or segment[:6] != (1, payload["offset"], profile["payload_base"], profile["payload_base"],
                                     payload["size"], payload["size"]):
        raise AssertionError("caption payload program header drift")
    offsets = receipt["veff"]["offsets"]
    if (list(struct.unpack_from(f"<{len(offsets)}I", elf, profile["offset_table"])) != offsets
            or offsets[-1] != len(veff)):
        raise AssertionError("effect offset table does not describe the subtitled archive")
    checked = 0
    for sub in receipt["subtitles"]:
        chunk = sub["chunk"]
        start, end = offsets[chunk:chunk + 2]
        decoded = decode_production(veff[start:end]).output
        if struct.unpack_from("<I", elf, profile["size_table"] + chunk * 4)[0] != len(decoded):
            raise AssertionError(f"effect decoded-size table drift for chunk {chunk}")
        if sha(decoded) != sub["decoded_sha256"]:
            raise AssertionError(f"subtitled effect {sub['effect']} readback drift")
        checked += 1
    return {"executable_words": 7, "subtitled_chunks": checked, "payload_offset": payload["offset"]}


def verify_subtitled_iso(iso: Path, receipt: dict, root: Path) -> dict:
    """Re-read a published image: member hashes, profile identity and the member readback."""
    iso = Path(iso)
    sub = receipt["subtitles"]
    profile = load_profile(sub["edition"], root)
    if sha((root / sub["profile"]["path"]).read_bytes()) != sub["profile"]["sha256"]:
        raise AssertionError("event subtitle profile drift")
    members = member_map(scan_iso9660(iso))
    data = {}
    with iso.open("rb") as stream:
        for name, digest in receipt["members"].items():
            member = members[name]
            stream.seek(member.extent_lba * 2048)
            data[name] = stream.read(member.size)
            if sha(data[name]) != digest:
                raise AssertionError(f"subtitled member drift: {name}")
    readback = verify_subtitle_members(data[profile["elf_member"]], data[ARCHIVE], profile, sub)
    if readback != receipt["member_readback"]:
        raise AssertionError("event subtitle member readback drift")
    return readback
