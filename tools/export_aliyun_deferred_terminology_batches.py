#!/usr/bin/env python3
"""Export unresolved ASCII terminology/style rows for final human consolidation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "work/review/local-model/aliyun/remaining-stages"
FINALIZED = RUN_ROOT / "finalized"
QUEUE = ROOT / "work/review/local-model/story-dialogue-unique.jsonl"
RANGES = (
    (76, 85),
    (86, 95),
    (96, 105),
    (106, 115),
    (116, 125),
    (126, 135),
    (136, 145),
    (146, 153),
    (185, 186),
)


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


def compact(text: object) -> str:
    return str(text).replace("\r", "").replace("\n", " / ").replace("|", "\\|")


def ascii_words(reasons: object) -> list[str]:
    words: list[str] = []
    if not isinstance(reasons, list):
        return words
    for reason in reasons:
        text = str(reason)
        if not text.startswith("introduced_ascii:"):
            continue
        words.extend(word for word in text.split(":", 1)[1].split(",") if word)
    return sorted(set(words), key=str.casefold)


def main() -> int:
    risks = read_jsonl(FINALIZED / "semantic-review.jsonl")
    queue = read_jsonl(QUEUE)
    queue_by_stage: dict[int, list[dict[str, object]]] = {}
    for row in queue:
        queue_by_stage.setdefault(int(row["stage_index"]), []).append(row)
    for rows in queue_by_stage.values():
        rows.sort(key=lambda row: int(row["unique_index"]))

    context_by_key: dict[tuple[int, int], tuple[str | None, str | None]] = {}
    for stage, rows in queue_by_stage.items():
        for position, row in enumerate(rows):
            before = str(rows[position - 1]["source_text"]) if position else None
            after = str(rows[position + 1]["source_text"]) if position + 1 < len(rows) else None
            context_by_key[(stage, int(row["unique_index"]))] = (before, after)

    batch_report = json.loads((RUN_ROOT / "report.json").read_text(encoding="utf-8"))
    available_stages = {
        int(row["stage_index"])
        for row in batch_report.get("stages", [])
        if isinstance(row, dict) and "stage_index" in row
    }

    exported = 0
    for first, last in RANGES:
        selected = [
            row for row in risks if first <= int(row["stage_index"]) <= last
        ]
        enriched: list[dict[str, object]] = []
        for row in selected:
            key = int(row["stage_index"]), int(row["unique_index"])
            before, after = context_by_key[key]
            words = ascii_words(row.get("reasons"))
            if not words:
                raise ValueError(f"non-terminology risk remains in deferred batch: {key}")
            enriched.append(
                {
                    "stage_index": key[0],
                    "unique_index": key[1],
                    "ascii_words": words,
                    "source_text": row["source_text"],
                    "translation": row["translation"],
                    "context_before_source": before,
                    "context_after_source": after,
                    "disposition": "defer_to_final_terminology_consolidation",
                }
            )

        batch_name = f"stage-{first:03d}-{last:03d}"
        output = RUN_ROOT / "editorial-batches" / batch_name
        write_jsonl(output / "deferred-terminology.jsonl", enriched)

        lines = [
            f"# 第 {first:03d}–{last:03d} 段延后术语审核",
            "",
            "本表只收录当前机器稿中的英文专名、口号或风格写法。文本结构校验已通过；这些行不在本批改写，留待全文完成后统一定稿术语。",
            "",
            "| 段:行 | 检出英文 | 日文原文 | 当前译文 | 前文（日文） | 后文（日文） |",
            "|---|---|---|---|---|---|",
        ]
        for row in enriched:
            lines.append(
                "| {stage:03d}:{index} | `{words}` | {source} | {translation} | {before} | {after} |".format(
                    stage=int(row["stage_index"]),
                    index=int(row["unique_index"]),
                    words=", ".join(row["ascii_words"]),
                    source=compact(row["source_text"]),
                    translation=compact(row["translation"]),
                    before=compact(row["context_before_source"] or "—"),
                    after=compact(row["context_after_source"] or "—"),
                )
            )
        (output / "deferred-terminology.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

        included_stages = sorted(
            stage for stage in available_stages if first <= stage <= last
        )
        write_json(
            output / "report.json",
            {
                "schema_version": 1,
                "kind": "aliyun_story_dialogue_editorial_batch",
                "status": "text_cleanup_complete_terminology_deferred",
                "stage_range": [first, last],
                "included_stages": included_stages,
                "strict_failure_count": 0,
                "deferred_terminology_row_count": len(enriched),
                "deferred_terminology": str(
                    (output / "deferred-terminology.jsonl").relative_to(ROOT)
                ),
                "human_readable_review": str(
                    (output / "deferred-terminology.md").relative_to(ROOT)
                ),
                "promotion": {
                    "allowed": False,
                    "reason": "final terminology consolidation and full editorial review are pending",
                },
            },
        )
        exported += len(enriched)

    if exported != len(risks):
        raise ValueError(
            f"deferred batch coverage mismatch: exported={exported} risks={len(risks)}"
        )
    print(f"batches={len(RANGES)} deferred_terminology_rows={exported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
