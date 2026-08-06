#!/usr/bin/env python3
"""Merge the Stage 011-015 Aliyun review runs into validated draft artifacts.

DeepSeek supplies the complete first pass.  Three objective glossary failures
are replaced by independently validator-clean Qwen singleton retries.  Known
substring/compound glossary false positives are recorded as explicit draft
exceptions.  Nothing produced here is promoted into ``corpus/``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Mapping, Sequence

try:
    from import_story_dialogue_local_model_batch import (
        build_stage_drafts,
        load_queue,
        validate_model_output,
    )
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.import_story_dialogue_local_model_batch import (
        build_stage_drafts,
        load_queue,
        validate_model_output,
    )

try:
    from srwz.translation_review import TranslationReviewError
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.srwz.translation_review import TranslationReviewError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
QUEUE = WORK_ROOT / "review" / "local-model" / "story-dialogue-unique.jsonl"
OUTPUT_ROOT = (
    WORK_ROOT / "review" / "local-model" / "aliyun" / "five-stage-011-015"
)
STAGES = tuple(range(11, 16))


def deep_dir(stage: int) -> Path:
    return (
        WORK_ROOT
        / "review"
        / "local-model"
        / "aliyun"
        / f"stage-{stage:03d}"
        / "general-models"
        / "deepseek-v4-flash-relevant-compact-lines"
    )


REPAIRS = {
    (13, 68): deep_dir(13).parent / "qwen3.7-plus-repair-068" / "validated.jsonl",
    (13, 96): deep_dir(13).parent / "qwen3.7-plus-repair-096" / "validated.jsonl",
    (15, 414): deep_dir(15).parent / "deepseek-v4-flash-repair-414" / "validated.jsonl",
}
REPAIR_MODELS = {
    (13, 68): "qwen3.7-plus",
    (13, 96): "qwen3.7-plus",
    (15, 414): "deepseek-v4-flash",
}


EXCEPTIONS: dict[tuple[int, int], tuple[str, str]] = {
    **{
        (14, index): (
            "system/unit",
            "复合词“都市ユニット”按“都市单元”处理；排除泛用UI词“单位”的子串强制。",
        )
        for index in (0, 2, 13, 64, 66, 67, 274, 338)
    },
    **{
        (14, index): (
            "people/gainer",
            "“ゲイナー”仅出现在机体名“キングゲイナー”中；排除人名子串强制，机体正式译名待人工统一。",
        )
        for index in (35, 47, 71)
    },
    **{
        (15, index): (
            "people/gainer",
            "“ゲイナー”仅出现在机体名“キングゲイナー”中；排除人名子串强制，机体正式译名待人工统一。",
        )
        for index in (80, 150, 153, 260, 368)
    },
    (15, 329): (
        "skill/guard",
        "“ボディガード”按人物语义译为“保镖”；排除技能词“ガード→防护”的子串强制。",
    ),
}


COMPLEX_KEYS = {
    (12, 4),
    (12, 169),
    (12, 185),
    (13, 7),
    (13, 132),
    (13, 173),
    (13, 222),
    (14, 100),
    (14, 107),
    (14, 269),
    (15, 265),
    (15, 274),
    (15, 328),
    (15, 330),
}
ASCII_WORD = re.compile(r"[A-Za-z]{3,}")


def complex_validated_path(stage: int, index: int) -> Path | None:
    parent = deep_dir(stage).parent
    if stage == 13:
        path = parent / "qwen3.7-plus-complex-review" / "validated.jsonl"
    else:
        path = parent / f"qwen3.7-plus-complex-{index:03d}" / "validated.jsonl"
    return path if path.is_file() and path.stat().st_size else None


def complex_manifest_path(stage: int, index: int) -> Path:
    parent = deep_dir(stage).parent
    if stage == 13:
        return parent / "qwen3.7-plus-complex-review" / "manifest.json"
    return parent / f"qwen3.7-plus-complex-{index:03d}" / "manifest.json"


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row is not an object: {path}:{line_number}")
        rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def append_note(candidate: dict[str, object], note: str) -> None:
    prior = str(candidate.get("notes", "")).strip()
    candidate["notes"] = f"{prior}\n{note}".strip()


def manifest_cost(path: Path) -> float | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    cost = value.get("pricing", {}).get("estimated_run_cost_cny")
    return float(cost) if isinstance(cost, (int, float)) else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets = [
        OUTPUT_ROOT / "merged-model-output.jsonl",
        OUTPUT_ROOT / "validated.jsonl",
        OUTPUT_ROOT / "report.json",
        OUTPUT_ROOT / "complex-review.jsonl",
        OUTPUT_ROOT / "terminology-review.jsonl",
    ]
    if not args.force and any(path.exists() for path in targets):
        raise SystemExit("five-stage outputs already exist; use --force")

    all_queue = load_queue(QUEUE)
    queue = [row for row in all_queue if int(row["stage_index"]) in STAGES]
    queue_by_key = {
        (int(row["stage_index"]), int(row["unique_index"])): row for row in queue
    }

    merged_by_key: dict[tuple[int, int], dict[str, object]] = {}
    deep_manifests: list[Path] = []
    for stage in STAGES:
        directory = deep_dir(stage)
        deep_manifests.append(directory / "manifest.json")
        for candidate in read_jsonl(directory / "parsed.jsonl"):
            key = (int(candidate["stage_index"]), int(candidate["unique_index"]))
            if key in merged_by_key:
                raise ValueError(f"duplicate DeepSeek candidate {key}")
            merged_by_key[key] = candidate

    repair_rows: dict[tuple[int, int], dict[str, object]] = {}
    for key, path in REPAIRS.items():
        rows = read_jsonl(path)
        exact = [
            row
            for row in rows
            if (int(row["stage_index"]), int(row["unique_index"])) == key
        ]
        if len(exact) != 1:
            raise ValueError(f"Qwen repair {key} is not exactly one validated row: {path}")
        repair = dict(exact[0])
        append_note(
            repair,
            f"严格术语失败后由 {REPAIR_MODELS[key]} 单条重译并复验。",
        )
        merged_by_key[key] = repair
        repair_rows[key] = repair

    for key, (term_id, note) in EXCEPTIONS.items():
        candidate = merged_by_key[key]
        refs = set(candidate.get("glossary_refs", []))
        exceptions = set(candidate.get("glossary_exceptions", []))
        refs.discard(term_id)
        exceptions.add(term_id)
        candidate["glossary_refs"] = sorted(refs)
        candidate["glossary_exceptions"] = sorted(exceptions)
        append_note(candidate, note)

    expected = set(queue_by_key)
    if set(merged_by_key) != expected:
        missing = sorted(expected - set(merged_by_key))
        extra = sorted(set(merged_by_key) - expected)
        raise ValueError(f"merged key mismatch: missing={missing[:12]} extra={extra[:12]}")

    merged = [merged_by_key[key] for key in sorted(merged_by_key)]
    validated, validated_by_key, missing = validate_model_output(queue, merged)
    if missing or len(validated_by_key) != len(queue):
        raise ValueError(
            f"merged validation incomplete: validated={len(validated_by_key)} "
            f"queue={len(queue)} missing={missing[:12]}"
        )

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUTPUT_ROOT / "merged-model-output.jsonl", merged)
    write_jsonl(OUTPUT_ROOT / "validated.jsonl", validated)
    drafts = build_stage_drafts(
        queue,
        validated_by_key,
        OUTPUT_ROOT / "drafts",
        force=args.force,
    )

    complex_rows: list[dict[str, object]] = []
    valid_complex_count = 0
    for key in sorted(COMPLEX_KEYS):
        stage, index = key
        qwen_path = complex_validated_path(stage, index)
        qwen_manifest = complex_manifest_path(stage, index)
        qwen_translation = None
        if qwen_path is not None:
            candidates = read_jsonl(qwen_path)
            exact = [
                row
                for row in candidates
                if (int(row["stage_index"]), int(row["unique_index"])) == key
            ]
            if len(exact) == 1:
                try:
                    revalidated, _, missing = validate_model_output(
                        [queue_by_key[key]], exact
                    )
                except TranslationReviewError:
                    revalidated, missing = [], [{"reason": "revalidation_failed"}]
                if len(revalidated) == 1 and not missing:
                    qwen_translation = str(revalidated[0]["translation"])
                    valid_complex_count += 1
        if qwen_translation:
            qwen_status = "validator_clean"
        elif qwen_manifest.is_file():
            qwen_status = "validator_failed"
        else:
            qwen_status = "interrupted_no_manifest"
        complex_rows.append(
            {
                "stage_index": stage,
                "unique_index": index,
                "source_text": str(queue_by_key[key]["source_text"]),
                "deepseek_translation": str(merged_by_key[key]["translation"]),
                "qwen_translation": qwen_translation,
                "qwen_status": qwen_status,
                "qwen_manifest": str(qwen_manifest.relative_to(PROJECT_ROOT))
                if qwen_manifest.is_file()
                else None,
                "selection": "deepseek_draft_pending_human_comparison",
            }
        )
    write_jsonl(OUTPUT_ROOT / "complex-review.jsonl", complex_rows)

    terminology_rows: list[dict[str, object]] = []
    for key in sorted(merged_by_key):
        source = str(queue_by_key[key]["source_text"])
        translation = str(merged_by_key[key]["translation"])
        introduced = sorted(
            set(ASCII_WORD.findall(translation)) - set(ASCII_WORD.findall(source))
        )
        if not introduced:
            continue
        terminology_rows.append(
            {
                "stage_index": key[0],
                "unique_index": key[1],
                "introduced_ascii_terms": introduced,
                "source_text": source,
                "translation": translation,
                "review_reason": "译文引入原文未含的ASCII词；可能是项目暂定机体名，也可能是未覆盖术语。",
            }
        )
    write_jsonl(OUTPUT_ROOT / "terminology-review.jsonl", terminology_rows)

    deep_costs = [manifest_cost(path) for path in deep_manifests]
    qwen_manifests = sorted(
        path
        for stage in STAGES
        for path in deep_dir(stage).parent.glob("qwen3.7-plus-*/manifest.json")
    )
    qwen_costs = [manifest_cost(path) for path in qwen_manifests]
    deep_repair_costs = [
        manifest_cost(REPAIRS[key].parent / "manifest.json")
        for key in REPAIRS
        if REPAIR_MODELS[key] == "deepseek-v4-flash"
    ]
    known_total_cost = sum(x for x in deep_costs if x is not None) + sum(
        x for x in qwen_costs if x is not None
    ) + sum(x for x in deep_repair_costs if x is not None)
    report = {
        "schema_version": 1,
        "kind": "aliyun_five_stage_review_drafts",
        "stages": list(STAGES),
        "status": "validated_draft_pending_human_review",
        "counts": {
            "queue_unique_count": len(queue),
            "validated_count": len(validated_by_key),
            "draft_count": len(drafts),
            "targeted_repair_count": len(repair_rows),
            "qwen_targeted_repair_count": sum(
                model == "qwen3.7-plus" for model in REPAIR_MODELS.values()
            ),
            "deepseek_targeted_repair_count": sum(
                model == "deepseek-v4-flash" for model in REPAIR_MODELS.values()
            ),
            "explicit_glossary_exception_count": len(EXCEPTIONS),
            "complex_review_count": len(COMPLEX_KEYS),
            "complex_qwen_valid_count": valid_complex_count,
            "introduced_ascii_terminology_review_count": len(terminology_rows),
        },
        "targeted_repairs": [
            {
                "stage_index": stage,
                "unique_index": index,
                "model": REPAIR_MODELS[(stage, index)],
                "path": str(REPAIRS[(stage, index)].relative_to(PROJECT_ROOT)),
            }
            for stage, index in sorted(REPAIRS)
        ],
        "glossary_exceptions": [
            {
                "stage_index": stage,
                "unique_index": index,
                "term_id": EXCEPTIONS[(stage, index)][0],
                "reason": EXCEPTIONS[(stage, index)][1],
            }
            for stage, index in sorted(EXCEPTIONS)
        ],
        "cost_estimate_cny": {
            "deepseek_complete_runs": round(sum(x for x in deep_costs if x is not None), 6),
            "qwen_known_manifest_runs": round(sum(x for x in qwen_costs if x is not None), 6),
            "deepseek_targeted_repair_runs": round(
                sum(x for x in deep_repair_costs if x is not None), 6
            ),
            "known_total": round(known_total_cost, 6),
            "interrupted_or_unaccounted_calls_excluded": True,
        },
        "artifacts": {
            "merged_model_output": "work/review/local-model/aliyun/five-stage-011-015/merged-model-output.jsonl",
            "validated": "work/review/local-model/aliyun/five-stage-011-015/validated.jsonl",
            "drafts": [str(path.relative_to(PROJECT_ROOT)) for path in drafts],
            "complex_review": "work/review/local-model/aliyun/five-stage-011-015/complex-review.jsonl",
            "terminology_review": "work/review/local-model/aliyun/five-stage-011-015/terminology-review.jsonl",
        },
        "promotion": {
            "allowed": False,
            "next_step": "human terminology and line-by-line review before writing corpus/zh",
        },
    }
    (OUTPUT_ROOT / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"stages={STAGES[0]:03d}-{STAGES[-1]:03d} "
        f"validated={len(validated_by_key)}/{len(queue)} drafts={len(drafts)} "
        f"repairs={len(repair_rows)} exceptions={len(EXCEPTIONS)} "
        f"complex_qwen={valid_complex_count}/{len(COMPLEX_KEYS)}"
    )
    print((OUTPUT_ROOT / "report.json").relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
