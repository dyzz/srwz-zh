"""Bring the main game's finished Chinese textures into the SP disc.

The main game's build is the answer key once more: for every chunk its build
changed, the Japanese chunk and the built Chinese chunk sit side by side. An SP
chunk then takes the Chinese in one of two ways:

  whole     SP has a chunk whose content is byte-identical to the main game's
            Japanese one (VEFF2DX tutorial titles, 66 MAPMODEL maps with
            terrain names, the KVMDATA pages SP did not touch): it becomes the
            main game's Chinese chunk.
  bytes     SP's chunk at the same place has the same size but differs
            elsewhere (SP recoloured a CLUT bank, added cells): every run of
            bytes the main build changed is copied over, but only where SP
            still holds exactly the main game's Japanese bytes for that run.
            Runs whose preimage differs are left and counted.

Every chunk stays in its own slot (compressed chunks are re-encoded with the
project codec and must fit), so no table in the executable changes.

Also here, because they are texture work of the same kind:
  * KVPDATA heading layout: the main game's draw patches are recorded as
    before/after bytes (config/assets/ui-headings-zh.json); each is applied
    where SP holds the exact before bytes.

Outputs (work/build/special-disc/components/textures/): the rewritten members, report.json.
"""
from __future__ import annotations

import collections
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from srwz.codec import decode_production, reencode_changed_suffix  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.tim2 import parse_tim2  # noqa: E402

ISO = ROOT / "rom/Super Robot Taisen Z - Special Disc [J].iso"
LOCKS = ROOT / "config/products/special-disc/disc-inventory.json"
OG_BUILD = ROOT / ("work/build/zh-release-original/388152fa50e72ed8f4edf6887d9eb1f37130dfc5ee92ba7baf3238aaee22c02f"
                   "/project/work/build/zh-release-full-story/components")
# Japanese main-game members: work/disc where extracted, else a hash-checked copy
OG_JAPANESE = {
    "EFF/VEFF2DX.BIN": ROOT / "work/disc/EFF/VEFF2DX.BIN",
    "MAP/MAPMODEL.BIN": ROOT / "work/disc/MAP/MAPMODEL.BIN",
    "KURODATA/KVMDATA.BIN": ROOT / "work/build/best-alpha1/inputs/original/KURODATA/KVMDATA.BIN",
    "AID_DATA/AIDDATA.BIN": ROOT / "work/build/best-alpha1/inputs/original/AID_DATA/AIDDATA.BIN",
    "BTL/TRICMN.BIN": ROOT / "work/build/best-alpha1/inputs/original/BTL/TRICMN.BIN",
}
OUT = ROOT / "work/build/special-disc/components/textures"
OG_EXE, SD_EXE = "SLPS_258.87", "SLPS_259.20"
# member: (main-game table start or explicit offsets, SP table start or SEG member, storage)
ARCHIVES = {
    "EFF/VEFF2DX.BIN": (0x31ABB0, 0x375230, "stream"),
    "MAP/MAPMODEL.BIN": (0x2FAAD0, 0x3542F0, "stream"),
    "KURODATA/KVMDATA.BIN": (0x3303F0, 0x39DF10, "raw"),
    "AID_DATA/AIDDATA.BIN": ((0, 23232), 0x37D510, "stream"),  # main game: atlas + animation only
    "BTL/TRICMN.BIN": ("BTL/TRICMN.SEG", "BTL/TRICMN.SEG", "stream"),
}
HEADINGS = ROOT / "config/assets/ui-headings-zh.json"
KVP, KVP_TABLE = "KURODATA/KVPDATA.BIN", 0x39B550
# (main-game chunk, first SP chunk, last SP chunk) for the heading runs no byte
# match reaches: the intermission COMMAND bar, "DATA HELP" and "Key Help".
# The search is confined to these chunks because the per-letter cells they use
# (H, e, l, p ...) are shared with SP's own Latin title bars ("CHALLENGE
# BATTLE", "STORY MODE", "SPECIAL DISC"), which must keep drawing Latin.
RETARGET_CHUNKS = ((160, 164, 164), (1167, 1198, 1198), (1192, 1223, 1223))
# Heading tokens whose Chinese cell would bury a letter SP still needs (see
# SHARED_LETTER_RECTS): skipped so the heading keeps the Latin cell the restored
# atlas still holds. "others" rides along because it shares the "OTHERS COMMAND"
# bar with command2, and half a translated bar reads worse than none.
SKIP_TOKENS = ("command2", "item", "others")
# The same, per main-game chunk: chunk 204 is SP's "MAP WEAPON" bar, which reads
# the M of FORMATION out of the 阵型 rect. Other formation patches are real
# FORMATION headings and keep their Chinese.
SKIP_CHUNK_TOKENS = ((204, "formation"),)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_member(members, locks, name: str) -> bytes:
    m = members[name]
    with ISO.open("rb") as f:
        f.seek(m.extent_lba * 2048)
        data = f.read(m.size)
    assert sha256(data) == locks[name], f"{name} lock drift"
    return data


def table_at(exe: bytes, start: int, size: int) -> list[int]:
    """Increasing u32 offsets from `start`, ending with the archive size."""
    values, pos = [], start
    while True:
        value = struct.unpack_from("<I", exe, pos)[0]
        if values and (value <= values[-1] or value > size):
            break
        values.append(value)
        pos += 4
        if value == size:
            break
    if values[-1] != size:
        values.append(size)
    return values


def seg_table(seg: bytes, size: int) -> list[int]:
    values = [v for v in struct.unpack(f"<{len(seg) // 4}I", seg)]
    out = [0]
    for v in values[1:]:
        if v and v > out[-1]:
            out.append(v)
    if out[-1] != size:
        out.append(size)
    return out


def encode_into(stored: bytes, data: bytes, slot: int) -> bytes:
    """Re-encode a changed stream; the slower maximum strategy only when the fast one misses the slot."""
    original = decode_production(stored)
    encoded = reencode_changed_suffix(stored, data, strategy="rust-fit", original_result=original)
    if len(encoded) > slot:
        encoded = reencode_changed_suffix(stored, data, strategy="rust-maximum", original_result=original)
    return encoded


def blocks(changed: list[tuple[int, int]], gap: int = 64) -> list[tuple[int, int]]:
    """Merge change runs closer than `gap` bytes into blocks (a label bitmap changes in many runs)."""
    out = []
    for a, b in changed:
        if out and a - out[-1][1] < gap:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def runs(before: bytes, after: bytes) -> list[tuple[int, int]]:
    """Byte ranges where two equal-length buffers differ."""
    out, start = [], None
    for i, (a, b) in enumerate(zip(before, after)):
        if a != b and start is None:
            start = i
        elif a == b and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(before)))
    return out


# Texel rectangles the main game's Chinese heading cells overwrite, but which SP
# still needs as Latin. SP composes its own title bars ("CHALLENGE BATTLE",
# "STORY MODE", "MAP WEAPON") letter by letter out of the word `OTHERSCOMMAND`
# and the `FORMATION` row, so the atlas doubles as SP's Latin alphabet. Copying
# the main game's page wholesale erases letters nothing else supplies.
#
# Each entry is (KVMDATA chunk, u0, v0, u1, v1) in texels; 4bpp, two texels per
# stored byte, rows of 128 bytes.
SHARED_LETTER_RECTS = (
    (4, 44, 234, 90, 254),    # 指令 sits on the H and T of OTHERSCOMMAND
    (4, 156, 234, 202, 254),  # 项目 sits on its O, M and D
    (2, 160, 56, 198, 72),    # 阵型 sits on the M of FORMATION
    (4, 120, 98, 166, 118),   # 其他 sits on the OTHERS of the same bar
)


def restore_shared_letters(output: bytearray, source: bytes, table: list[int]) -> dict:
    """Put SP's own Latin letters back where a Chinese cell would bury them."""
    counts = {}
    for chunk, u0, v0, u1, v1 in SHARED_LETTER_RECTS:
        start = table[chunk]
        picture = parse_tim2(bytes(output[start:table[chunk + 1]])).pictures[0]
        base = start + picture.offset + picture.header_size
        row = picture.width // 2
        changed = 0
        for y in range(v0, v1):
            a = base + y * row + u0 // 2
            b = base + y * row + (u1 + 1) // 2
            if output[a:b] != source[a:b]:
                output[a:b] = source[a:b]
                changed += b - a
        counts[f"chunk{chunk}:{u0},{v0}"] = changed
    return counts


def main() -> None:
    inventory = json.loads(LOCKS.read_text())
    locks = {m["path"]: m["sha256"] for m in inventory["sp"]["members"]}
    og_locks = {m["path"]: m["sha256"] for m in inventory["original"]["members"]}
    members = member_map(scan_iso9660(ISO))
    sp_exe = read_member(members, locks, SD_EXE)
    og_exe = (ROOT / "work/disc" / OG_EXE).read_bytes()
    zh_exe = (OG_BUILD / OG_EXE).read_bytes()
    report, outputs = {}, {}

    for member, (og_spec, sp_spec, storage) in ARCHIVES.items():
        japanese = OG_JAPANESE[member].read_bytes()
        assert sha256(japanese) == og_locks[member], f"{member}: not the main game's Japanese member"
        chinese = (OG_BUILD / member).read_bytes()
        source = read_member(members, locks, member)
        if isinstance(og_spec, str):
            og_seg = (ROOT / "work/disc" / og_spec).read_bytes()
            assert sha256(og_seg) == og_locks[og_spec]
            jt = seg_table(og_seg, len(japanese))
            zt = seg_table(og_seg, len(chinese))
            st = seg_table(read_member(members, locks, sp_spec), len(source))
        else:
            if isinstance(og_spec, tuple):
                jt, zt = list(og_spec) + [len(japanese)], list(og_spec) + [len(chinese)]
            else:
                jt, zt = table_at(og_exe, og_spec, len(japanese)), table_at(zh_exe, og_spec, len(chinese))
            st = table_at(sp_exe, sp_spec, len(source))
        assert jt == zt, f"{member}: the main build moved chunks"

        def content(blob: bytes):
            """(content, is_stream): stream chunks decoded, anything the codec refuses taken raw."""
            if storage == "raw":
                return blob, False
            try:
                result = decode_production(blob)
            except Exception:  # noqa: BLE001 - not a codec stream (tables, raw records)
                return blob, False
            return result.output, True

        sp_chunks = [source[a:b] for a, b in zip(st, st[1:])]
        sp_content, sp_stream = {}, {}
        by_hash = collections.defaultdict(list)
        for k, blob in enumerate(sp_chunks):
            data, is_stream = content(blob)
            sp_content[k], sp_stream[k] = data, is_stream
            by_hash[sha256(data)].append(k)

        output = bytearray(source)
        counts, notes = collections.Counter(), []
        done = set()
        moved: dict[int, bytearray] = {}
        for i in range(len(jt) - 1):
            jp_blob, zh_blob = japanese[jt[i]:jt[i + 1]], chinese[zt[i]:zt[i + 1]]
            if jp_blob == zh_blob:
                continue
            jp_data, jp_stream = content(jp_blob)
            zh_data, zh_stream = content(zh_blob)
            if jp_data == zh_data or jp_stream != zh_stream:
                continue
            targets = [k for k in by_hash.get(sha256(jp_data), []) if k not in done]
            mode = "whole"
            if not targets and i in sp_content and len(sp_content[i]) == len(jp_data):
                targets, mode = [i], "bytes"
            if not targets:
                # the changed bytes may sit elsewhere in SP (world-map title bitmaps moved inside
                # their members): find each changed block, by its exact Japanese bytes, in one SP chunk
                placed = 0
                if len(jp_data) == len(zh_data):
                    for a, b in blocks(runs(jp_data, zh_data)):
                        needle = jp_data[a:b]
                        if len(needle) < 128:
                            continue
                        found = [(k, sp_content[k].find(needle)) for k in sp_content
                                 if k not in done and sp_content[k].find(needle) >= 0]
                        if len(found) != 1 or sp_content[found[0][0]].count(needle) != 1:
                            continue
                        k, at = found[0]
                        moved.setdefault(k, bytearray(sp_content[k]))[at:at + len(needle)] = zh_data[a:b]
                        placed += 1
                if placed:
                    counts["main-game chunks placed by search"] += 1
                else:
                    counts["main-game chunks with no SP counterpart"] += 1
                continue
            for k in targets:
                data = bytearray(sp_content[k])
                if mode == "whole":
                    data[:] = zh_data
                else:
                    changed = runs(jp_data, zh_data)
                    applied = [r for r in changed if bytes(data[r[0]:r[1]]) == jp_data[r[0]:r[1]]]
                    for a, b in applied:
                        data[a:b] = zh_data[a:b]
                    skipped = sum(b - a for a, b in changed) - sum(b - a for a, b in applied)
                    if skipped:
                        notes.append(dict(main_game_chunk=i, sp_chunk=k, runs=len(changed),
                                          runs_applied=len(applied), bytes_left=skipped))
                    if not applied:
                        counts["same-place chunks with no matching run"] += 1
                        continue
                slot = st[k + 1] - st[k]
                if not sp_stream[k]:
                    stored = bytes(data)
                else:
                    stored = (zh_blob[:decode_production(zh_blob).consumed]
                              if mode == "whole" else encode_into(sp_chunks[k], bytes(data), slot))
                    assert decode_production(stored).output == bytes(data), (member, k)
                if len(stored) > slot:
                    counts["does not fit its slot"] += 1
                    notes.append(dict(main_game_chunk=i, sp_chunk=k, needs=len(stored), slot=slot))
                    continue
                output[st[k]:st[k + 1]] = stored + bytes(slot - len(stored))
                counts[f"{mode}"] += 1
                done.add(k)
        for k, data in moved.items():
            slot = st[k + 1] - st[k]
            stored = bytes(data) if not sp_stream[k] else encode_into(sp_chunks[k], bytes(data), slot)
            if sp_stream[k]:
                assert decode_production(stored).output == bytes(data), (member, k)
            if len(stored) > slot:
                counts["searched chunk does not fit its slot"] += 1
                continue
            output[st[k]:st[k + 1]] = stored + bytes(slot - len(stored))
            counts["chunks rewritten by search"] += 1
        if member == "KURODATA/KVMDATA.BIN":
            restored = restore_shared_letters(output, source, st)
            if restored:
                report["letter_bank_restore"] = restored

        assert len(output) == len(source)
        if output != source:
            outputs[member] = bytes(output)
        report[member] = dict(sp_chunks=len(sp_chunks), main_game_chunks=len(jt) - 1, **counts,
                              partial=notes[:20])

    # KVPDATA heading layout: the main game's recorded draw patches
    headings = json.loads(HEADINGS.read_text(encoding="utf-8"))
    kvp = bytearray(read_member(members, locks, KVP))
    kvp_table = table_at(sp_exe, KVP_TABLE, len(kvp))

    def locate(patch) -> list[tuple[int, int]]:
        """(SP chunk, offset) of every exact copy of the patch's before bytes."""
        before = bytes.fromhex(patch["before_hex"])
        found, position = [], kvp.find(before)
        while position >= 0 and len(before) >= 16:
            chunk = max(i for i, t in enumerate(kvp_table[:-1]) if t <= position)
            found.append((chunk, position))
            position = kvp.find(before, position + 1)
        return found

    # SP moved the main game's drawing chunks as wholes (+3, +4 ...). A patch found once, at its
    # own offset inside the chunk, fixes where its main-game chunk went; the others follow it.
    chunk_of: dict[int, int] = {}
    for patch in headings["draw_patches"]:
        inside = patch["offset"] - patch["chunk_start"]
        hits = [(c, p) for c, p in locate(patch) if p - kvp_table[c] == inside]
        if len(hits) == 1:
            chunk_of.setdefault(patch["chunk_index"], hits[0][0])
    applied, missing, skipped_tokens = 0, [], collections.Counter()
    for patch in headings["draw_patches"]:
        if (patch.get("token") in SKIP_TOKENS
                or (patch["chunk_index"], patch.get("token")) in SKIP_CHUNK_TOKENS):
            skipped_tokens[patch["token"]] += 1
            continue
        inside = patch["offset"] - patch["chunk_start"]
        hits = [(c, p) for c, p in locate(patch) if p - kvp_table[c] == inside]
        if len(hits) > 1 and patch["chunk_index"] in chunk_of:
            hits = [(c, p) for c, p in hits if c == chunk_of[patch["chunk_index"]]]
        if len(hits) != 1:
            missing.append(dict(chunk=patch["chunk_index"], token=patch.get("token"), hits=len(hits)))
            continue
        before, after = bytes.fromhex(patch["before_hex"]), bytes.fromhex(patch["after_hex"])
        position = hits[0][1]
        kvp[position:position + len(before)] = after
        applied += 1

    # Sequence pass for the patches no byte match reaches.
    #
    # SP rebuilt these help/command screens, so their 34-byte records differ from
    # the main game's in geometry and colour even where they still draw the same
    # atlas cells in the same order. Byte matching therefore misses them, but the
    # run of source cells is unchanged: "DATA HELP" is still D-A-T-A-H-E-L-P.
    #
    # Match a patch run to an SP run by that cell sequence, then copy each
    # patch's whole result record. The destination quad has to come with the
    # source UV: the main game replaces a row of Latin letters with two wide
    # Chinese cells and zeroes the quads of the letters left over, so carrying
    # only the UV would stamp the same word at every old letter position.
    # Colour words are taken from the patch too, keeping each pass (shadow, main)
    # exactly as the main game tuned it.
    def cells_of(record: bytes) -> tuple[int, int, int]:
        f = struct.unpack("<17h", record)
        return f[2] & 0xF, f[15] & 0xFFFF, f[16] & 0xFFFF

    runs_by_chunk: dict[int, list[dict]] = collections.defaultdict(list)
    for patch in headings["draw_patches"]:
        runs_by_chunk[patch["chunk_index"]].append(patch)
    for chunk_index in runs_by_chunk:
        runs_by_chunk[chunk_index].sort(key=lambda p: p["offset"])

    retargeted, retarget_log = 0, collections.Counter()
    unresolved = {m["chunk"] for m in missing}
    for main_chunk, sp_first, sp_last in RETARGET_CHUNKS:
        if main_chunk not in unresolved:
            continue
        run = [p for p in runs_by_chunk[main_chunk]
               if p.get("token") not in SKIP_TOKENS
               and (p["chunk_index"], p.get("token")) not in SKIP_CHUNK_TOKENS]
        if not run:
            continue
        wanted = [cells_of(bytes.fromhex(p["before_hex"])) for p in run]
        window = len(run)
        limit = min(kvp_table[sp_last + 1], len(kvp)) - 34 * window
        for position in range(kvp_table[sp_first], limit + 1):
            # A record the byte pass already rewrote holds the patch result, so
            # accept either the Japanese cell or the Chinese one it becomes.
            got = [cells_of(kvp[position + 34 * i:position + 34 * i + 34]) for i in range(window)]
            if any(g != w and g != cells_of(bytes.fromhex(run[i]["after_hex"]))
                   for i, (g, w) in enumerate(zip(got, wanted))):
                continue
            for i, patch in enumerate(run):
                kvp[position + 34 * i:position + 34 * i + 34] = bytes.fromhex(patch["after_hex"])
            chunk = max(i for i, t in enumerate(kvp_table[:-1]) if t <= position)
            retarget_log[chunk] += window
            retargeted += window
            break

    if applied or retargeted:
        outputs[KVP] = bytes(kvp)
    report[KVP] = dict(patches=len(headings["draw_patches"]), applied=applied,
                       retargeted_by_cell=retargeted,
                       retargeted_chunks={str(k): v for k, v in sorted(retarget_log.items())},
                       skipped_shared_letter_tokens=dict(skipped_tokens),
                       chunk_moves={str(k): v for k, v in sorted(chunk_of.items())}, not_found=missing[:30])

    OUT.mkdir(parents=True, exist_ok=True)
    for member, data in outputs.items():
        (OUT / member).parent.mkdir(parents=True, exist_ok=True)
        (OUT / member).write_bytes(data)
    summary = dict(answer_key=dict(chinese=str(OG_BUILD.relative_to(ROOT)),
                                   japanese={m: str(p.relative_to(ROOT)) for m, p in OG_JAPANESE.items()}),
                   archives=report, files={m: sha256(d) for m, d in outputs.items()},
                   original_files={m: locks[m] for m in outputs})
    (OUT / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
