#!/usr/bin/env python3
"""Build the reviewed v0.2 ZKAN translations into fixed-span members."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
from typing import Mapping

from srwz.chinese_layout import (
    ChineseLayoutProfile,
    load_layout_profiles,
    load_release_protected_terms,
    reflow_chinese_paragraph,
    rendered_line_width,
    tokenize_dialogue,
)
from srwz.codec import decode_production as decode, reencode_changed_suffix
from srwz.iso_layout import ExecutableOffsetSpec, read_executable_archive_offsets
from srwz.font_flavor import load_font_flavor_reference
from srwz.library import (
    LibraryScopeError,
    build_runtime_zkn_decoded_chunk,
    parse_runtime_zkn_decoded_chunk,
    parse_zkn_decoded_chunk,
    validate_library_scope_mapping,
)
from srwz.library_menu import build_jtim_library_menu
from srwz.text import (
    load_text_table,
    original_fullwidth_ascii_overrides,
    project_runtime_text_table,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/library/v0.2-reviewed-writeback.json"
ARCHIVES = (
    ("robot", "DATA/MTVZKNRT.BIN", "ROBO"),
    ("character", "DATA/MTVZKNPT.BIN", "CHAR"),
    ("glossary", "DATA/MTVZKNKW.BIN", "KYWD"),
)
BODY_TAGS = frozenset({"DSCR", "DSC2"})
BREAK_END = frozenset("。！？!?，、；：,;:…—")
CLOSING = frozenset("，。！？；：、,.!?;:％%”’）》】〕〉」』…—")
OPENING = frozenset("“‘（《【〔〈「『")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument(
        "--audit-capacity",
        action="store_true",
        help="Report every over-budget fixed chunk without writing components.",
    )
    return parser.parse_args()


def project_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else PROJECT_ROOT / path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_lock(path: Path, data: bytes | None = None) -> dict[str, object]:
    payload = path.read_bytes() if data is None else data
    return {
        "path": str(path.resolve().relative_to(PROJECT_ROOT)),
        "size": len(payload),
        "sha256": sha256_bytes(payload),
    }


def load_json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise SystemExit(f"unsupported JSON contract: {path}")
    return document


def locked_member(path: Path, lock: Mapping[str, object], label: str) -> bytes:
    data = path.read_bytes()
    if len(data) != lock.get("size") or sha256_bytes(data) != lock.get("sha256"):
        raise SystemExit(f"{label} size or SHA-256 drift")
    return data


def font_mapping(manifest: dict) -> tuple[Path, object, dict[str, int], dict[str, int]]:
    proposal_ref = manifest.get("proposal")
    if not isinstance(proposal_ref, dict):
        raise SystemExit("release font manifest has no proposal")
    proposal_path = project_path(proposal_ref.get("path"))
    proposal_data = proposal_path.read_bytes()
    if (
        len(proposal_data) != proposal_ref.get("size")
        or sha256_bytes(proposal_data) != proposal_ref.get("sha256")
    ):
        raise SystemExit("release font proposal lock drift")
    proposal = load_json(proposal_path)

    def mapping(rows: object, label: str) -> dict[str, int]:
        if not isinstance(rows, list):
            raise SystemExit(f"font {label} mapping is malformed")
        result = {}
        used = set()
        for row in rows:
            if not isinstance(row, dict):
                raise SystemExit(f"font {label} row is malformed")
            character = row.get("character")
            try:
                code = int(str(row.get("code")), 16)
            except ValueError as exc:
                raise SystemExit(f"font {label} code is malformed") from exc
            if not isinstance(character, str) or len(character) != 1:
                raise SystemExit(f"font {label} character is malformed")
            if character in result or code in used:
                raise SystemExit(f"font {label} mapping is not one-to-one")
            result[character] = code
            used.add(code)
        return result

    primary = mapping(proposal.get("assignments"), "primary")
    aliases = mapping(proposal.get("surface_alias_assignments", []), "alias")
    table_ref = manifest.get("inputs", {}).get("text_table")
    if not isinstance(table_ref, dict):
        raise SystemExit("release font manifest has no text table")
    table_path = project_path(table_ref.get("path"))
    table_data = table_path.read_bytes()
    if (
        len(table_data) != table_ref.get("size")
        or sha256_bytes(table_data) != table_ref.get("sha256")
    ):
        raise SystemExit("release font text-table lock drift")
    return proposal_path, load_text_table(table_path), primary, aliases


def reflow_body(
    text: str,
    width: int,
    *,
    profile: ChineseLayoutProfile | None = None,
    protected_terms: tuple[str, ...] = (),
) -> tuple[str, tuple[int, ...]]:
    if profile is not None:
        if profile.maximum_width != width or profile.line_count_mode != "minimum":
            raise LibraryScopeError(
                f"LIBRARY layout profile/width drift: {profile.profile_id}"
            )
        logical = text.replace("\r", "").replace("\n", "")
        try:
            result = reflow_chinese_paragraph(
                logical,
                profile=profile,
                protected_terms=protected_terms,
            )
        except ValueError as error:
            raise LibraryScopeError(str(error)) from error
        if result.text.replace("\n", "") != logical:
            raise LibraryScopeError("LIBRARY balanced reflow changed content")
        return result.text, result.line_widths

    logical = text.replace("\r", "").replace("\n", "")
    tokens = list(tokenize_dialogue(logical))
    lines: list[str] = []
    while tokens:
        used = 0
        end = 0
        for index, token in enumerate(tokens, start=1):
            if used + token.width > width:
                break
            used += token.width
            end = index
        if end == 0:
            # The shared dialogue tokenizer deliberately keeps ASCII words and
            # bracketed titles together.  LIBRARY prose has no such atomicity
            # requirement: a long quoted move/title may wrap visually inside
            # the token, just as the original Japanese fields do.
            token_text = tokens[0].text
            split_at = 0
            for position, _character in enumerate(token_text, start=1):
                if rendered_line_width(token_text[:position]) > width:
                    break
                split_at = position
            if split_at <= 0:
                raise LibraryScopeError(
                    f"LIBRARY glyph exceeds {width} cells: {token_text!r}"
                )
            lines.append(token_text[:split_at])
            tokens = [
                *tokenize_dialogue(token_text[split_at:]),
                *tokens[1:],
            ]
            continue
        while end > 1 and tokens[end - 1].text[-1] in OPENING:
            end -= 1
        if end < len(tokens) and tokens[end].text[0] in CLOSING:
            if sum(token.width for token in tokens[: end + 1]) <= width:
                end += 1
            elif end > 1:
                # Keep a closing mark with the character before it instead of
                # leaving punctuation alone at the start of the next line.
                end -= 1
                while end > 1 and tokens[end - 1].text[-1] in OPENING:
                    end -= 1
        line = "".join(token.text for token in tokens[:end])
        lines.append(line)
        tokens = tokens[end:]
    result = "\n".join(lines)
    widths = tuple(rendered_line_width(line) for line in lines)
    if "".join(lines) != logical or max(widths, default=0) > width:
        raise LibraryScopeError(
            "LIBRARY body reflow changed content or exceeded width: "
            f"content_exact={''.join(lines) == logical} widths={widths} "
            f"lines={lines!r}"
        )
    return result, widths


def reflow_body_legacy(text: str, width: int) -> tuple[str, tuple[int, ...]]:
    """Preserve the older punctuation-biased wrap as a capacity fallback."""

    logical = text.replace("\r", "").replace("\n", "")
    tokens = list(tokenize_dialogue(logical))
    lines: list[str] = []
    while tokens:
        used = 0
        end = 0
        last_preferred = 0
        for index, token in enumerate(tokens, start=1):
            if used + token.width > width:
                break
            used += token.width
            end = index
            if token.text and token.text[-1] in BREAK_END:
                last_preferred = index
        if end == 0:
            token_text = tokens[0].text
            split_at = 0
            for position, _character in enumerate(token_text, start=1):
                if rendered_line_width(token_text[:position]) > width:
                    break
                split_at = position
            if split_at <= 0:
                raise LibraryScopeError(
                    f"LIBRARY glyph exceeds {width} cells: {token_text!r}"
                )
            lines.append(token_text[:split_at])
            tokens = [
                *tokenize_dialogue(token_text[split_at:]),
                *tokens[1:],
            ]
            continue
        if end < len(tokens) and last_preferred and used >= width - 4:
            end = last_preferred
        while end > 1 and tokens[end - 1].text[-1] in OPENING:
            end -= 1
        if end < len(tokens) and tokens[end].text[0] in CLOSING:
            if sum(token.width for token in tokens[: end + 1]) <= width:
                end += 1
        line = "".join(token.text for token in tokens[:end])
        lines.append(line)
        tokens = tokens[end:]
    result = "\n".join(lines)
    widths = tuple(rendered_line_width(line) for line in lines)
    if "".join(lines) != logical or max(widths, default=0) > width:
        raise LibraryScopeError(
            "LIBRARY legacy body reflow changed content or exceeded width: "
            f"content_exact={''.join(lines) == logical} widths={widths} "
            f"lines={lines!r}"
        )
    return result, widths


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_production_layout(
    layout: dict,
    widths: dict,
) -> tuple[
    dict[str, ChineseLayoutProfile],
    tuple[str, ...],
    Path,
    Path,
    tuple[Path, ...],
]:
    profile_path = project_path(layout.get("profile_config"))
    release_path = project_path(layout.get("protected_term_release"))
    raw_profile_ids = layout.get("body_profiles")
    if not isinstance(raw_profile_ids, dict) or set(raw_profile_ids) != {
        "ROBO",
        "CHAR",
        "KYWD",
    }:
        raise SystemExit("LIBRARY body-profile inventory drift")
    profiles = load_layout_profiles(profile_path)
    selected = {}
    for kind, profile_id in raw_profile_ids.items():
        profile = profiles.get(profile_id)
        if (
            profile is None
            or profile.maximum_width != widths.get(kind)
            or profile.maximum_lines is not None
            or profile.line_count_mode != "minimum"
        ):
            raise SystemExit(f"LIBRARY layout profile drift: {kind}")
        selected[kind] = profile
    protected_terms = load_release_protected_terms(
        release_path,
        project_root=PROJECT_ROOT,
    )
    release = load_json(release_path)
    glossary_paths = tuple(
        project_path(raw_path)
        for raw_path in release.get("glossary_sources", ())
    )
    if not glossary_paths:
        raise SystemExit("LIBRARY protected-term glossary inventory is empty")
    return (
        selected,
        protected_terms,
        profile_path,
        release_path,
        glossary_paths,
    )


def main() -> int:
    args = parse_args()
    if args.workers <= 0:
        raise SystemExit("workers must be positive")
    config_path = args.config.resolve()
    config = load_json(config_path)
    if (
        config.get("profile_id") != "library-v0.2-reviewed-release"
        or config.get("status") != "reviewed"
        or config.get("release_eligible") is not True
    ):
        raise SystemExit("LIBRARY reviewed writeback identity drift")
    scope_path = project_path(config.get("scope_config"))
    scope = load_json(scope_path)
    validate_library_scope_mapping(scope)
    locks = scope.get("source_member_locks")
    if not isinstance(locks, dict):
        raise SystemExit("LIBRARY source-member locks are missing")

    corpus_ref = config.get("corpus")
    if not isinstance(corpus_ref, dict):
        raise SystemExit("LIBRARY reviewed corpus reference is missing")
    corpus_path = project_path(corpus_ref.get("path"))
    corpus = load_json(corpus_path)
    entries = corpus.get("entries")
    summary = corpus.get("summary")
    if (
        corpus.get("status") != "reviewed"
        or corpus.get("release_eligible") is not True
        or not isinstance(entries, list)
        or not isinstance(summary, dict)
        or len(entries) != corpus_ref.get("expected_entry_count")
        or summary.get("field_reference_count")
        != corpus_ref.get("expected_field_reference_count")
        or summary.get("human_reviewed_count")
        != corpus_ref.get("expected_human_reviewed_count")
        or summary.get("deterministic_reviewed_count")
        != corpus_ref.get("expected_deterministic_reviewed_count")
    ):
        raise SystemExit("LIBRARY reviewed corpus contract drift")
    translation_by_hash = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("LIBRARY corpus entry is malformed")
        source_hash = entry.get("source_text_sha256")
        translation = entry.get("translation")
        if (
            not isinstance(source_hash, str)
            or len(source_hash) != 64
            or not isinstance(translation, str)
            or not translation
            or source_hash in translation_by_hash
        ):
            raise SystemExit("LIBRARY corpus entry identity drift")
        translation_by_hash[source_hash] = translation

    font_manifest_path = project_path(config.get("font_manifest"))
    font_manifest = load_json(font_manifest_path)
    if font_manifest.get("status") != (
        "offline_global_zh_release_font_coverage_passed_runtime_pending"
    ):
        raise SystemExit("LIBRARY build requires the validated release font")
    proposal_path, base_table, primary, aliases = font_mapping(font_manifest)
    encoding_overrides = dict(primary)
    encoding_overrides.update(aliases)
    encoding_overrides.update(original_fullwidth_ascii_overrides(base_table))
    encoding_overrides[" "] = ord(" ")
    runtime_table = project_runtime_text_table(base_table, primary)
    runtime_table = project_runtime_text_table(runtime_table, aliases)
    runtime_table = project_runtime_text_table(
        runtime_table,
        original_fullwidth_ascii_overrides(base_table),
    )

    executable_lock = locks.get("SLPS_258.87")
    if not isinstance(executable_lock, dict):
        raise SystemExit("LIBRARY executable lock is missing")
    executable_path = project_path(executable_lock.get("path"))
    executable = locked_member(executable_path, executable_lock, "SLPS_258.87")
    codec = config.get("codec")
    layout = config.get("layout")
    if not isinstance(codec, dict) or not isinstance(layout, dict):
        raise SystemExit("LIBRARY codec/layout config is missing")
    widths = layout.get("body_line_widths")
    if not isinstance(widths, dict):
        raise SystemExit("LIBRARY body widths are missing")
    (
        layout_profiles,
        protected_terms,
        layout_profile_path,
        layout_release_path,
        layout_glossary_paths,
    ) = load_production_layout(layout, widths)
    alignment = int(layout.get("decoded_alignment", 0))
    output_root = project_path(config["outputs"]["component_root"])
    if output_root.exists() and not args.force:
        raise SystemExit(f"refusing to replace existing output root: {output_root}")

    menu_contract = scope.get("library_menu_tim2")
    menu_member = "DATA/JTIM.BIN"
    menu_member_lock = locks.get(menu_member)
    if not isinstance(menu_contract, dict) or not isinstance(menu_member_lock, dict):
        raise SystemExit("LIBRARY menu source/writeback contract is missing")
    menu_writeback = menu_contract.get("writeback")
    if not isinstance(menu_writeback, dict):
        raise SystemExit("LIBRARY menu writeback contract is missing")
    menu_font_flavor = load_font_flavor_reference(
        PROJECT_ROOT,
        menu_writeback.get("font_flavor"),
    )
    menu_font_flavor_path = project_path(menu_font_flavor["path"])
    menu_font_lock_path = project_path(menu_font_flavor["font_lock"])
    menu_font_lock_data = menu_font_lock_path.read_bytes()
    if sha256_bytes(menu_font_lock_data) != menu_font_flavor["font_lock_sha256"]:
        raise SystemExit("LIBRARY menu font-lock drift")
    menu_font_lock = load_json(menu_font_lock_path)
    menu_font_ref = menu_font_lock.get("font")
    if not isinstance(menu_font_ref, dict):
        raise SystemExit("LIBRARY menu font reference is missing")
    menu_font_path = project_path(menu_font_ref.get("path"))
    menu_font_data = menu_font_path.read_bytes()
    if (
        len(menu_font_data) != menu_font_ref.get("size")
        or sha256_bytes(menu_font_data) != menu_font_ref.get("sha256")
    ):
        raise SystemExit("LIBRARY menu font drift")
    menu_source_path = project_path(menu_member_lock.get("path"))
    menu_source = locked_member(
        menu_source_path,
        menu_member_lock,
        menu_member,
    )
    menu_output, menu_report = build_jtim_library_menu(
        menu_source,
        menu_contract,
        font_path=menu_font_path,
        project_root=PROJECT_ROOT,
    )
    menu_report["font_path"] = str(menu_font_path.relative_to(PROJECT_ROOT))

    archive_reports = []
    capacity_failures = []
    output_payloads: dict[str, bytes] = {menu_member: menu_output}
    used_hashes = set()
    for domain, member, expected_kind in ARCHIVES:
        lock = locks.get(member)
        if not isinstance(lock, dict):
            raise SystemExit(f"LIBRARY source lock is missing: {member}")
        source_path = project_path(lock.get("path"))
        source = locked_member(source_path, lock, member)
        spec = ExecutableOffsetSpec(
            name=member,
            member=member,
            table_start=int(str(lock["slps_table_start"]), 0),
            table_end=int(str(lock["slps_table_end"]), 0),
        )
        offsets = read_executable_archive_offsets(executable, spec, len(source))
        if len(offsets) - 1 != lock.get("expected_chunk_count"):
            raise SystemExit(f"LIBRARY entry-count drift: {member}")

        def build_chunk(item: tuple[int, int, int]) -> tuple[int, bytes, dict]:
            index, start, end = item
            stored = source[start:end]
            decoded = decode(stored)
            if any(stored[decoded.consumed :]):
                raise LibraryScopeError(
                    f"{member} chunk {index} has nonzero trailing bytes"
                )
            document = parse_zkn_decoded_chunk(decoded.output)
            if document.kind != expected_kind:
                raise LibraryScopeError(
                    f"{member} chunk {index} kind drift: {document.kind}"
                )
            replacements = {}
            body_variants = {}
            chunk_hashes = set()
            for field in document.fields:
                if field.text is None:
                    continue
                source_hash = sha256_bytes(field.text.encode("utf-8"))
                if field.text.strip():
                    translation = translation_by_hash.get(source_hash)
                    if translation is None:
                        raise LibraryScopeError(
                            f"missing LIBRARY translation: {domain}/{index:03d}/{field.tag}"
                        )
                    chunk_hashes.add(source_hash)
                else:
                    translation = field.text
                if field.tag in BODY_TAGS:
                    try:
                        dense_text, dense_widths = reflow_body(
                            translation,
                            int(widths[expected_kind]),
                            profile=layout_profiles[expected_kind],
                            protected_terms=protected_terms,
                        )
                        legacy_text, legacy_widths = reflow_body_legacy(
                            translation,
                            int(widths[expected_kind]),
                        )
                    except LibraryScopeError as error:
                        raise LibraryScopeError(
                            f"localized LIBRARY layout failed: "
                            f"{domain}/{index:03d}/{field.tag}: {error}"
                        ) from error
                    body_variants[field.tag] = {
                        "dense": (dense_text, dense_widths),
                        "legacy": (legacy_text, legacy_widths),
                    }
                    translation = dense_text
                replacements[field.tag] = translation

            def rebuild(candidate_replacements: dict[str, str]) -> bytes:
                return build_runtime_zkn_decoded_chunk(
                    document,
                    base_table,
                    candidate_replacements,
                    overrides=encoding_overrides,
                    alignment=alignment,
                )

            def compress(candidate_decoded: bytes) -> bytes:
                return reencode_changed_suffix(
                    stored,
                    candidate_decoded,
                    strategy=str(codec["strategy"]),
                    min_match_length=int(codec["min_match_length"]),
                    max_match_chain=int(codec["max_match_chain"]),
                    lazy_matching=bool(codec["lazy_matching"]),
                    max_output_size=len(stored),
                    original_result=decoded,
                )

            rebuilt_decoded = rebuild(replacements)
            fallback_body_tags: tuple[str, ...] = ()
            try:
                encoded = compress(rebuilt_decoded)
            except (RuntimeError, ValueError) as dense_error:
                encoded = None
                body_tags = sorted(
                    body_variants,
                    key=lambda tag: (tag != "DSC2", tag),
                )
                for fallback_count in range(1, len(body_tags) + 1):
                    for candidate_tags in combinations(
                        body_tags, fallback_count
                    ):
                        candidate_replacements = dict(replacements)
                        for tag in candidate_tags:
                            candidate_replacements[tag] = body_variants[tag][
                                "legacy"
                            ][0]
                        candidate_decoded = rebuild(candidate_replacements)
                        try:
                            candidate_encoded = compress(candidate_decoded)
                        except (RuntimeError, ValueError):
                            continue
                        replacements = candidate_replacements
                        rebuilt_decoded = candidate_decoded
                        encoded = candidate_encoded
                        fallback_body_tags = tuple(candidate_tags)
                        break
                    if encoded is not None:
                        break
                if encoded is not None:
                    dense_error = None

            selected_body_widths = {
                tag: body_variants[tag][
                    "legacy" if tag in fallback_body_tags else "dense"
                ][1]
                for tag in body_variants
            }
            body_line_count = sum(
                len(line_widths)
                for line_widths in selected_body_widths.values()
            )
            maximum_width = max(
                (
                    line_width
                    for line_widths in selected_body_widths.values()
                    for line_width in line_widths
                ),
                default=0,
            )
            expected_text = dict(replacements)
            if encoded is None:
                if args.audit_capacity:
                    unconstrained = reencode_changed_suffix(
                        stored,
                        rebuilt_decoded,
                        strategy=str(codec["strategy"]),
                        min_match_length=int(codec["min_match_length"]),
                        max_match_chain=int(codec["max_match_chain"]),
                        lazy_matching=bool(codec["lazy_matching"]),
                        max_output_size=len(rebuilt_decoded) * 2 + len(stored),
                        original_result=decoded,
                    )
                    return index, stored, {
                        "entry_index": index,
                        "slot_size": len(stored),
                        "source_encoded_size": decoded.consumed,
                        "output_encoded_size": len(unconstrained),
                        "headroom": len(stored) - len(unconstrained),
                        "source_decoded_size": len(decoded.output),
                        "output_decoded_size": len(rebuilt_decoded),
                        "text_field_count": len(expected_text),
                        "body_line_count": body_line_count,
                        "maximum_body_line_width": maximum_width,
                        "capacity_fallback_body_tags": list(
                            fallback_body_tags
                        ),
                        "translation_hashes": sorted(chunk_hashes),
                        "capacity_failure": str(dense_error),
                    }
                raise LibraryScopeError(
                    f"localized LIBRARY compression failed: "
                    f"{domain}/{index:03d} slot={len(stored)} "
                    f"decoded={len(rebuilt_decoded)}: {dense_error}"
                ) from dense_error
            output = encoded + bytes(len(stored) - len(encoded))
            reread_compressed = decode(output)
            reread = parse_runtime_zkn_decoded_chunk(
                reread_compressed.output,
                runtime_table,
            )
            actual_text = {
                field.tag: field.text
                for field in reread.fields
                if field.text is not None
            }
            if actual_text != expected_text:
                raise LibraryScopeError(
                    f"localized LIBRARY reread mismatch: {domain}/{index:03d}"
                )
            source_binary = {
                field.tag: field.data
                for field in document.fields
                if field.text is None
            }
            output_binary = {
                field.tag: field.data
                for field in reread.fields
                if field.text is None
            }
            if output_binary != source_binary:
                raise LibraryScopeError(
                    f"localized LIBRARY binary-field drift: {domain}/{index:03d}"
                )
            return index, output, {
                "entry_index": index,
                "slot_size": len(stored),
                "source_encoded_size": decoded.consumed,
                "output_encoded_size": len(encoded),
                "headroom": len(stored) - len(encoded),
                "source_decoded_size": len(decoded.output),
                "output_decoded_size": len(rebuilt_decoded),
                "text_field_count": len(expected_text),
                "body_line_count": body_line_count,
                "maximum_body_line_width": maximum_width,
                "dense_body_layout": not fallback_body_tags,
                "capacity_fallback_body_tags": list(fallback_body_tags),
                "translation_hashes": sorted(chunk_hashes),
                "codec_round_trip_exact": True,
                "runtime_text_reread_exact": True,
                "binary_fields_preserved": True,
            }

        work = [
            (index, start, end)
            for index, (start, end) in enumerate(zip(offsets, offsets[1:]))
        ]
        with ThreadPoolExecutor(
            max_workers=min(args.workers, len(work)),
            thread_name_prefix=f"library-{domain}",
        ) as executor:
            built = list(executor.map(build_chunk, work))
        built.sort(key=lambda item: item[0])
        output = b"".join(item[1] for item in built)
        reports = [item[2] for item in built]
        capacity_failures.extend(
            {
                "domain": domain,
                "member": member,
                **item,
            }
            for item in reports
            if "capacity_failure" in item
        )
        if len(output) != len(source):
            raise SystemExit(f"LIBRARY archive size drift: {member}")
        for report in reports:
            used_hashes.update(report.pop("translation_hashes"))
        output_payloads[member] = output
        archive_reports.append(
            {
                "domain": domain,
                "member": member,
                "entry_count": len(reports),
                "source_size": len(source),
                "output_size": len(output),
                "source_sha256": sha256_bytes(source),
                "output_sha256": sha256_bytes(output),
                "minimum_chunk_headroom": min(item["headroom"] for item in reports),
                "maximum_body_line_width": max(
                    item["maximum_body_line_width"] for item in reports
                ),
                "dense_body_layout_entry_count": sum(
                    item["dense_body_layout"] for item in reports
                ),
                "capacity_fallback_entry_count": sum(
                    not item["dense_body_layout"] for item in reports
                ),
                "capacity_fallback_field_count": sum(
                    len(item["capacity_fallback_body_tags"])
                    for item in reports
                ),
                "chunk_spans_preserved": True,
                "offset_table_unchanged": True,
                "codec_round_trip_exact": True,
                "runtime_text_reread_exact": True,
                "binary_fields_preserved": True,
                "entries": reports,
            }
        )

    if args.audit_capacity:
        print(json.dumps({"capacity_failures": capacity_failures}, indent=2))
        return 1 if capacity_failures else 0

    if used_hashes != set(translation_by_hash):
        raise SystemExit(
            "LIBRARY translation usage coverage drift: "
            f"unused={len(set(translation_by_hash) - used_hashes)} "
            f"unknown={len(used_hashes - set(translation_by_hash))}"
        )
    output_paths = {}
    for member, payload in output_payloads.items():
        path = output_root / member
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
        output_paths[member] = path

    report = {
        "schema_version": 1,
        "status": "library_v0.2_reviewed_components_static_validated",
        "profile_id": config["profile_id"],
        "release_eligible": True,
        "inputs": {
            "config": file_lock(config_path),
            "scope_config": file_lock(scope_path),
            "corpus": file_lock(corpus_path),
            "font_manifest": file_lock(font_manifest_path),
            "font_proposal": file_lock(proposal_path),
            "executable": file_lock(executable_path, executable),
            "menu_font_flavor": file_lock(menu_font_flavor_path),
            "menu_font_lock": file_lock(menu_font_lock_path, menu_font_lock_data),
            "menu_font": file_lock(menu_font_path, menu_font_data),
            "menu_source": file_lock(menu_source_path, menu_source),
            "layout_profiles": file_lock(layout_profile_path),
            "layout_release": file_lock(layout_release_path),
            **{
                f"layout_glossary_{index:03d}": file_lock(path)
                for index, path in enumerate(layout_glossary_paths)
            },
        },
        "translation": {
            "unique_text_count": len(translation_by_hash),
            "used_unique_text_count": len(used_hashes),
            "field_reference_count": summary["field_reference_count"],
            "human_reviewed_count": summary["human_reviewed_count"],
            "deterministic_reviewed_count": summary[
                "deterministic_reviewed_count"
            ],
        },
        "codec": dict(codec),
        "layout": {
            "algorithm": "balanced-simplified-chinese-v1",
            "profiles": {
                kind: profile.profile_id
                for kind, profile in sorted(layout_profiles.items())
            },
            "protected_term_count": len(protected_terms),
            "body_line_widths": dict(widths),
        },
        "library_menu": menu_report,
        "archives": archive_reports,
        "outputs": {
            member: file_lock(path, output_payloads[member])
            for member, path in output_paths.items()
        },
        "acceptance": {
            "all_2709_translations_consumed": len(used_hashes) == 2709,
            "all_4921_text_fields_written": summary["field_reference_count"] == 4921,
            "all_784_entries_rebuilt": sum(
                item["entry_count"] for item in archive_reports
            )
            == 784,
            "all_archive_sizes_preserved": all(
                item["source_size"] == item["output_size"]
                for item in archive_reports
            ),
            "all_chunk_spans_preserved": all(
                item["chunk_spans_preserved"] for item in archive_reports
            ),
            "all_runtime_text_reread_exact": all(
                item["runtime_text_reread_exact"] for item in archive_reports
            ),
            "all_binary_fields_preserved": all(
                item["binary_fields_preserved"] for item in archive_reports
            ),
            "library_menu_member_size_preserved": menu_report[
                "member_size_preserved"
            ],
            "library_menu_both_states_written": menu_report[
                "all_six_labels_built_in_both_states"
            ],
            "library_menu_tim2_metadata_preserved": menu_report[
                "tim2_metadata_preserved"
            ],
            "library_menu_clut_preserved": menu_report[
                "clut_and_non_image_bytes_preserved"
            ],
            "all_editorial_statuses_reviewed": all(
                entry.get("editorial_status") == "reviewed" for entry in entries
            ),
            "release_eligible": True,
        },
        "runtime": {
            "status": "not_tested",
            "required_flows": [
                "pilot_status_triangle_to_character_encyclopedia",
                "unit_status_triangle_to_robot_encyclopedia",
                "library_glossary_and_keyword_popup",
            ],
        },
    }
    if not all(
        report["acceptance"].values()
    ):
        raise SystemExit("LIBRARY component acceptance failed")
    report_path = output_root / "component-validation.json"
    write_json(report_path, report)
    manifest_path = project_path(config["outputs"]["manifest"])
    if args.refresh_manifest:
        write_json(manifest_path, report)
    elif not manifest_path.is_file() or load_json(manifest_path) != report:
        raise SystemExit(
            "LIBRARY component manifest drift; rerun with --refresh-manifest"
        )
    print(
        "LIBRARY components validated: "
        f"entries=784 texts={len(used_hashes)} refs={summary['field_reference_count']} "
        f"min_headroom={min(item['minimum_chunk_headroom'] for item in archive_reports)}"
    )
    for member, path in output_paths.items():
        print(f"{member}: {path.relative_to(PROJECT_ROOT)} {sha256_bytes(output_payloads[member])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
