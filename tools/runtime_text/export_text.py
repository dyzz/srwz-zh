#!/usr/bin/env python3
"""Export the editable runtime-text folder for the special ARMSX2 build.

Everything the emulator reads is plain UTF-8 text that players can edit:

  settings.txt            game identity and font settings
  story/stage-NNN.txt     dialogue in script order (scenes, sections, triggers)
  battle/<作品>/<人物>.txt  SRVC battle lines (shared ones in battle/_共用台词.txt)
  names.txt               protagonist default names and battle pilot names
  charmap.txt             character -> game code (the emulator appends to it)

The Chinese text is the released localization, decoded from the release
build's own STAGE/SRVC/COMPDATA bytes, so the emulator reproduces the release
layout exactly.  Every record is round-tripped through the same encoding rules
the emulator uses before anything is written.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_pack as bp  # noqa: E402

from srwz.font import glyph_index_for_code, read_extended_glyph_table  # noqa: E402
from srwz.stage import parse_stage, read_stage_function_addresses  # noqa: E402
from srwz.text import decode_text, load_text_table  # noqa: E402

PROJECT_ROOT = bp.PROJECT_ROOT
SITE_ROOT = PROJECT_ROOT.parent / "srwz-community-web/public/data"
TAG_NAMES = {0x31: "color", 0x32: "width", 0x33: "height", 0x34: "space"}
TAG_CODES = {name: code for code, name in TAG_NAMES.items()}
SPACE_CODE = 0x8140
FONT_SOURCE = PROJECT_ROOT / "work/font-source/harmonyos-sans-sc-1.0/HarmonyOS_Sans_SC_Regular.ttf"
FONT_NAME = "HarmonyOS_Sans_SC_Regular.ttf"
# HarmonyOS Sans SC is bundled unmodified with its license, as its agreement
# allows (with a prominent notice, never as a stand-alone download).
FONT_LICENSE = FONT_SOURCE.parent / "LICENSE.txt"
FONT_LICENSE_NAME = "HarmonyOS_Sans_LICENSE.txt"
TOKEN = re.compile(r"<(color|width|height|space|[0-9A-F]{2}):([0-9A-F]{2})>|\{([0-9A-F]{2})\}|\$[A-Za-z]")


def fullwidth_ascii_code(character: str) -> int | None:
    """Shift-JIS code of the stock full-width glyph for an ASCII alphanumeric."""
    if "0" <= character <= "9":
        return 0x824F + ord(character) - ord("0")
    if "A" <= character <= "Z":
        return 0x8260 + ord(character) - ord("A")
    if "a" <= character <= "z":
        return 0x8281 + ord(character) - ord("a")
    return None


def encode(text: str, charmap: dict[str, int], *, battle: bool = False) -> bytes:
    """Reference encoder; the emulator implements exactly these rules."""
    out = bytearray()
    i = 0
    while i < len(text):
        match = TOKEN.match(text, i)
        if match:
            if match.group(1):
                name = match.group(1)
                out += bytes([TAG_CODES.get(name) or int(name, 16), int(match.group(2), 16)])
            elif match.group(3):
                out.append(int(match.group(3), 16))
            else:
                out += match.group(0).encode("ascii")
            i = match.end()
            continue
        character = text[i]
        i += 1
        if character == "\n":
            out += b"\\n" if battle else b"\n"
        elif character in charmap:
            out += struct.pack(">H", charmap[character])
        elif fullwidth_ascii_code(character) is not None:
            out += struct.pack(">H", fullwidth_ascii_code(character))
        elif character == " ":
            out += struct.pack(">H", SPACE_CODE)
        elif 0x21 <= ord(character) <= 0x7E:
            out.append(ord(character))
        else:
            raise ValueError(f"character not in charmap: {character!r}")
    return bytes(out)


def decode(raw: bytes, table) -> str:
    text = decode_text(raw + b"\0", 0, table).text
    # Literal "\n" markers in SRVC lines become real line breaks in the file.
    return text.replace("\\n", "\n")


def text_block(text: str) -> list[str]:
    # A blank line ends a record, so an intentionally empty line is "\".
    return [line if line else "\\" for line in text.split("\n")]


def comment_block(text: str) -> list[str]:
    return ["; " + line for line in text.split("\n")]


def safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_") or "_"


BATTLE_HEADER = [
    "# 格式：@日文校验 日文字节数 / 中文（可多行，换行即游戏内换行）/ ; 日文原文参考 / 空行分隔。",
    "# 同一句日文全游戏只有一种译文：只属于一个人物的台词在该人物文件里，多人共用的在 _共用台词.txt。",
]


def export_battle(out: Path, iso: Path, rel: Path, table, zh_table, learn, pending) -> int:
    """battle/<作品>/<人物>.txt for lines one character owns, battle/_共用台词.txt
    for lines several characters share; lines keep SRVC (chunk, record) order."""
    pairs = bp.battle_line_pairs(iso, rel, table, zh_table)
    words = lambda data: tuple(struct.unpack(f"<{len(data) // 4}I", data))  # noqa: E731
    jp_bin = bp.iso_member(iso, "BTL/SRVC.BIN")
    order: dict[bytes, int] = {}
    for chunk in bp.parse_srvc_archive(jp_bin, words(bp.iso_member(iso, "BTL/SRVC.SEG")), table):
        for record in chunk.records:
            key = jp_bin[record.archive_text_start:record.archive_text_end].rstrip(b"\0")
            order.setdefault(key, len(order))

    persons: dict[str, tuple[str, str, str]] = {}
    owners: dict[str, list[str]] = {}
    for path in sorted((SITE_ROOT / "catalog").glob("work-*.json")):
        catalog = json.loads(path.read_text())
        for person in catalog["people"]:
            persons[person["id"]] = (catalog["work"]["title"], person["translation"], person["sourceText"])
        for line in catalog["battleLines"]:
            owners.setdefault(line["sourceText"].replace("\\n", "\n"), line["personIds"])

    files: dict[Path, list[tuple[int, list[str]]]] = {}
    for jp, zh in pairs.items():
        learn(zh)
        text = decode(zh, zh_table)
        jp_text = decode(jp, table)
        pending.append((text, zh, True))
        block = ["", f"@{bp.fnv1a32(jp):08x} {len(jp)}", *text_block(text), *comment_block(jp_text)]
        people = owners.get(jp_text, [])
        if len(people) == 1 and people[0] in persons:
            work, name, source = persons[people[0]]
            path = out / "battle" / safe_name(work) / f"{safe_name(name)}.txt"
            files.setdefault(path, [(-1, [f"# {name}（{source}） · {work}", *BATTLE_HEADER])])
        else:
            path = out / "battle" / "_共用台词.txt"
            files.setdefault(path, [(-1, ["# 多个人物共用的战斗台词", *BATTLE_HEADER])])
            names = [persons[p][1] for p in people if p in persons]
            if names:
                block.append("; 使用者：" + "、".join(names[:12]) + (f" 等 {len(names)} 人" if len(names) > 12 else ""))
        files[path].append((order.get(jp, 1 << 30), block))
    for path, blocks in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [line for _, block in sorted(blocks, key=lambda item: item[0]) for line in block]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(pairs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", default="rom/original.iso")
    parser.add_argument("--release-root", default="work/build/zh-release-full-story/components")
    parser.add_argument("--out", default="work/build/runtime-text/SLPS-25887")
    parser.add_argument("--without-font", action="store_true", help="do not bundle the HarmonyOS font")
    args = parser.parse_args()

    iso = PROJECT_ROOT / args.iso
    rel = PROJECT_ROOT / args.release_root
    out = PROJECT_ROOT / args.out
    table = load_text_table(PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json")
    assignments = json.loads((PROJECT_ROOT / "config/encoding/zh-release-font-assignments.json").read_text())
    zh_table = bp.release_table(table, assignments)

    jp_slps = bp.iso_member(iso, "SLPS_258.87")
    zh_slps = (rel / "SLPS_258.87").read_bytes()
    jp_chunks = bp.stage_chunks(jp_slps, bp.iso_member(iso, "HEDBDY/HB.BIN"), bp.iso_member(iso, "DATA/STAGE.BIN"))
    zh_chunks = bp.stage_chunks(zh_slps, (rel / "HEDBDY/HB.BIN").read_bytes(), (rel / "DATA/STAGE.BIN").read_bytes())
    jp_font = bp.decode_vt1_font_segment(jp_slps, bp.iso_member(iso, "DATA/VT1.BIN")).decoded
    zh_font = bp.decode_vt1_font_segment(zh_slps, (rel / "DATA/VT1.BIN").read_bytes()).decoded
    jp_ext = read_extended_glyph_table(jp_slps)
    zh_ext = read_extended_glyph_table(zh_slps)
    jp_functions = read_stage_function_addresses(jp_slps)
    zh_functions = read_stage_function_addresses(zh_slps)
    private = bp.PrivateCodes({entry.code for entry in jp_ext})

    def glyph(font, ext, code):
        index = glyph_index_for_code(code, ext)
        return font[index * 288:(index + 1) * 288]

    # Character -> game code, chosen exactly as the pack transcoder did so
    # existing savestates keep their meaning.
    charmap: dict[str, int] = {}

    def learn(raw: bytes) -> None:
        for kind, chunk in bp.tokens(raw):
            if kind != "code":
                continue
            code = struct.unpack(">H", chunk)[0]
            character = zh_table.characters.get(code)
            if character is None or character in charmap:
                continue
            if code == SPACE_CODE or any(lo <= code <= hi for lo, hi in bp.NATIVE_RANGES):
                charmap[character] = code
                continue
            bitmap = glyph(zh_font, zh_ext, code)
            try:
                same = glyph(jp_font, jp_ext, code) == bitmap
            except ValueError:
                same = False
            charmap[character] = code if same else private.code_for(
                glyph_index_for_code(code, zh_ext), bitmap, character)

    site_titles = {}
    site_files = {}
    site_index = json.loads((SITE_ROOT / "site-index.json").read_text())
    entries = []
    for section in site_index["routeSections"]:
        for row in section["rows"]:
            for stage in row["stages"]:
                for resource in stage["resources"]:
                    site_titles[resource["stageIndex"]] = (
                        f"第{row['episode']}话「{stage['title']}」（{stage['sourceTitle']}） · {stage['lane']}")
                    lane = stage["lane"].split("（")[0]
                    entries.append((resource["stageIndex"], row["episode"], lane, stage["title"],
                                    resource["resourceName"].removesuffix(".bin")))
    # File name: 第NN话_路线_标题.txt; a second file for the same episode and
    # route gets the STAGE resource name appended.
    seen = {}
    for index, episode, lane, title, resource in entries:
        seen.setdefault((episode, lane), []).append(index)
    for index, episode, lane, title, resource in entries:
        name = f"第{episode:02d}话_{lane}_{title}"
        if len(seen[(episode, lane)]) > 1:
            name += f"_{resource}"
        site_files[index] = safe_name(name)

    if out.exists():
        shutil.rmtree(out)
    (out / "story").mkdir(parents=True)
    pending: list[tuple[str, bytes, bool]] = []  # (text, expected bytes, battle) round-trip checks
    stage_files = 0
    shared_variants = 0
    story_records = 0
    for index, jp_data in enumerate(jp_chunks):
        zh_data = zh_chunks[index]
        jp_parsed = parse_stage(jp_data, table, stage_index=index, function_address=jp_functions[index])
        if not jp_parsed.dialogue_count:
            continue
        zh_parsed = parse_stage(zh_data, zh_table, stage_index=index, function_address=zh_functions[index])
        zh_offsets = {e.entry_id: e.text_offset for e in zh_parsed.entries if e.kind == "dialogue"}
        name = jp_data[bp.STAGE_NAME_OFFSET:bp.STAGE_NAME_OFFSET + 0x20].split(b"\0", 1)[0].decode("ascii")
        by_offset: dict[int, dict] = {}
        offset_of_id: dict[str, int] = {}
        for entry in jp_parsed.entries:
            if entry.kind != "dialogue" or entry.entry_id not in zh_offsets:
                continue
            offset_of_id[entry.entry_id] = entry.text_offset
            record = by_offset.setdefault(entry.text_offset, {
                "ids": [],
                "jp": bp.raw_string(jp_data, entry.text_offset),
                "variants": {},
            })
            record["ids"].append(entry.entry_id)
            record["variants"][entry.entry_id] = bp.raw_string(zh_data, zh_offsets[entry.entry_id])

        site_path = SITE_ROOT / f"stages/stage-{index:03d}.json"
        order: list[tuple[str, str, list[str]]] = []  # (scene, section label, ids)
        if site_path.exists():
            site = json.loads(site_path.read_text())
            ids_by_section: dict[str, list] = {}
            for dialogue in site["dialogues"]:
                ids_by_section.setdefault(dialogue["section"], []).append(dialogue)
            scene_names = {"visual-novel": "剧情场景", "battlefield": "战场"}
            for scene in site["sceneSequence"]:
                for section in scene["sections"]:
                    trigger = site["sectionTriggers"].get(section, {}).get("label", "")
                    label = section.replace("Section ", "段 ") + (f" · {trigger}" if trigger else "")
                    ids = [d["id"] for d in sorted(ids_by_section.get(section, []), key=lambda d: d["ordinal"])]
                    order.append((scene_names.get(scene["kind"], scene["kind"]), label, ids))
        listed = {i for _, _, ids in order for i in ids}
        rest = [e.entry_id for e in jp_parsed.entries if e.kind == "dialogue" and e.entry_id in offset_of_id
                and e.entry_id not in listed]
        if rest:
            order.append(("未排序", "脚本分析未覆盖的对白", rest))

        lines = [
            f"# {site_titles.get(index, '')}".rstrip(" #"),
            f"# STAGE {index:03d} · {name}",
            "# 格式：@偏移 日文校验 / 说话人 / 中文（可多行）/ ; 开头为日文原文参考 / 空行分隔。",
            "# 只改说话人和中文；@ 行、; 行和标题行由工具生成。空的一行请写成 \\。",
        ]
        written: set[int] = set()
        current_scene = None
        for scene, label, ids in order:
            block: list[str] = []
            for entry_id in ids:
                offset = offset_of_id.get(entry_id)
                if offset is None or offset in written:
                    continue
                written.add(offset)
                record = by_offset[offset]
                # The stock disc points every use of a shared source at one
                # string, so the first use in script order wins.
                record["zh"] = record["variants"][entry_id]
                others = [(other, raw) for other, raw in record["variants"].items() if raw != record["zh"]]
                learn(record["zh"])
                if b"\n" in record["zh"]:
                    speaker_raw, _, body_raw = record["zh"].partition(b"\n")
                    speaker, body = decode(speaker_raw, zh_table), decode(body_raw, zh_table)
                    pending.append((speaker + "\n" + body, record["zh"], False))
                else:
                    # No speaker line at all (captions such as place names): "-".
                    speaker, body = "-", decode(record["zh"], zh_table)
                    pending.append((body, record["zh"], False))
                jp_text = decode(record["jp"], table)
                block += ["", f"@{offset:05X} {bp.fnv1a32(record['jp']):08x}", speaker, *text_block(body),
                          *comment_block(jp_text)]
                for other, raw in others:
                    shared_variants += 1
                    variant = decode(raw, zh_table).replace("\n", " / ")
                    block.append(f"; [共用原文] {other.split('/', 3)[-1]} 在发布版中译为：{variant}")
                story_records += 1
            if not block:
                continue
            if scene != current_scene:
                lines += ["", f"== {scene} =="]
                current_scene = scene
            lines += ["", f"--- {label} ---", *block]
        missing = set(by_offset) - written
        if missing:
            raise SystemExit(f"stage {index}: {len(missing)} records not written")
        file_name = site_files.get(index) or (f"附_教学_{name.removesuffix('.bin')}" if name.startswith("stg_5")
                                             else f"附_特殊段_{name.removesuffix('.bin')}")
        (out / f"story/{file_name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        stage_files += 1

    battle_count = export_battle(out, iso, rel, table, zh_table, learn, pending)

    def decode_release(raw: bytes) -> str:
        return decode(raw, zh_table)

    name_lines = ["# 名字。格式：日文 = 中文。玩家改过的名字不受影响。", "", "[主角默认名]"]
    for jp, zh in bp.release_default_names(jp_slps, zh_slps, decode_release):
        learn(zh)
        name_lines.append(f"{decode(jp, table)} = {decode(zh, zh_table)}")
        pending.append((decode(zh, zh_table), zh, False))
    name_lines += ["", "[驾驶员名]"]
    for jp, zh in bp.pilot_name_pairs(rel, zh_table).items():
        learn(zh)
        name_lines.append(f"{decode(jp, table)} = {decode(zh, zh_table)}")
        pending.append((decode(zh, zh_table), zh, False))
    (out / "names.txt").write_text("\n".join(name_lines) + "\n", encoding="utf-8")

    # Round trip: the text written above must re-encode to the release bytes
    # (modulo the code each character is assigned).
    transcode = {}
    for character, code in charmap.items():
        transcode[character] = code
    mismatches = 0
    for text, release_raw, battle in pending:
        expected = bytearray()
        for kind, chunk in bp.tokens(release_raw):
            if kind == "code":
                character = zh_table.characters.get(struct.unpack(">H", chunk)[0])
                expected += struct.pack(">H", charmap[character]) if character in charmap else chunk
            else:
                expected += chunk
        if encode(text, charmap, battle=battle) != bytes(expected):
            mismatches += 1
            if mismatches <= 5:
                print("round-trip mismatch:", repr(text[:40]), bytes(expected).hex()[:60],
                      encode(text, charmap, battle=battle).hex()[:60])
    if mismatches:
        raise SystemExit(f"{mismatches} records do not round-trip")

    charmap_lines = ["# 字码表：字符 TAB 游戏编码。模拟器遇到新字符会自动追加；已有行请勿修改。"]
    charmap_lines += [f"{c}\t{code:04X}" for c, code in sorted(charmap.items(), key=lambda item: item[1])]
    (out / "charmap.txt").write_text("\n".join(charmap_lines) + "\n", encoding="utf-8")

    (out / "settings.txt").write_text("\n".join([
        "# 改版 ARMSX2 运行时中文设置",
        "serial = SLPS-25887",
        "stage_base = 0x7566F0",
        "stage_name_offset = 0x30",
        f"font = {FONT_NAME}",
        "font_size = 22",
        "font_y_offset = 0",
        "",
    ]), encoding="utf-8")
    (out / "README.txt").write_text("""改版 ARMSX2 运行时中文文本（超级机器人大战Z 原版日文盘 SLPS-25887）

本目录下的文件都可以用文本编辑器直接修改（UTF-8）。游戏运行中保存后，约 2 秒自动生效；
已经显示在画面上的句子要等下次出现时才会更新。

story/stage-NNN.txt  每话剧情，按游戏里的出现顺序分段（== 场景 ==、--- 段 · 触发条件 ---）。
    每句格式：
      @偏移 日文校验      ← 定位用，不要改
      说话人              ← "-" 表示这句没有说话人（如地点标题）
      中文第一行          ← 可多行，换行就是游戏里的换行；空的一行写成 \
      ; 日文原文          ← 以 ; 开头的行只是参考，模拟器忽略
    句与句之间空一行。$n、$F 等是主角名记号，会自动展开。
    "; [共用原文]" 表示原版里多处共用同一句，只能用一种译文。

battle/      战斗台词：battle/<作品>/<人物>.txt 是该人物独有的台词，battle/_共用台词.txt 是多人共用的台词。
             每句：@日文校验 字节数 / 中文 / ; 日文。同一句日文全游戏只有一种译文。
names.txt    [主角默认名] 和 [驾驶员名]：日文 = 中文。玩家自己改过的名字不受影响。
charmap.txt  字符与游戏编码的对应表。模拟器遇到新字会自动追加，请不要改已有的行。
settings.txt 字体等设置。默认字体是随附的 HarmonyOS Sans SC Regular（和发布版汉化补丁同一款）。
             换成自己的字体：把 TTF/OTF 放进本目录，font = 后写该文件名；font_size（默认 22）、
             font_y_offset（默认 0）可微调字号和上下位置。字体里没有的字会改用游戏自带字库的字形，
             游戏字库也没有的字显示为空白。

字体声明：本软件使用 HarmonyOS Sans 字体（HarmonyOS Sans Fonts）。
Copyright 2021 Huawei Device Co., Ltd. 按 HarmonyOS Sans Fonts License Agreement 授权，
随附未经修改的字体文件，协议全文见 HarmonyOS_Sans_LICENSE.txt。

控制标记：<color:XX> <width:XX> <height:XX> <space:XX> 与游戏原有标记相同。
""", encoding="utf-8")
    if not args.without_font:
        shutil.copy2(FONT_SOURCE, out / FONT_NAME)
        shutil.copy2(FONT_LICENSE, out / FONT_LICENSE_NAME)

    print(f"stages={stage_files} story_records={story_records} shared_variants={shared_variants} battle={battle_count} "
          f"charmap={len(charmap)} private={len(private.by_index)} out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
