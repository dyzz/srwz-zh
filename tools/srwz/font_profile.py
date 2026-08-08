"""Load a font build profile with hash-locked configuration inheritance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .font import sha256_bytes
from .font_flavor import (
    FontFlavorError,
    font_flavor_metadata,
    load_font_flavor_reference,
)


class FontProfileError(ValueError):
    """A font profile or inherited base configuration is invalid."""


def _project_path(project_root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise FontProfileError("font profile path must be a non-empty string")
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise FontProfileError(
            f"font profile path escapes project root: {relative}"
        ) from error
    return path


def _json_object(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FontProfileError(f"cannot load font profile: {path}") from error
    if not isinstance(document, dict):
        raise FontProfileError("font profile root must be an object")
    if document.get("schema_version") != 1:
        raise FontProfileError("unsupported font profile schema")
    return document


def load_font_profile(project_root: Path, path: Path) -> dict:
    """Resolve one profile and its explicitly owned rasterizer policy."""

    document = _json_object(path)
    base_reference = document.get("base_font_config")
    if base_reference is None:
        base = document
        base_metadata = None
    else:
        if not isinstance(base_reference, Mapping):
            raise FontProfileError("base_font_config must be an object")
        base_path = _project_path(project_root, base_reference.get("path"))
        base_bytes = base_path.read_bytes()
        actual_hash = sha256_bytes(base_bytes)
        if actual_hash != base_reference.get("sha256"):
            raise FontProfileError("base font configuration SHA-256 drift")
        base = _json_object(base_path)
        if "base_font_config" in base:
            raise FontProfileError("nested font profile inheritance is unsupported")
        base_metadata = {
            "path": str(base_path.relative_to(project_root.resolve())),
            "sha256": actual_hash,
        }

    flavor_reference = document.get("font_flavor", base.get("font_flavor"))
    flavor_overrides_base = (
        base_reference is not None and "font_flavor" in document
    )
    direct_font_lock = document.get("font_lock", base.get("font_lock"))
    direct_font_lock_overrides_base = (
        base_reference is not None and "font_lock" in document
    )
    if flavor_reference is not None and direct_font_lock is not None:
        raise FontProfileError(
            "font profile cannot combine font_flavor with direct font_lock"
        )
    if flavor_reference is not None:
        try:
            flavor = load_font_flavor_reference(
                project_root,
                flavor_reference,
            )
        except FontFlavorError as error:
            raise FontProfileError(str(error)) from error
        font_lock = flavor["font_lock"]
        unsupported_character_fallbacks = flavor[
            "unsupported_character_fallbacks"
        ]
        flavor_metadata = font_flavor_metadata(flavor)
    else:
        flavor = None
        font_lock = direct_font_lock
        unsupported_character_fallbacks = document.get(
            "unsupported_character_fallbacks",
            base.get("unsupported_character_fallbacks", []),
        )
        flavor_metadata = None
    font_lock_overrides_base = (
        flavor_overrides_base or direct_font_lock_overrides_base
    )
    codec = base.get("codec")
    base_rasterizer = base.get("rasterizer")
    rasterizer = document.get("rasterizer", base_rasterizer)
    rasterizer_overrides_base = (
        base_reference is not None and "rasterizer" in document
    )
    scope = document.get("scope")
    if not isinstance(font_lock, str) or not font_lock:
        raise FontProfileError("font profile has no font_lock")
    if not isinstance(rasterizer, dict):
        raise FontProfileError("font profile has no rasterizer")
    if (
        (rasterizer_overrides_base or font_lock_overrides_base)
        and document.get("reraster_all_selected_visible_characters") is not True
    ):
        raise FontProfileError(
            "an inherited profile may override the font or rasterizer only "
            "when it "
            "rerasterizes every selected visible character"
        )
    if (
        not isinstance(codec, dict)
        or codec.get("strategy") != "rust-fit"
        or not isinstance(codec.get("min_match_length"), int)
        or codec["min_match_length"] < 2
        or not isinstance(codec.get("max_match_chain"), int)
        or codec["max_match_chain"] <= 0
        or codec.get("lazy_matching") is not False
    ):
        raise FontProfileError(
            "font profile must use the Rust fit-to-budget codec contract"
        )
    if not isinstance(scope, dict):
        raise FontProfileError("font profile has no scope")
    _project_path(project_root, font_lock)

    profile_id = document.get("font_profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise FontProfileError("font profile has no stable ID")
    return {
        "document": document,
        "profile_id": profile_id,
        "font_lock": font_lock,
        "font_flavor": flavor_metadata,
        "unsupported_character_fallbacks": (
            unsupported_character_fallbacks
        ),
        "codec": codec,
        "rasterizer": rasterizer,
        "rasterizer_overrides_base": rasterizer_overrides_base,
        "font_lock_overrides_base": font_lock_overrides_base,
        "scope": scope,
        "base_font_config": base_metadata,
    }


__all__ = [
    "FontProfileError",
    "load_font_profile",
]
