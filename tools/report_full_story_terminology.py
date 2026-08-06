#!/usr/bin/env python3
"""Build full-story Chinese character counts and terminology usage reports."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work/review"
QUEUE = WORK / "local-model/story-dialogue-unique.jsonl"
STAGE10 = WORK / "story-dialogue-stage-010-reviewed-unique-draft.json"
FIVE = WORK / "local-model/aliyun/five-stage-011-015/validated.jsonl"
REMAINING = (
    WORK / "local-model/aliyun/remaining-stages/finalized/validated.jsonl"
)
FIVE_TERMS = (
    WORK / "local-model/aliyun/five-stage-011-015/terminology-review.jsonl"
)
REMAINING_TERMS = (
    WORK / "local-model/aliyun/remaining-stages/finalized/semantic-review.jsonl"
)
SUBTITLE_BASELINE = WORK / "subtitle-sources/subtitle-terminology-baseline.json"
OUTPUT = WORK / "full-story-terminology"
ASCII_WORD = re.compile(r"[A-Za-z]{3,}")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    temporary.replace(path)


def is_han(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2FA1F
    )


def han_count(text: str) -> int:
    return sum(is_han(character) for character in text)


def compact(value: object) -> str:
    return str(value).replace("\r", "").replace("\n", " / ").replace("\t", " ")


def refs_from_existing(row: Mapping[str, object]) -> tuple[list[str], list[str]]:
    selected = str(row.get("existing_translation", ""))
    for candidate in row.get("existing_translations", []):
        if not isinstance(candidate, Mapping):
            continue
        if str(candidate.get("translation", "")) != selected:
            continue
        return (
            [str(item) for item in candidate.get("glossary_refs", [])],
            [str(item) for item in candidate.get("glossary_exceptions", [])],
        )
    return [], []


def load_translations(
    queue: list[dict[str, object]],
) -> dict[tuple[int, int], dict[str, object]]:
    translations: dict[tuple[int, int], dict[str, object]] = {}
    queue_by_key = {
        (int(row["stage_index"]), int(row["unique_index"])): row for row in queue
    }

    for key, row in queue_by_key.items():
        if row.get("review_state") != "locked_reviewed":
            continue
        refs, exceptions = refs_from_existing(row)
        translations[key] = {
            "translation": str(row["existing_translation"]),
            "glossary_refs": refs,
            "glossary_exceptions": exceptions,
            "layer": "committed_reviewed",
        }

    stage10 = json.loads(STAGE10.read_text(encoding="utf-8"))
    stage10_translations = stage10["translations"]
    stage10_refs = stage10.get("glossary_refs_by_index", {})
    stage10_exceptions = stage10.get("glossary_exceptions_by_index", {})
    stage10_hashes = stage10.get("machine_audit", {}).get("source_hashes", [])
    stage10_rows = sorted(
        (row for row in queue if int(row["stage_index"]) == 10),
        key=lambda row: int(row["unique_index"]),
    )
    if len(stage10_rows) != len(stage10_translations):
        raise ValueError("stage 010 queue/draft coverage mismatch")
    for row in stage10_rows:
        index = int(row["unique_index"])
        if index >= len(stage10_translations):
            raise ValueError(f"stage 010 unique index out of range: {index}")
        if stage10_hashes and str(row["source_text_sha256"]) != str(stage10_hashes[index]):
            raise ValueError(f"stage 010 source hash mismatch: {index}")
        translations[(10, index)] = {
            "translation": str(stage10_translations[index]),
            "glossary_refs": [str(item) for item in stage10_refs.get(str(index), [])],
            "glossary_exceptions": [
                str(item) for item in stage10_exceptions.get(str(index), [])
            ],
            "layer": "stage_010_reviewed_draft",
        }

    for path, layer in (
        (FIVE, "aliyun_011_015_validated_draft"),
        (REMAINING, "aliyun_remaining_validated_draft"),
    ):
        for candidate in read_jsonl(path):
            key = int(candidate["stage_index"]), int(candidate["unique_index"])
            if key in translations:
                raise ValueError(f"translation layers overlap at {key}")
            source = queue_by_key.get(key)
            if source is None:
                raise ValueError(f"translated row is absent from queue: {key}")
            candidate_hash = candidate.get("source_text_sha256")
            if candidate_hash and str(candidate_hash) != str(source["source_text_sha256"]):
                raise ValueError(f"source hash mismatch at {key}")
            translations[key] = {
                "translation": str(candidate["translation"]),
                "glossary_refs": [
                    str(item) for item in candidate.get("glossary_refs", [])
                ],
                "glossary_exceptions": [
                    str(item) for item in candidate.get("glossary_exceptions", [])
                ],
                "layer": layer,
            }

    if set(translations) != set(queue_by_key):
        missing = sorted(set(queue_by_key) - set(translations))
        extra = sorted(set(translations) - set(queue_by_key))
        raise ValueError(
            f"full translation coverage mismatch: missing={missing[:12]} extra={extra[:12]}"
        )
    return translations


def write_tsv(path: Path, fieldnames: list[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: compact(value) if isinstance(value, str) else value
                    for field, value in row.items()
                }
            )
    temporary.replace(path)


def main() -> int:
    queue = read_jsonl(QUEUE)
    queue.sort(key=lambda row: (int(row["stage_index"]), int(row["unique_index"])))
    translations = load_translations(queue)

    layer_counts: dict[str, Counter[str]] = defaultdict(Counter)
    distinct_han: set[str] = set()
    index_rows: list[dict[str, object]] = []
    unique_han_count = 0
    expanded_han_count = 0
    unique_non_whitespace = 0
    expanded_non_whitespace = 0
    expanded_entry_count = 0
    stage_set: set[int] = set()

    term_usage: dict[str, dict[str, object]] = {}
    glossary_matched_rows = 0
    glossary_expanded_rows = 0
    glossary_term_row_pairs = 0
    glossary_term_expanded_pairs = 0

    for source in queue:
        stage = int(source["stage_index"])
        unique_index = int(source["unique_index"])
        key = stage, unique_index
        selected = translations[key]
        translation = str(selected["translation"])
        occurrence_count = int(source["occurrence_count"])
        row_han = han_count(translation)
        row_non_whitespace = len(re.sub(r"\s", "", translation))
        layer = str(selected["layer"])
        refs = set(str(item) for item in selected["glossary_refs"])
        exceptions = set(str(item) for item in selected["glossary_exceptions"])

        stage_set.add(stage)
        expanded_entry_count += occurrence_count
        unique_han_count += row_han
        expanded_han_count += row_han * occurrence_count
        unique_non_whitespace += row_non_whitespace
        expanded_non_whitespace += row_non_whitespace * occurrence_count
        distinct_han.update(character for character in translation if is_han(character))
        layer_counts[layer]["unique_rows"] += 1
        layer_counts[layer]["expanded_entries"] += occurrence_count
        layer_counts[layer]["unique_han_characters"] += row_han
        layer_counts[layer]["expanded_han_characters"] += row_han * occurrence_count

        index_rows.append(
            {
                "stage_index": stage,
                "unique_index": unique_index,
                "source_text_sha256": source["source_text_sha256"],
                "occurrence_count": occurrence_count,
                "translation_layer": layer,
                "han_character_count": row_han,
                "translation": translation,
            }
        )

        terms = [term for term in source.get("glossary_terms", []) if isinstance(term, Mapping)]
        if terms:
            glossary_matched_rows += 1
            glossary_expanded_rows += occurrence_count
        for term in terms:
            term_id = str(term["id"])
            canonical = str(term.get("translation", ""))
            usage = term_usage.setdefault(
                term_id,
                {
                    "term_id": term_id,
                    "categories": set(),
                    "statuses": set(),
                    "source_terms": set(),
                    "canonical_translations": set(),
                    "domains": set(),
                    "notes": set(),
                    "enforce_values": set(),
                    "matched_unique_rows": 0,
                    "matched_expanded_occurrences": 0,
                    "referenced_unique_rows": 0,
                    "exception_unique_rows": 0,
                    "canonical_present_unique_rows": 0,
                    "canonical_missing_unique_rows": 0,
                    "canonical_missing_examples": [],
                },
            )
            usage["categories"].add(str(term.get("category", "")))
            usage["statuses"].add(str(term.get("status", "")))
            usage["source_terms"].update(str(item) for item in term.get("source_terms", []))
            if canonical:
                usage["canonical_translations"].add(canonical)
            usage["domains"].update(str(item) for item in term.get("domains", []))
            if term.get("notes"):
                usage["notes"].add(str(term["notes"]))
            usage["enforce_values"].add(bool(term.get("enforce")))
            usage["matched_unique_rows"] += 1
            usage["matched_expanded_occurrences"] += occurrence_count
            usage["referenced_unique_rows"] += int(term_id in refs)
            usage["exception_unique_rows"] += int(term_id in exceptions)
            canonical_present = bool(canonical and canonical in translation)
            usage["canonical_present_unique_rows"] += int(canonical_present)
            if bool(term.get("enforce")) and not canonical_present and term_id not in exceptions:
                usage["canonical_missing_unique_rows"] += 1
                examples = usage["canonical_missing_examples"]
                if len(examples) < 3:
                    examples.append(f"{stage:03d}:{unique_index} {compact(translation)}")
            glossary_term_row_pairs += 1
            glossary_term_expanded_pairs += occurrence_count

    glossary_rows: list[dict[str, object]] = []
    category_counts: Counter[str] = Counter()
    for term_id, usage in sorted(term_usage.items()):
        categories = sorted(item for item in usage["categories"] if item)
        for category in categories:
            category_counts[category] += 1
        glossary_rows.append(
            {
                "term_id": term_id,
                "category": " | ".join(categories),
                "status": " | ".join(sorted(item for item in usage["statuses"] if item)),
                "source_terms": " | ".join(sorted(usage["source_terms"])),
                "canonical_translation": " | ".join(
                    sorted(usage["canonical_translations"])
                ),
                "enforce": " | ".join(
                    "true" if item else "false" for item in sorted(usage["enforce_values"])
                ),
                "domains": " | ".join(sorted(usage["domains"])),
                "matched_unique_rows": usage["matched_unique_rows"],
                "matched_expanded_occurrences": usage["matched_expanded_occurrences"],
                "referenced_unique_rows": usage["referenced_unique_rows"],
                "exception_unique_rows": usage["exception_unique_rows"],
                "canonical_present_unique_rows": usage["canonical_present_unique_rows"],
                "canonical_missing_unique_rows": usage["canonical_missing_unique_rows"],
                "canonical_missing_examples": " || ".join(
                    usage["canonical_missing_examples"]
                ),
                "notes": compact(" | ".join(sorted(usage["notes"]))),
            }
        )

    queue_by_stage: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in queue:
        queue_by_stage[int(row["stage_index"])].append(row)
    position_by_key: dict[tuple[int, int], tuple[str | None, str | None]] = {}
    for stage, rows in queue_by_stage.items():
        rows.sort(key=lambda row: int(row["unique_index"]))
        for position, row in enumerate(rows):
            before = str(rows[position - 1]["source_text"]) if position else None
            after = str(rows[position + 1]["source_text"]) if position + 1 < len(rows) else None
            position_by_key[(stage, int(row["unique_index"]))] = before, after

    pending_rows: list[dict[str, object]] = []
    pending_groups: Counter[str] = Counter()
    pending_group_details: dict[str, dict[str, object]] = {}
    queue_by_key = {
        (int(row["stage_index"]), int(row["unique_index"])): row for row in queue
    }
    for path, provenance in (
        (FIVE_TERMS, "aliyun_011_015_terminology_review"),
        (REMAINING_TERMS, "aliyun_remaining_semantic_review"),
    ):
        for raw in read_jsonl(path):
            stage = int(raw["stage_index"])
            unique_index = int(raw["unique_index"])
            if "introduced_ascii_terms" in raw:
                terms = sorted(set(str(item) for item in raw["introduced_ascii_terms"]))
            else:
                terms = sorted(
                    {
                        word
                        for reason in raw.get("reasons", [])
                        if str(reason).startswith("introduced_ascii:")
                        for word in str(reason).split(":", 1)[1].split(",")
                        if word
                    },
                    key=str.casefold,
                )
            if not terms:
                continue
            group = " + ".join(terms)
            pending_groups[group] += 1
            group_detail = pending_group_details.setdefault(
                group,
                {
                    "ascii_terms": group,
                    "unique_row_count": 0,
                    "expanded_occurrence_count": 0,
                    "stages": set(),
                    "provenance": set(),
                    "examples": [],
                },
            )
            group_detail["unique_row_count"] += 1
            group_detail["expanded_occurrence_count"] += int(
                queue_by_key[(stage, unique_index)]["occurrence_count"]
            )
            group_detail["stages"].add(stage)
            group_detail["provenance"].add(provenance)
            examples = group_detail["examples"]
            if len(examples) < 3:
                examples.append(
                    f"{stage:03d}:{unique_index} {compact(raw['source_text'])} => "
                    f"{compact(raw['translation'])}"
                )
            before, after = position_by_key[(stage, unique_index)]
            pending_rows.append(
                {
                    "stage_index": stage,
                    "unique_index": unique_index,
                    "ascii_terms": ", ".join(terms),
                    "source_text": compact(raw["source_text"]),
                    "current_translation": compact(raw["translation"]),
                    "context_before_source": compact(before or ""),
                    "context_after_source": compact(after or ""),
                    "provenance": provenance,
                    "disposition": "final_terminology_review",
                }
            )
    pending_rows.sort(key=lambda row: (int(row["stage_index"]), int(row["unique_index"])))

    write_jsonl(OUTPUT / "full-text-index.jsonl", index_rows)
    glossary_fields = [
        "term_id",
        "category",
        "status",
        "source_terms",
        "canonical_translation",
        "enforce",
        "domains",
        "matched_unique_rows",
        "matched_expanded_occurrences",
        "referenced_unique_rows",
        "exception_unique_rows",
        "canonical_present_unique_rows",
        "canonical_missing_unique_rows",
        "canonical_missing_examples",
        "notes",
    ]
    write_tsv(OUTPUT / "glossary-usage.tsv", glossary_fields, glossary_rows)
    canonical_missing_rows = [
        row for row in glossary_rows if int(row["canonical_missing_unique_rows"]) > 0
    ]
    write_tsv(
        OUTPUT / "canonical-missing.tsv",
        glossary_fields,
        canonical_missing_rows,
    )
    pending_fields = [
        "stage_index",
        "unique_index",
        "ascii_terms",
        "source_text",
        "current_translation",
        "context_before_source",
        "context_after_source",
        "provenance",
        "disposition",
    ]
    write_tsv(OUTPUT / "pending-surface-forms.tsv", pending_fields, pending_rows)
    pending_group_rows = [
        {
            "ascii_terms": group,
            "unique_row_count": detail["unique_row_count"],
            "expanded_occurrence_count": detail["expanded_occurrence_count"],
            "stage_count": len(detail["stages"]),
            "stages": ",".join(str(stage) for stage in sorted(detail["stages"])),
            "provenance": " | ".join(sorted(detail["provenance"])),
            "examples": " || ".join(detail["examples"]),
        }
        for group, detail in pending_group_details.items()
    ]
    pending_group_rows.sort(
        key=lambda row: (-int(row["unique_row_count"]), str(row["ascii_terms"]).casefold())
    )
    write_tsv(
        OUTPUT / "pending-surface-groups.tsv",
        [
            "ascii_terms",
            "unique_row_count",
            "expanded_occurrence_count",
            "stage_count",
            "stages",
            "provenance",
            "examples",
        ],
        pending_group_rows,
    )

    subtitle_summary: dict[str, object] | None = None
    if SUBTITLE_BASELINE.is_file():
        subtitle = json.loads(SUBTITLE_BASELINE.read_text(encoding="utf-8"))
        subtitle_summary = dict(subtitle.get("summary", {}))
        subtitle_summary["path"] = str(SUBTITLE_BASELINE.relative_to(ROOT))

    missing_canonical_terms = sum(
        int(row["canonical_missing_unique_rows"]) > 0 for row in glossary_rows
    )
    missing_canonical_rows = sum(
        int(row["canonical_missing_unique_rows"]) for row in glossary_rows
    )
    summary = {
        "schema_version": 1,
        "kind": "srwz_full_story_terminology_and_character_inventory",
        "scope": {
            "stage_count": len(stage_set),
            "stages": sorted(stage_set),
            "unique_text_row_count": len(queue),
            "expanded_entry_count": expanded_entry_count,
            "coverage_complete": len(index_rows) == len(queue),
        },
        "translation_layers": {
            layer: dict(counts) for layer, counts in sorted(layer_counts.items())
        },
        "chinese_character_counts": {
            "definition": "CJK Han ideographs only; punctuation, Latin letters, digits, whitespace, and control tokens are excluded.",
            "deduplicated_translation_han_occurrences": unique_han_count,
            "expanded_in_game_han_occurrences": expanded_han_count,
            "distinct_han_characters": len(distinct_han),
            "deduplicated_non_whitespace_characters_all_scripts": unique_non_whitespace,
            "expanded_non_whitespace_characters_all_scripts": expanded_non_whitespace,
        },
        "terminology": {
            "used_structured_glossary_term_count": len(glossary_rows),
            "category_term_counts": dict(sorted(category_counts.items())),
            "rows_with_structured_glossary_matches": glossary_matched_rows,
            "expanded_entries_with_structured_glossary_matches": glossary_expanded_rows,
            "glossary_term_row_pairs": glossary_term_row_pairs,
            "glossary_term_expanded_pairs": glossary_term_expanded_pairs,
            "terms_with_unexcepted_canonical_missing_rows": missing_canonical_terms,
            "unexcepted_canonical_missing_row_count": missing_canonical_rows,
            "pending_surface_form_row_count": len(pending_rows),
            "pending_surface_form_group_count": len(pending_groups),
            "subtitle_baseline": subtitle_summary,
        },
        "artifacts": {
            "full_text_index": str((OUTPUT / "full-text-index.jsonl").relative_to(ROOT)),
            "glossary_usage": str((OUTPUT / "glossary-usage.tsv").relative_to(ROOT)),
            "canonical_missing": str(
                (OUTPUT / "canonical-missing.tsv").relative_to(ROOT)
            ),
            "pending_surface_forms": str(
                (OUTPUT / "pending-surface-forms.tsv").relative_to(ROOT)
            ),
            "pending_surface_groups": str(
                (OUTPUT / "pending-surface-groups.tsv").relative_to(ROOT)
            ),
        },
        "promotion": {
            "allowed": False,
            "reason": "terminology consolidation and human editorial review are pending",
        },
    }
    write_json(OUTPUT / "summary.json", summary)

    readme = f"""# SRWZ 全文术语与中文字数清单

本目录以当前 154 个故事文本段的 69,167 条去重文本为范围。译文按优先级取自已审定正文、第 010 段审稿草稿、第 011–015 段验证草稿及其余段验证草稿；四层必须无重叠且完整覆盖。

## 字数口径

- 去重译文汉字出现次数：{unique_han_count:,}
- 按游戏内 {expanded_entry_count:,} 条文本展开后的汉字出现次数：{expanded_han_count:,}
- 实际使用的不同汉字：{len(distinct_han):,}

这里只统计 CJK 汉字，不包含标点、拉丁字母、数字、空白和控制符。`summary.json` 同时保留所有文字系统的非空白字符数。

## 术语文件

- `glossary-usage.tsv`：全文实际命中的结构化术语、分类、规范译名、去重/展开频次与例外。
- `canonical-missing.tsv`：规范译名尚未落到当前译文且没有登记例外的高优先级条目。
- `pending-surface-forms.tsv`：模型输出中仍需统一的英文专名/口号写法，带完整原文、当前译文和前后文。
- `pending-surface-groups.tsv`：将上述表面写法按检出词合并后的 147 组定稿入口。
- `full-text-index.jsonl`：每条去重文本所采用的译文层、出现次数及汉字数，用于复算。

术语尚未写回正式语料；最终选择完成并复验前，不允许晋升。
"""
    (OUTPUT / "README.md").write_text(readme, encoding="utf-8")
    print(
        f"stages={len(stage_set)} unique_rows={len(queue)} expanded={expanded_entry_count} "
        f"han_unique={unique_han_count} han_expanded={expanded_han_count} "
        f"glossary_terms={len(glossary_rows)} pending_rows={len(pending_rows)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
