"""Transform the SP executable, AID archive and effect archive into the event gallery.

This is a pure member transform used by the SP full-text assembly as its final
executable stage and by the isolated-candidate wrapper in ``build.py``. It
never touches an ISO: the caller relocates the three grown members.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.codec import decode_production
from special_disc.event_gallery.aid import patch_aid
from special_disc.event_gallery.menu import build as build_menu
from special_disc.event_gallery.subtitles import (build_many, records as resource_records,
                                                  CAPTION_DISPLAY_WIDTH, caption_geometry, vram_limit_for)
from special_disc.event_gallery.runtime import generate as generate_runtime

PAYLOAD_BASE = 0x820000
RUNTIME_BASE = 0x822000
FRAME_ENTRY = 0x822100
ELF_BASE = 0xFF680
PRIVATE_END = 0x8C0000  # payload, map-dialogue blocks (0x830000) and the roster/unit snapshot (0x840000)
TALK_BASE = 0x830000  # runtime.py places map-dialogue blocks here (.org 0xE000)
PAYLOAD_SIZE = 0x20000
PACKET_BASE = 0x82F000  # runtime.S GALLERY_PACKET; reserved to the payload end
PACKET_SIZE = 0x1000
VEFF_OFFSET_TABLE = 0x375230
VEFF_SIZE_TABLE = 0x375700
CONFIG = ROOT / "config/products/special-disc/event-gallery.json"
FONT = ROOT / "work/font-source/harmonyos-sans-sc-1.0/HarmonyOS_Sans_SC_Regular.ttf"
# The installed shared-font codebook every SP writer encodes with (locked SP input).
PROPOSAL = ROOT / "work/build/special-disc/text-candidate/font/proposal.json"
MEMBERS = ("SLPS_259.20", "AID_DATA/AIDDATA.BIN", "EFF/VEFF2DX.BIN")
# Instruction sites rewritten in the executable: (address, expected words, replacement words).
HOOKS = (
    (0x143EA8, (0x0C0913BC,), (0x0C000000 | (FRAME_ENTRY >> 2),)),
    (0x144B30, (0x0C050604,), (0x0C000000 | ((RUNTIME_BASE + 0xA00) >> 2),)),
    (0x144B00, (0x0C05B790,), (0x0C000000 | ((RUNTIME_BASE + 0xE00) >> 2),)),
    (0x320F30, (0x27BDFFD0, 0xFFBF0020), (0x08000000 | ((RUNTIME_BASE + 0x500) >> 2), 0)),
    # Reserve the gallery below the native heap instead of in high-RAM scratch.
    # Source BSS ends at 0x81c600; the private segment ends at PRIVATE_END.
    (0x1001D0, (0x3C040082,), (0x3C04008B,)),
    (0x1001D8, (0x2484C600,), (0x24840000,)),
    (0x44E734, (0x81C600,), (PRIVATE_END,)),
    (0x1410F4, (0x3C040082,), (0x3C04008B,)),
    (0x141100, (0x2484C600,), (0x24840000,)),
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_config(path: Path = CONFIG) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("subtitle_source"):
        config["subtitles"] = json.loads((ROOT / config["subtitle_source"]).read_text(encoding="utf-8"))["captions"]
    if config.get("talk_source"):
        config["talk"] = json.loads((ROOT / config["talk_source"]).read_text(encoding="utf-8"))["scenes"]
    return config


def encode_talk(talk: dict, proposal: Path) -> dict:
    """Encode every dialogue line with the SP codebook, as the SP stage writer stores it."""
    from special_disc.writeback.migrate_slps_text import encoding_tables
    from special_disc.writeback.migrate_stage_dialogue import stored_stage_translation
    from srwz.text import encode_text
    table, _, overrides, _ = encoding_tables(proposal)
    encoded = {}
    for scene, data in talk.items():
        sections = []
        for section in data["sections"]:
            records = []
            for record in section["records"]:
                words = list(record["words"])
                text = None
                if "text" in record:
                    words[3] = record["pilot_sp"]
                    shown = record["speaker"] + "\n" + record["text"] if record["speaker"] else record["text"]
                    text = encode_text(stored_stage_translation(shown), table, overrides=overrides, terminate=True)
                records.append({"words": words, "text": text})
            sections.append({"section": section["section"], "header": section["header"], "records": records})
        encoded[scene] = sections
    return encoded


def checked_patch(elf: bytearray, address: int, expected: bytes, replacement: bytes) -> None:
    offset = address - ELF_BASE
    if elf[offset:offset + len(expected)] != expected:
        raise ValueError(f"SP instruction preimage changed at {address:#x}")
    if len(expected) != len(replacement):
        raise ValueError("Instruction patch must retain its original length")
    elf[offset:offset + len(replacement)] = replacement


def assemble_runtime(outdir: Path, entries, voice_timelines, talk=None) -> tuple[bytes, dict]:
    runtime_receipt = generate_runtime(entries, outdir, voice_timelines, talk)
    source = Path(__file__).with_name("runtime.S")
    assembler = shutil.which("mipsel-linux-gnu-as")
    linker = shutil.which("mipsel-linux-gnu-ld")
    objcopy = shutil.which("mipsel-linux-gnu-objcopy")
    if not all((assembler, linker, objcopy)):
        raise ValueError("MIPS little endian binutils are required")
    obj, elf, binary = outdir / "runtime.o", outdir / "runtime.elf", outdir / "runtime.bin"
    subprocess.run([assembler, "-EL", "-mips3", "-I", str(outdir), "-o", str(obj), str(source)], check=True)
    subprocess.run([linker, "-EL", f"-Ttext={RUNTIME_BASE:#x}", "-e", "gallery_selector",
                    "-o", str(elf), str(obj)], check=True)
    subprocess.run([objcopy, "-O", "binary", "-j", ".text", str(elf), str(binary)], check=True)
    return binary.read_bytes(), runtime_receipt


def veff_offsets(elf: bytes, archive_size: int) -> list[int]:
    offsets = []
    for index in range(1024):
        value = struct.unpack_from("<I", elf, VEFF_OFFSET_TABLE + index * 4)[0]
        offsets.append(value)
        if value == archive_size:
            break
    else:
        raise ValueError("VEFF offset table lacks an archive-size sentinel")
    if not all(a < b for a, b in zip(offsets, offsets[1:])):
        raise ValueError("VEFF offset table is not monotonic")
    return offsets


def caption_quad() -> bytes:
    """One immutable caption quad drawn after the complete map/effect pass."""
    quad = bytearray(48)
    quad[0], quad[1] = 0x19, 0x80  # point sampling; no extra linear blur
    half = CAPTION_DISPLAY_WIDTH // 2  # whole-texel width; see subtitles.CAPTION_DISPLAY_WIDTH
    struct.pack_into("<8h", quad, 4, -half, 82, half, 82, half, 102, -half, 102)
    quad[20:36] = bytes((128, 128, 128, 128)) * 4
    # Texture rectangle (u, v, width, height); v is replaced per caption line.
    struct.pack_into("<4h", quad, 36, 0, 0, *caption_geometry())
    quad[44], quad[45] = 0x44, 0x80
    return struct.pack("<5I4H", 2, 0, 0, 0, 0, 0, 1, 1, 1) + bytes(quad)


def apply_event_gallery(elf: bytes, aid: bytes, veff: bytes, *, config: dict | None = None,
                        workdir: Path, font: Path = FONT, proposal: Path = PROPOSAL) -> dict:
    """Return the gallery members plus the receipt binding every input.

    ``elf`` is the fully text-patched executable; the gallery hooks are applied
    last. ``aid`` and ``veff`` are the native members. The result holds the
    three new members, the re-encoded subtitle chunks for readback and the
    static receipt.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    config = load_config() if config is None else config
    if not font.is_file():
        raise ValueError(f"gallery caption font missing: {font}")
    base_elf = bytes(elf)
    aid_out, elf_bytes, aid_receipt = patch_aid(aid, base_elf)
    elf_out = bytearray(elf_bytes)
    offsets = veff_offsets(base_elf, len(veff))
    resources, voice_timelines, compression = {}, {}, {}
    for entry in config["entries"]:
        for effect in entry["effects"]:
            chunk = effect + 1
            start, end = offsets[chunk:chunk + 2]
            decoded = decode_production(veff[start:end])
            raw = decoded.output
            compression[effect] = {"flags": decoded.flags,
                                   "header_unknown_1": decoded.metadata.get("header_unknown_1", 0)}
            if "header_unknown_0" in decoded.metadata:
                compression[effect]["header_unknown_0"] = decoded.metadata["header_unknown_0"]
            resources[effect] = raw
            rec = resource_records(raw)
            if rec[0][0] & 0x40:
                voice_timelines[effect] = rec[-1]
    menu_receipt = build_menu(base_elf, config["entries"], workdir, proposal)
    talk = encode_talk(config["talk"], proposal) if config.get("talk") else None
    runtime, runtime_receipt = assemble_runtime(workdir, config["entries"], voice_timelines, talk)
    # Runtime .text spans 0x822000..; the caption table owns 0x825800..0x826800
    # and scene scripts start after it at 0x826800.
    if any(runtime[0x3800:0x4800]):
        raise ValueError("Gallery runtime data overlaps the independent caption table")
    payload = bytearray(PAYLOAD_SIZE)
    menu = (workdir / "menu-data.bin").read_bytes()
    code_end = PACKET_BASE - RUNTIME_BASE
    if len(menu) >= 0x1F00 or 0x2000 + len(runtime) > PAYLOAD_SIZE:
        raise ValueError("Gallery payload overlaps its state or exceeds the loaded segment")
    if any(runtime[code_end:TALK_BASE - RUNTIME_BASE]):
        raise ValueError("Gallery runtime overlaps the per-frame GIF packet buffer")
    payload[:len(menu)] = menu
    payload[0x2000:0x2000 + len(runtime)] = runtime
    for row in menu_receipt["patches"]:
        address = int(row, 0)
        offset = address - ELF_BASE
        checked_patch(elf_out, address, base_elf[offset:offset + 4], (workdir / f"patch-{address:x}.bin").read_bytes())
    for address, expected, replacement in HOOKS:
        checked_patch(elf_out, address, struct.pack(f"<{len(expected)}I", *expected),
                      struct.pack(f"<{len(replacement)}I", *replacement))

    replacements, subtitle_receipt = {}, []
    jobs = [(effect, [c for c in config["subtitles"] if c.get("effect", 273) == effect]) for effect in resources]
    jobs = [(effect, captions) for effect, captions in jobs if captions]
    built = build_many((resources[effect], captions, font, workdir / f"effect-{effect}", compression[effect],
                        vram_limit_for(effect)) for effect, captions in jobs)
    for (effect, captions), (raw, packed, sub_receipt) in zip(jobs, built):
        decoded_resource = resources[effect]
        if effect == 257:
            assert sub_receipt["texture"]["native_vram_end_block"] <= 0x3D00, "Feedback backup overlaps scene textures"
        chunk = effect + 1
        if struct.unpack_from("<I", elf_out, VEFF_SIZE_TABLE + chunk * 4)[0] != len(decoded_resource):
            raise ValueError(f"VEFF decoded-size table drift for chunk {chunk}")
        struct.pack_into("<I", elf_out, VEFF_SIZE_TABLE + chunk * 4, len(raw))
        replacements[chunk] = (raw, packed)
        subtitle_receipt.append({"effect": effect, "chunk": chunk, "decoded_sha256": sha(raw),
                                 "packed_sha256": sha(packed), **sub_receipt})
    veff_out, new_offsets = bytearray(), [0]
    for chunk, (start, end) in enumerate(zip(offsets, offsets[1:])):
        if chunk in replacements:
            packed = replacements[chunk][1]
            allocation = max(end - start, (len(packed) + 15) & ~15)
            veff_out += packed + bytes(allocation - len(packed))
        else:
            veff_out += veff[start:end]
        new_offsets.append(len(veff_out))
    # The SP has one VEFF offset table. Preserve each unrelated encoded chunk.
    if base_elf.count(struct.pack("<8I", *offsets[:8])) != 1:
        raise ValueError("VEFF offset table is not unique in the executable")
    struct.pack_into(f"<{len(new_offsets)}I", elf_out, VEFF_OFFSET_TABLE, *new_offsets)
    payload[0x1C00:0x1C10] = bytes((3,)) + bytes(15)
    caption_animation = caption_quad()
    payload[0x1C10:0x1C10 + len(caption_animation)] = caption_animation
    caption_table = bytearray()
    for sub in subtitle_receipt:
        draw = sub["runtime_draw"]
        captions = [c for c in config["subtitles"] if c["effect"] == sub["effect"]]
        for index, caption in enumerate(captions):
            tail = draw["palette_byte"] | (((draw["picture"] << 2) | draw["group"]) << 8)
            # v offset of the line, texture width in the high half (runtime.S writes both).
            caption_table += struct.pack("<5I", sub["effect"], caption["start_frame"], caption["end_frame"],
                                         index * draw["row_height"] | draw["width"] << 16, tail)
    caption_table += struct.pack("<5I", 0xFFFFFFFF, 0, 0, 0, 0)
    if len(caption_table) >= 0x1000:
        raise ValueError("caption table exceeds its reserved block")
    payload[0x5800:0x5800 + len(caption_table)] = caption_table
    # runtime.S builds the caption and feedback-copy GIF packets at
    # GALLERY_PACKET every frame; scene data placed there is overwritten while
    # the native placeholder/spawn code still reads it (2026-10-14 regression).
    packet = PACKET_BASE - PAYLOAD_BASE
    if any(payload[packet:packet + PACKET_SIZE]):
        raise ValueError("Gallery data overlaps the per-frame GIF packet buffer")

    # Preserve all 71 original program headers. Add a separate header in the
    # verified padding before the first segment instead of repurposing a slot.
    ph = struct.unpack_from("<I", elf_out, 28)[0]
    count = struct.unpack_from("<H", elf_out, 44)[0]
    if count != 71 or elf_out[ph + count * 32:ph + (count + 1) * 32] != bytes(32) or ph + (count + 1) * 32 > 0x980:
        raise ValueError("SP program header layout changed; gallery segment cannot be added")
    elf_out += bytes((-len(elf_out)) % 0x1000)
    payload_offset = len(elf_out)
    struct.pack_into("<8I", elf_out, ph + count * 32, 1, payload_offset, PAYLOAD_BASE,
                     PAYLOAD_BASE, len(payload), PRIVATE_END - PAYLOAD_BASE, 7, 16)
    struct.pack_into("<H", elf_out, 44, count + 1)
    elf_out += payload
    elf_out = bytes(elf_out)
    veff_out = bytes(veff_out)
    receipt = {
        "config": {"path": str(CONFIG.relative_to(ROOT)), "sha256": sha(CONFIG.read_bytes())},
        "subtitle_source": {"path": config.get("subtitle_source"),
                            "sha256": sha((ROOT / config["subtitle_source"]).read_bytes()) if config.get("subtitle_source") else None},
        "font": {"path": str(font.relative_to(ROOT)) if font.is_relative_to(ROOT) else str(font), "sha256": sha(font.read_bytes())},
        "proposal": {"path": str(proposal.relative_to(ROOT)), "sha256": sha(proposal.read_bytes())},
        "source_files": {str(p.relative_to(ROOT)): sha(p.read_bytes())
                         for p in sorted(Path(__file__).parent.glob("*.py")) + sorted((Path(__file__).parent / "assets").glob("*.bin"))
                         + [Path(__file__).with_name("runtime.S"), Path(__file__).parent / "assets/manifest.json"]},
        "input_elf_sha256": sha(base_elf), "elf_sha256": sha(elf_out),
        "input_aid_sha256": sha(aid), "input_veff_sha256": sha(veff),
        "scene_count": len(config["entries"]), "caption_count": len(config["subtitles"]),
        "payload": {"address": hex(PAYLOAD_BASE), "offset": payload_offset, "size": len(payload),
                    "private_end": hex(PRIVATE_END)},
        "hooks": [{"address": hex(address), "words": len(expected)} for address, expected, _ in HOOKS],
        "menu": menu_receipt, "runtime": runtime_receipt, "aid": aid_receipt, "subtitles": subtitle_receipt,
        "veff": {"source_bytes": len(veff), "bytes": len(veff_out), "sha256": sha(veff_out),
                 "edited_chunks": sorted(replacements), "offsets": new_offsets,
                 "unrelated_encoded_chunks_preserved": True},
        "runtime_acceptance": "LRPS2 cold-start evidence is recorded separately per candidate identity",
    }
    (workdir / "gallery-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return {"members": {MEMBERS[0]: elf_out, MEMBERS[1]: aid_out, MEMBERS[2]: veff_out},
            "replacements": replacements, "offsets": new_offsets, "receipt": receipt}


def verify_gallery_members(elf: bytes, veff: bytes, receipt: dict) -> dict:
    """Independent readback of the gallery hooks, payload segment and subtitled chunks."""
    for address, _, replacement in HOOKS:
        offset = address - ELF_BASE
        if elf[offset:offset + 4 * len(replacement)] != struct.pack(f"<{len(replacement)}I", *replacement):
            raise AssertionError(f"gallery hook missing at {address:#x}")
    ph = struct.unpack_from("<I", elf, 28)[0]
    count = struct.unpack_from("<H", elf, 44)[0]
    segment = struct.unpack_from("<8I", elf, ph + (count - 1) * 32)
    payload = receipt["payload"]
    if count != 72 or segment[:6] != (1, payload["offset"], PAYLOAD_BASE, PAYLOAD_BASE, payload["size"], PRIVATE_END - PAYLOAD_BASE):
        raise AssertionError("gallery payload program header drift")
    packet = payload["offset"] + PACKET_BASE - PAYLOAD_BASE
    if any(elf[packet:packet + PACKET_SIZE]):
        raise AssertionError("gallery data occupies the per-frame GIF packet buffer")
    offsets = receipt["veff"]["offsets"]
    if list(struct.unpack_from(f"<{len(offsets)}I", elf, VEFF_OFFSET_TABLE)) != offsets or offsets[-1] != len(veff):
        raise AssertionError("VEFF offset table does not describe the subtitled archive")
    checked = 0
    for sub in receipt["subtitles"]:
        chunk = sub["chunk"]
        start, end = offsets[chunk:chunk + 2]
        decoded = decode_production(veff[start:end]).output
        if struct.unpack_from("<I", elf, VEFF_SIZE_TABLE + chunk * 4)[0] != len(decoded):
            raise AssertionError(f"VEFF decoded-size table drift for chunk {chunk}")
        if sha(decoded) != sub["decoded_sha256"]:
            raise AssertionError(f"subtitled effect {sub['effect']} readback drift")
        checked += 1
    return {"hooks": len(HOOKS), "subtitled_chunks": checked, "payload_offset": payload["offset"],
            "packet_buffer": f"{PACKET_BASE:#x}+{PACKET_SIZE:#x} clear"}
