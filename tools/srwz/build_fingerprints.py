"""Semantic identities shared by the font and text build consumers."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

# Every file whose bytes can change a produced component. rebuild_zh_font uses
# this set for its verified-chain cache; the edition seeder uses the same set to
# decide whether a previous run's component caches may be carried forward.
# Paths outside it (ISO builder, verifiers, orchestration, docs) never change
# component bytes, so editing them must not force a component rebuild.
COMPONENT_BUILD_DEFINITION_ROOTS = (
    "tools/srwz",
    "tools/native/srwz-codec-rs/Cargo.toml",
    "tools/native/srwz-codec-rs/Cargo.lock",
    "tools/native/srwz-codec-rs/src",
    "tools/rebuild_zh_font.py",
    "tools/prepare_zh_release_font.py",
    "tools/update_zh_release_font_snapshot.py",
    "tools/build_zh_font_component.py",
    "tools/verify_zh_release_font.py",
    "tools/build_library_v02_component.py",
    "tools/build_story_component.py",
    "tools/build_text_update_iso.py",
    "tools/ui_atlas.py",
    "tools/build_ui_headings.py",
    "tools/build_full_story_components.py",
    "tools/build_aid_battle_prompts.py",
    "tools/build_tricmn_battle_overlays.py",
    "tools/compose_full_story_library_components.py",
    "config",
    "corpus/ja",
    "corpus/zh",
    "corpus/glossary",
)


def is_component_build_definition(relative_path: str) -> bool:
    """True when a project-relative path can influence produced component bytes.

    Receipts under ``manifests/`` count as well: several are consumed as locks
    by the component chain, so a hand edit there must not be carried over.
    """

    for root in COMPONENT_BUILD_DEFINITION_ROOTS:
        if relative_path == root or relative_path.startswith(root + "/"):
            return True
    return relative_path.startswith(("vendor/upstream-python/", "manifests/"))


def font_binary_signature(proposal: Mapping[str, object]) -> str:
    """Exclude only corpus-selection bookkeeping, retaining every font input."""

    return hashlib.sha256(
        json.dumps(
            {key: value for key, value in proposal.items() if key != "ui_selection"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
