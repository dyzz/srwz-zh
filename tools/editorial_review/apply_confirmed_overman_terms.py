#!/usr/bin/env python3
"""Apply the 2026-08-28 confirmed Overman terminology decisions.

The broad replacements below are limited to JSON ``translation`` fields and
to the player guide.  Explicit keyed dictionaries used by the formation and
remaining-UI builders are handled separately.  Ambiguous Chinese words such as
``玩家``, ``过热`` and ``光子垫`` are handled only at explicitly identified
source IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

UNAMBIGUOUS_REPLACEMENTS = (
    ("贝洛·科利什", "贝罗·库利修"),
    ("贝洛·科里什", "贝罗·库利修"),
    ("休斯·高利", "修兹·高富利"),
    ("休兹·高利", "修兹·高富利"),
    ("亚蒂特·基斯勒", "阿蒂特·基斯拉"),
    ("辛西娅·雷恩", "辛西亚·琳"),
    ("辛西娅·莱恩", "辛西亚·琳"),
    ("该隐·比乔", "该隐·比琼"),
    ("莎拉·柯达玛", "莎拉·古塔玛"),
    ("安娜·梅黛尤", "安娜·梅戴尤"),
    ("超限战术", "超限技"),
    ("超限技能", "超限技"),
    ("超技能", "超限技"),
    ("超感知", "超限感应"),
    ("超感 ", "超限感应"),
    ("电锯枪", "锯刃枪"),
    ("超限攻击", "超限技攻击"),
    ("超限连击", "超限技连击"),
    ("贝洛", "贝罗"),
    ("高利", "高富利"),
    ("亚蒂特", "阿蒂特"),
    ("辛西娅", "辛西亚"),
)

EXPLICIT_TRANSLATIONS = {
    "menu/SLPS/09/0078": "游戏玩家",
    "menu/Compdata/02/0516": "锯刃枪（射击）",
    "menu/Compdata/02/0517": "锯刃枪（斩击）",
    "menu/Compdata/02/0518": "光子垫攻击",
    "menu/Compdata/02/0519": "超限技攻击",
    "menu/Compdata/02/0521": "超限灼热",
    "menu/Compdata/02/0544": "超限技连击",
    "battle:05149": "“该隐·比琼那家伙，\\n　煽动大逃亡！”",
    "battle:06040": "“超限灼热是！”",
    "battle:06043": "“爱与勇气是言语！\\n　明白这个就是超限灼热！！”",
    "battle:06048": "“呜哇啊啊啊！超限灼热！！”",
    "battle:06559": "“该隐·比琼，\\n　竟敢耍我！”",
}

EXPLICIT_FILE_REPLACEMENTS = {
    "corpus/zh/menu/stage-default-formations.json": (
        ('"シンシア": "辛西娅"', '"シンシア": "辛西亚"'),
        ('"アデット隊": "亚蒂特队"', '"アデット隊": "阿蒂特队"'),
        ('"ガウリ隊": "高利队"', '"ガウリ隊": "高富利队"'),
    ),
    "corpus/zh/menu/remaining-ui.json": (
        ('"0x6B6A0": "超限战术"', '"0x6B6A0": "超限技"'),
        ('"0x74298": "超限战术"', '"0x74298": "超限技"'),
        ("驾驶员超感知Lv3以上", "驾驶员超限感应Lv3以上"),
    ),
}


def replace_translation_fields(path: Path) -> tuple[str, int]:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    current_id: str | None = None
    changes = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('"id":'):
            try:
                current_id = json.loads("{" + stripped.rstrip(",") + "}")["id"]
            except json.JSONDecodeError:
                current_id = None
        if '"translation":' not in line:
            continue
        updated = line
        for old, new in UNAMBIGUOUS_REPLACEMENTS:
            updated = updated.replace(old, new)
        if current_id in EXPLICIT_TRANSLATIONS:
            prefix, _separator, tail = updated.partition('"translation":')
            comma = "," if tail.rstrip().endswith(",") else ""
            newline = "\n" if updated.endswith("\n") else ""
            updated = (
                f'{prefix}"translation": '
                f'{json.dumps(EXPLICIT_TRANSLATIONS[current_id], ensure_ascii=False)}'
                f"{comma}{newline}"
            )
        if updated != line:
            lines[index] = updated
            changes += 1
    return "".join(lines), changes


def replace_guide_text(path: Path) -> tuple[str, int]:
    original = path.read_text(encoding="utf-8")
    updated = original
    for old, new in UNAMBIGUOUS_REPLACEMENTS:
        updated = updated.replace(old, new)
    updated = updated.replace('"name": "玩家"', '"name": "游戏玩家"')
    updated = updated.replace("<h3>玩家</h3>", "<h3>游戏玩家</h3>")
    updated = updated.replace("解锁过热", "解锁超限灼热")
    if path.name == "srwz-z-flow-guide.html":
        pattern = re.compile(
            r'(<script type="application/json" id="guide-manifest">)(.*?)(</script>)'
        )
        match = pattern.search(updated)
        if match is None:
            raise ValueError("guide manifest is missing")
        manifest = json.loads(match.group(2))
        for relative, lock in manifest["inputs"].items():
            source = PROJECT_ROOT / relative
            if not source.is_file():
                continue
            payload = source.read_bytes()
            lock["size"] = len(payload)
            lock["sha256"] = hashlib.sha256(payload).hexdigest()
        serialized = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
        updated = pattern.sub(rf"\g<1>{serialized}\g<3>", updated, count=1)
    return updated, int(updated != original)


def replace_library_weapon_context(path: Path, text: str) -> tuple[str, int]:
    if path != PROJECT_ROOT / "corpus/zh/library/v0.2-reviewed.json":
        return text, 0
    updated = text.replace("战钢枪", "锯刃枪").replace("斩钢", "锯刃枪")
    updated = updated.replace("过热攻击", "超限灼热攻击")
    updated = updated.replace("“过热”", "“超限灼热”")
    updated = updated.replace("发动了过热", "发动了超限灼热")
    return updated, int(updated != text)


def replace_explicit_file_context(path: Path, text: str) -> tuple[str, int]:
    relative = str(path.relative_to(PROJECT_ROOT))
    updated = text
    replacements = EXPLICIT_FILE_REPLACEMENTS.get(relative, ())
    for old, new in replacements:
        updated = updated.replace(old, new)
    return updated, sum(text.count(old) for old, _new in replacements)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    json_paths = sorted((PROJECT_ROOT / "corpus/zh").rglob("*.json"))
    json_paths += sorted((PROJECT_ROOT / "config/library").glob("*.json"))
    guide_paths = sorted((PROJECT_ROOT / "guide/data").glob("*.json"))
    guide_paths.append(PROJECT_ROOT / "guide/srwz-z-flow-guide.html")

    changed: list[tuple[Path, int]] = []
    for path in json_paths:
        updated, line_changes = replace_translation_fields(path)
        updated, context_changes = replace_library_weapon_context(path, updated)
        updated, explicit_context_changes = replace_explicit_file_context(
            path, updated
        )
        if updated != path.read_text(encoding="utf-8"):
            changed.append(
                (
                    path,
                    line_changes + context_changes + explicit_context_changes,
                )
            )
            if args.write:
                path.write_text(updated, encoding="utf-8")
    for path in guide_paths:
        updated, count = replace_guide_text(path)
        if updated != path.read_text(encoding="utf-8"):
            changed.append((path, count))
            if args.write:
                path.write_text(updated, encoding="utf-8")

    for path, count in changed:
        print(f"{path.relative_to(PROJECT_ROOT)}\t{count}")
    print(f"changed_files={len(changed)} write={args.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
