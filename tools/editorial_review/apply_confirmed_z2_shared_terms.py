#!/usr/bin/env python3
"""Apply the 2026-08-28 confirmed Z1/Z2 shared-work name decisions.

The broad replacements are restricted to JSON ``translation`` fields and to
the player guide.  Ambiguous terms are changed only at an explicit source ID,
glossary reference, display-name file, or guide heading.  In particular, the
ordinary battle action ``反击`` and the weapon/technology term ``飞行装甲`` are
not globally rewritten as the skills/unit ``先手反击`` and ``乘波者``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

UNAMBIGUOUS_TRANSLATION_REPLACEMENTS = (
    ("菲·辛露", "飞・心露"),
    ("菲·辛路", "飞・心露"),
    ("菲・辛路", "飞・心露"),
    ("菲·新路", "飞・心露"),
    ("菲伊", "飞"),
    ("继美·罗森迈尔", "鸫・罗森迈亚"),
    ("继美", "鸫"),
    ("泰战机", "泰坦战机"),
    ("泰坦克", "泰坦战车"),
    ("贝克·大帝RX3", "大贝克RX3"),
    ("元素系统", "元素协调系统"),
    ("阿萨基姆·多温", "阿萨基姆·杜文"),
)

EXACT_TRANSLATION_REPLACEMENTS = {
    "菲": "飞",
    "继美": "鸫",
}

EXPLICIT_ID_TRANSLATIONS = {
    "skill/counter": "先手反击",
    "skill/intuition": "看穿",
    "skill/mental-resistance": "精神耐性",
    "ability/element-system": "元素协调系统",
    "menu/SLPS/09/0006": "先手反击",
    "menu/SLPS/09/0050": "看穿",
    "menu/SLPS/09/0054": "精神耐性",
    "menu/Compdata/04/0012": "元素协调系统",
}

SOURCE_BOUND_REPLACEMENTS = {
    "people/speaker-cac236e00621": (("菲", "飞"),),
    "people/speaker-66a2dbb4f5b6": (("继美", "鸫"),),
    "unit/panther": (("豹式", "猎豹"),),
    "weapon/panther-shoot": (("豹式", "猎豹"),),
}

# These records do not carry a glossary reference, so the stable source IDs
# provide the same source-bound protection.  Do not make 豹式 a broad
# replacement: it is also a deprecated translation of unrelated Leopard units.
FEI_PERSON_SOURCE_IDS = (
    # Fei Shinlu's short name is one Han character, so it must never be
    # replaced globally.  These stable IDs are the complete source-bound set
    # whose Japanese source contains the standalone person name フェイ.
    "battle:07836",
    "battle:07843",
    "battle:07924",
    "battle:07926",
    "battle:15279",
    "battle:23492",
    "battle:23495",
    "battle:23694",
    "story/058/dialogue/02.02/0169",
    "story/060/dialogue/01.04/0002",
    "story/065/dialogue/01.04/0007",
    "story/065/dialogue/01.11/0010",
    "story/065/dialogue/01.12/0002",
    "story/065/dialogue/01.12/0003",
    "story/065/dialogue/01.19/0000",
    "story/066/dialogue/02.01/0101",
    "story/068/dialogue/01.05/0002",
    "story/068/dialogue/01.05/0009",
    "story/068/dialogue/01.12/0001",
    "story/072/dialogue/02.01/0136",
    "story/072/dialogue/02.01/0140",
    "story/104/dialogue/01.02/0005",
    "story/104/dialogue/01.37/0001",
    "story/107/dialogue/01.16/0028",
    "story/107/dialogue/01.17/0028",
    "story/108/dialogue/01.09/0003",
    "story/108/dialogue/01.10/0003",
    "story/108/dialogue/02.01/0046",
    "story/108/dialogue/02.01/0050",
    "story/108/dialogue/02.01/0059",
    "story/120/dialogue/01.13/0012",
    "story/131/dialogue/01.25/0012",
    "story/132/dialogue/01.12/0011",
    "story/133/dialogue/01.04/0009",
)

EXPLICIT_CONTENT_REPLACEMENTS = {
    **{entry_id: (("菲", "飞"),) for entry_id in FEI_PERSON_SOURCE_IDS},
    "battle:04003": (("豹式", "猎豹"),),
    "battle:07371": (("豹式", "猎豹"),),
    "battle:16340": (("豹式", "猎豹"),),
    "battle:16406": (("豹式", "猎豹"),),
    "library-text/08ea77b64e94bd0f": (("豹式", "猎豹"),),
    "library-text/7aed069672d6c4e2": (("豹式", "猎豹"),),
    "library-text/a6cf8c67a37e935a": (("豹式", "猎豹"),),
    "library-text/a8d941716efed0fc": (("豹式", "猎豹"),),
    "library-text/e505cd2c111d0413": (("豹式", "猎豹"),),
    "story/014/dialogue/01.10/0007": (("豹式", "猎豹"),),
    "story/015/dialogue/02.01/0052": (("豹式", "猎豹"),),
    "story/148/dialogue/02.01/0270": (("豹式", "猎豹"),),
}

DISPLAY_NAME_REPLACEMENTS = (
    ('"泰战机"', '"泰坦战机"'),
    ('"泰坦克"', '"泰坦战车"'),
    ('"飞行装甲"', '"乘波者"'),
    ('"贝克·大帝RX3"', '"大贝克RX3"'),
    ('"豹式"', '"猎豹"'),
)

EXPLICIT_FILE_REPLACEMENTS = {
    "corpus/zh/story-system-dialogue.json": (
        ('"speaker": "继美"', '"speaker": "鸫"'),
    ),
    "corpus/zh/menu/remaining-ui.json": (
        ('"0x6B5E0": "元素系统"', '"0x6B5E0": "元素协调系统"'),
        ('"0x74300": "元素系统"', '"0x74300": "元素协调系统"'),
    ),
}

GUIDE_EXACT_REPLACEMENTS = (
    ('"name": "反击"', '"name": "先手反击"'),
    ('"name": "识破"', '"name": "看穿"'),
    ('"name": "精神抗性"', '"name": "精神耐性"'),
    ("<h3>反击</h3>", "<h3>先手反击</h3>"),
    ("<h3>识破</h3>", "<h3>看穿</h3>"),
    ("<h3>精神抗性</h3>", "<h3>精神耐性</h3>"),
    ("<h3>元素系统</h3>", "<h3>元素协调系统</h3>"),
    ("王者盖纳与3台豹式加入。", "王者盖纳与3台猎豹加入。"),
    ("<strong>豹式（莎拉机）</strong>", "<strong>猎豹（莎拉机）</strong>"),
)

ID_RE = re.compile(r'"id"\s*:\s*("(?:\\.|[^"\\])*")')
FIELD_RE = re.compile(
    r'("(?P<field>translation|notes)"\s*:\s*)'
    r'(?P<value>"(?:\\.|[^"\\])*")'
)


def collect_bound_replacements(payload: object) -> dict[str, tuple[tuple[str, str], ...]]:
    result: dict[str, tuple[tuple[str, str], ...]] = {}

    def visit(node: object) -> None:
        if isinstance(node, dict):
            entry_id = node.get("id")
            refs = node.get("glossary_refs")
            if isinstance(entry_id, str) and isinstance(refs, list):
                replacements: list[tuple[str, str]] = []
                for ref in refs:
                    replacements.extend(SOURCE_BOUND_REPLACEMENTS.get(ref, ()))
                if replacements:
                    result[entry_id] = tuple(replacements)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload)
    return result


def replace_json_fields(path: Path) -> tuple[str, int]:
    original = path.read_text(encoding="utf-8")
    payload = json.loads(original)
    bound = collect_bound_replacements(payload)
    current_id: str | None = None
    changes = 0
    output: list[str] = []

    for line in original.splitlines(keepends=True):
        id_match = ID_RE.search(line)
        if id_match:
            current_id = json.loads(id_match.group(1))

        def update(match: re.Match[str]) -> str:
            nonlocal changes
            field = match.group("field")
            value = json.loads(match.group("value"))
            updated = value
            if field == "translation":
                for old, new in UNAMBIGUOUS_TRANSLATION_REPLACEMENTS:
                    updated = updated.replace(old, new)
                updated = EXACT_TRANSLATION_REPLACEMENTS.get(updated, updated)
                for old, new in bound.get(current_id or "", ()):
                    updated = updated.replace(old, new)
                for old, new in EXPLICIT_CONTENT_REPLACEMENTS.get(
                    current_id or "", ()
                ):
                    updated = updated.replace(old, new)
                if current_id in EXPLICIT_ID_TRANSLATIONS:
                    updated = EXPLICIT_ID_TRANSLATIONS[current_id]
            else:
                for old, new in UNAMBIGUOUS_TRANSLATION_REPLACEMENTS:
                    updated = updated.replace(old, new)
            if updated == value:
                return match.group(0)
            changes += 1
            return match.group(1) + json.dumps(updated, ensure_ascii=False)

        output.append(FIELD_RE.sub(update, line))
    return "".join(output), changes


def replace_explicit_context(path: Path, text: str) -> tuple[str, int]:
    relative = str(path.relative_to(PROJECT_ROOT))
    updated = text
    changes = 0
    if relative == "corpus/zh/display-names/units-full.json":
        for old, new in DISPLAY_NAME_REPLACEMENTS:
            count = updated.count(old)
            updated = updated.replace(old, new)
            changes += count
    for old, new in EXPLICIT_FILE_REPLACEMENTS.get(relative, ()):
        if old == new:
            continue
        count = updated.count(old)
        updated = updated.replace(old, new)
        changes += count
    # The Wave Rider display-name entry is source-bound by its stable library
    # hash.  Descriptions of the separate Flying Armor technology and weapon
    # deliberately remain unchanged.
    if relative == "corpus/zh/library/v0.2-reviewed.json":
        pattern = re.compile(
            r'("id": "library-text/6a8ef3620f3734b4",\n'
            r'\s+"source_text_sha256": "[^"]+",\n'
            r'\s+"translation": )"飞行装甲"'
        )
        updated, count = pattern.subn(r'\1"乘波者"', updated)
        changes += count
    return updated, changes


def replace_guide(path: Path) -> tuple[str, int]:
    original = path.read_text(encoding="utf-8")
    updated = original
    changes = 0
    for old, new in UNAMBIGUOUS_TRANSLATION_REPLACEMENTS:
        count = updated.count(old)
        updated = updated.replace(old, new)
        changes += count
    for old, new in GUIDE_EXACT_REPLACEMENTS:
        count = updated.count(old)
        updated = updated.replace(old, new)
        changes += count
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
            content = source.read_bytes()
            lock["size"] = len(content)
            lock["sha256"] = hashlib.sha256(content).hexdigest()
        serialized = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
        refreshed = pattern.sub(rf"\g<1>{serialized}\g<3>", updated, count=1)
        if refreshed != updated:
            changes += 1
            updated = refreshed
    return updated, changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    json_paths = sorted((PROJECT_ROOT / "corpus/zh").rglob("*.json"))
    guide_paths = sorted((PROJECT_ROOT / "guide/data").glob("*.json"))
    guide_paths.append(PROJECT_ROOT / "guide/srwz-z-flow-guide.html")
    changed: list[tuple[Path, int]] = []

    for path in json_paths:
        updated, field_changes = replace_json_fields(path)
        updated, explicit_changes = replace_explicit_context(path, updated)
        if updated != path.read_text(encoding="utf-8"):
            changed.append((path, field_changes + explicit_changes))
            if args.write:
                path.write_text(updated, encoding="utf-8")
    for path in guide_paths:
        updated, count = replace_guide(path)
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
