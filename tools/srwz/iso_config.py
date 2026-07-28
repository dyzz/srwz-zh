"""Shared schema and directory-contract checks for ISO build profiles."""

from __future__ import annotations

import json
from pathlib import Path


class IsoBuildError(RuntimeError):
    """An ISO build profile cannot meet its pinned contract."""


def _require_config_path_under(
    raw: object,
    prefix: Path,
    *,
    context: str,
) -> None:
    if not isinstance(raw, str) or not raw:
        raise IsoBuildError(f"{context} must be a non-empty path")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise IsoBuildError(f"{context} must be project-relative")
    try:
        path.relative_to(prefix)
    except ValueError as error:
        raise IsoBuildError(
            f"{context} must be under {prefix.as_posix()}/"
        ) from error


def validate_directory_contract(config: dict) -> None:
    """Require profile-owned input, work, component and output paths."""

    profile_id = config.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise IsoBuildError("ISO build config needs profile_id")
    if Path(profile_id).name != profile_id:
        raise IsoBuildError(
            "ISO build profile_id must be one path segment"
        )
    for field in (
        "component_validation_manifest",
        "runtime_evidence_manifest",
    ):
        raw = config.get(field)
        if raw is None:
            continue
        _require_config_path_under(
            raw,
            Path("manifests"),
            context=field.replace("_", " "),
        )
        if Path(raw).suffix.lower() != ".json":
            raise IsoBuildError(f"{field} path must end in .json")

    _require_config_path_under(
        config.get("source_iso", {}).get("path"),
        Path("rom"),
        context="source ISO",
    )
    if Path(config["source_iso"]["path"]).suffix.lower() != ".iso":
        raise IsoBuildError("source ISO path must end in .iso")
    work_prefix = Path("work") / "build" / profile_id
    workspace = config.get("workspace")
    required_workspace_fields = {
        "original_tree",
        "staging_tree",
        "base_xml",
        "build_xml",
        "lba_log",
    }
    if not isinstance(workspace, dict) or (
        required_workspace_fields - set(workspace)
    ):
        raise IsoBuildError("ISO workspace contract is incomplete")
    for field, raw in workspace.items():
        _require_config_path_under(
            raw,
            work_prefix / "iso",
            context=f"workspace {field}",
        )
    replacements = config.get("replacements")
    if not isinstance(replacements, list) or not replacements:
        raise IsoBuildError("ISO build needs replacement components")
    for index, replacement in enumerate(replacements):
        if not isinstance(replacement, dict):
            raise IsoBuildError(
                f"replacement {index} must be an object"
            )
        _require_config_path_under(
            replacement.get("source"),
            work_prefix / "components",
            context=f"replacement {index} source",
        )
    output_prefix = Path("build") / "iso" / profile_id
    if not isinstance(config.get("output"), dict):
        raise IsoBuildError("ISO output contract is missing")
    _require_config_path_under(
        config.get("output", {}).get("path"),
        output_prefix,
        context="output ISO",
    )
    _require_config_path_under(
        config.get("output", {}).get("report"),
        output_prefix,
        context="output report",
    )
    if Path(config["output"]["path"]).suffix.lower() != ".iso":
        raise IsoBuildError("output ISO path must end in .iso")
    layout = config.get("layout")
    if not isinstance(layout, dict):
        raise IsoBuildError("ISO layout contract is missing")
    raw_segments = layout.get("shift_segments")
    if raw_segments is not None:
        if not isinstance(raw_segments, list) or not raw_segments:
            raise IsoBuildError(
                "layout shift_segments must be a non-empty array"
            )
        seen = set()
        previous_shift = -1
        for index, segment in enumerate(raw_segments):
            if not isinstance(segment, dict):
                raise IsoBuildError(
                    f"layout shift segment {index} is invalid"
                )
            first_member = segment.get("first_member")
            shift_sectors = segment.get("shift_sectors")
            if (
                not isinstance(first_member, str)
                or not first_member
                or first_member in seen
            ):
                raise IsoBuildError(
                    f"layout shift segment {index} first_member is invalid"
                )
            if (
                not isinstance(shift_sectors, int)
                or isinstance(shift_sectors, bool)
                or shift_sectors < 0
                or shift_sectors < previous_shift
            ):
                raise IsoBuildError(
                    f"layout shift segment {index} shift is invalid"
                )
            seen.add(first_member)
            previous_shift = shift_sectors


def load_config(path: Path) -> dict:
    """Load an ISO build profile and enforce the shared schema."""

    with path.open(encoding="utf-8") as source:
        config = json.load(source)
    if config.get("schema_version") != 2:
        raise IsoBuildError("unsupported ISO build config schema")
    validate_directory_contract(config)
    return config


def expected_shift_segments(
    config: dict,
) -> tuple[tuple[str, int], ...]:
    """Return explicit LBA-shift breakpoints, with legacy compatibility."""

    raw_segments = config["layout"].get("shift_segments")
    if raw_segments is not None:
        return tuple(
            (segment["first_member"], segment["shift_sectors"])
            for segment in raw_segments
        )
    return (
        (
            config["layout"]["first_shifted_member"],
            config["layout"]["expected_shift_sectors"],
        ),
    )


__all__ = [
    "IsoBuildError",
    "expected_shift_segments",
    "load_config",
    "validate_directory_contract",
]
