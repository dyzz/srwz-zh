"""Resolve the single project-wide font identity used by Chinese assets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .font import sha256_bytes
from .font_source import (
    FontSourceError,
    load_font_lock,
    validate_font_lock,
    verify_font_fallbacks,
    verify_font_lock_files,
)


class FontFlavorError(ValueError):
    """A global font flavor is malformed or has drifted."""


def _project_path(project_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise FontFlavorError("font flavor path must be a non-empty string")
    root = project_root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise FontFlavorError(
            f"font flavor path escapes project root: {relative}"
        ) from error
    return path


def load_font_flavor(project_root: Path, path: Path) -> dict:
    """Load one global flavor and verify its pinned primary lock."""

    try:
        data = path.read_bytes()
        document = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FontFlavorError(f"cannot load font flavor: {path}") from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise FontFlavorError("unsupported font flavor schema")
    flavor_id = document.get("font_flavor_id")
    if not isinstance(flavor_id, str) or not flavor_id:
        raise FontFlavorError("font flavor has no stable ID")
    primary = document.get("primary")
    if not isinstance(primary, Mapping):
        raise FontFlavorError("font flavor has no primary source")
    lock_path = _project_path(project_root, primary.get("font_lock"))
    try:
        lock_data = lock_path.read_bytes()
    except OSError as error:
        raise FontFlavorError(f"cannot load font lock: {lock_path}") from error
    lock_sha256 = sha256_bytes(lock_data)
    if lock_sha256 != primary.get("font_lock_sha256"):
        raise FontFlavorError("font flavor primary lock SHA-256 drift")
    try:
        lock = load_font_lock(lock_path)
        validate_font_lock(lock)
    except FontSourceError as error:
        raise FontFlavorError(str(error)) from error
    fallbacks = document.get("unsupported_character_fallbacks", [])
    if not isinstance(fallbacks, list):
        raise FontFlavorError("font flavor fallbacks must be a list")
    return {
        "document": document,
        "flavor_id": flavor_id,
        "path": str(path.resolve().relative_to(project_root.resolve())),
        "sha256": sha256_bytes(data),
        "font_lock": str(lock_path.relative_to(project_root.resolve())),
        "font_lock_sha256": lock_sha256,
        "unsupported_character_fallbacks": fallbacks,
    }


def load_font_flavor_reference(
    project_root: Path,
    reference: object,
) -> dict:
    return load_font_flavor(
        project_root,
        _project_path(project_root, reference),
    )


def font_flavor_metadata(flavor: Mapping) -> dict:
    return {
        "font_flavor_id": flavor["flavor_id"],
        "path": flavor["path"],
        "sha256": flavor["sha256"],
        "font_lock": flavor["font_lock"],
        "font_lock_sha256": flavor["font_lock_sha256"],
    }


def verify_font_flavor_files(
    project_root: Path,
    work_root: Path,
    flavor: Mapping,
) -> tuple[dict, dict[str, Path], dict[str, Path], tuple[dict, ...]]:
    """Verify the primary font and every explicit missing-glyph fallback."""

    try:
        lock = load_font_lock(project_root / flavor["font_lock"])
        primary_files = verify_font_lock_files(project_root, work_root, lock)
        fallback_paths, fallback_reports = verify_font_fallbacks(
            project_root,
            work_root,
            flavor["unsupported_character_fallbacks"],
        )
    except FontSourceError as error:
        raise FontFlavorError(str(error)) from error
    return lock, primary_files, fallback_paths, fallback_reports


__all__ = [
    "FontFlavorError",
    "font_flavor_metadata",
    "load_font_flavor",
    "load_font_flavor_reference",
    "verify_font_flavor_files",
]
