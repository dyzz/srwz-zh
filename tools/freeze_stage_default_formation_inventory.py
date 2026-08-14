#!/usr/bin/env python3
"""Explicitly freeze reviewed STAGE default-formation positions.

This is an audit/refreeze command, not part of the normal build.  Daily builds
load the resulting fixed-position inventory and never rescan STAGE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from srwz.stage_formations import (
        build_locked_formation_inventory,
        discover_known_stage_default_formations,
        discover_structural_stage_default_formations,
        filter_current_stage_default_formations,
    )
    from srwz.text import (
        PreparedTextEncoder,
        load_text_table,
        original_fullwidth_ascii_overrides,
    )
except ModuleNotFoundError:
    from tools.srwz.stage_formations import (
        build_locked_formation_inventory,
        discover_known_stage_default_formations,
        discover_structural_stage_default_formations,
        filter_current_stage_default_formations,
    )
    from tools.srwz.text import (
        PreparedTextEncoder,
        load_text_table,
        original_fullwidth_ascii_overrides,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE = PROJECT_ROOT / "work/disc/DATA/STAGE.BIN"
DEFAULT_CURRENT_STAGE = (
    PROJECT_ROOT / "work/build/zh-release-full-story/iso/staging/DATA/STAGE.BIN"
)
DEFAULT_HB = PROJECT_ROOT / "work/build/full-story-stage/components/HEDBDY/HB.BIN"
DEFAULT_TABLE = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
DEFAULT_CORPUS = PROJECT_ROOT / "corpus/zh/menu/stage-default-formations.json"
DEFAULT_FONT_MANIFEST = PROJECT_ROOT / "manifests/zh-release-font-validation.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "config/stage-default-formation-inventory.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze reviewed default-formation positions after an explicit scan."
    )
    parser.add_argument("--stage", type=Path, default=DEFAULT_STAGE)
    parser.add_argument("--current-stage", type=Path, default=DEFAULT_CURRENT_STAGE)
    parser.add_argument("--hb", type=Path, default=DEFAULT_HB)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--font-manifest", type=Path, default=DEFAULT_FONT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def file_lock(path: Path, payload: bytes) -> dict:
    return {
        "path": str(path.resolve().relative_to(PROJECT_ROOT.resolve())),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def load_replacement_bytes(
    manifest_path: Path,
    table,
    translations_by_source: dict[str, str],
) -> dict[str, bytes]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    proposal_reference = manifest.get("proposal")
    if not isinstance(proposal_reference, dict) or not isinstance(
        proposal_reference.get("path"), str
    ):
        raise SystemExit("release font manifest has no proposal reference")
    proposal_path = PROJECT_ROOT / proposal_reference["path"]
    proposal_payload = proposal_path.read_bytes()
    if hashlib.sha256(proposal_payload).hexdigest() != proposal_reference.get(
        "sha256"
    ):
        raise SystemExit("release font proposal SHA-256 drift")
    proposal = json.loads(proposal_payload.decode("utf-8"))
    overrides = {
        item["character"]: int(item["code"], 16)
        for item in proposal.get("assignments", [])
    }
    overrides.update(
        {
            item["character"]: int(item["code"], 16)
            for item in proposal.get("surface_alias_assignments", [])
        }
    )
    overrides.update(original_fullwidth_ascii_overrides(table))
    overrides[" "] = ord(" ")
    encoder = PreparedTextEncoder(table, overrides)
    return {
        source: encoder.encode(translation, terminate=True)
        for source, translation in translations_by_source.items()
    }


def main() -> int:
    args = parse_args()
    if args.output.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite without --force: {args.output}")
    stage = args.stage.read_bytes()
    current_stage = args.current_stage.read_bytes()
    hb = args.hb.read_bytes()
    table = load_text_table(args.table)
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    translations_by_source = corpus["translations_by_source_text"]
    accepted_current_translations = corpus.get(
        "accepted_current_translations_by_source_text", {}
    )
    if (
        not isinstance(accepted_current_translations, dict)
        or any(
            source not in translations_by_source
            or not isinstance(translations, list)
            or not translations
            or any(
                not isinstance(translation, str) or not translation
                for translation in translations
            )
            for source, translations in accepted_current_translations.items()
        )
    ):
        raise SystemExit("invalid accepted current formation translations")
    sources = frozenset(translations_by_source)

    structural = discover_structural_stage_default_formations(stage, hb, table)
    structural_sources = {
        cell.source_text for group in structural for cell in group.cells
    }
    if sources != structural_sources:
        missing = sorted(structural_sources - sources)
        extra = sorted(sources - structural_sources)
        raise SystemExit(
            "reviewed corpus does not cover the explicit scan: "
            f"missing={missing!r} extra={extra!r}"
        )
    groups = discover_known_stage_default_formations(
        stage,
        hb,
        table,
        sources,
    )
    replacement_bytes = load_replacement_bytes(
        args.font_manifest,
        table,
        translations_by_source,
    )
    accepted_keys = {
        f"{source}\0{index}": translation
        for source, translations in accepted_current_translations.items()
        for index, translation in enumerate(translations)
    }
    accepted_bytes = load_replacement_bytes(
        args.font_manifest,
        table,
        accepted_keys,
    )
    groups = filter_current_stage_default_formations(
        stage,
        current_stage,
        hb,
        groups,
        replacement_bytes,
        translations_by_source,
        {
            source: tuple(
                (
                    translation,
                    accepted_bytes[f"{source}\0{index}"],
                )
                for index, translation in enumerate(translations)
            )
            for source, translations in accepted_current_translations.items()
        },
    )
    document = build_locked_formation_inventory(groups)
    document["source_stage"] = file_lock(args.stage, stage)
    document["source_current_stage"] = file_lock(
        args.current_stage, current_stage
    )
    document["source_hb"] = file_lock(args.hb, hb)
    document["source_corpus"] = file_lock(args.corpus, args.corpus.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    expected = document["expected"]
    print(f"output={args.output}")
    print(f"group_count={expected['group_count']}")
    print(f"stage_count={expected['stage_count']}")
    print(f"entry_count={expected['entry_count']}")
    print(f"unique_source_count={expected['unique_source_count']}")
    print(f"inventory_sha256={expected['inventory_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
