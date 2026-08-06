#!/usr/bin/env python3
"""Apply user-confirmed terms to canonical story dialogue by Japanese source text.

The source-text guard is intentional: similar Chinese spellings such as
ガリア/ギャリア and エーデル/ジ・エーデル refer to different entities.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "work" / "review" / "local-model" / "story-dialogue-unique.jsonl"
DEFAULT_STORY_DIR = PROJECT_ROOT / "corpus" / "zh" / "story-dialogue"
DEFAULT_SPEAKERS = PROJECT_ROOT / "corpus" / "zh" / "story-speakers.json"

JI_EDEL_SHORT = "极·艾岱尔"
JI_EDEL_FULL = "极·艾岱尔·贝鲁那尔"

JI_EDEL_FULL_OLD = (
    "The·艾黛尔·贝尔纳尔",
    "吉·艾黛尔·贝尔纳尔",
    "吉·艾德尔·贝尔纳尔",
    "吉·埃德尔·贝尔纳尔",
    "吉·艾岱尔·贝尔纳尔",
    "艾黛尔·贝尔纳尔",
)
JI_EDEL_SHORT_OLD = (
    "The·艾黛尔",
    "吉·艾黛尔",
    "吉·艾德尔",
    "吉·埃德尔",
    "吉·艾岱尔",
    "艾黛尔",
)


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def replace_any(text: str, old_values: tuple[str, ...], new_value: str) -> str:
    for old_value in old_values:
        text = text.replace(old_value, new_value)
    return text


def transform_translation(source_text: str, translation: str) -> tuple[str, tuple[str, ...]]:
    """Return a source-aware terminology revision and the rules that matched."""
    result = translation
    matched = []

    if "ウォーカーマシン" in source_text:
        result = replace_any(
            result,
            ("Walker \n　Machine", "Walker Machine", "步行机器", "步行机甲", "步行机"),
            "WM",
        )
        matched.append("walker-machine")

    if "ギャリア" in source_text:
        full_name = "ウォーカー・ギャリア" in source_text or "ウォーカーギャリア" in source_text
        target = "沃克·伽利亚" if full_name else "伽利亚"
        result = replace_any(
            result,
            ("沃克·加里亚", "沃克·加利亚", "加里亚", "加利亚", "亚纪", "伽利亚"),
            target,
        )
        matched.append("gallia")

    if "エルゴ" in source_text:
        if "エルゴフォーム" in source_text or "エルゴ・フォ" in source_text or "エルゴフォ" in source_text:
            result = replace_any(
                result,
                (
                    "埃尔戈佛奥奥奥奥奥奥姆",
                    "Ergo Fooooooorm",
                    "Ergo形态",
                    "工学（Ergo）形态",
                ),
                "工学形态",
            )
            matched.append("ergo-form")
        elif "エルゴブレイク" in source_text:
            result = replace_any(result, ("Ergo Break", "工学（Ergo）分裂", "工学分裂"), "工学分解")
            matched.append("ergo-break")
        elif "エルゴ・エンド" in source_text or "エルゴ・エェェェンド" in source_text:
            result = replace_any(result, ("工学·终焉", "工学·终结", "Ergo终结", "Ergo End"), "工学终结")
            matched.append("ergo-end")
        elif "エルゴスト" in source_text:
            result = replace_any(result, ("终焉风暴", "Ergo Storm", "工学（Ergo）风暴"), "工学风暴")
            matched.append("ergo-storm")
        else:
            result = result.replace("艾尔戈的战士们", "工学战士们")
            result = replace_any(result, ("工学（Ergo）", "艾尔戈", "埃尔戈", "Ergo"), "工学")
            matched.append("ergo")

    if "ジ・エーデル" in source_text:
        full_name = "ジ・エーデル・ベルナル" in source_text
        target = JI_EDEL_FULL if full_name else JI_EDEL_SHORT
        result = replace_any(result, JI_EDEL_FULL_OLD, target)
        result = replace_any(result, JI_EDEL_SHORT_OLD, target)
        matched.append("ji-edel-full" if full_name else "ji-edel")

    if "ジ・エンド" in source_text:
        result = replace_any(
            result,
            ("尼尔瓦修 the END", "尼尔瓦修 the End", "尼尔瓦修The End", "尼尔瓦修THE END"),
            "尼尔瓦修终式",
        )
        matched.append("the-end")

    return result, tuple(matched)


def build_source_by_occurrence(source_path: Path) -> dict[str, str]:
    result = {}
    for row in load_jsonl(source_path):
        source_text = str(row["source_text"])
        for occurrence_id in row["occurrence_ids"]:
            occurrence_id = str(occurrence_id)
            if occurrence_id in result:
                raise ValueError(f"duplicate story occurrence ID: {occurrence_id}")
            result[occurrence_id] = source_text
    return result


def apply_story_terms(*, source_path: Path, story_dir: Path) -> dict[str, int]:
    source_by_id = build_source_by_occurrence(source_path)
    counts: Counter[str] = Counter()
    changed_files = 0
    for path in sorted(story_dir.glob("stage-*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for entry in document.get("entries", []):
            if not isinstance(entry, Mapping):
                continue
            source_text = source_by_id.get(str(entry.get("id", "")))
            translation = entry.get("translation")
            if source_text is None or not isinstance(translation, str):
                continue
            revised, matched = transform_translation(source_text, translation)
            if not matched:
                continue
            for rule_id in matched:
                required = {
                    "walker-machine": "WM",
                    "gallia": "伽利亚",
                    "ergo": "工学",
                    "ergo-form": "工学形态",
                    "ergo-break": "工学分解",
                    "ergo-end": "工学终结",
                    "ergo-storm": "工学风暴",
                    "ji-edel": JI_EDEL_SHORT,
                    "ji-edel-full": JI_EDEL_FULL,
                    "the-end": "尼尔瓦修终式",
                }[rule_id]
                if required not in revised:
                    raise ValueError(
                        f"could not apply {rule_id} to {entry.get('id')}: {translation!r}"
                    )
            if revised == translation:
                continue
            entry["translation"] = revised
            note = str(entry.get("notes", "")).strip()
            marker = "用户确认术语定稿。"
            if marker not in note:
                entry["notes"] = f"{note} {marker}".strip()
            counts.update(matched)
            changed = True
        if changed:
            write_json(path, document)
            changed_files += 1
    counts["changed-files"] = changed_files
    return dict(counts)


def apply_speaker_name(*, path: Path) -> int:
    document = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for entry in document.get("entries", []):
        if entry.get("translation") == "吉·艾黛尔":
            entry["translation"] = JI_EDEL_SHORT
            count += 1
    if count:
        write_json(path, document)
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--story-dir", type=Path, default=DEFAULT_STORY_DIR)
    parser.add_argument("--speakers", type=Path, default=DEFAULT_SPEAKERS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    counts = apply_story_terms(source_path=args.source, story_dir=args.story_dir)
    counts["speaker-names"] = apply_speaker_name(path=args.speakers)
    print(json.dumps(counts, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
