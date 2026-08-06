#!/usr/bin/env python3
"""Promote all validated story drafts while preserving their real status."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

try:
    from build_story_dialogue_stage_translation import build_stage_document
    from preprocess_full_story_terminology import (
        curated_rules,
        normalized,
        occurrence_matches,
        spans,
        user_rules,
    )
    from report_full_story_terminology import refs_from_existing
    from srwz.translation_review import (
        audit_translation_release,
        load_glossary,
        load_source_corpus,
        load_translations,
        term_occurs,
    )
except ModuleNotFoundError:  # pragma: no cover
    from tools.build_story_dialogue_stage_translation import build_stage_document
    from tools.preprocess_full_story_terminology import (
        curated_rules,
        normalized,
        occurrence_matches,
        spans,
        user_rules,
    )
    from tools.report_full_story_terminology import refs_from_existing
    from tools.srwz.translation_review import (
        audit_translation_release,
        load_glossary,
        load_source_corpus,
        load_translations,
        term_occurs,
    )


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "work/review"
QUEUE = REVIEW / "local-model/story-dialogue-unique.jsonl"
STAGE10 = REVIEW / "story-dialogue-stage-010-reviewed-unique-draft.json"
FIVE = REVIEW / "local-model/aliyun/five-stage-011-015/validated.jsonl"
REMAINING = REVIEW / "local-model/aliyun/remaining-stages/finalized/validated.jsonl"
TERM_ROOT = REVIEW / "full-story-terminology"
PREPROCESSED = TERM_ROOT / "preprocessed-terms.json"
DECISIONS = TERM_ROOT / "imported-decisions.json"
PENDING = TERM_ROOT / "pending-surface-forms.tsv"
BASELINE = REVIEW / "subtitle-sources/subtitle-terminology-baseline.json"
OUTPUT = REVIEW / "full-story-promotion"
TRANSLATION_ROOT = ROOT / "corpus/zh/story-dialogue"
RELEASE = ROOT / "corpus/releases/v1.json"
EDITORIAL_OVERRIDES = ROOT / "corpus/review/full-story-line-edits-v1.json"


# Decisions containing alternatives or instructions require an exact mapping.
# None means the reviewed Latin/UI form is intentionally retained.
SURFACE_MAPS: dict[str, dict[str, str | None]] = {
    "P:ui-lesson": {"LESSON": None, "LESSON1": None, "LESSON2": None, "LESSON3": None},
    "P:ui-library": {"LIBRARY": None, "Q": None, "A": None},
    "P:project-big-o-weapons": {"O Thunder": "O雷霆", "Plasma Gimmick": "等离子机关"},
    "P:ui-weapon-tags": {"PLA": None, "ALL": None, "TRI": None, "DVE": None, "SR": None},
    "P:ui-controls": {
        "Start": "START", "Select": "SELECT", "START": None, "SELECT": None,
        "HELP": None, "R1": None, "R2": None, "L1": None, "L2": None,
    },
    "P:project-aquarion-greek": {"Alpha": "阿尔法", "Omega": "欧米伽", "Delta": "德尔塔"},
    "P:style-catchphrases": {},
    "P:ui-difficulty": {"Easy": "简单", "Normal": "普通", "Hard": "困难"},
    "P:subtitle-compac": {"Compact": "魂魄", "compac": "魂魄", "Compac Drive": "魂魄驱动器"},
    "P:project-side": {"Side1": "Side 1", "Side 1": None, "Side 7": None},
    "P:project-formations": {"TRI": None, "Wide": None},
    "P:project-aquarion-vectors": {
        "Vector Alpha": "阿尔法战机", "Vector Omega": "欧米伽战机",
        "Vector Mars": "火星战机", "Vector Sol": "太阳战机",
        "Vector": "战机", "Luna": "月亮战机",
    },
    # Attack/catchphrase spellings remain Latin; standalone Ergo follows the decision.
    "P:wiki-ergo": {"Ergo": "工学（Ergo）", "Ergo Fooooooorm": None, "Ergo Break": None},
}

SPECIAL_ITEMS = {
    "P:conflict-fire-great-gravion",
    "P:user-u03",
    "P:user-u13",
    "P:user-u42",
    "P:wiki-origin-law",
}

FALSE_POSITIVE_TERM_IDS = {
    # Confirmed by the terminology review.
    "people/kira",
    "skill/commander",
    "skill/guard",
    "system/evasion",
    "system/turn",
    # Additional Stage 010 substring collisions exposed by the formal builder.
    "people/ray",  # レイ inside メテオブレイカー
    "people/shinn",  # シン inside シンプル
    "place/io",  # イオ inside イオン
}

SUPERSEDED_DIALOGUE_TERMS = {
    "unit/rush-rod": "user/unit/rush-rod",
    "unit/buffalo": "user/unit/buffalo",
    "unit/aquarion": "user/unit/aquarion",
    "unit/dominator": "user/unit/dominator",
    "unit/assault-aquarion": "user/unit/assault-aquarion",
}
USER_TERM_IDS = {
    "organization/ageha-team",
    "people/black-charisma",
    *SUPERSEDED_DIALOGUE_TERMS.values(),
}


# The terminology review originally inspected Latin surface forms emitted by
# the machine drafts.  Some earlier reviewed rows and a handful of later rows
# already contained Chinese variants, so they never entered that surface-form
# queue.  These rules are deliberately source-aware: a Chinese replacement is
# only made when the corresponding Japanese term occurs in that exact row.
SOURCE_AWARE_DECISION_REPAIRS: tuple[dict[str, object], ...] = (
    {
        "decision_id": "P:user-u02",
        "source_patterns": ("ビーター・サービス", "ビーターサービス"),
        "chosen_translation": "彼特维修公司",
        "translation_variants": (
            "比特服务公司", "比塔·服务", "比塔服务", "比特服务", "修理服务",
        ),
    },
    {
        "decision_id": "P:user-u46",
        "source_patterns": ("パラダイムシティ", "パラダイム・シティ"),
        "chosen_translation": "帕拉达伊姆城",
        "translation_variants": ("帕拉迪姆城", "帕拉戴姆城", "范式城", "天堂城", "乐园都市"),
    },
    {
        "decision_id": "P:project-paradigm-company",
        "source_patterns": ("パラダイム社",),
        "chosen_translation": "帕拉达伊姆公司",
        "translation_variants": (
            "帕拉达伊姆公司公司", "帕拉戴姆公司", "帕拉迪姆公司", "范式公司", "Paradigm公司",
        ),
    },
    {
        "decision_id": "P:user-u47",
        "source_patterns": ("ジェノサイドロンシステム",),
        "chosen_translation": "杰诺赛德隆系统",
        "translation_variants": (
            "杰诺赛德隆系统系统", "Genocide Ron System", "种族灭绝系统", "灭绝系统",
        ),
    },
    {
        "decision_id": "P:source-g-soldier",
        "source_patterns": ("Gソルジャー隊", "Ｇソルジャー隊"),
        "chosen_translation": "G-Soldier队",
        "translation_variants": ("G士兵队",),
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--update-release", action="store_true")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, object]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row is not an object: {path}:{number}")
        rows.append(value)
    return rows


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def key_for(row: Mapping[str, object]) -> tuple[int, int]:
    return int(row["stage_index"]), int(row["unique_index"])


def append_note(row: dict[str, object], note: str) -> None:
    prior = str(row.get("notes", "")).strip()
    if note not in prior:
        row["notes"] = f"{prior}\n{note}".strip()


def load_selected_rows(queue: list[dict[str, object]]) -> dict[tuple[int, int], dict[str, object]]:
    selected: dict[tuple[int, int], dict[str, object]] = {}
    for source in queue:
        if source.get("review_state") != "locked_reviewed":
            continue
        refs, exceptions = refs_from_existing(source)
        status = "reviewed"
        for candidate in source.get("existing_translations", []):
            if isinstance(candidate, Mapping) and str(candidate.get("translation", "")) == str(source.get("existing_translation", "")):
                status = str(candidate.get("editorial_status", status))
                break
        selected[key_for(source)] = {
            "translation": str(source["existing_translation"]),
            "editorial_status": status,
            "glossary_refs": refs,
            "glossary_exceptions": exceptions,
            "notes": "",
            "layer": "committed_reviewed",
        }

    stage10 = read_json(STAGE10)
    rows10 = sorted((row for row in queue if int(row["stage_index"]) == 10), key=lambda row: int(row["unique_index"]))
    translations = stage10.get("translations")
    if not isinstance(translations, list) or len(translations) != len(rows10):
        raise ValueError("Stage 010 reviewed draft coverage mismatch")
    hashes = stage10.get("machine_audit", {}).get("source_hashes", [])
    refs = stage10.get("glossary_refs_by_index", {})
    exceptions = stage10.get("glossary_exceptions_by_index", {})
    notes = stage10.get("notes_by_index", {})
    for source in rows10:
        index = int(source["unique_index"])
        if hashes and str(hashes[index]) != str(source["source_text_sha256"]):
            raise ValueError(f"Stage 010 source hash mismatch: {index}")
        selected[(10, index)] = {
            "translation": str(translations[index]),
            "editorial_status": "reviewed",
            "glossary_refs": list(refs.get(str(index), [])),
            "glossary_exceptions": list(exceptions.get(str(index), [])),
            "notes": str(notes.get(str(index), "")),
            "layer": "stage_010_reviewed_draft",
        }

    for path, layer in ((FIVE, "aliyun_011_015_validated_draft"), (REMAINING, "aliyun_remaining_validated_draft")):
        for candidate in read_jsonl(path):
            key = key_for(candidate)
            if key in selected:
                raise ValueError(f"translation layers overlap at {key}")
            selected[key] = {
                "translation": str(candidate["translation"]),
                "editorial_status": "draft",
                "glossary_refs": list(candidate.get("glossary_refs", [])),
                "glossary_exceptions": list(candidate.get("glossary_exceptions", [])),
                "notes": str(candidate.get("notes", "")),
                "layer": layer,
            }
    expected = {key_for(row) for row in queue}
    if set(selected) != expected:
        raise ValueError(f"translation coverage mismatch: missing={sorted(expected-set(selected))[:8]}")
    return selected


def resolved_decisions() -> dict[str, dict[str, object]]:
    rows = read_json(DECISIONS).get("decisions", [])
    decisions = {
        str(row["id"]): dict(row)
        for row in rows
        if isinstance(row, Mapping) and row.get("resolution_status") == "resolved"
    }
    deferred = [str(row.get("id")) for row in rows if isinstance(row, Mapping) and row.get("resolution_status") == "deferred"]
    if deferred != ["P:unresolved-tam"]:
        raise ValueError("the only permitted deferred decision is P:unresolved-tam")
    return decisions


def exact_occurrences() -> dict[tuple[int, int], list[tuple[str, str]]]:
    """Rebuild the exact assignment used to create preprocessed-terms.json."""
    rules = user_rules(read_json(BASELINE)) + curated_rules()
    by_key: dict[tuple[int, int], list[tuple[str, str]]] = defaultdict(list)
    observed: dict[str, Counter[str]] = defaultdict(Counter)
    for row in read_tsv(PENDING):
        key = int(row["stage_index"]), int(row["unique_index"])
        source = str(row["source_text"])
        for phrase in spans(str(row["current_translation"])):
            matches = [rule for rule in rules if occurrence_matches(rule, phrase, source)]
            if matches:
                matches.sort(key=lambda value: 0 if value["disposition"] == "locked_user" else 1)
                item_id = "P:" + str(matches[0]["id"])
            else:
                slug = re.sub(r"[^a-z0-9]+", "-", normalized(phrase)).strip("-")[:80]
                item_id = "P:unresolved-" + slug
            by_key[key].append((item_id, phrase))
            observed[item_id][phrase] += 1
    for item in read_json(PREPROCESSED).get("items", []):
        if not isinstance(item, Mapping) or item.get("item_type") != "preprocessed":
            continue
        item_id = str(item["id"])
        expected = Counter({str(key): int(value) for key, value in item.get("observed_forms", {}).items()})
        if observed[item_id] != expected:
            raise ValueError(f"preprocessed occurrence drift for {item_id}")
    return by_key


def record_change(audit: list[dict[str, object]], key: tuple[int, int], item_id: str, before: str, after: str, reason: str) -> None:
    if before != after:
        audit.append({
            "stage_index": key[0], "unique_index": key[1], "decision_id": item_id,
            "before": before, "after": after, "reason": reason,
        })


def replace_the_titles(value: str, *, heat: bool, crusher: bool) -> str:
    if crusher:
        value = re.sub(r"(?i)THE[ ·]CRUSHER", "THE CRUSHER", value)
    if heat:
        value = re.sub(r"(?i)THE[ ·]HEAT", "THE HEAT", value)
    return value


def apply_global_user_terms(queue_by_key: Mapping[tuple[int, int], Mapping[str, object]], selected: dict[tuple[int, int], dict[str, object]], decisions: Mapping[str, Mapping[str, object]], audit: list[dict[str, object]]) -> None:
    ageha = str(decisions["U:U33"]["chosen_translation"])
    charisma = str(decisions["U:U49"]["chosen_translation"])
    for key, source in sorted(queue_by_key.items()):
        source_text = str(source["source_text"])
        before = str(selected[key]["translation"])
        after = before
        ids = []
        if "アゲハ隊" in source_text:
            ids.append("U:U33")
            for variant in ("阿盖哈队", "扬羽队"):
                after = after.replace(variant, ageha)
            if ageha not in after:
                raise ValueError(f"U33 has an unrecognized translation at {key}: {after}")
        if "黒のカリスマ" in source_text:
            ids.append("U:U49")
            variants = (
                "黑色的魅力领袖", "黑色魅力的领袖", "黑色魅力领袖", "黑色魅力的男人",
                "黑色魅力人物", "黑之救世主", "黑色魅惑者", "黑色的魅力", "黑色的领袖",
                "黑色魅影", "黑色魅力", "黑色领袖", "黑之领袖", "黑之卡里斯马",
            )
            for variant in variants:
                after = after.replace(variant, charisma)
            if charisma not in after:
                raise ValueError(f"U49 has an unrecognized translation at {key}: {after}")
        if "アイラビュ" in source_text:
            ids.append("P:user-u42")
            latin = r"(?i)I\s+LOVE\s+YOU"
            phonetic = r"(?:爱拉比优|爱拉比尤|爱老虎油|哎呀呀)"
            for pattern in (latin, phonetic):
                after = re.sub(pattern + r"[~～]?[，,]", "爱你哟～，", after)
                after = re.sub(pattern + r"[~～]?……", "爱你哟～……", after)
                after = re.sub(pattern + r"[~～]?[！!]", "爱你哟～！", after)
                after = re.sub(pattern + r"[~～]?", "爱你哟～！", after)
            after = after.replace("Forever", "永远").replace("FOREVER", "永远")
            if "爱你哟～" not in after:
                raise ValueError(f"U42 has an unrecognized translation at {key}: {after}")
        if after != before:
            selected[key]["translation"] = after
            append_note(selected[key], "全文术语定稿：" + ", ".join(ids) + "。")
            record_change(audit, key, ",".join(ids), before, after, "global_user_term")


def apply_stage10_canonical_fixes(selected: dict[tuple[int, int], dict[str, object]], audit: list[dict[str, object]]) -> None:
    fixes = {
        (10, 35): ("白方", "不明舰1号", "C:system/bogey-one"),
        (10, 38): ("白方", "不明舰1号", "C:system/bogey-one"),
        (10, 65): ("白方", "不明舰1号", "C:system/bogey-one"),
        (10, 57): ("杰利特", "捷利特", "C:people/speaker-238791253f52"),
        (10, 238): ("杰利特", "捷利特", "C:people/speaker-238791253f52"),
        (10, 258): ("杰利特", "捷利特", "C:people/speaker-238791253f52"),
        (10, 350): ("宇宙殖民卫星", "宇宙殖民地", "C:place/space-colony"),
        (10, 398): ("宇宙居民", "宇宙移民", "C:people/spacenoid"),
        (10, 399): ("宇宙居民", "宇宙移民", "C:people/spacenoid"),
    }
    for key, (find, replace, item_id) in fixes.items():
        before = str(selected[key]["translation"])
        if find not in before:
            raise ValueError(f"canonical fix drift at {key}: missing {find!r}")
        after = before.replace(find, replace)
        selected[key]["translation"] = after
        append_note(selected[key], f"全文术语定稿：{item_id}。")
        record_change(audit, key, item_id, before, after, "canonical_missing_fix")


def apply_surface_decisions(selected: dict[tuple[int, int], dict[str, object]], decisions: Mapping[str, Mapping[str, object]], occurrences: Mapping[tuple[int, int], list[tuple[str, str]]], audit: list[dict[str, object]]) -> None:
    for key, raw in sorted(occurrences.items()):
        operations = [(item_id, phrase) for item_id, phrase in raw if item_id in decisions and item_id != "P:unresolved-tam"]
        if not operations:
            continue
        before = str(selected[key]["translation"])
        value = before
        item_ids = {item_id for item_id, _ in operations}
        if "P:conflict-fire-great-gravion" in item_ids:
            chosen = str(decisions["P:conflict-fire-great-gravion"]["chosen_translation"])
            find = "Fire……不，是Great Gravion吗！"
            if find not in value:
                raise ValueError(f"Great Gravion reviewed row drift at {key}")
            value = value.replace(find, chosen)
        if "P:wiki-origin-law" in item_ids:
            value = value.replace("Origin·Low", "源理之力").replace("Origin Law", "源理之力")
        if key == (150, 72):
            value = re.sub(r"THE[· ]HEAT[· ]CRUSHER", "THE CRUSHER", value, flags=re.IGNORECASE)
        else:
            value = replace_the_titles(value, heat="P:user-u03" in item_ids, crusher="P:user-u13" in item_ids)
        for item_id, phrase in sorted(operations, key=lambda item: -len(item[1])):
            if item_id in SPECIAL_ITEMS:
                continue
            chosen = str(decisions[item_id]["chosen_translation"])
            explicit = SURFACE_MAPS.get(item_id)
            if explicit == {}:
                continue
            if explicit is not None and phrase not in explicit:
                raise ValueError(f"unmapped reviewed surface {item_id}: {phrase!r}")
            replacement = explicit.get(phrase) if explicit is not None else chosen
            if replacement is None or replacement == phrase:
                continue
            if chosen and chosen in value and phrase in chosen:
                continue
            if phrase in value:
                value = value.replace(phrase, replacement)
        if value != before:
            selected[key]["translation"] = value
            applied = sorted(item_ids)
            append_note(selected[key], "全文术语定稿：" + ", ".join(applied) + "。")
            record_change(audit, key, ",".join(applied), before, value, "reviewed_surface_decision")


def apply_source_aware_decision_repairs(
    queue_by_key: Mapping[tuple[int, int], Mapping[str, object]],
    selected: dict[tuple[int, int], dict[str, object]],
    decisions: Mapping[str, Mapping[str, object]],
    audit: list[dict[str, object]],
) -> None:
    """Apply reviewed terminology to Chinese variants missed by the ASCII queue."""
    for rule in SOURCE_AWARE_DECISION_REPAIRS:
        decision_id = str(rule["decision_id"])
        chosen = str(rule["chosen_translation"])
        reviewed = decisions.get(decision_id)
        if reviewed is None or str(reviewed.get("chosen_translation", "")) != chosen:
            raise ValueError(f"source-aware decision drift: {decision_id} != {chosen!r}")
        source_patterns = tuple(str(value) for value in rule["source_patterns"])
        variants = tuple(str(value) for value in rule["translation_variants"])
        for key, source in sorted(queue_by_key.items()):
            source_text = str(source["source_text"])
            if not any(pattern in source_text for pattern in source_patterns):
                continue
            before = str(selected[key]["translation"])
            matching_variants = tuple(variant for variant in variants if variant in before)
            if chosen in before and not matching_variants:
                continue
            after = before
            for variant in matching_variants:
                after = after.replace(variant, chosen)
            if chosen not in after:
                raise ValueError(
                    f"source-aware repair has an unknown translation at {key} "
                    f"for {decision_id}: {before!r}"
                )
            selected[key]["translation"] = after
            append_note(selected[key], f"全文术语定稿补漏：{decision_id}。")
            record_change(
                audit,
                key,
                decision_id,
                before,
                after,
                "source_aware_reviewed_decision_repair",
            )


def repair_serialization_artifacts(
    selected: dict[tuple[int, int], dict[str, object]],
    audit: list[dict[str, object]],
) -> None:
    """Remove a known model response tail without rewriting sentence content."""
    for key, row in sorted(selected.items()):
        before = str(row["translation"])
        after = before.replace("},{”", "")
        if after == before:
            continue
        row["translation"] = after
        append_note(row, "删除模型响应串行化尾部污染。")
        record_change(
            audit,
            key,
            "repair/serialized-json-tail",
            before,
            after,
            "mechanical_serialization_artifact_repair",
        )


def apply_editorial_overrides(
    queue_by_key: Mapping[tuple[int, int], Mapping[str, object]],
    selected: dict[tuple[int, int], dict[str, object]],
    audit: list[dict[str, object]],
) -> dict[str, int]:
    """Apply source-hash-locked human/Codex line reviews after terminology."""
    document = read_json(EDITORIAL_OVERRIDES)
    entries = document.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("editorial override entries must be a list")
    seen: set[tuple[int, int]] = set()
    reviewed = changed = 0
    for raw in entries:
        if not isinstance(raw, Mapping):
            raise ValueError("editorial override entry is not an object")
        key = key_for(raw)
        if key in seen:
            raise ValueError(f"duplicate editorial override: {key}")
        seen.add(key)
        source = queue_by_key.get(key)
        if source is None:
            raise ValueError(f"editorial override references an unknown row: {key}")
        expected_hash = str(raw["source_text_sha256"])
        if str(source["source_text_sha256"]) != expected_hash:
            raise ValueError(f"editorial override source hash drift: {key}")
        before = str(selected[key]["translation"])
        expected_translation = str(raw["expected_translation"])
        if before != expected_translation:
            raise ValueError(
                f"editorial override translation drift at {key}: "
                f"expected {expected_translation!r}, found {before!r}"
            )
        after = str(raw["translation"])
        if not after:
            raise ValueError(f"editorial override is empty: {key}")
        selected[key]["translation"] = after
        selected[key]["editorial_status"] = "reviewed"
        append_note(selected[key], f"逐句语义审校：{raw['review_id']}。")
        reviewed += 1
        if after != before:
            changed += 1
            record_change(
                audit,
                key,
                str(raw["review_id"]),
                before,
                after,
                "reviewed_line_edit",
            )
    return {"reviewed_row_count": reviewed, "changed_row_count": changed}


def reconcile_glossary(
    queue_by_key: Mapping[tuple[int, int], Mapping[str, object]],
    selected: dict[tuple[int, int], dict[str, object]],
    glossary: Iterable[object],
    audit: list[dict[str, object]],
) -> None:
    """Make refs truthful and register only audited substring exceptions."""
    term_by_id = {str(term.term_id): term for term in glossary}
    unhandled = []
    for key, source in sorted(queue_by_key.items()):
        row = selected[key]
        source_text = str(source["source_text"])
        before = str(row["translation"])
        value = before
        refs = set(str(item) for item in row.get("glossary_refs", []))
        exceptions = set(str(item) for item in row.get("glossary_exceptions", []))

        # Objective typography/name fixes from the Stage 010 builder audit.
        relevant = {
            term_id
            for term_id, term in term_by_id.items()
            if "story" in term.domains and term_occurs(term, source_text)
        }
        queue_term_ids = {
            str(term["id"])
            for term in source.get("glossary_terms", [])
            if isinstance(term, Mapping)
        }
        if "system/mobile-suit" in refs and "MS" not in value:
            value = value.replace("机动战士", "MS")
        if "unit/gundam-mk-ii-short" in refs and "Mk-II" not in value:
            value = value.replace("MK-II", "Mk-II")
        if "organization/earth-alliance-short" in refs and "地球联合" not in value:
            value = value.replace("联合军", "地球联合")
        if "people/killer-the-butcher" in refs and "杀手布彻" not in value:
            value = value.replace("杀手·布彻", "杀手布彻")
        if "system/bogey-one" in refs and "不明舰1号" not in value:
            value = value.replace("Bogey One", "不明舰1号")
        if "unit/rush-rod" in relevant and "拉什罗德" not in value:
            value = value.replace("Rush Rod", "拉什罗德").replace("冲刺杆", "拉什罗德")
        if "unit/buffalo" in relevant and "水牛" not in value:
            value = value.replace("Buffalo", "水牛")
        if "unit/dominator" in relevant and "支配者" not in value:
            value = value.replace("Dominator", "支配者")
        if "unit/aquarion" in relevant and "亚库艾里翁" not in value:
            value = value.replace("Aquarion Luna", "月亮亚库艾里翁")
            value = value.replace("Aquarion", "亚库艾里翁")

        for term_id in sorted(relevant):
            term = term_by_id[term_id]
            canonical_present = str(term.translation) in value
            if canonical_present:
                # The builder auto-references enforced canonical text. Keeping
                # an old exception would create an invalid ref/exception overlap.
                exceptions.discard(term_id)
                if term.enforce or term_id in USER_TERM_IDS:
                    refs.add(term_id)
                continue
            if term_id in refs:
                refs.remove(term_id)
            if term_id in FALSE_POSITIVE_TERM_IDS:
                exceptions.add(term_id)
                continue
            replacement_term_id = SUPERSEDED_DIALOGUE_TERMS.get(term_id)
            if replacement_term_id is not None:
                replacement_term = term_by_id[replacement_term_id]
                if str(replacement_term.translation) not in value:
                    unhandled.append(
                        (key, replacement_term_id, str(replacement_term.translation), source_text, value)
                    )
                    continue
                exceptions.add(term_id)
                refs.add(replacement_term_id)
                continue
            if term_id not in queue_term_ids:
                # The queue exporter applies the project's narrower relevance
                # filter. A raw substring-only formal match rejected there is
                # recorded explicitly instead of silently becoming a ref.
                exceptions.add(term_id)
                continue
            if key == (10, 350) and term_id == "system/space-colony-short":
                exceptions.add(term_id)
                continue
            if term.enforce and term_id not in exceptions:
                unhandled.append((key, term_id, str(term.translation), source_text, value))

        if value != before:
            row["translation"] = value
            append_note(row, "正式词表构建审计修正。")
            record_change(audit, key, "formal_glossary", before, value, "formal_glossary_reconciliation")
        row["glossary_refs"] = sorted(refs)
        row["glossary_exceptions"] = sorted(exceptions)

    if unhandled:
        rendered = "\n".join(
            f"{key} {term_id}={translation!r} :: {current!r}"
            for key, term_id, translation, _, current in unhandled[:30]
        )
        raise ValueError(f"unhandled enforced glossary misses ({len(unhandled)}):\n{rendered}")


def build_draft(stage: int, queue_rows: Iterable[Mapping[str, object]], selected: Mapping[tuple[int, int], Mapping[str, object]]) -> dict[str, object]:
    rows = sorted(queue_rows, key=lambda row: int(row["unique_index"]))
    if [int(row["unique_index"]) for row in rows] != list(range(len(rows))):
        raise ValueError(f"Stage {stage:03d} unique indices are not contiguous")
    translations, statuses, refs, exceptions, notes = [], {}, {}, {}, {}
    for source in rows:
        index = int(source["unique_index"])
        row = selected[(stage, index)]
        translations.append(str(row["translation"]))
        statuses[str(index)] = str(row["editorial_status"])
        if row.get("glossary_refs"):
            refs[str(index)] = sorted(set(str(x) for x in row["glossary_refs"]))
        if row.get("glossary_exceptions"):
            exceptions[str(index)] = sorted(set(str(x) for x in row["glossary_exceptions"]))
        if row.get("notes"):
            notes[str(index)] = str(row["notes"])
    document: dict[str, object] = {
        "schema_version": 1,
        "draft_kind": "full_story_terminology_promoted_unique_draft",
        "stage_index": stage,
        "ordering": "unique_index from story-dialogue-unique.jsonl",
        "editorial_status": "draft",
        "translations": translations,
        "editorial_status_by_index": statuses,
        "glossary_refs_by_index": refs,
    }
    if exceptions:
        document["glossary_exceptions_by_index"] = exceptions
    if notes:
        document["notes_by_index"] = notes
    return document


def update_existing_stage(
    stage: int,
    queue_rows: Iterable[Mapping[str, object]],
    selected: Mapping[tuple[int, int], Mapping[str, object]],
) -> int:
    """Patch only translations that changed, preserving reviewed file metadata."""
    path = TRANSLATION_ROOT / f"stage-{stage:03d}.json"
    document = read_json(path)
    by_hash = {
        str(source["source_text_sha256"]): selected[(stage, int(source["unique_index"]))]
        for source in queue_rows
    }
    changed = 0
    for entry in document.get("entries", []):
        if not isinstance(entry, dict):
            continue
        candidate = by_hash[str(entry["source_text_sha256"])]
        translation = str(candidate["translation"])
        if str(entry.get("translation", "")) == translation:
            continue
        entry["translation"] = translation
        entry["glossary_refs"] = sorted(set(str(x) for x in candidate.get("glossary_refs", [])))
        exceptions = sorted(set(str(x) for x in candidate.get("glossary_exceptions", [])))
        if exceptions:
            entry["glossary_exceptions"] = exceptions
        else:
            entry.pop("glossary_exceptions", None)
        if candidate.get("notes"):
            entry["notes"] = str(candidate["notes"])
        changed += 1
    if changed:
        write_json(path, document)
    return changed


def update_release(stages: list[int]) -> None:
    release = read_json(RELEASE)
    non_story = [str(path) for path in release.get("translation_sources", []) if not str(path).startswith("corpus/zh/story-dialogue/stage-")]
    release["translation_sources"] = non_story + [f"corpus/zh/story-dialogue/stage-{stage:03d}.json" for stage in stages]
    glossary_sources = [str(path) for path in release.get("glossary_sources", [])]
    full_glossary = "corpus/glossary/story-dialogue-full-v1.json"
    if full_glossary not in glossary_sources:
        glossary_sources.append(full_glossary)
    release["glossary_sources"] = glossary_sources
    for item in release.get("coverage_plan", []):
        if isinstance(item, dict) and item.get("batch_id") == "v1-story-dialogue":
            item["status"] = "draft_complete"
    release["notes"] = (
        "v1 remains in progress. All 82,719 story-dialogue records across 154 text stages now have corpus files: "
        "stages 001-009 and 018 retain their committed reviewed status, Stage 010 is reviewed, and the validated "
        "Stage 011-015 plus remaining-stage machine translations remain draft. The full-story terminology decisions "
        "are applied; Tam remains explicitly deferred. Draft rows still require line editing and runtime validation."
    )
    write_json(RELEASE, release)


def main() -> int:
    args = parse_args()
    report_path = OUTPUT / "report.json"
    if report_path.exists() and not args.force:
        raise SystemExit("full-story promotion output exists; use --force")
    queue = sorted(read_jsonl(QUEUE), key=key_for)
    queue_by_key = {key_for(row): row for row in queue}
    stages = sorted({int(row["stage_index"]) for row in queue})
    if len(stages) != 154:
        raise ValueError(f"expected 154 story stages, found {len(stages)}")
    selected = load_selected_rows(queue)
    decisions = resolved_decisions()
    audit: list[dict[str, object]] = []
    apply_global_user_terms(queue_by_key, selected, decisions, audit)
    apply_stage10_canonical_fixes(selected, audit)
    apply_surface_decisions(selected, decisions, exact_occurrences(), audit)
    apply_source_aware_decision_repairs(queue_by_key, selected, decisions, audit)
    repair_serialization_artifacts(selected, audit)

    release = read_json(RELEASE)
    source_entries = load_source_corpus(ROOT / str(release["source_corpus"]["path"]))
    glossary_paths = [ROOT / str(path) for path in release.get("glossary_sources", [])]
    full_glossary = ROOT / "corpus/glossary/story-dialogue-full-v1.json"
    if full_glossary not in glossary_paths:
        glossary_paths.append(full_glossary)
    glossary = load_glossary(glossary_paths)
    reconcile_glossary(queue_by_key, selected, glossary, audit)
    line_editing = apply_editorial_overrides(queue_by_key, selected, audit)
    by_stage: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in queue:
        by_stage[int(row["stage_index"])].append(row)

    existing_entry_changes = sum(
        update_existing_stage(stage, by_stage[stage], selected)
        for stage in [*range(1, 10), 18]
    )
    existing_reviewed_changed_keys = {
        (int(row["stage_index"]), int(row["unique_index"]))
        for row in audit
        if int(row["stage_index"]) in {*range(1, 10), 18}
    }
    generated = []
    for stage in stages:
        draft = build_draft(stage, by_stage[stage], selected)
        write_json(OUTPUT / "drafts" / f"stage-{stage:03d}-unique-draft.json", draft)
        output_path = TRANSLATION_ROOT / f"stage-{stage:03d}.json"
        if output_path.exists() and stage in {*range(1, 10), 18}:
            continue
        if output_path.exists() and not args.force:
            raise ValueError(f"translation output exists; use --force: {output_path}")
        document, _ = build_stage_document(source_entries, glossary, stage_index=stage, draft=draft)
        write_json(output_path, document)
        generated.append(str(output_path.relative_to(ROOT)))
    if args.update_release:
        update_release(stages)

    current_release = read_json(RELEASE)
    all_translations = load_translations(
        [ROOT / str(path) for path in current_release.get("translation_sources", [])]
    )
    story_sources = tuple(
        source
        for source in source_entries
        if source.get("domain") == "story" and source.get("kind") == "dialogue"
    )
    story_ids = {str(source["id"]) for source in story_sources}
    story_translations = tuple(
        record
        for record in all_translations
        if record.batch_id == "v1-story-dialogue" and record.entry_id in story_ids
    )
    story_audit = audit_translation_release(story_sources, story_translations, glossary)

    change_counts = Counter(str(row["decision_id"]) for row in audit)
    report = {
        "schema_version": 1,
        "kind": "srwz_full_story_dialogue_promotion",
        "status": "full_draft_promoted_pending_line_edit_and_runtime_validation",
        "scope": {
            "stage_count": len(stages),
            "unique_text_row_count": len(queue),
            "expanded_entry_count": sum(int(row["occurrence_count"]) for row in queue),
            "generated_stage_file_count": len(generated),
            "existing_reviewed_stage_file_count": len(stages) - len(generated),
            "updated_existing_reviewed_unique_row_count": len(existing_reviewed_changed_keys),
            "existing_reviewed_entry_writes_this_run": existing_entry_changes,
        },
        "terminology": {
            "resolved_decision_count": len(decisions),
            "deferred_decision_ids": ["P:unresolved-tam"],
            "changed_unique_row_count": len({(row["stage_index"], row["unique_index"]) for row in audit}),
            "audit_event_count": len(audit),
            "change_counts_by_decision": dict(sorted(change_counts.items())),
        },
        "line_editing": {
            **line_editing,
            "override_source": str(EDITORIAL_OVERRIDES.relative_to(ROOT)),
        },
        "editorial_boundary": {
            "reviewed_stages": list(range(1, 11)) + [18],
            "machine_draft_rows_remain_draft": True,
            "release_updated": bool(args.update_release),
            "runtime_validated": False,
        },
        "validation": {
            "story_dialogue_audit": "passed",
            "source_entry_count": story_audit["source_entry_count"],
            "translation_entry_count": story_audit["translation_entry_count"],
            "coverage_percent": story_audit["coverage_percent"],
            "editorial_status_counts": story_audit["editorial_status_counts"],
            "glossary_reference_count": story_audit["glossary_reference_count"],
            "glossary_exception_count": story_audit["glossary_exception_count"],
        },
        "artifacts": {
            "translation_root": str(TRANSLATION_ROOT.relative_to(ROOT)),
            "generated_stage_files": generated,
            "terminology_audit": str((OUTPUT / "terminology-audit.jsonl").relative_to(ROOT)),
            "promotion_drafts": str((OUTPUT / "drafts").relative_to(ROOT)),
        },
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / "terminology-audit.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in audit:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    write_json(report_path, report)
    print(f"stages={len(stages)} unique={len(queue)} generated={len(generated)} term_changed_rows={report['terminology']['changed_unique_row_count']}")
    print(report_path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
