"""Where and when each new SD battle line is spoken: owner, event slot, opponent/ally/stage conditions.

The SD SRVC archive has the main game's selector layout (only the chunk magic is 0x4F01), so the
review site's selector decoder (srwz-community-web/scripts/export_srvc_special_conditions.py, reverse-
engineered from SLPS_258.87 on 2026-09-14) is reused as is; only its lookup tables are rebuilt from
the SD disc: pilot names and SRVC chunks from BTL/SIPI.BIN + COMPDATA pilot records, unit names from
BTL/SIRB.BIN + COMPDATA unit records, Chinese names from the migrated preview COMPDATA.

Output: battle-lines.json - one row per new unique line, every occurrence with its trigger analysis,
the other lines of the same candidate/slot (with the main game's Chinese) and the speaker's other lines.
"""
from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

from common import HERE, ROOT, load_json

sys.path.insert(0, str(ROOT / "tools/special_disc/writeback"))
import srwz.srvc as srvc  # noqa: E402
from srwz.codec import decode_production  # noqa: E402
from srwz.image_export import parse_seg_offsets  # noqa: E402
from srwz.iso9660 import member_map, scan_iso9660  # noqa: E402
from srwz.text import SrwzTextError, decode_text, load_text_table  # noqa: E402
import migrate_compdata as mc  # noqa: E402
import migrate_slps_text as mst  # noqa: E402

EXPORTER = ROOT.parent / "srwz-community-web/scripts/export_srvc_special_conditions.py"
spec = importlib.util.spec_from_file_location("srvc_conditions", EXPORTER)
sc = importlib.util.module_from_spec(spec)
sys.modules["srvc_conditions"] = sc
spec.loader.exec_module(sc)

PREVIEW_COMPDATA = ROOT / "work/build/special-disc/components/system-text/DATA/COMPDATA.BN"
PILOTS = (0x2B50, 178, 969)
UNITS = (0x54B94, 68, 854)
STAGE_TITLES = ROOT / "work/review/special-disc/text-export/out"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def name_at(data: bytes, offset: int, table) -> str:
    try:
        return decode_text(data, offset, table).text
    except SrwzTextError:
        return ""


def stage_names() -> dict[int, str]:
    """SD STAGE chunk index -> 'stg_xxx 话名' from the export's episode files."""
    out = {}
    for folder in ("01-剧情模式", "02-挑战模式"):
        for path in sorted((STAGE_TITLES / folder).glob("*.json")):
            doc = load_json(path)
            for chunk in doc.get("info", {}).get("chunks", []) or [doc.get("info", {}).get("chunk", "")]:
                if chunk:
                    index, name = chunk.split(" ", 1)
                    out[int(index)] = f"{name}（{doc['title']}）"
    return out


def main() -> None:
    locks = {m["path"]: m["sha256"] for m in json.loads(mc.LOCKS.read_text())["sp"]["members"]}
    members = member_map(scan_iso9660(mc.ISO))
    read = lambda name: mc.read_member(members, locks, name)  # noqa: E731
    table, _menu, _story, readback = mst.encoding_tables()
    archive, seg = read("BTL/SRVC.BIN"), read("BTL/SRVC.SEG")
    sipi, sirb = read("BTL/SIPI.BIN"), read("BTL/SIRB.BIN")
    cd = decode_production(read("DATA/COMPDATA.BN")).output
    cd_zh = decode_production(PREVIEW_COMPDATA.read_bytes()).output

    # pilots: SIPI row i <-> COMPDATA pilot record i
    start, stride, count = PILOTS
    pilot_rows, owners = {}, collections.defaultdict(dict)
    for i in range(1, count):
        a = start + stride * i
        raw = cd[a + 2:a + 23].split(b"\0")[0]
        raw_zh = cd_zh[a + 2:a + 23].split(b"\0")[0]
        jp = decode_text(raw + b"\0", 0, table).text if raw else ""
        zh = decode_text(raw_zh + b"\0", 0, readback).text if raw_zh else ""
        fields = struct.unpack_from("<8H", sipi, i * 16)
        pilot_rows[i] = ({"sourceText": jp, "translation": zh}, fields)
        if fields[2] != 0xFFFF:
            owner = owners[fields[2]].setdefault((jp, zh), {"sourceText": jp, "translation": zh, "pilotRecordIndices": []})
            owner["pilotRecordIndices"].append(i)
    owners_by_chunk = {c: sorted(v.values(), key=lambda o: o["pilotRecordIndices"]) for c, v in owners.items()}

    # units: SIRB row i <-> COMPDATA unit record i
    start, stride, count = UNITS
    units_by_resource, unit_rows = collections.defaultdict(list), []
    for i in range(len(sirb) // 12):
        pointer = struct.unpack_from("<I", cd, start + stride * i)[0] - mc.SD_BASE
        pointer_zh = struct.unpack_from("<I", cd_zh, start + stride * i)[0] - mc.SD_BASE
        unit = sc.UnitName(entry_id=f"sd-unit/{i:03d}", source_text=name_at(cd, pointer, table),
                           translation=name_at(cd_zh, pointer_zh, readback))
        fields = struct.unpack_from("<6H", sirb, i * 12)
        units_by_resource[fields[1]].append(unit)
        unit_rows.append((unit, fields))
    tags = sc.TagTables(pilot_rows, unit_rows)
    slots = {s["index"]: s for s in sc.event_slot_catalog()}
    stages = stage_names()

    corpus = load_json(ROOT / "corpus/zh/battle/srvc-lines.json")
    main_zh = {e["source_text_sha256"]: e["translation"] for e in corpus["entries"] if e.get("translation")}

    srvc.SRVC_MAGIC = 0x4F01
    offsets = parse_seg_offsets(seg, len(archive))
    chunks = srvc.parse_srvc_archive(archive, offsets, table)

    def describe(p: dict) -> str:
        role = {"current": "自身", "opponent": "对手", "ally": "友军／援护对象", "partner": "对方主机"}.get(
            p.get("runtimeParticipantRole", ""), "")
        neg = "不是" if p.get("polarity") == "exclude" else ""
        if "stageProgress" in p:
            sp = p["stageProgress"]
            name = stages.get(sp["stageNumber"], f"关卡编号{sp['stageNumber']}")
            rel = {"equal": "仅在", "not-equal": "不在", "before": "早于", "after": "晚于",
                   "at-least": "不早于", "at-most": "不晚于"}.get(sp["relation"], sp["relation"])
            return f"关卡条件：{rel} {name}"
        if "personGroupCrossReference" in p:
            ref = p["personGroupCrossReference"]
            people = "／".join(f"{x['sourceText']}（{x['translation'] or '未译'}）" for x in ref["people"]) or f"语音组{ref['groupId']}"
            role = {0: "自身", 1: "对手", 2: "友军／援护对象", 3: "对方主机"}.get(p["rawByte2"], role)
            return f"{role}{neg}是：{people}"
        if "unitResourceCrossReference" in p:
            ref = p["unitResourceCrossReference"]
            units = "／".join(sorted({f"{u['sourceText']}（{u['translation'] or '未译'}）" for u in ref["units"]})) or f"机体资源{ref['resourceId']}"
            role = {0: "自身", 1: "对手", 2: "友军／援护对象", 3: "对方主机"}.get(p["rawByte2"], role)
            return f"{role}机体{neg}是：{units}"
        if "participantTag" in p:
            tag = p["participantTag"]
            examples = "、".join(f"{m['sourceText']}（{m['translation']}）" for m in tag["memberExamples"][:5])
            scope = tag.get("seriesName") or "（按标签）"
            return f"{role}{neg}属于标签组 {scope}#{tag['bit']}（{tag['memberCount']} 名，如 {examples}）"
        if "stateCondition" in p:
            return f"{role}状态条件：{p['stateCondition']['category']} 位{p['stateCondition']['bit']}{'（否定）' if neg else ''}"
        return f"未解读条件 {p['rawHex']}"

    lines = collections.OrderedDict()
    for chunk, a, b in zip(chunks, offsets, offsets[1:]):
        data = archive[a:b]
        _magic, packed, candidate_count, text_count = struct.unpack_from("<4H", data)
        new_records = [i for i, r in enumerate(chunk.records) if sha(r.text) not in main_zh]
        if not new_records:
            continue
        predicate_count, quick_count = packed & 0xFF, packed >> 8
        cat_start = 8
        cand_start = cat_start + sc.CATEGORY_COUNT * sc.CATEGORY_SIZE
        pred_start = cand_start + candidate_count * sc.CANDIDATE_SIZE
        quick_start = pred_start + predicate_count * sc.PREDICATE_SIZE
        slot_of = {}
        for slot in range(sc.CATEGORY_COUNT):
            s, n, flag = struct.unpack_from("<HBB", data, cat_start + slot * sc.CATEGORY_SIZE)
            for c in range(s, s + n):
                slot_of[c] = (slot, flag)
        owner = owners_by_chunk.get(chunk.chunk_index, [])
        speaker = "／".join(sorted({o["sourceText"] for o in owner})) or f"语音组{chunk.chunk_index}"
        speaker_zh = "／".join(sorted({o["translation"] for o in owner if o["translation"]}))
        known_lines = [dict(jp=r.text, zh=main_zh[sha(r.text)]) for r in chunk.records if sha(r.text) in main_zh]
        for c in range(candidate_count):
            sel_start, sel_count, weight, mode, text_start, text_n, _b7 = struct.unpack_from(
                "<BBBBHBB", data, cand_start + c * sc.CANDIDATE_SIZE)
            records = range(text_start, text_start + text_n)
            if not any(r in new_records for r in records):
                continue
            slot, flag = slot_of.get(c, (None, 0))
            conditions = []
            if mode == 0:
                for k in range(sel_start, sel_start + sel_count):
                    raw = data[pred_start + k * sc.PREDICATE_SIZE: pred_start + (k + 1) * sc.PREDICATE_SIZE]
                    p = sc.predicate_mapping(raw, units_by_resource, owners_by_chunk, tags)
                    conditions.append(describe(p))
            else:
                for k in range(sel_start, sel_start + sel_count):
                    v0, v1 = struct.unpack_from("<HH", data, quick_start + k * 4)
                    conditions.append(f"剧情脚本指定：{stages.get(v0, f'关卡编号{v0}')} 的第{v1}号事件战斗")
            slot_info = slots.get(slot, {})
            siblings = [dict(jp=chunk.records[r].text, zh=main_zh.get(sha(chunk.records[r].text), ""))
                        for r in records if r not in new_records]
            for r in records:
                if r not in new_records:
                    continue
                text = chunk.records[r].text
                row = lines.setdefault(text, dict(id=f"sd-battle:{len(lines):03d}", jp=text, sha256=sha(text),
                                                  occurrences=[]))
                row["occurrences"].append(dict(
                    chunk=chunk.chunk_index, record=r, speaker=speaker, speaker_zh=speaker_zh,
                    slot=slot, scene=slot_info.get("name", f"槽{slot}"), role=slot_info.get("roleLabel", ""),
                    weight=weight, conditions=conditions,
                    same_candidate=siblings[:6],
                ))
                row.setdefault("speaker_other_lines", {})[speaker] = known_lines[:8]
    out = list(lines.values())
    (HERE / "battle-lines.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    occ = sum(len(r["occurrences"]) for r in out)
    cond = sum(1 for r in out if any(o["conditions"] for o in r["occurrences"]))
    print(f"{len(out)} new lines, {occ} occurrences, {cond} with conditions")
    print(collections.Counter(o["scene"] for r in out for o in r["occurrences"]).most_common(12))


if __name__ == "__main__":
    main()
