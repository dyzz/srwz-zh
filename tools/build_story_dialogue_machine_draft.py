#!/usr/bin/env python3
"""Build an explicitly machine-generated story-dialogue review draft.

This tool is deliberately a *review* stage, not a translation release.  It
uses the public Google translation endpoint only to create a first-pass draft,
protects the project's glossary and runtime tokens, and runs the same Chinese
layout rules used by the committed translation builders.  The output stays
under ``work/`` and is never added to ``corpus/releases/v1.json`` by this
command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from srwz.chinese_layout import ChineseLayoutError, reflow_chinese_dialogue
    from srwz.translation_review import (
        GlossaryTerm,
        TranslationReviewError,
        load_glossary,
        load_source_corpus,
        term_occurs,
    )
except ModuleNotFoundError:
    from tools.srwz.chinese_layout import ChineseLayoutError, reflow_chinese_dialogue
    from tools.srwz.translation_review import (
        GlossaryTerm,
        TranslationReviewError,
        load_glossary,
        load_source_corpus,
        term_occurs,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_RELEASE = PROJECT_ROOT / "corpus" / "releases" / "v1.json"
DEFAULT_ENGLISH_ALIASES = (
    PROJECT_ROOT / "corpus" / "glossary" / "story-english-aliases-v1.json"
)
DEFAULT_SOURCE_LANGUAGE = "ja"
DEFAULT_TARGET_LANGUAGE = "zh-CN"
DEFAULT_WORKERS = 4
DEFAULT_TIMEOUT = 30

_STRUCTURAL_TOKEN = re.compile(
    r"\$[A-Za-z]"
    r"|%(?:\d+\$)?[diouxXeEfFgGcrsa]"
    r"|\{[0-9A-Fa-f]{2}\}"
    r"|<[A-Za-z0-9_]+:[0-9A-Fa-f]{2}>"
    r"|●+"
)
_KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\u30fd-\u30ff\u31f0-\u31ff]")
_ASCII_QUOTES = re.compile(r'"([^"\n]*)"')
_PUNCT_SPACE = re.compile(r"\s+([，。！？；：、,.!?;:…])")
_CLOSE_SPACE = re.compile(r"\s+([”’）》】〕〉」』])")
_OPEN_SPACE = re.compile(r"([“‘《【〔〈「『])\s+")
_DUPLICATE_SPACE = re.compile(r"[ \t]{2,}")
_CJK_SPACE = re.compile(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF·]) +(?=[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF·])")
_CJK_PUNCT_SPACE = re.compile(
    r"(?<=[\u3400-\u4dbf\u4e00-\u9fff\uF900-\uFAFF·]) +(?=[，。！？；：、,.!?;:…])"
)


class MachineDraftError(ValueError):
    """The draft could not be produced without losing source structure."""


def _load_upstream_story(path: Path) -> dict[str, object]:
    """Load the read-only English reference for one upstream story XML.

    The pointer offset is the stable join key between ``STAGE.BIN`` and the
    upstream XML.  The English project is a reference input only: this
    command never writes to it and never executes any upstream binary.
    """

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise MachineDraftError(f"invalid upstream story XML: {path}: {error}") from error

    english_by_pointer: dict[int, str] = {}
    duplicate_pointers: list[int] = []
    for entry in root.findall("./Strings/Entry"):
        raw_pointer = (entry.findtext("PointerOffset") or "").strip()
        english = (entry.findtext("EnglishText") or "").strip()
        if not raw_pointer or not english:
            continue
        try:
            pointer = int(raw_pointer, 10)
        except ValueError as error:
            raise MachineDraftError(
                f"invalid upstream PointerOffset {raw_pointer!r}: {path}"
            ) from error
        prior = english_by_pointer.get(pointer)
        if prior is not None and prior != english:
            duplicate_pointers.append(pointer)
            # Keep the first translation in document order.  The conflict is
            # reported in the draft metadata rather than silently overwritten.
            continue
        english_by_pointer[pointer] = english

    english_speakers: dict[int, str] = {}
    for entry in root.findall("./Speakers/Entry"):
        raw_id = (entry.findtext("Id") or "").strip()
        english = (entry.findtext("EnglishText") or "").strip()
        if not raw_id or not english:
            continue
        try:
            speaker_id = int(raw_id, 10)
        except ValueError as error:
            raise MachineDraftError(
                f"invalid upstream speaker Id {raw_id!r}: {path}"
            ) from error
        english_speakers.setdefault(speaker_id, english)

    return {
        "path": path.resolve(),
        "english_by_pointer": english_by_pointer,
        "english_speakers": english_speakers,
        "duplicate_pointers": tuple(sorted(set(duplicate_pointers))),
    }


def _upstream_story_path(story_dir: Path, stage: int) -> Path:
    for filename in (f"{stage:03d}.xml", f"{stage}.xml"):
        candidate = story_dir / filename
        if candidate.is_file():
            return candidate
    raise MachineDraftError(
        f"upstream story XML not found for stage {stage:03d}: {story_dir}"
    )


def _load_speaker_translations(stage: int) -> dict[int, str]:
    path = PROJECT_ROOT / "corpus" / "zh" / "story-speakers.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MachineDraftError(f"cannot load speaker translations: {path}") from error
    result: dict[int, str] = {}
    for entry in document.get("entries", ()):
        if not isinstance(entry, Mapping):
            continue
        parts = str(entry.get("id", "")).split("/")
        if len(parts) != 4 or parts[:2] != ["story", f"{stage:03d}"]:
            continue
        try:
            speaker_id = int(parts[-1], 10)
        except ValueError:
            continue
        translation = str(entry.get("translation", "")).strip()
        if translation:
            result[speaker_id] = translation
    return result


def _load_english_aliases(path: Path) -> tuple[tuple[str, str, str], ...]:
    """Load exact English-to-Chinese aliases used by the upstream reference.

    These aliases are deliberately kept in data rather than embedded in the
    translator.  They are only applied when an upstream English string is
    selected, and therefore cannot accidentally alter Japanese-source drafts.
    Matching remains case-sensitive: generic English words must not be
    rewritten merely because they resemble a character or unit name.
    """

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MachineDraftError(f"cannot load English alias glossary: {path}") from error
    if not isinstance(document, Mapping) or document.get("schema_version") != 1:
        raise MachineDraftError(f"invalid English alias glossary schema: {path}")
    raw_terms = document.get("terms")
    if not isinstance(raw_terms, list):
        raise MachineDraftError(f"English alias glossary terms must be an array: {path}")
    aliases: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()
    seen_sources: set[str] = set()
    for index, raw in enumerate(raw_terms):
        if not isinstance(raw, Mapping):
            raise MachineDraftError(f"English alias term {index} must be an object: {path}")
        term_id = str(raw.get("id", "")).strip()
        translation = str(raw.get("translation", "")).strip()
        source_terms = raw.get("source_terms")
        if not term_id or not translation or not isinstance(source_terms, list):
            raise MachineDraftError(f"malformed English alias term {index}: {path}")
        if term_id in seen_ids:
            raise MachineDraftError(f"duplicate English alias id {term_id!r}: {path}")
        seen_ids.add(term_id)
        for source_term in source_terms:
            source_term = str(source_term).strip()
            if len(source_term) <= 1:
                raise MachineDraftError(
                    f"English alias source term is too short at {index}: {path}"
                )
            if source_term in seen_sources:
                raise MachineDraftError(
                    f"duplicate English alias source term {source_term!r}: {path}"
                )
            seen_sources.add(source_term)
            aliases.append((source_term, translation, term_id))
    return tuple(sorted(aliases, key=lambda item: (-len(item[0]), item[0], item[2])))


def _source_pointer(entry: Mapping[str, object]) -> int | None:
    provenance = entry.get("provenance")
    if not isinstance(provenance, Mapping):
        return None
    raw_pointer = provenance.get("pointer_offset")
    try:
        return int(raw_pointer) if raw_pointer is not None else None
    except (TypeError, ValueError):
        return None


def _speaker_alias_terms(
    upstream: Mapping[str, object],
    speaker_translations: Mapping[int, str],
) -> tuple[tuple[str, str, str], ...]:
    english_speakers = upstream.get("english_speakers", {})
    if not isinstance(english_speakers, Mapping):
        return ()
    terms: list[tuple[str, str, str]] = []
    for raw_id, english in english_speakers.items():
        try:
            speaker_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        canonical = str(speaker_translations.get(speaker_id, "")).strip()
        english = str(english).strip()
        if len(english) > 1 and canonical and english != canonical:
            terms.append((english, canonical, f"speaker/{speaker_id:03d}"))
    return tuple(sorted(terms, key=lambda item: (-len(item[0]), item[0])))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "ignored JSON destination under work/; defaults to "
            "work/review/story-dialogue-stage-NNN-machine-draft.json"
        ),
    )
    parser.add_argument("--source-language", default=DEFAULT_SOURCE_LANGUAGE)
    parser.add_argument("--target-language", default=DEFAULT_TARGET_LANGUAGE)
    parser.add_argument(
        "--upstream-story-dir",
        type=Path,
        help=(
            "read-only upstream story XML directory; when supplied, use a "
            "matched EnglishText by STAGE.BIN pointer offset and fall back "
            "to Japanese for entries without an English match"
        ),
    )
    parser.add_argument(
        "--english-aliases",
        type=Path,
        default=DEFAULT_ENGLISH_ALIASES,
        help=(
            "data-driven exact English aliases to protect when using the "
            "read-only upstream reference"
        ),
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--line-width", type=int, default=24)
    parser.add_argument("--max-lines", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _work_output(path: Path) -> Path:
    resolved = _project_path(path).resolve()
    try:
        resolved.relative_to(WORK_ROOT.resolve())
    except ValueError as error:
        raise MachineDraftError(f"output must stay under {WORK_ROOT}") from error
    return resolved


def _source_groups(
    source_entries: Sequence[Mapping[str, object]],
    stage: int,
) -> list[tuple[str, str, list[Mapping[str, object]]]]:
    groups: dict[str, list[Mapping[str, object]]] = {}
    order: list[str] = []
    for entry in source_entries:
        if (
            entry.get("domain") != "story"
            or entry.get("kind") != "dialogue"
            or entry.get("scope_index") != stage
        ):
            continue
        source_hash = str(entry["source_text_sha256"])
        if source_hash not in groups:
            groups[source_hash] = []
            order.append(source_hash)
        groups[source_hash].append(entry)
    return [(source_hash, str(groups[source_hash][0]["source_text"]), groups[source_hash]) for source_hash in order]


def _term_candidates(
    source_text: str,
    glossary: Sequence[GlossaryTerm],
) -> list[tuple[str, str, str]]:
    """Return (source term, canonical translation, term id), longest first."""

    candidates: dict[str, tuple[str, str]] = {}
    for term in glossary:
        if "story" not in term.domains or not term_occurs(term, source_text):
            continue
        for source_term in term.source_terms:
            if len(source_term) <= 1 or source_term not in source_text:
                continue
            # Existing v1 term order is authoritative when aliases overlap.
            candidates.setdefault(source_term, (term.translation, term.term_id))
    return [
        (source_term, translation, term_id)
        for source_term, (translation, term_id) in sorted(
            candidates.items(), key=lambda item: (-len(item[0]), item[0])
        )
    ]


def _protect_source(
    source_text: str,
    glossary: Sequence[GlossaryTerm],
    *,
    glossary_source_text: str | None = None,
    extra_terms: Sequence[tuple[str, str, str]] = (),
) -> tuple[str, dict[str, str], tuple[str, ...]]:
    """Replace glossary terms and structural tokens with opaque placeholders."""

    protected: dict[str, str] = {}
    term_ids: list[str] = []
    current = source_text.replace("\r\n", "\n").replace("\r", "\n")
    # Source newlines are authoring/layout hints, not sentence boundaries for
    # the translation service.  Reflow will choose the final 24-cell breaks
    # after translation.  Keeping them here makes Google join clauses in the
    # wrong order surprisingly often.
    current = re.sub(r"\n[　 \t]*", " ", current).replace("　", " ")
    next_id = 0

    def replace_matches(pattern: re.Pattern[str], values: Mapping[str, str] | None = None) -> None:
        nonlocal current, next_id

        def replace(match: re.Match[str]) -> str:
            nonlocal next_id
            key = f"SRWZTERM{next_id:04d}"
            next_id += 1
            protected[key] = values[match.group(0)] if values is not None else match.group(0)
            return key

        current = pattern.sub(replace, current)

    # Runtime controls must be protected before glossary text is matched.
    replace_matches(_STRUCTURAL_TOKEN)
    term_source = glossary_source_text if glossary_source_text is not None else source_text
    glossary_candidates = _term_candidates(term_source, glossary)
    for source_term, translation, term_id in glossary_candidates:
        if source_term not in current:
            continue
        key = f"SRWZTERM{next_id:04d}"
        next_id += 1
        protected[key] = translation
        term_ids.append(term_id)
        current = current.replace(source_term, key)
    for source_term, translation, term_id in sorted(
        extra_terms,
        key=lambda item: (-len(item[0]), item[0], item[2]),
    ):
        if len(source_term) <= 1 or source_term not in current:
            continue
        key = f"SRWZTERM{next_id:04d}"
        next_id += 1
        protected[key] = translation
        term_ids.append(term_id)
        current = current.replace(source_term, key)
    return current, protected, tuple(dict.fromkeys(term_ids))


def _restore_protected(text: str, protected: Mapping[str, str]) -> tuple[str, tuple[str, ...]]:
    missing = tuple(key for key in protected if key not in text)
    restored = text
    for key, value in protected.items():
        restored = restored.replace(key, value)
    return restored, missing


def _google_translate(
    text: str,
    *,
    source_language: str,
    target_language: str,
    timeout: int,
) -> str:
    url = (
        "https://translate.googleapis.com/translate_a/single?client=gtx"
        f"&sl={quote(source_language)}&tl={quote(target_language)}&dt=t&q={quote(text)}"
    )
    request = Request(url, headers={"User-Agent": "srwz-zh-machine-draft/1"})
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            pieces = payload[0]
            result = "".join(str(piece[0]) for piece in pieces if piece and piece[0])
            if not result:
                raise MachineDraftError("translation endpoint returned an empty result")
            return result
        except Exception as error:  # pragma: no cover - network failures are environment-specific.
            last_error = error
            if attempt < 3:
                time.sleep(0.5 * (attempt + 1))
    raise MachineDraftError(f"translation endpoint failed: {last_error}")


def _normalize_translation(text: str) -> str:
    value = text.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("「", "“").replace("」", "”")
    value = value.replace("『", "“").replace("』", "”")
    value = _ASCII_QUOTES.sub(lambda match: f"“{match.group(1)}”", value)
    value = value.replace("...", "……")
    value = _PUNCT_SPACE.sub(r"\1", value)
    value = _CLOSE_SPACE.sub(r"\1", value)
    value = _OPEN_SPACE.sub(r"\1", value)
    value = re.sub(r"[ \t]*\n[ \t]*", "\n", value)
    # Google commonly inserts spaces around an opaque alias token.  Once the
    # token is restored, remove only spaces that are unambiguously internal
    # to Chinese text; keep spaces between ordinary Latin words intact.
    value = _CJK_SPACE.sub("", value)
    value = _CJK_PUNCT_SPACE.sub("", value)
    value = _DUPLICATE_SPACE.sub(" ", value)
    return value.strip(" \t\n")


def _restore_dialogue_quote_shape(source_text: str, translation: str) -> str:
    """Keep the game's Japanese dialogue quote shape in Chinese output.

    Upstream English XML intentionally omits the Japanese corner quotes, but
    the in-game text uses them as part of the dialogue presentation.  Restore
    a single Chinese pair only when the source has a complete outer pair; do
    not invent quotes for unquoted controls or fragments.
    """

    source = source_text.strip()
    value = translation.strip()
    if not value:
        return value
    starts_quoted = source.startswith(("「", "『"))
    ends_quoted = source.endswith(("」", "』"))
    if not (starts_quoted and ends_quoted):
        return value
    if value.startswith(("“", "‘", "「", "『")):
        left_ok = True
    else:
        left_ok = False
        value = "“" + value
    if value.endswith(("”", "’", "」", "』")):
        right_ok = True
    else:
        right_ok = False
        value = value + "”"
    # Keep the variables explicit so a future quote policy can distinguish a
    # source with already-normalized opening/closing punctuation.
    _ = left_ok, right_ok
    return value


def _translate_one(
    source_text: str,
    glossary: Sequence[GlossaryTerm],
    *,
    translation_input: str,
    glossary_source_text: str | None,
    extra_terms: Sequence[tuple[str, str, str]],
    source_language: str,
    target_language: str,
    timeout: int,
    line_width: int,
    max_lines: int,
) -> dict[str, object]:
    protected_source, protected, term_ids = _protect_source(
        translation_input,
        glossary,
        glossary_source_text=glossary_source_text,
        extra_terms=extra_terms,
    )
    translated = _google_translate(
        protected_source,
        source_language=source_language,
        target_language=target_language,
        timeout=timeout,
    )
    restored, missing = _restore_protected(translated, protected)
    normalized = _normalize_translation(restored)
    normalized = _restore_dialogue_quote_shape(source_text, normalized)
    layout_error = ""
    try:
        protected_terms = tuple(
            value for value in protected.values() if len(value) > 1 and "\n" not in value
        )
        normalized = reflow_chinese_dialogue(
            normalized,
            protected_terms=protected_terms,
            line_width=line_width,
            max_lines=max_lines,
        ).text
    except (ChineseLayoutError, AssertionError) as error:
        layout_error = str(error)
    return {
        "translation": normalized,
        "glossary_term_ids": list(term_ids),
        "missing_placeholders": list(missing),
        "layout_error": layout_error,
        "kana_residue": bool(_KANA.search(normalized)),
        "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "translation_input_sha256": hashlib.sha256(
            translation_input.encode("utf-8")
        ).hexdigest(),
    }


def main() -> int:
    args = parse_args()
    if args.stage < 0:
        raise MachineDraftError("--stage must be non-negative")
    if args.workers <= 0 or args.workers > 16:
        raise MachineDraftError("--workers must be between 1 and 16")
    output = _work_output(
        args.output
        or WORK_ROOT / "review" / f"story-dialogue-stage-{args.stage:03d}-machine-draft.json"
    )
    if output.exists() and not args.force:
        raise MachineDraftError(f"output exists; use --force: {output}")

    release = json.loads(_project_path(args.release).read_text(encoding="utf-8"))
    source_config = release.get("source_corpus")
    if not isinstance(source_config, dict):
        raise MachineDraftError("release has no source_corpus object")
    source_path = _project_path(Path(str(source_config["path"])))
    source_entries = load_source_corpus(source_path)
    glossary_paths = [
        _project_path(Path(str(raw))) for raw in release.get("glossary_sources", ())
    ]
    glossary = load_glossary(glossary_paths)
    groups = _source_groups(source_entries, args.stage)
    if not groups:
        raise MachineDraftError(f"no story dialogue found for stage {args.stage:03d}")

    upstream: dict[str, object] | None = None
    upstream_path: Path | None = None
    speaker_aliases: tuple[tuple[str, str, str], ...] = ()
    english_aliases: tuple[tuple[str, str, str], ...] = ()
    speaker_translations: dict[int, str] = {}
    if args.upstream_story_dir is not None:
        upstream_dir = _project_path(args.upstream_story_dir).resolve()
        if not upstream_dir.is_dir():
            raise MachineDraftError(
                f"upstream story directory is not a directory: {upstream_dir}"
            )
        upstream_path = _upstream_story_path(upstream_dir, args.stage)
        upstream = _load_upstream_story(upstream_path)
        speaker_translations = _load_speaker_translations(args.stage)
        speaker_aliases = _speaker_alias_terms(upstream, speaker_translations)
        english_aliases = _load_english_aliases(
            _project_path(args.english_aliases).resolve()
        )

    # Plan the language/source for each unique Japanese string before making
    # network calls.  Pointer matches are deterministic even when a repeated
    # Japanese string has different translations at different locations.
    plans: list[dict[str, object]] = []
    for source_hash, source_text, group in groups:
        translation_input = source_text
        source_language = args.source_language
        translation_source = "japanese_source"
        matched: list[tuple[int, str]] = []
        if upstream is not None:
            english_by_pointer = upstream.get("english_by_pointer", {})
            if isinstance(english_by_pointer, Mapping):
                for entry in group:
                    pointer = _source_pointer(entry)
                    if pointer is None:
                        continue
                    english = str(english_by_pointer.get(pointer, "")).strip()
                    if english:
                        matched.append((pointer, english))
            if matched:
                translation_input = matched[0][1]
                source_language = "en"
                translation_source = "upstream_english"
        plans.append(
            {
                "source_hash": source_hash,
                "source_text": source_text,
                "translation_input": translation_input,
                "source_language": source_language,
                "translation_source": translation_source,
                "matched_pointers": [pointer for pointer, _ in matched],
                "matched_texts": [text for _, text in matched],
            }
        )

    results: list[dict[str, object] | None] = [None] * len(plans)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                _translate_one,
                plan["source_text"],
                glossary,
                translation_input=plan["translation_input"],
                glossary_source_text=plan["source_text"],
                extra_terms=english_aliases + speaker_aliases,
                source_language=plan["source_language"],
                target_language=args.target_language,
                timeout=args.timeout,
                line_width=args.line_width,
                max_lines=args.max_lines,
            ): index
            for index, plan in enumerate(plans)
        }
        for future in as_completed(futures):
            index = futures[future]
            result = future.result()
            plan = plans[index]
            result["translation_source"] = plan["translation_source"]
            result["source_language"] = plan["source_language"]
            result["matched_pointers"] = plan["matched_pointers"]
            result["source_hash"] = plan["source_hash"]
            result["upstream_pointer_conflict"] = len(
                set(plan["matched_texts"])
            ) > 1
            results[index] = result

    assert all(result is not None for result in results)
    complete = [result for result in results if result is not None]
    translations = [str(result["translation"]) for result in complete]
    notes_by_index = {
        str(index): "; ".join(
            note
            for note in (
                f"missing placeholders: {result['missing_placeholders']}"
                if result["missing_placeholders"]
                else "",
                f"layout: {result['layout_error']}"
                if result["layout_error"]
                else "",
                "machine output contains Japanese kana"
                if result["kana_residue"]
                else "",
            )
            if note
        )
        for index, result in enumerate(complete)
        if result["missing_placeholders"] or result["layout_error"] or result["kana_residue"]
    }
    glossary_refs_by_index = {
        str(index): result["glossary_term_ids"]
        for index, result in enumerate(complete)
        if result["glossary_term_ids"]
    }
    translation_source_by_index = {
        str(index): result["translation_source"]
        for index, result in enumerate(complete)
    }
    upstream_pointer_by_index = {
        str(index): result["matched_pointers"]
        for index, result in enumerate(complete)
        if result["matched_pointers"]
    }
    source_counts: dict[str, int] = {}
    language_counts: dict[str, int] = {}
    for result in complete:
        source_kind = str(result["translation_source"])
        source_counts[source_kind] = source_counts.get(source_kind, 0) + 1
        language = str(result["source_language"])
        language_counts[language] = language_counts.get(language, 0) + 1
    upstream_conflict_count = sum(
        bool(result["upstream_pointer_conflict"]) for result in complete
    )
    document = {
        "schema_version": 1,
        "draft_kind": "machine_translation_review",
        "stage_index": args.stage,
        "editorial_status": "draft",
        "source_corpus": {
            "path": str(source_path.relative_to(PROJECT_ROOT)),
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "entry_count": sum(len(group[2]) for group in groups),
            "unique_source_text_count": len(groups),
        },
        "translation_provider": {
            "name": "Google Translate web endpoint",
            "endpoint": "https://translate.googleapis.com/translate_a/single",
            "source_language": (
                next(iter(language_counts))
                if len(language_counts) == 1
                else "mixed"
            ),
            "target_language": args.target_language,
            "tool_version": 1,
        },
        "upstream_reference": (
            {
                "story_xml": str(upstream_path)
                if upstream_path is not None
                else None,
                "sha256": hashlib.sha256(upstream_path.read_bytes()).hexdigest()
                if upstream_path is not None
                else None,
                "pointer_translation_count": len(
                    upstream.get("english_by_pointer", {})
                )
                if upstream is not None
                else 0,
                "speaker_translation_count": len(speaker_aliases),
                "english_alias_count": len(english_aliases),
                "duplicate_pointers": list(
                    upstream.get("duplicate_pointers", ())
                    if upstream is not None
                    else ()
                ),
            }
            if upstream_path is not None
            else None
        ),
        "layout_policy": {
            "line_width": args.line_width,
            "max_lines": args.max_lines,
            "reflow": "tools.srwz.chinese_layout.reflow_chinese_dialogue",
        },
        "translations": translations,
        "glossary_refs_by_index": glossary_refs_by_index,
        "notes_by_index": notes_by_index,
        "translation_source_by_index": translation_source_by_index,
        "upstream_pointer_by_index": upstream_pointer_by_index,
        "machine_audit": {
            "missing_placeholder_count": sum(bool(result["missing_placeholders"]) for result in complete),
            "layout_error_count": sum(bool(result["layout_error"]) for result in complete),
            "kana_residue_count": sum(bool(result["kana_residue"]) for result in complete),
            "source_hashes": [source_hash for source_hash, _, _ in groups],
            "translation_source_counts": source_counts,
            "source_language_counts": language_counts,
            "upstream_pointer_match_count": sum(
                bool(result["matched_pointers"]) for result in complete
            ),
            "upstream_pointer_conflict_count": upstream_conflict_count,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"machine draft: stage={args.stage:03d} entries={document['source_corpus']['entry_count']} "
        f"unique={len(translations)} missing_placeholders={document['machine_audit']['missing_placeholder_count']} "
        f"layout_errors={document['machine_audit']['layout_error_count']} "
        f"kana_residue={document['machine_audit']['kana_residue_count']}"
    )
    print(f"draft: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, MachineDraftError, TranslationReviewError) as error:
        print(f"machine draft failed: {error}", file=sys.stderr)
        raise SystemExit(1)
