#!/usr/bin/env python3
"""Prepare the complete story-dialogue queue for a local translation model.

This command is deliberately offline.  It reads the clean-room Japanese source
corpus, the already reviewed Chinese records, and the project's glossary, then
writes ignored ``work/`` artifacts that a local model can consume.  It does not
call a translation service and it never promotes model output to ``corpus/zh``.

Two text views are emitted:

* a unique-per-stage JSONL queue (one model decision for each repeated source
  string, with stable source hashes and occurrence IDs); and
* an all-record TSV index (every runtime ID, including duplicates), so a model
  result can be expanded deterministically by the existing stage builder.

The terminology bundle contains every release glossary entry, relevant-term
indexes, source-term conflicts, and a small explicitly provisional set for
terms discovered while preparing the next story batches.  Provisional terms
are never treated as approved canonical translations by the release builder.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

try:
    from srwz.diagnostics import require_work_output
    from srwz.translation_review import (
        GlossaryTerm,
        TranslationRecord,
        TranslationReviewError,
        load_glossary,
        load_source_corpus,
        load_translations,
        term_occurs,
    )
except ModuleNotFoundError:  # pragma: no cover - direct checkout invocation
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.translation_review import (
        GlossaryTerm,
        TranslationRecord,
        TranslationReviewError,
        load_glossary,
        load_source_corpus,
        load_translations,
        term_occurs,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_RELEASE = PROJECT_ROOT / "corpus" / "releases" / "v1.json"
DEFAULT_UNIQUE_OUTPUT = (
    WORK_ROOT / "review" / "local-model" / "story-dialogue-unique.jsonl"
)
DEFAULT_RECORD_OUTPUT = (
    WORK_ROOT / "review" / "local-model" / "story-dialogue-records.tsv"
)
DEFAULT_TERMINOLOGY_OUTPUT = (
    WORK_ROOT / "review" / "local-model" / "story-dialogue-terminology.json"
)
DEFAULT_MANIFEST_OUTPUT = (
    WORK_ROOT / "review" / "local-model" / "story-dialogue-manifest.json"
)

_STRUCTURAL_TOKEN = re.compile(
    r"\{[0-9A-Fa-f]{2}\}"
    r"|<[A-Za-z0-9_]+:[0-9A-Fa-f]{2}>"
    r"|%(?:\d+\$)?[diouxXeEfFgGcrsa]"
    r"|\$[A-Za-z]"
    r"|●+"
)
_KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff\u31f0-\u31ff]")


# These are intentionally not folded into an approved release glossary.  They
# are terms already selected while manually reviewing the next batch, but the
# project still wants a second pass before calling them canonical.
PROVISIONAL_TERMS = (
    {
        "id": "provisional/story-dialogue/joule-team",
        "source_terms": ["ジュール隊"],
        "translation": "玖尔队",
        "category": "organization",
        "status": "needs_human_review",
        "enforce": False,
        "notes": "Stage 010 temporary decision; verify against the project's Gundam name policy before promotion.",
    },
    {
        "id": "provisional/story-dialogue/meteor-breaker",
        "source_terms": ["メテオブレイカー"],
        "translation": "流星破碎器",
        "category": "technology",
        "status": "needs_human_review",
        "enforce": False,
        "notes": "Stage 010 temporary equipment translation; keep consistent during model drafting, then review once globally.",
    },
    {
        "id": "provisional/story-dialogue/flare-motor",
        "source_terms": ["フレアモーター"],
        "translation": "闪焰发动机",
        "category": "technology",
        "status": "needs_human_review",
        "enforce": False,
        "notes": "Stage 010 temporary equipment translation; no project-wide canonical decision yet.",
    },
    {
        "id": "provisional/story-dialogue/voltaire",
        "source_terms": ["ボルテール"],
        "translation": "沃尔泰尔",
        "category": "unit",
        "status": "needs_human_review",
        "enforce": False,
        "notes": "Stage 010 ship-name candidate; verify before release.",
    },
)


def _project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _output(path: Path) -> Path:
    return require_work_output(_project_path(path), WORK_ROOT).resolve()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument(
        "--stage",
        type=int,
        action="append",
        help="limit output to one or more STAGE.BIN scope indices; default is all",
    )
    parser.add_argument("--unique-output", type=Path, default=DEFAULT_UNIQUE_OUTPUT)
    parser.add_argument("--records-output", type=Path, default=DEFAULT_RECORD_OUTPUT)
    parser.add_argument(
        "--terminology-output",
        type=Path,
        default=DEFAULT_TERMINOLOGY_OUTPUT,
    )
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _guard_outputs(paths: Sequence[Path], *, force: bool) -> None:
    for path in paths:
        if path.exists() and not force:
            raise TranslationReviewError(f"output exists; use --force: {path}")


def _release_paths(release: Mapping[str, object], key: str) -> tuple[Path, ...]:
    raw = release.get(key, ())
    if not isinstance(raw, list):
        raise TranslationReviewError(f"release {key} must be an array")
    return tuple(_project_path(Path(str(path))).resolve() for path in raw)


def _load_raw_glossary_terms(paths: Iterable[Path]) -> list[dict[str, object]]:
    """Load raw terms with provenance for the model-facing bundle."""

    result: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        for raw in document.get("terms", ()):
            if not isinstance(raw, Mapping):
                continue
            term_id = str(raw.get("id", "")).strip()
            if not term_id:
                continue
            if term_id in seen_ids:
                raise TranslationReviewError(
                    f"duplicate glossary term id across release sources: {term_id}"
                )
            seen_ids.add(term_id)
            item = dict(raw)
            item["source_file"] = str(path.relative_to(PROJECT_ROOT))
            result.append(item)
    return result


def _term_record(term: GlossaryTerm) -> dict[str, object]:
    return {
        "id": term.term_id,
        "source_terms": list(term.source_terms),
        "translation": term.translation,
        "category": term.category,
        "status": term.status,
        "domains": list(term.domains),
        "enforce": term.enforce,
        "source_match": term.source_match,
        "notes": term.notes,
    }


def _structural_tokens(text: str) -> list[str]:
    return _STRUCTURAL_TOKEN.findall(text)


def _quote_shape(text: str) -> str:
    value = text.strip()
    if value.startswith(("「", "『")) and value.endswith(("」", "』")):
        return "dialogue_quoted"
    if not value:
        return "empty"
    if _KANA.search(value) is None and "　" in value and "\n" not in value:
        # Scene cards in this game are generally two labels separated by a
        # full-width space; this is only a hint for the model, not a parser rule.
        return "scene_card_candidate"
    if _STRUCTURAL_TOKEN.fullmatch(value) or value in {"！", "？？？"}:
        return "control_or_punctuation"
    return "unquoted"


def _translation_index(
    records: Sequence[TranslationRecord],
) -> dict[str, TranslationRecord]:
    return {record.entry_id: record for record in records}


def _speaker_index(records: Sequence[TranslationRecord]) -> dict[str, TranslationRecord]:
    return {
        record.entry_id: record
        for record in records
        if record.entry_id.startswith("story/") and "/speaker/" in record.entry_id
    }


def _stage_groups(
    source_entries: Sequence[Mapping[str, object]],
    stage_filter: set[int] | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return unique model rows and complete runtime rows in source order."""

    grouped: OrderedDict[tuple[int, str], list[Mapping[str, object]]] = OrderedDict()
    for entry in source_entries:
        if entry.get("domain") != "story" or entry.get("kind") != "dialogue":
            continue
        stage = int(entry.get("scope_index", -1))
        if stage_filter is not None and stage not in stage_filter:
            continue
        source_hash = str(entry["source_text_sha256"])
        grouped.setdefault((stage, source_hash), []).append(entry)

    unique_rows: list[dict[str, object]] = []
    record_rows: list[dict[str, object]] = []
    next_unique_index: defaultdict[int, int] = defaultdict(int)
    for (stage, source_hash), entries in grouped.items():
        # Keep this O(number of unique source strings).  Scanning every index
        # already emitted for a stage makes a full export needlessly quadratic.
        unique_index = next_unique_index[stage]
        next_unique_index[stage] += 1
        first = entries[0]
        provenance = first.get("provenance")
        pointer_offsets = []
        sections = []
        speaker_ids = []
        for entry in entries:
            if entry.get("section") not in sections:
                sections.append(entry.get("section"))
            raw_provenance = entry.get("provenance")
            if isinstance(raw_provenance, Mapping):
                for key in ("pointer_offset", "pointer_offsets"):
                    raw = raw_provenance.get(key)
                    values = raw if isinstance(raw, list) else [raw]
                    for value in values:
                        if isinstance(value, int) and value not in pointer_offsets:
                            pointer_offsets.append(value)
                speaker = raw_provenance.get("speaker_id")
                if isinstance(speaker, int) and speaker not in speaker_ids:
                    speaker_ids.append(speaker)
        unique_rows.append(
            {
                "schema_version": 1,
                "stage_index": stage,
                "unique_index": unique_index,
                "source_text": str(first["source_text"]),
                "source_text_sha256": source_hash,
                "occurrence_count": len(entries),
                "occurrence_ids": [str(entry["id"]) for entry in entries],
                "sections": sections,
                "speaker_ids": speaker_ids,
                "pointer_offsets": pointer_offsets,
                "source_quote_shape": _quote_shape(str(first["source_text"])),
                "source_newline_count": str(first["source_text"]).count("\n"),
                "structural_tokens": _structural_tokens(str(first["source_text"])),
            }
        )
        for entry in entries:
            raw_provenance = entry.get("provenance")
            speaker_id = (
                raw_provenance.get("speaker_id")
                if isinstance(raw_provenance, Mapping)
                else None
            )
            record_rows.append(
                {
                    "id": str(entry["id"]),
                    "stage_index": stage,
                    "section": str(entry.get("section", "")),
                    "speaker_id": speaker_id if isinstance(speaker_id, int) else "",
                    "unique_index": unique_index,
                    "source_text": str(entry["source_text"]),
                    "source_text_sha256": source_hash,
                }
            )
    return unique_rows, record_rows


def _attach_translation_state(
    unique_rows: list[dict[str, object]],
    record_rows: list[dict[str, object]],
    translations: Mapping[str, TranslationRecord],
    speakers: Mapping[str, TranslationRecord],
) -> None:
    records_by_id = {str(row["id"]): row for row in record_rows}
    states_by_unique: dict[tuple[int, int], list[TranslationRecord]] = defaultdict(list)
    for row in record_rows:
        record = translations.get(str(row["id"]))
        if record is not None:
            states_by_unique[(int(row["stage_index"]), int(row["unique_index"]))].append(record)
        speaker_id = row.get("speaker_id")
        if speaker_id != "":
            key = f"story/{int(row['stage_index']):03d}/speaker/{int(speaker_id):03d}"
            speaker = speakers.get(key)
            if speaker is not None:
                row["speaker_translation"] = speaker.translation
                row["speaker_status"] = speaker.editorial_status
            else:
                row["speaker_translation"] = ""
                row["speaker_status"] = "missing"
        else:
            row["speaker_translation"] = ""
            row["speaker_status"] = "missing"

    for row in unique_rows:
        key = (int(row["stage_index"]), int(row["unique_index"]))
        states = states_by_unique.get(key, [])
        decisions = {
            (record.translation, record.editorial_status, record.translation_action)
            for record in states
        }
        row["existing_translations"] = [
            {
                "translation": translation,
                "editorial_status": status,
                "translation_action": action,
                "glossary_refs": sorted(
                    {
                        term_id
                        for record in states
                        if record.translation == translation
                        and record.editorial_status == status
                        and record.translation_action == action
                        for term_id in record.glossary_refs
                    }
                ),
                "glossary_exceptions": sorted(
                    {
                        term_id
                        for record in states
                        if record.translation == translation
                        and record.editorial_status == status
                        and record.translation_action == action
                        for term_id in record.glossary_exceptions
                    }
                ),
                "notes": sorted(
                    {
                        record.notes
                        for record in states
                        if record.translation == translation
                        and record.editorial_status == status
                        and record.translation_action == action
                        and record.notes
                    }
                ),
            }
            for translation, status, action in sorted(decisions)
        ]
        if not states:
            row["review_state"] = "needs_machine_draft"
            row["existing_translation"] = ""
            row["existing_editorial_status"] = ""
        elif len(decisions) == 1:
            translation, status, action = next(iter(decisions))
            row["existing_translation"] = translation
            row["existing_editorial_status"] = status
            row["review_state"] = (
                "locked_reviewed"
                if status in {"reviewed", "final"}
                else "needs_editorial_review"
            )
        else:
            row["existing_translation"] = ""
            row["existing_editorial_status"] = "conflict"
            row["review_state"] = "translation_conflict"

    # Keep this local assertion: every exported record must point at one unique
    # row, and no stale speaker state should be silently dropped.
    if any(row["id"] not in records_by_id for row in record_rows):
        raise TranslationReviewError("internal record index mismatch")


def _attach_terms(
    unique_rows: list[dict[str, object]],
    glossary: Sequence[GlossaryTerm],
    provisional: Sequence[Mapping[str, object]],
) -> None:
    provisional_terms: list[GlossaryTerm] = []
    for raw in provisional:
        provisional_terms.append(
            GlossaryTerm(
                term_id=str(raw["id"]),
                source_terms=tuple(str(value) for value in raw["source_terms"]),
                translation=str(raw["translation"]),
                category=str(raw["category"]),
                status="proposed",
                domains=("story",),
                enforce=False,
                notes=str(raw.get("notes", "")),
            )
        )
    all_terms = tuple(glossary) + tuple(provisional_terms)
    source_variants: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for term in all_terms:
        for source_term in term.source_terms:
            source_variants[source_term][term.translation].add(term.term_id)
    for row in unique_rows:
        source_text = str(row["source_text"])
        relevant = []
        seen_ids: set[str] = set()
        for term in all_terms:
            if "story" not in term.domains or not term_occurs(term, source_text):
                continue
            if term.term_id in seen_ids:
                continue
            seen_ids.add(term.term_id)
            relevant.append(_term_record(term))
        relevant.sort(key=lambda item: (-max(map(len, item["source_terms"])), item["id"]))
        row["glossary_terms"] = relevant
        row["glossary_conflicts"] = [
            {
                "source_term": source_term,
                "variants": [
                    {
                        "translation": translation,
                        "term_ids": sorted(term_ids),
                    }
                    for translation, term_ids in sorted(
                        source_variants[source_term].items()
                    )
                ],
                "action": "human_review_before_promoting_model_output",
            }
            for source_term in sorted(
                {
                    source_term
                    for term in relevant
                    for source_term in term["source_terms"]
                    if len(source_variants[source_term]) > 1
                }
            )
        ]
        row["must_preserve"] = list(row["structural_tokens"])
        row["model_output"] = ""


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _write_records_tsv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "id",
        "stage_index",
        "section",
        "speaker_id",
        "speaker_translation",
        "speaker_status",
        "unique_index",
        "source_text_sha256",
        "source_text",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_terminology(
    path: Path,
    raw_terms: Sequence[Mapping[str, object]],
    provisional: Sequence[Mapping[str, object]],
    unique_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    by_source: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for raw in raw_terms:
        translation = str(raw.get("translation", ""))
        for source_term in raw.get("source_terms", ()):
            source_term = str(source_term)
            if len(source_term) > 1 and translation:
                by_source[source_term][translation].add(str(raw.get("id", "")))
    conflicts = []
    for source_term, variants in sorted(by_source.items()):
        if len(variants) > 1:
            conflicts.append(
                {
                    "source_term": source_term,
                    "variants": [
                        {"translation": translation, "term_ids": sorted(term_ids)}
                        for translation, term_ids in sorted(variants.items())
                    ],
                    "action": "human_review_before_promoting_model_output",
                }
            )
    terms_by_id = {str(raw["id"]): dict(raw) for raw in raw_terms}
    for raw in provisional:
        terms_by_id[str(raw["id"])] = dict(raw)
    relevant_ids = sorted(
        {
            str(term["id"])
            for row in unique_rows
            for term in row.get("glossary_terms", ())
        }
    )
    document = {
        "schema_version": 1,
        "kind": "story_dialogue_local_model_terminology",
        "status": "input_only",
        "source": "release glossary bundle plus explicitly provisional terms",
        "terms": [terms_by_id[key] for key in sorted(terms_by_id)],
        "relevant_term_ids": relevant_ids,
        "source_term_conflicts": conflicts,
        "policy": {
            "canonical_statuses": ["researched", "approved"],
            "provisional_status": "needs_human_review",
            "never_auto_promote": True,
            "conflict_action": "human_review_before_release",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "term_count": len(document["terms"]),
        "relevant_term_count": len(relevant_ids),
        "source_term_conflict_count": len(conflicts),
        "provisional_term_count": len(provisional),
    }


def build_batch_documents(
    release_path: Path,
    *,
    stage_filter: set[int] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object], dict[str, object]]:
    release = json.loads(release_path.read_text(encoding="utf-8"))
    source_config = release.get("source_corpus")
    if not isinstance(source_config, Mapping):
        raise TranslationReviewError("release has no source_corpus object")
    source_path = _project_path(Path(str(source_config["path"]))).resolve()
    source_entries = load_source_corpus(source_path)
    translation_paths = _release_paths(release, "translation_sources")
    glossary_paths = _release_paths(release, "glossary_sources")
    translations = _translation_index(load_translations(translation_paths))
    speakers = _speaker_index(tuple(translations.values()))
    glossary = load_glossary(glossary_paths)
    raw_terms = _load_raw_glossary_terms(glossary_paths)
    unique_rows, record_rows = _stage_groups(source_entries, stage_filter)
    _attach_translation_state(unique_rows, record_rows, translations, speakers)
    _attach_terms(unique_rows, glossary, PROVISIONAL_TERMS)
    term_stats = {
        "release_glossary_paths": [str(path.relative_to(PROJECT_ROOT)) for path in glossary_paths],
        "release_glossary_term_count": len(raw_terms),
        "provisional_term_count": len(PROVISIONAL_TERMS),
    }
    counts = {
        "stage_count": len({int(row["stage_index"]) for row in unique_rows}),
        "record_count": len(record_rows),
        "unique_source_text_count": len(unique_rows),
        "source_character_count_excluding_newlines": sum(
            len(str(row["source_text"]).replace("\n", "")) for row in record_rows
        ),
        "unique_source_character_count_excluding_newlines": sum(
            len(str(row["source_text"]).replace("\n", "")) for row in unique_rows
        ),
        "locked_reviewed_unique_count": sum(
            row.get("review_state") == "locked_reviewed" for row in unique_rows
        ),
        "needs_machine_draft_unique_count": sum(
            row.get("review_state") == "needs_machine_draft" for row in unique_rows
        ),
    }
    metadata = {
        "source_corpus": str(source_path.relative_to(PROJECT_ROOT)),
        "source_corpus_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "stage_filter": sorted(stage_filter) if stage_filter is not None else None,
        "stage_indices": sorted({int(row["stage_index"]) for row in unique_rows}),
        "route_map": "docs/STAGE_ROUTE_MAP.md",
        "counts": counts,
        "terminology": term_stats,
    }
    return unique_rows, record_rows, metadata, {"raw_terms": raw_terms}


def main() -> int:
    args = _parse_args()
    stage_filter = None if not args.stage else set(args.stage)
    if stage_filter is not None and any(stage < 0 for stage in stage_filter):
        raise TranslationReviewError("--stage must be non-negative")
    paths = tuple(
        _output(path)
        for path in (
            args.unique_output,
            args.records_output,
            args.terminology_output,
            args.manifest_output,
        )
    )
    _guard_outputs(paths, force=args.force)
    unique_rows, record_rows, metadata, extra = build_batch_documents(
        _project_path(args.release).resolve(),
        stage_filter=stage_filter,
    )
    terminology_stats = _write_terminology(
        paths[2],
        extra["raw_terms"],
        PROVISIONAL_TERMS,
        unique_rows,
    )
    _write_jsonl(paths[0], unique_rows)
    _write_records_tsv(paths[1], record_rows)
    manifest = {
        "schema_version": 1,
        "kind": "story_dialogue_local_model_batch_manifest",
        "status": "input_only",
        "metadata": metadata,
        "terminology": terminology_stats,
        "files": {
            "unique_jsonl": str(paths[0].relative_to(PROJECT_ROOT)),
            "records_tsv": str(paths[1].relative_to(PROJECT_ROOT)),
            "terminology_json": str(paths[2].relative_to(PROJECT_ROOT)),
        },
        "model_contract": {
            "input": "unique_jsonl; one JSON object per line",
            "output": "JSONL with stage_index, unique_index, source_text_sha256, translation",
            "join_key": ["stage_index", "source_text_sha256"],
            "do_not_change": ["stage_index", "unique_index", "source_text_sha256"],
            "output_fields": {
                "required": [
                    "stage_index",
                    "unique_index",
                    "source_text_sha256",
                    "translation",
                ],
                "optional": ["notes", "translation_action", "glossary_refs", "glossary_exceptions"],
                "forbidden": ["source_text", "occurrence_ids", "pointer_offsets"],
            },
            "preserve": "every item in structural_tokens exactly once",
            "layout": {
                "line_width": 24,
                "max_lines": 3,
                "model_should_not_insert_manual_breaks": True,
                "postprocess": "reflow_chinese_dialogue",
            },
            "reviewed_rows": "skip rows whose review_state is locked_reviewed",
            "provisional_terms": "use as candidates only; human review is required",
            "promotion": "never direct; import validator and human review are required",
        },
    }
    paths[3].parent.mkdir(parents=True, exist_ok=True)
    paths[3].write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "local model batch prepared: "
        f"stages={metadata['counts']['stage_count']} "
        f"records={metadata['counts']['record_count']} "
        f"unique={metadata['counts']['unique_source_text_count']} "
        f"locked_reviewed={metadata['counts']['locked_reviewed_unique_count']} "
        f"needs_machine={metadata['counts']['needs_machine_draft_unique_count']}"
    )
    print(f"unique JSONL: {paths[0]}")
    print(f"records TSV: {paths[1]}")
    print(f"terminology: {paths[2]}")
    print(f"manifest: {paths[3]}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, TranslationReviewError) as error:
        print(f"local model batch failed: {error}", file=sys.stderr)
        raise SystemExit(1)
