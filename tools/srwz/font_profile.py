"""Load a font build profile with hash-locked configuration inheritance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .font import sha256_bytes


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
    """Resolve one profile while keeping rasterizer ownership in its base."""

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

    font_lock = base.get("font_lock")
    codec = base.get("codec")
    rasterizer = base.get("rasterizer")
    scope = document.get("scope")
    if not isinstance(font_lock, str) or not font_lock:
        raise FontProfileError("font profile has no font_lock")
    if not isinstance(rasterizer, dict):
        raise FontProfileError("font profile has no rasterizer")
    if (
        not isinstance(codec, dict)
        or codec.get("strategy") != "rust-maximum"
        or not isinstance(codec.get("min_match_length"), int)
        or codec["min_match_length"] < 2
        or not isinstance(codec.get("max_match_chain"), int)
        or codec["max_match_chain"] <= 0
        or codec.get("lazy_matching") is not True
    ):
        raise FontProfileError(
            "font profile must use the Rust maximum codec contract"
        )
    if not isinstance(scope, dict):
        raise FontProfileError("font profile has no scope")
    _project_path(project_root, font_lock)

    profile_id = document.get(
        "font_profile_id",
        "srwz-first-five-unified-font-v3",
    )
    if not isinstance(profile_id, str) or not profile_id:
        raise FontProfileError("font profile has no stable ID")
    return {
        "document": document,
        "profile_id": profile_id,
        "font_lock": font_lock,
        "codec": codec,
        "rasterizer": rasterizer,
        "scope": scope,
        "base_font_config": base_metadata,
    }


__all__ = [
    "FontProfileError",
    "load_font_profile",
]
