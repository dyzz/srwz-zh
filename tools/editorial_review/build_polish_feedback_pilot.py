#!/usr/bin/env python3
"""Build a read-only, source-verified polishing-feedback pilot dataset.

The committed seed contains human adjudications.  This tool binds every target
to the current Chinese corpus and to Japanese text parsed from original game
data, then writes review-only artifacts below ``work/review``.  It never edits
translation corpora and its output is not a production build input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Iterable, Mapping

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from srwz.codec import decode_production
from srwz.font import sha256_bytes
from srwz.image_export import parse_seg_offsets
from srwz.iso9660 import SECTOR_SIZE, member_map, scan_iso9660
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.srvc import parse_srvc_archive
from srwz.stage import parse_stage, read_stage_function_addresses
from srwz.text import load_text_table


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED = PROJECT_ROOT / "config/editorial/polish-feedback-pilot-v1.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "work/review/polish-feedback-pilot-v1"

FINDING_VALIDITIES = frozenset(
    {"valid", "partially_valid", "invalid", "unresolved"}
)
PROPOSAL_DISPOSITIONS = frozenset(
    {
        "accept_exact",
        "accept_direction_rewrite",
        "accept_partial",
        "reject_keep_current",
        "unresolved",
    }
)
SEVERITIES = frozenset({"none", "minor", "major", "blocking"})


class PilotValidationError(ValueError):
    """The curated pilot or one of its source bindings has drifted."""


def _load_json(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PilotValidationError(f"cannot load JSON {path}: {error}") from error
    if not isinstance(document, dict):
        raise PilotValidationError(f"JSON root must be an object: {path}")
    return document


def _project_path(project_root: Path, reference: str) -> Path:
    path = Path(reference)
    return path if path.is_absolute() else project_root / path


def _locked_payload(
    project_root: Path,
    reference: Mapping[str, object],
    *,
    label: str,
) -> tuple[Path, bytes]:
    raw_path = reference.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise PilotValidationError(f"{label} has no path")
    path = _project_path(project_root, raw_path)
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise PilotValidationError(f"cannot read {label}: {path}: {error}") from error
    if (
        reference.get("size") != len(payload)
        or reference.get("sha256") != sha256_bytes(payload)
    ):
        raise PilotValidationError(f"{label} size or SHA-256 drift: {path}")
    return path, payload


def validate_seed(document: Mapping[str, object]) -> tuple[dict, ...]:
    """Validate the human-authored adjudication contract without game data."""

    if (
        document.get("schema_version") != 1
        or document.get("pilot_id") != "srwz-polish-feedback-distillation-v1"
        or document.get("status") != "curated_pilot"
    ):
        raise PilotValidationError("unsupported polishing-feedback pilot identity")
    policy = document.get("policy")
    if (
        not isinstance(policy, dict)
        or policy.get("translation_writeback") != "forbidden"
        or not isinstance(policy.get("promotion"), dict)
        or policy["promotion"].get("allowed") is not False
        or policy["promotion"].get("requires_human_confirmation") is not True
    ):
        raise PilotValidationError("pilot writeback and promotion policy is unsafe")

    raw_decisions = document.get("decisions")
    if not isinstance(raw_decisions, list) or not raw_decisions:
        raise PilotValidationError("pilot has no decisions")
    decision_ids: set[str] = set()
    all_targets: set[str] = set()
    decisions: list[dict] = []
    for raw_decision in raw_decisions:
        if not isinstance(raw_decision, dict):
            raise PilotValidationError("pilot decision must be an object")
        decision = deepcopy(raw_decision)
        decision_id = decision.get("decision_id")
        if (
            not isinstance(decision_id, str)
            or not decision_id
            or decision_id in decision_ids
        ):
            raise PilotValidationError(f"duplicate or invalid decision ID: {decision_id}")
        decision_ids.add(decision_id)
        if decision.get("contributor") not in {"要开心", "天敌Nep"}:
            raise PilotValidationError(f"{decision_id} has an unknown contributor")
        if not isinstance(decision.get("batch_id"), str):
            raise PilotValidationError(f"{decision_id} has no feedback batch")

        feedback = decision.get("feedback")
        if (
            not isinstance(feedback, dict)
            or not isinstance(feedback.get("finding"), str)
            or not feedback["finding"]
            or not isinstance(feedback.get("proposal"), str)
            or not feedback["proposal"]
        ):
            raise PilotValidationError(f"{decision_id} has invalid feedback evidence")

        adjudication = decision.get("adjudication")
        if not isinstance(adjudication, dict):
            raise PilotValidationError(f"{decision_id} has no adjudication")
        if adjudication.get("finding_validity") not in FINDING_VALIDITIES:
            raise PilotValidationError(f"{decision_id} has invalid finding validity")
        if adjudication.get("proposal_disposition") not in PROPOSAL_DISPOSITIONS:
            raise PilotValidationError(f"{decision_id} has invalid proposal disposition")
        if adjudication.get("severity") not in SEVERITIES:
            raise PilotValidationError(f"{decision_id} has invalid severity")
        if not isinstance(adjudication.get("scope"), str) or not adjudication["scope"]:
            raise PilotValidationError(f"{decision_id} has no review scope")
        issue_types = adjudication.get("issue_types")
        if (
            not isinstance(issue_types, list)
            or not issue_types
            or any(not isinstance(item, str) or not item for item in issue_types)
            or len(issue_types) != len(set(issue_types))
        ):
            raise PilotValidationError(f"{decision_id} has invalid issue types")
        for field in ("accepted_elements", "rejected_elements"):
            elements = adjudication.get(field)
            if not isinstance(elements, list) or any(
                not isinstance(item, str) or not item for item in elements
            ):
                raise PilotValidationError(f"{decision_id} has invalid {field}")
        if not isinstance(adjudication.get("rationale"), str) or not adjudication[
            "rationale"
        ]:
            raise PilotValidationError(f"{decision_id} has no rationale")

        approval = decision.get("approval")
        if (
            not isinstance(approval, dict)
            or approval.get("status") != "confirmed"
            or not isinstance(approval.get("promotion"), dict)
            or approval["promotion"].get("allowed") is not False
        ):
            raise PilotValidationError(f"{decision_id} is not safely review-only")

        targets = decision.get("targets")
        baseline = decision.get("baseline_by_target")
        if not isinstance(targets, list) or not targets or not isinstance(baseline, dict):
            raise PilotValidationError(f"{decision_id} has invalid targets or baseline")
        local_targets: set[str] = set()
        for target in targets:
            if not isinstance(target, dict):
                raise PilotValidationError(f"{decision_id} target must be an object")
            target_id = target.get("id")
            source_hash = target.get("expected_source_text_sha256")
            if (
                not isinstance(target_id, str)
                or not target_id
                or target_id in local_targets
                or target_id in all_targets
                or target.get("role") not in {"primary", "same_source", "related_term"}
                or not isinstance(source_hash, str)
                or len(source_hash) != 64
                or not isinstance(target.get("expected_translation"), str)
                or not target["expected_translation"]
                or not isinstance(baseline.get(target_id), str)
                or not baseline[target_id]
            ):
                raise PilotValidationError(
                    f"{decision_id} has invalid or duplicate target {target_id}"
                )
            local_targets.add(target_id)
            all_targets.add(target_id)
        if set(baseline) != local_targets:
            raise PilotValidationError(f"{decision_id} baseline coverage does not match targets")
        decisions.append(decision)

    contributors = {decision["contributor"] for decision in decisions}
    validities = {
        decision["adjudication"]["finding_validity"] for decision in decisions
    }
    dispositions = {
        decision["adjudication"]["proposal_disposition"] for decision in decisions
    }
    if contributors != {"要开心", "天敌Nep"}:
        raise PilotValidationError("pilot must represent both major contributors")
    if not {"valid", "partially_valid", "invalid"}.issubset(validities):
        raise PilotValidationError("pilot does not cover positive, partial, and negative findings")
    if not {
        "accept_exact",
        "accept_direction_rewrite",
        "accept_partial",
        "reject_keep_current",
    }.issubset(dispositions):
        raise PilotValidationError("pilot does not cover all resolved proposal outcomes")
    return tuple(decisions)


def load_corpus_targets(
    project_root: Path,
    target_ids: Iterable[str],
) -> dict[str, dict]:
    """Load only the committed Chinese corpus records needed by the pilot."""

    wanted = set(target_ids)
    story_by_stage: dict[int, set[str]] = {}
    battle_ids: set[str] = set()
    for target_id in wanted:
        if target_id.startswith("story/"):
            try:
                stage_index = int(target_id.split("/", 2)[1])
            except (IndexError, ValueError) as error:
                raise PilotValidationError(f"invalid story target ID: {target_id}") from error
            story_by_stage.setdefault(stage_index, set()).add(target_id)
        elif target_id.startswith("battle:"):
            battle_ids.add(target_id)
        else:
            raise PilotValidationError(f"unsupported pilot target ID: {target_id}")

    result: dict[str, dict] = {}
    for stage_index, stage_targets in sorted(story_by_stage.items()):
        relative_path = Path(f"corpus/zh/story-dialogue/stage-{stage_index:03d}.json")
        document = _load_json(project_root / relative_path)
        for entry in document.get("entries", []):
            if isinstance(entry, dict) and entry.get("id") in stage_targets:
                target_id = entry["id"]
                result[target_id] = {
                    **entry,
                    "corpus_path": relative_path.as_posix(),
                }
    if battle_ids:
        relative_path = Path("corpus/zh/battle/srvc-lines.json")
        document = _load_json(project_root / relative_path)
        for entry in document.get("entries", []):
            if isinstance(entry, dict) and entry.get("id") in battle_ids:
                target_id = entry["id"]
                result[target_id] = {
                    **entry,
                    "corpus_path": relative_path.as_posix(),
                }
    missing = sorted(wanted - set(result))
    if missing:
        raise PilotValidationError(f"pilot targets missing from Chinese corpus: {missing}")
    return result


def _read_original_hb(project_root: Path, config: Mapping[str, object]) -> bytes:
    source = config.get("source")
    if not isinstance(source, dict):
        raise PilotValidationError("story component source configuration is missing")
    reference = source.get("hb")
    iso_reference = source.get("iso")
    if not isinstance(reference, dict) or not isinstance(iso_reference, str):
        raise PilotValidationError("story HB source configuration is invalid")
    member_name = reference.get("member")
    if not isinstance(member_name, str) or not member_name:
        raise PilotValidationError("story HB member name is invalid")
    iso_path = _project_path(project_root, iso_reference)
    try:
        member = member_map(scan_iso9660(iso_path)).get(member_name)
    except OSError as error:
        raise PilotValidationError(f"cannot scan source ISO {iso_path}: {error}") from error
    if member is None:
        raise PilotValidationError(f"source ISO has no member {member_name}")
    with iso_path.open("rb") as source_file:
        source_file.seek(member.extent_lba * SECTOR_SIZE)
        payload = source_file.read(member.size)
    if (
        reference.get("size") != len(payload)
        or reference.get("sha256") != sha256_bytes(payload)
    ):
        raise PilotValidationError("original HB size or SHA-256 drift")
    return payload


def load_story_sources(
    project_root: Path,
    stage_indices: Iterable[int],
) -> dict[str, dict]:
    """Recover target Japanese and local context from original STAGE chunks."""

    config = _load_json(project_root / "config/story-component.json")
    source = config.get("source")
    if not isinstance(source, dict):
        raise PilotValidationError("story source configuration is missing")
    _stage_path, stage_payload = _locked_payload(
        project_root, source.get("stage", {}), label="original STAGE.BIN"
    )
    _slps_path, slps_payload = _locked_payload(
        project_root, source.get("slps", {}), label="original SLPS"
    )
    table_path, _table_payload = _locked_payload(
        project_root, source.get("text_table", {}), label="original text table"
    )
    table = load_text_table(table_path)
    hb_payload = _read_original_hb(project_root, config)
    offsets = read_executable_archive_offsets(
        hb_payload,
        ExecutableOffsetSpec(
            name="HEDBDY/HB.BIN STAGE offsets",
            member="HEDBDY/HB.BIN",
            table_start=30320,
            table_end=31144,
        ),
        len(stage_payload),
    )
    functions = read_stage_function_addresses(slps_payload)
    result: dict[str, dict] = {}
    for stage_index in sorted(set(stage_indices)):
        if not 0 <= stage_index < len(offsets) - 1:
            raise PilotValidationError(f"story stage index outside STAGE archive: {stage_index}")
        corpus_document = _load_json(
            project_root
            / f"corpus/zh/story-dialogue/stage-{stage_index:03d}.json"
        )
        current_translation_by_id = {
            row["id"]: row["translation"]
            for row in corpus_document.get("entries", [])
            if isinstance(row, dict)
            and isinstance(row.get("id"), str)
            and isinstance(row.get("translation"), str)
        }
        stored = stage_payload[offsets[stage_index] : offsets[stage_index + 1]]
        decoded = decode_production(stored)
        alignment_tail = stored[decoded.consumed :]
        if len(alignment_tail) > 15 or any(alignment_tail):
            raise PilotValidationError(
                f"STAGE {stage_index:03d} has non-alignment compressed trailing bytes"
            )
        parsed = parse_stage(
            decoded.output,
            table,
            stage_index=stage_index,
            function_address=functions[stage_index],
        )
        if parsed.unknown_code_count:
            raise PilotValidationError(f"STAGE {stage_index:03d} has unknown text codes")
        dialogues = [entry for entry in parsed.entries if entry.kind == "dialogue"]
        positions = {entry.entry_id: index for index, entry in enumerate(dialogues)}
        for entry in dialogues:
            position = positions[entry.entry_id]
            context = []
            for candidate in dialogues[max(0, position - 1) : position + 2]:
                if candidate.section != entry.section:
                    continue
                context.append(
                    {
                        "id": candidate.entry_id,
                        "relation": (
                            "target"
                            if candidate.entry_id == entry.entry_id
                            else "previous"
                            if positions[candidate.entry_id] < position
                            else "next"
                        ),
                        "source_ja": candidate.text,
                        "current_translation": current_translation_by_id.get(
                            candidate.entry_id
                        ),
                    }
                )
            result[entry.entry_id] = {
                "source_ja": entry.text,
                "source_text_sha256": hashlib.sha256(
                    entry.text.encode("utf-8")
                ).hexdigest(),
                "original_location": {
                    "stage_index": stage_index,
                    "section": entry.section,
                    "ordinal": entry.ordinal,
                    "text_offset": entry.text_offset,
                },
                "source_context": context,
            }
    return result


def load_battle_sources(project_root: Path) -> dict[str, dict]:
    """Recover the exact production ordering and occurrences of original SRVC text."""

    config = _load_json(project_root / "config/full-story-components.json")
    reference = config.get("srvc_battle_text")
    if not isinstance(reference, dict):
        raise PilotValidationError("SRVC battle-text configuration is missing")
    _bin_path, source_bin = _locked_payload(
        project_root, reference.get("original_bin", {}), label="original SRVC.BIN"
    )
    _seg_path, source_seg = _locked_payload(
        project_root, reference.get("original_seg", {}), label="original SRVC.SEG"
    )
    table = load_text_table(
        project_root / "vendor/upstream-python/project/tbl_all.json"
    )
    offsets = parse_seg_offsets(source_seg, len(source_bin))
    chunks = parse_srvc_archive(source_bin, offsets, table)
    records = [record for chunk in chunks for record in chunk.records]
    first_records: dict[str, object] = {}
    occurrences: dict[str, list[dict]] = {}
    for record in records:
        first_records.setdefault(record.text, record)
        occurrences.setdefault(record.text, []).append(
            {
                "chunk_index": record.chunk_index,
                "record_index": record.record_index,
                "archive_text_start": record.archive_text_start,
                "encoded_size": record.encoded_size,
            }
        )
    ordered_source_texts = sorted(
        first_records,
        key=lambda text: (first_records[text].archive_text_start, text),
    )
    result = {}
    for index, source_text in enumerate(ordered_source_texts):
        result[f"battle:{index:05d}"] = {
            "source_ja": source_text,
            "source_text_sha256": hashlib.sha256(
                source_text.encode("utf-8")
            ).hexdigest(),
            "original_location": {
                "occurrence_count": len(occurrences[source_text]),
                "occurrences": occurrences[source_text],
            },
            "source_context": [],
        }
    return result


def bind_sources(
    project_root: Path,
    decisions: Iterable[Mapping[str, object]],
) -> tuple[dict, ...]:
    """Bind curated decisions to corpus and parsed originals, failing on drift."""

    decisions = tuple(decisions)
    target_ids = [
        target["id"]
        for decision in decisions
        for target in decision["targets"]
    ]
    corpus_targets = load_corpus_targets(project_root, target_ids)
    story_indices = {
        int(target_id.split("/", 2)[1])
        for target_id in target_ids
        if target_id.startswith("story/")
    }
    story_sources = load_story_sources(project_root, story_indices)
    battle_sources = (
        load_battle_sources(project_root)
        if any(target_id.startswith("battle:") for target_id in target_ids)
        else {}
    )
    originals = {**story_sources, **battle_sources}

    bound = []
    for raw_decision in decisions:
        decision = deepcopy(raw_decision)
        enriched_targets = []
        for target in decision["targets"]:
            target_id = target["id"]
            corpus = corpus_targets[target_id]
            original = originals.get(target_id)
            if original is None:
                raise PilotValidationError(f"original source target not parsed: {target_id}")
            expected_hash = target["expected_source_text_sha256"]
            if corpus.get("source_text_sha256") != expected_hash:
                raise PilotValidationError(f"Chinese corpus source hash drift: {target_id}")
            if original.get("source_text_sha256") != expected_hash:
                raise PilotValidationError(f"original Japanese source hash drift: {target_id}")
            if corpus.get("translation") != target["expected_translation"]:
                raise PilotValidationError(f"current translation drift: {target_id}")
            if target_id.startswith("battle:") and (
                corpus.get("occurrence_count")
                != original["original_location"]["occurrence_count"]
            ):
                raise PilotValidationError(f"battle occurrence-count drift: {target_id}")
            enriched_targets.append(
                {
                    **target,
                    "corpus_path": corpus["corpus_path"],
                    "editorial_status": corpus.get("editorial_status"),
                    "current_translation": corpus["translation"],
                    "source_ja": original["source_ja"],
                    "original_location": original["original_location"],
                    "source_context": original["source_context"],
                    "validation": {
                        "stable_id_found": True,
                        "source_hash_exact": True,
                        "current_translation_exact": True,
                    },
                }
            )
        decision["targets"] = enriched_targets
        bound.append(decision)
    return tuple(bound)


def build_summary(document: Mapping[str, object], decisions: tuple[dict, ...]) -> dict:
    contributor_counts = Counter(decision["contributor"] for decision in decisions)
    validity_counts = Counter(
        decision["adjudication"]["finding_validity"] for decision in decisions
    )
    disposition_counts = Counter(
        decision["adjudication"]["proposal_disposition"] for decision in decisions
    )
    severity_counts = Counter(
        decision["adjudication"]["severity"] for decision in decisions
    )
    issue_type_counts = Counter(
        issue_type
        for decision in decisions
        for issue_type in decision["adjudication"]["issue_types"]
    )
    target_count = sum(len(decision["targets"]) for decision in decisions)
    story_target_count = sum(
        target["id"].startswith("story/")
        for decision in decisions
        for target in decision["targets"]
    )
    battle_target_count = target_count - story_target_count
    return {
        "schema_version": 1,
        "pilot_id": document["pilot_id"],
        "status": "source_verified_review_dataset",
        "source_register": document["source_register"],
        "decision_count": len(decisions),
        "target_count": target_count,
        "target_domain_counts": {
            "story": story_target_count,
            "battle": battle_target_count,
        },
        "contributor_counts": dict(sorted(contributor_counts.items())),
        "finding_validity_counts": dict(sorted(validity_counts.items())),
        "proposal_disposition_counts": dict(sorted(disposition_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
        "issue_type_counts": dict(sorted(issue_type_counts.items())),
        "validation": {
            "stable_ids_found": True,
            "source_hashes_match_original_japanese": True,
            "current_translations_match_seed": True,
            "original_story_context_recovered": True,
            "original_battle_occurrences_recovered": True,
            "translation_corpus_modified": False,
            "promotion_allowed": False,
        },
    }


def _review_markdown(summary: Mapping[str, object], decisions: tuple[dict, ...]) -> str:
    lines = [
        "# SRWZ 润色反馈蒸馏 pilot v1",
        "",
        (
            f"本报告绑定了 {summary['decision_count']} 条人工裁决、"
            f"{summary['target_count']} 个稳定目标。所有日文均由原盘重新解析，"
            "所有当前译文和 source hash 均与提交语料一致。"
        ),
        "",
        "> 这是只读 review/eval 数据。`promotion.allowed=false`，不能作为自动写回授权。",
        "",
        "## 分布",
        "",
        f"- 贡献者：{json.dumps(summary['contributor_counts'], ensure_ascii=False)}",
        f"- 问题成立性：{json.dumps(summary['finding_validity_counts'], ensure_ascii=False)}",
        f"- 建议处理：{json.dumps(summary['proposal_disposition_counts'], ensure_ascii=False)}",
        f"- 目标域：{json.dumps(summary['target_domain_counts'], ensure_ascii=False)}",
        "",
        "## 裁决索引",
        "",
        "| ID | 贡献者 | batch | 问题成立性 | 建议处理 | 目标 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for decision in decisions:
        adjudication = decision["adjudication"]
        target_ids = "<br>".join(target["id"] for target in decision["targets"])
        lines.append(
            "| {decision_id} | {contributor} | {batch_id} | {validity} | "
            "{disposition} | {targets} |".format(
                decision_id=decision["decision_id"],
                contributor=decision["contributor"],
                batch_id=decision["batch_id"],
                validity=adjudication["finding_validity"],
                disposition=adjudication["proposal_disposition"],
                targets=target_ids,
            )
        )
    lines.extend(["", "## 样本详情", ""])
    for decision in decisions:
        lines.extend(
            [
                f"### {decision['decision_id']} · {decision['contributor']} · {decision['batch_id']}",
                "",
                f"- 反馈判断：{decision['feedback']['finding']}",
                f"- 反馈方案：{decision['feedback']['proposal']}",
                (
                    f"- 裁决：{decision['adjudication']['finding_validity']} / "
                    f"{decision['adjudication']['proposal_disposition']}"
                ),
                f"- 理由：{decision['adjudication']['rationale']}",
                "",
            ]
        )
        for target in decision["targets"]:
            source = target["source_ja"].replace("\n", "\\n")
            translation = target["current_translation"].replace("\n", "\\n")
            lines.extend(
                [
                    f"  - `{target['id']}` ({target['role']})",
                    f"    - 日文：`{source}`",
                    f"    - 当前定稿：`{translation}`",
                    f"    - source hash：`{target['expected_source_text_sha256']}`",
                ]
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    output_root: Path,
    document: Mapping[str, object],
    decisions: tuple[dict, ...],
) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    jsonl = "".join(
        json.dumps(decision, ensure_ascii=False, sort_keys=True) + "\n"
        for decision in decisions
    )
    decisions_path = output_root / "decisions.jsonl"
    decisions_path.write_text(jsonl, encoding="utf-8")
    summary = build_summary(document, decisions)
    summary["decisions_jsonl_sha256"] = hashlib.sha256(
        jsonl.encode("utf-8")
    ).hexdigest()
    summary_path = output_root / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    review_path = output_root / "review.md"
    review_path.write_text(_review_markdown(summary, decisions), encoding="utf-8")
    return summary


def run(seed_path: Path, output_root: Path, project_root: Path = PROJECT_ROOT) -> dict:
    document = _load_json(seed_path)
    decisions = validate_seed(document)
    bound = bind_sources(project_root, decisions)
    return write_outputs(output_root, document, bound)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only, source-verified SRWZ polishing pilot."
    )
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run(args.seed, args.output_root)
    print(
        json.dumps(
            {
                "status": "ok",
                "output_root": str(args.output_root),
                "decision_count": summary["decision_count"],
                "target_count": summary["target_count"],
                "promotion_allowed": summary["validation"]["promotion_allowed"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
