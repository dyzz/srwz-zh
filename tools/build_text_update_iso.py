#!/usr/bin/env python3
"""Rebuild the current Chinese ISO after a text-only localization update.

The repository, a hash-locked original ISO, and pinned downloadable/buildable
toolchains are the authorities.  Files below ``work/`` are caches or outputs:
they are verified before reuse and regenerated when absent or stale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping

from srwz.build_fingerprints import font_binary_signature as _font_binary_signature
from srwz.iso_layout import CORE_ARCHIVE_SPECS
from srwz.ui_atlas_suite import UiAtlasSuiteError, build_ui_atlas_suite


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ISO_CONFIG = PROJECT_ROOT / "config/iso/zh-release-current-build.json"
DEFAULT_CHAIN_CONFIG = PROJECT_ROOT / "config/fonts/zh-font-build-chain.json"
DEFAULT_TIMING_REPORT = (
    PROJECT_ROOT / "work/build/zh-release-full-story/text-update-build.json"
)
DEFAULT_ORIGINAL_ISO_CACHE = (
    PROJECT_ROOT / "work/cache/original-iso-verification.json"
)
ORIGINAL_DISC_MANIFEST = PROJECT_ROOT / "manifests/original-disc.json"
RELEASE_MENU_CORPUS = PROJECT_ROOT / "corpus/zh/menu/release-v0.3.json"
TEXT_LOCK_CONFIGS = (
    PROJECT_ROOT / "config/story-component.json",
    PROJECT_ROOT / "config/full-story-components.json",
)
TEXT_INPUT_PREFIXES = ("corpus/zh/", "corpus/runtime/")
FROZEN_ASSET_PREFIXES = ("corpus/zh/ui-atlas/",)
MTV_PROS_TABLE_START = CORE_ARCHIVE_SPECS["MTV_PROS.BIN"].table_start
MTV_PROS_TABLE_END = CORE_ARCHIVE_SPECS["MTV_PROS.BIN"].table_end


class TextUpdateBuildError(RuntimeError):
    """The text-only production build contract could not be satisfied."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build and reread the current Chinese ISO from tracked build "
            "definitions plus the hash-locked original disc. Generated files "
            "under work/ are verified caches, never hidden source inputs."
        )
    )
    parser.add_argument("--iso-config", type=Path, default=DEFAULT_ISO_CONFIG)
    parser.add_argument("--chain-config", type=Path, default=DEFAULT_CHAIN_CONFIG)
    parser.add_argument("--components-only", action="store_true",
                        help="Build the complete component set without writing an ISO.")
    parser.add_argument(
        "--refresh-manifests",
        action="store_true",
        help=(
            "Refresh tracked text-input, component, ISO, and readback locks "
            "after an intentional translation change."
        ),
    )
    parser.add_argument(
        "--force-full",
        action="store_true",
        help=(
            "Rebuild every registered UI atlas too. The default text path "
            "reuses the atlas suite only after a deterministic hash check."
        ),
    )
    parser.add_argument(
        "--release-proof",
        action="store_true",
        help=(
            "After the normal structurally validated ISO build, force a full "
            "semantic content readback and build the ISO a second time as a "
            "determinism proof. This is intentionally outside the fast daily "
            "text-candidate path."
        ),
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help=(
            "Verify/bootstrap the original-member cache and pinned toolchains, "
            "then stop before component and ISO writes."
        ),
    )
    parser.add_argument("--story-workers", type=int, default=4)
    parser.add_argument("--library-workers", type=int, default=4)
    parser.add_argument("--atlas-workers", type=int, default=4)
    parser.add_argument("--timing-report", type=Path, default=DEFAULT_TIMING_REPORT)
    args = parser.parse_args()
    for name in ("story_workers", "library_workers", "atlas_workers"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")
    return args


def _project_path(raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise TextUpdateBuildError("project path must be a non-empty string")
    path = (PROJECT_ROOT / raw).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as error:
        raise TextUpdateBuildError(f"path escapes project root: {raw}") from error
    return path


def _load_object(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TextUpdateBuildError(f"cannot read JSON object: {path}") from error
    if not isinstance(document, dict):
        raise TextUpdateBuildError(f"JSON root must be an object: {path}")
    return document


def _write_object(path: Path, document: Mapping) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path) -> tuple[int, str]:
    return path.stat().st_size, _sha256(path)


def _stat_identity(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
    }


def _verify_original_iso(
    source_iso: Path,
    source_reference: Mapping[str, object],
    *,
    cache_path: Path | None = None,
    force: bool = False,
) -> dict[str, object]:
    """Reuse a full original-disc proof while the OS file identity is exact."""

    cache_path = (
        DEFAULT_ORIGINAL_ISO_CACHE if cache_path is None else cache_path.resolve()
    )
    source_lock = {
        "path": source_reference.get("path"),
        "size": source_reference.get("size"),
        "sha256": source_reference.get("sha256"),
    }
    original_manifest = _load_object(ORIGINAL_DISC_MANIFEST)
    disc_lock = original_manifest.get("disc")
    if (
        not isinstance(disc_lock, dict)
        or source_lock["size"] != disc_lock.get("file_size")
        or source_lock["sha256"] != disc_lock.get("sha256")
    ):
        raise TextUpdateBuildError(
            "ISO build config disagrees with manifests/original-disc.json"
        )
    manifest_lock = {
        "path": str(ORIGINAL_DISC_MANIFEST.relative_to(PROJECT_ROOT)),
        "size": ORIGINAL_DISC_MANIFEST.stat().st_size,
        "sha256": _sha256(ORIGINAL_DISC_MANIFEST),
    }
    stat_identity = _stat_identity(source_iso)
    try:
        cached = _load_object(cache_path)
    except TextUpdateBuildError:
        cached = {}
    if (
        not force
        and cached.get("schema_version") == 1
        and cached.get("status") == "original_iso_fully_verified"
        and cached.get("source_lock") == source_lock
        and cached.get("manifest_lock") == manifest_lock
        and cached.get("file_identity") == stat_identity
    ):
        print(
            "[cache] original ISO proof reused: size/inode/mtime/ctime and "
            "repository locks match",
            flush=True,
        )
        return {"reused": True, "reason": "exact file identity and locks match"}

    _run_python(["tools/verify_original_disc.py", "--iso", str(source_iso)])
    receipt = {
        "schema_version": 1,
        "status": "original_iso_fully_verified",
        "source_lock": source_lock,
        "manifest_lock": manifest_lock,
        "file_identity": _stat_identity(source_iso),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    _write_object(cache_path, receipt)
    return {"reused": False, "reason": "full original-disc verification completed"}


def _reference_matches(reference: Mapping[str, object]) -> bool:
    raw_path = reference.get("path")
    if not isinstance(raw_path, str):
        return False
    path = _project_path(raw_path)
    if not path.is_file():
        return False
    size, digest = _file_identity(path)
    return size == reference.get("size") and digest == reference.get("sha256")


def _content_reference_matches(reference: Mapping[str, object]) -> bool:
    """Match a SHA-locked file reference whose size field may be omitted."""

    raw_path = reference.get("path")
    expected_digest = reference.get("sha256")
    if (
        not isinstance(raw_path, str)
        or not isinstance(expected_digest, str)
        or len(expected_digest) != 64
    ):
        return False
    path = _project_path(raw_path)
    if not path.is_file():
        return False
    expected_size = reference.get("size")
    if expected_size is not None and path.stat().st_size != expected_size:
        return False
    return _sha256(path) == expected_digest


def _iter_path_references(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        if isinstance(value.get("path"), str):
            yield value
        for child in value.values():
            yield from _iter_path_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_path_references(child)


def _tracked_config_paths() -> tuple[Path, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "config"],
        cwd=PROJECT_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    paths = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        path = PROJECT_ROOT / raw.decode("utf-8")
        if path.suffix == ".json":
            paths.append(path)
    if not paths:
        raise TextUpdateBuildError("Git has no tracked JSON build configs")
    return tuple(paths)


def _assert_no_untracked_production_json() -> None:
    """Reject JSON that a clean checkout would silently lose.

    The release-font scanner consumes whole corpus directories, so an
    untracked JSON file there would otherwise influence a local build without
    existing in Git. Editorial dashboard state is deliberately outside the
    production closure.
    """

    discovered = set()
    for ignored in (False, True):
        command = ["git", "ls-files", "-z", "--others"]
        if ignored:
            command.extend(("--ignored", "--exclude-standard"))
        else:
            command.append("--exclude-standard")
        command.extend(
            (
                "--",
                "corpus/zh",
                "corpus/ja",
                "corpus/runtime",
                "corpus/glossary",
                "config",
            )
        )
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=True,
            stdout=subprocess.PIPE,
        )
        discovered.update(
            raw.decode("utf-8")
            for raw in completed.stdout.split(b"\0")
            if raw
        )
    unexpected = sorted(
        path
        for path in discovered
        if path.endswith(".json") and not path.startswith("config/editorial/")
    )
    if unexpected:
        raise TextUpdateBuildError(
            "production JSON is not tracked by Git: " + ", ".join(unexpected)
        )


def collect_original_member_locks(
    config_paths: Iterable[Path],
) -> dict[str, dict[str, object]]:
    """Collect one consistent lock for every tracked work/disc cache path."""

    locks: dict[str, dict[str, object]] = {}
    owners: dict[str, list[str]] = {}
    for config_path in config_paths:
        document = _load_object(config_path)
        for reference in _iter_path_references(document):
            raw_path = reference.get("path")
            if not isinstance(raw_path, str) or not raw_path.startswith("work/disc/"):
                continue
            size = reference.get("size")
            digest = reference.get("sha256")
            member = raw_path.removeprefix("work/disc/")
            relative = PurePosixPath(member)
            if (
                not member
                or relative.is_absolute()
                or any(part in ("", ".", "..") for part in relative.parts)
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size <= 0
                or not isinstance(digest, str)
                or len(digest) != 64
            ):
                raise TextUpdateBuildError(
                    f"invalid original-member lock in {config_path}: {raw_path}"
                )
            identity = {"path": raw_path, "size": size, "sha256": digest}
            prior = locks.get(member)
            if prior is not None and prior != identity:
                locations = ", ".join([*owners[member], str(config_path)])
                raise TextUpdateBuildError(
                    f"conflicting original-member locks for {member}: {locations}"
                )
            locks[member] = identity
            owners.setdefault(member, []).append(str(config_path))
    if not locks:
        raise TextUpdateBuildError("no original-member cache locks were found")
    return dict(sorted(locks.items()))


def _refresh_text_locks(
    config_paths: Iterable[Path],
    *,
    refresh: bool,
) -> list[str]:
    changed = []
    for config_path in config_paths:
        document = _load_object(config_path)
        config_changed = False
        for reference in _iter_path_references(document):
            raw_path = reference.get("path")
            if (
                not isinstance(raw_path, str)
                or not raw_path.startswith(TEXT_INPUT_PREFIXES)
                or "size" not in reference
                or "sha256" not in reference
            ):
                continue
            path = _project_path(raw_path)
            if not path.is_file():
                raise TextUpdateBuildError(f"tracked text input is missing: {raw_path}")
            actual_size, actual_digest = _file_identity(path)
            if (
                reference.get("size") == actual_size
                and reference.get("sha256") == actual_digest
            ):
                continue
            if raw_path.startswith(FROZEN_ASSET_PREFIXES):
                raise TextUpdateBuildError(
                    f"{raw_path} belongs to a frozen rendered asset; use the "
                    "asset review/refreeze workflow, not the text-only build"
                )
            if not refresh:
                raise TextUpdateBuildError(
                    f"text lock drift: {raw_path}; rerun with --refresh-manifests"
                )
            reference["size"] = actual_size
            reference["sha256"] = actual_digest
            config_changed = True
            changed.append(raw_path)
        if config_changed:
            _write_object(config_path, document)
            print(f"[refresh] text input locks: {config_path.relative_to(PROJECT_ROOT)}")
    return changed


def _refresh_release_menu_selection_lock(*, refresh: bool) -> bool:
    """Bind the embedded release-menu digest to its current source rows."""

    document = _load_object(RELEASE_MENU_CORPUS)
    entries = document.get("entries")
    expected = document.get("expected")
    if not isinstance(entries, list) or not isinstance(expected, dict):
        raise TextUpdateBuildError("release menu selection contract is malformed")
    digest = hashlib.sha256(
        json.dumps(
            entries,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if expected.get("selection_sha256") == digest:
        return False
    if not refresh:
        raise TextUpdateBuildError(
            "release menu selection lock drift; rerun with --refresh-manifests"
        )
    expected["selection_sha256"] = digest
    _write_object(RELEASE_MENU_CORPUS, document)
    print("[refresh] release menu selection lock", flush=True)
    return True


def _audit_other_text_locks(config_paths: Iterable[Path]) -> None:
    auto_paths = {path.resolve() for path in TEXT_LOCK_CONFIGS}
    for config_path in config_paths:
        if config_path.resolve() in auto_paths:
            continue
        document = _load_object(config_path)
        for reference in _iter_path_references(document):
            raw_path = reference.get("path")
            if (
                not isinstance(raw_path, str)
                or not raw_path.startswith(TEXT_INPUT_PREFIXES)
                or "size" not in reference
                or "sha256" not in reference
            ):
                continue
            if not _reference_matches(reference):
                raise TextUpdateBuildError(
                    f"text change also invalidates {config_path.relative_to(PROJECT_ROOT)} "
                    f"({raw_path}); refresh that specialized contract first"
                )


def _font_cache_requires_force(chain: Mapping[str, object]) -> bool:
    flavor_path = _project_path(chain.get("font_flavor"))
    flavor = _load_object(flavor_path)
    lock_paths = [flavor.get("primary", {}).get("font_lock")]
    lock_paths.extend(
        item.get("font_lock")
        for item in flavor.get("unsupported_character_fallbacks", [])
        if isinstance(item, dict)
    )
    force = False
    for raw_lock in lock_paths:
        lock = _load_object(_project_path(raw_lock))
        for label in ("font", "license"):
            reference = lock.get(label)
            if not isinstance(reference, dict):
                raise TextUpdateBuildError(f"font lock has no {label}: {raw_lock}")
            raw_path = reference.get("path")
            path = _project_path(raw_path)
            if path.exists() and not _reference_matches(reference):
                force = True
    return force


def _update_full_component_dependencies(*, refresh: bool) -> None:
    config_path = PROJECT_ROOT / "config/full-story-components.json"
    config = _load_object(config_path)
    references = (
        config["full_story_font"]["manifest"],
        config["full_story_font"]["slps"],
        config["full_story_font"]["vt1"],
        config["full_story_stage"]["report"],
        config["full_story_stage"]["stage"],
        config["full_story_stage"]["hb"],
        config["runtime_keywords"]["library_archive"],
        config["runtime_keywords"]["library_component_manifest"],
        config["remaining_ui"]["stage_default_formation_inventory"],
    )
    changed = False
    for reference in references:
        path = _project_path(reference.get("path"))
        if not path.is_file():
            raise TextUpdateBuildError(f"derived component is missing: {path}")
        size, digest = _file_identity(path)
        if reference.get("size") == size and reference.get("sha256") == digest:
            continue
        if not refresh:
            raise TextUpdateBuildError(
                f"derived dependency lock drift: {path.relative_to(PROJECT_ROOT)}; "
                "rerun with --refresh-manifests"
            )
        reference["size"] = size
        reference["sha256"] = digest
        changed = True

    font_manifest_reference = config["full_story_font"]["manifest"]
    font_manifest = _load_object(_project_path(font_manifest_reference["path"]))
    proposal_reference = font_manifest.get("proposal")
    snapshot_reference = font_manifest.get("inputs", {}).get(
        "allocation_snapshot"
    )
    compatibility = config.get("composition", {}).get("release_codebook")
    if not all(
        isinstance(value, dict)
        for value in (proposal_reference, snapshot_reference, compatibility)
    ):
        raise TextUpdateBuildError(
            "integrated release codebook dependency contract is malformed"
        )
    proposal = _load_object(_project_path(proposal_reference["path"]))
    snapshot = _load_object(_project_path(snapshot_reference["path"]))
    assignments = proposal.get("assignments")
    if not isinstance(assignments, list):
        raise TextUpdateBuildError("release font proposal assignments are malformed")
    current_compatibility = {
        "release_snapshot": dict(snapshot_reference),
        "release_snapshot_primary_mapping_sha256": snapshot.get(
            "primary_mapping_sha256"
        ),
        "release_assignment_count": len(assignments),
        "release_assignment_mapping_sha256": _assignment_mapping_sha256(
            assignments
        ),
    }
    if any(
        compatibility.get(key) != value
        for key, value in current_compatibility.items()
    ):
        if not refresh:
            raise TextUpdateBuildError(
                "integrated release codebook lock drift; rerun with "
                "--refresh-manifests"
            )
        compatibility.update(current_compatibility)
        changed = True
    if changed:
        _write_object(config_path, config)
        print(
            "[refresh] integrated font/story/library and release-codebook "
            "dependency locks"
        )


def _assert_full_component_dependencies_current() -> None:
    config = _load_object(PROJECT_ROOT / "config/full-story-components.json")
    references = (
        config["full_story_font"]["manifest"],
        config["full_story_font"]["slps"],
        config["full_story_font"]["vt1"],
        config["full_story_stage"]["report"],
        config["full_story_stage"]["stage"],
        config["full_story_stage"]["hb"],
        config["kvmdata"],
        config["runtime_keywords"]["library_archive"],
        config["runtime_keywords"]["library_component_manifest"],
        config["remaining_ui"]["stage_default_formation_inventory"],
    )
    stale = [
        str(reference.get("path"))
        for reference in references
        if not _reference_matches(reference)
    ]
    if stale:
        raise TextUpdateBuildError(
            "component dependency cache is absent or stale: " + ", ".join(stale)
        )


def _ui_atlas_cache_is_current(
    chain: Mapping[str, object], *, reconstruct: bool = False,
    verified_files: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    raw_suite = chain.get("atlas_suite")
    if not isinstance(raw_suite, str):
        return False, "font chain has no atlas suite"
    suite_path = _project_path(raw_suite)
    try:
        suite = _load_object(suite_path)
        archive_path = _project_path(
            f"{suite['outputs']['component_root']}/KURODATA/KVMDATA.BIN"
        )
        manifest_path = _project_path(suite["outputs"]["manifest"])
        if not manifest_path.is_file():
            return False, "combined atlas manifest is missing"
        report = _load_object(manifest_path)
        if reconstruct:
            archive, expected_report = build_ui_atlas_suite(PROJECT_ROOT, suite_path)
            if not archive_path.is_file() or archive_path.read_bytes() != archive:
                return False, "combined atlas output is missing or stale"
            if report != expected_report:
                return False, "combined atlas manifest is stale"
        else:
            # A reviewed composition is already bound to each component's
            # config, report and archive. Recheck those identities; rebuilding
            # the same byte ownership map adds no information for a text edit.
            if (
                report.get("inputs", {}).get("config", {}).get("sha256")
                != _sha256(suite_path)
                or not report.get("acceptance")
                or not all(report["acceptance"].values())
                or report.get("outputs", {}).get("archive") != suite.get("expected_output")
            ):
                return False, "combined atlas proof no longer matches its config"
            pending = [suite, report]
            component_manifests = {
                item["manifest"]["path"] for item in suite["components"]
            }
            checked = dict(verified_files or {})
            while pending:
                document = pending.pop()
                for reference in _iter_path_references(document):
                    if "sha256" not in reference:
                        continue
                    raw = reference["path"]
                    if raw == suite["source"]["member"]["member"]:
                        continue  # ISO-relative archive name, not a project file.
                    expected = reference["sha256"]
                    if raw in checked:
                        if checked[raw] != expected:
                            return False, f"conflicting atlas input locks: {raw}"
                        continue
                    if not _content_reference_matches(reference):
                        return False, f"atlas input or output changed: {raw}"
                    checked[raw] = expected
                    if raw in component_manifests:
                        pending.append(_load_object(_project_path(raw))["inputs"])
            archive_reference = {
                "path": str(archive_path.relative_to(PROJECT_ROOT.resolve())),
                **suite["expected_output"],
            }
            if not _reference_matches(archive_reference):
                return False, "combined atlas output is missing or stale"
        integrated = _load_object(PROJECT_ROOT / "config/full-story-components.json")
        if not _reference_matches(integrated.get("kvmdata", {})):
            return False, "integrated KVMDATA lock is missing or stale"
        return True, "reviewed suite inputs, manifests, and KVMDATA SHA-256 match"
    except (KeyError, OSError, TextUpdateBuildError, UiAtlasSuiteError) as error:
        return False, str(error)


def _ui_atlas_output_exists(chain: Mapping[str, object]) -> bool:
    raw_suite = chain.get("atlas_suite")
    if not isinstance(raw_suite, str):
        return False
    try:
        suite = _load_object(_project_path(raw_suite))
        output_root = _project_path(suite["outputs"]["component_root"])
    except (KeyError, OSError, TextUpdateBuildError):
        return False
    return (output_root / "KURODATA/KVMDATA.BIN").is_file()


def verify_mtv_pros_endpoint(
    slps_path: Path,
    archive_path: Path,
) -> dict[str, object]:
    """Require the executable's last MTV_PROS offset to equal the archive size."""

    executable = slps_path.read_bytes()
    archive_size = archive_path.stat().st_size
    positions = tuple(range(MTV_PROS_TABLE_START, MTV_PROS_TABLE_END, 4))
    if not positions or positions[-1] + 4 > len(executable):
        raise TextUpdateBuildError("MTV_PROS offset table is outside SLPS_258.87")
    offsets = tuple(struct.unpack_from("<I", executable, offset)[0] for offset in positions)
    if offsets[0] != 0 or any(
        current >= following for current, following in zip(offsets, offsets[1:])
    ):
        raise TextUpdateBuildError("MTV_PROS offset table is not strictly increasing")
    if offsets[-1] != archive_size:
        raise TextUpdateBuildError(
            f"MTV_PROS/SLPS mismatch: executable endpoint={offsets[-1]}, "
            f"archive size={archive_size}"
        )
    return {
        "slps": str(slps_path.relative_to(PROJECT_ROOT)),
        "archive": str(archive_path.relative_to(PROJECT_ROOT)),
        "offset_count": len(offsets),
        "final_offset": offsets[-1],
        "archive_size": archive_size,
        "exact": True,
    }


def _git_state() -> dict[str, object]:
    def output(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()

    return {
        "head": output("rev-parse", "HEAD"),
        "dirty_paths": output("status", "--short").splitlines(),
    }


def _run_python(arguments: list[str]) -> None:
    subprocess.run([sys.executable, *arguments], cwd=PROJECT_ROOT, check=True)


def _incremental_component_arguments(*, refresh_manifest: bool) -> list[str]:
    arguments = [
        "tools/build_full_story_components.py",
        "--config",
        "config/full-story-components.json",
        "--force",
        "--incremental",
    ]
    if refresh_manifest:
        arguments.append("--refresh-manifest")
    return arguments


def _assignment_mapping_sha256(assignments: list[object]) -> str:
    try:
        rows = sorted(
            (item["character"], item["code"], item["glyph_index"])
            for item in assignments
            if isinstance(item, dict)
        )
    except (KeyError, TypeError) as error:
        raise TextUpdateBuildError(
            "release font proposal assignment is malformed"
        ) from error
    if len(rows) != len(assignments):
        raise TextUpdateBuildError(
            "release font proposal assignment is malformed"
        )
    return hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _font_component_cache_is_current(
    release: Mapping[str, object],
    *,
    allow_proposal_rebind: bool = False,
) -> tuple[bool, str]:
    outputs = release.get("outputs")
    if not isinstance(outputs, dict):
        return False, "release font output contract is malformed"
    raw_manifest = outputs.get("manifest")
    if not isinstance(raw_manifest, str):
        return False, "release font manifest is not registered"
    manifest_path = _project_path(raw_manifest)
    if not manifest_path.is_file():
        return False, "release font manifest is missing"
    try:
        manifest = _load_object(manifest_path)
        references = [
            manifest["font_component"]["report"],
            manifest["font_component"]["slps"],
            manifest["font_component"]["vt1"],
        ]
        if not allow_proposal_rebind:
            references.append(manifest["proposal"])
    except KeyError:
        return False, "release font manifest output locks are incomplete"
    stale = [
        str(reference.get("path"))
        for reference in references
        if not isinstance(reference, dict) or not _reference_matches(reference)
    ]
    if stale:
        return False, "release font cache is stale: " + ", ".join(stale)
    return True, "proposal and font component outputs match locked SHA-256"


def _changed_translation_sources(font_manifest: Mapping[str, object]) -> set[str]:
    """Compare the current selected translation tree with the prior font proof."""

    selection = font_manifest.get("inputs", {}).get("translation_selection")
    if not isinstance(selection, dict):
        raise TextUpdateBuildError("font manifest has no translation selection")
    root_reference = selection.get("root")
    pattern = selection.get("glob", "**/*.json")
    exclude_globs = selection.get("exclude_globs", [])
    sources = selection.get("sources")
    if (
        not isinstance(root_reference, str)
        or not isinstance(pattern, str)
        or not isinstance(exclude_globs, list)
        or any(not isinstance(item, str) for item in exclude_globs)
        or not isinstance(sources, list)
    ):
        raise TextUpdateBuildError("font translation selection is malformed")
    root = _project_path(root_reference)
    prior = {
        reference["path"]: reference
        for reference in sources
        if isinstance(reference, dict) and isinstance(reference.get("path"), str)
    }
    current_paths = {
        str(path.relative_to(PROJECT_ROOT.resolve()))
        for path in root.glob(pattern)
        if path.is_file()
        and not any(path.relative_to(root).match(glob) for glob in exclude_globs)
    }
    changed = set(prior) ^ current_paths
    changed.update(
        raw_path
        for raw_path in set(prior) & current_paths
        if not _content_reference_matches(prior[raw_path])
    )
    return changed


def _story_component_cache_is_current(
    changed_translation_sources: set[str],
) -> tuple[bool, str]:
    story_prefixes = ("corpus/zh/story-dialogue/",)
    story_files = {
        "corpus/zh/story-conditions.json",
        "corpus/zh/story-speakers.json",
        "corpus/zh/story-tickers.json",
        "corpus/zh/story-z-reports.json",
    }
    changed_story = sorted(
        path
        for path in changed_translation_sources
        if path in story_files or path.startswith(story_prefixes)
    )
    if changed_story:
        return False, "story translation changed: " + ", ".join(changed_story)
    integrated = _load_object(PROJECT_ROOT / "config/full-story-components.json")
    references = integrated.get("full_story_stage")
    if not isinstance(references, dict):
        return False, "integrated story output locks are missing"
    report_reference = references.get("report")
    if not isinstance(report_reference, dict) or not _reference_matches(
        report_reference
    ):
        return False, "story component report is missing or stale"
    report = _load_object(_project_path(report_reference["path"]))
    inputs = report.get("inputs")
    if not isinstance(inputs, dict):
        return False, "story component input locks are missing"
    proposal_reference = inputs.get("proposal", {})
    proposal_path = proposal_reference.get("path")
    same_font = bool(
        isinstance(proposal_path, str)
        and report.get("font_binary_signature")
        == _font_binary_signature(_load_object(_project_path(proposal_path)))
    )
    stale_inputs = [
        label
        for label, reference in inputs.items()
        if not (label == "proposal" and same_font)
        and isinstance(reference, dict)
        and isinstance(reference.get("path"), str)
        and not _content_reference_matches(reference)
    ]
    if stale_inputs:
        return False, "story component input changed: " + ", ".join(stale_inputs)
    stale_outputs = [
        label
        for label in ("stage", "hb")
        if not isinstance(references.get(label), dict)
        or not _reference_matches(references[label])
    ]
    if stale_outputs:
        return False, "story component output changed: " + ", ".join(stale_outputs)
    return True, "story inputs and outputs match locked SHA-256"


def _rebind_story_font_proposal(*, refresh_manifests: bool) -> None:
    integrated = _load_object(PROJECT_ROOT / "config/full-story-components.json")
    path = _project_path(integrated["full_story_stage"]["report"]["path"])
    report = _load_object(path)
    reference = report["inputs"]["proposal"]
    if _content_reference_matches(reference):
        return
    proposal = _load_object(_project_path(reference["path"]))
    if report.get("font_binary_signature") != _font_binary_signature(proposal):
        raise TextUpdateBuildError("story font mapping changed; rebuild STAGE")
    if not refresh_manifests:
        raise TextUpdateBuildError("story font proof drift; rerun with --refresh-manifests")
    reference["sha256"] = _sha256(_project_path(reference["path"]))
    _write_object(path, report)
    print("[refresh] rebound unchanged STAGE bytes to current font selection", flush=True)


def _library_component_cache_is_current(
    *,
    ignore_font_manifest: bool,
    ignore_font_proposal: bool = False,
) -> tuple[bool, str]:
    integrated = _load_object(PROJECT_ROOT / "config/full-story-components.json")
    reference = integrated.get("runtime_keywords", {}).get(
        "library_component_manifest"
    )
    if not isinstance(reference, dict) or not _reference_matches(reference):
        return False, "reviewed LIBRARY manifest is missing or stale"
    manifest = _load_object(_project_path(reference["path"]))
    inputs = manifest.get("inputs")
    outputs = manifest.get("outputs")
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        return False, "reviewed LIBRARY locks are incomplete"
    stale_inputs = [
        label
        for label, item in inputs.items()
        if not (ignore_font_manifest and label == "font_manifest")
        and not (ignore_font_proposal and label == "font_proposal")
        and isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and not _content_reference_matches(item)
    ]
    if stale_inputs:
        return False, "reviewed LIBRARY input changed: " + ", ".join(stale_inputs)
    stale_outputs = [
        member
        for member, item in outputs.items()
        if not isinstance(item, dict) or not _reference_matches(item)
    ]
    if stale_outputs:
        return False, "reviewed LIBRARY output changed: " + ", ".join(stale_outputs)
    return True, "LIBRARY binary inputs and outputs match locked SHA-256"


def _rebind_library_font_manifest(
    *,
    refresh_manifests: bool,
    allow_proposal_rebind: bool,
) -> bool:
    """Refresh a metadata-only font proof edge without rebuilding LIBRARY bytes."""

    integrated = _load_object(PROJECT_ROOT / "config/full-story-components.json")
    reference = integrated["runtime_keywords"]["library_component_manifest"]
    manifest_path = _project_path(reference["path"])
    manifest = _load_object(manifest_path)
    target = manifest["inputs"]["font_manifest"]
    current_path = _project_path(target["path"])
    size, digest = _file_identity(current_path)
    current = {"path": target["path"], "size": size, "sha256": digest}
    font_manifest = _load_object(current_path)
    proposal_changed = (
        font_manifest.get("proposal") != manifest["inputs"].get("font_proposal")
    )
    if target == current and not proposal_changed:
        return False
    if not refresh_manifests:
        raise TextUpdateBuildError(
            "reviewed LIBRARY font proof drift; rerun with --refresh-manifests"
        )
    cache_current, reason = _library_component_cache_is_current(
        ignore_font_manifest=True,
        ignore_font_proposal=allow_proposal_rebind,
    )
    if not cache_current:
        raise TextUpdateBuildError(reason)
    if proposal_changed and not allow_proposal_rebind:
        raise TextUpdateBuildError(
            "font proposal changed; reviewed LIBRARY must be rebuilt"
        )
    manifest["inputs"]["font_manifest"] = current
    if proposal_changed:
        manifest["inputs"]["font_proposal"] = font_manifest["proposal"]
    _write_object(manifest_path, manifest)
    print(
        "[refresh] rebound unchanged LIBRARY bytes to current font proof",
        flush=True,
    )
    return True


def _rebuild_release_font(
    chain: Mapping[str, object],
    *,
    refresh_manifests: bool,
) -> dict[str, object]:
    raw_release = chain.get("release_profile")
    if not isinstance(raw_release, str):
        raise TextUpdateBuildError("font chain has no release profile")
    release = _load_object(_project_path(raw_release))
    outputs = release.get("outputs")
    snapshot = release.get("allocation_snapshot")
    if not isinstance(outputs, dict) or not isinstance(snapshot, dict):
        raise TextUpdateBuildError("release font output contract is malformed")
    proposal_path = _project_path(outputs["proposal"])
    strict_cache_current, _strict_cache_reason = _font_component_cache_is_current(
        release
    )
    prior_proposal = (
        _load_object(proposal_path) if strict_cache_current else None
    )
    raster_handoff = str(proposal_path.with_suffix(".rasters.json"))
    _run_python(
        [
            "tools/prepare_zh_release_font.py",
            "--config",
            raw_release,
            "--force",
            "--reuse-raster-cache",
            "--raster-output",
            raster_handoff,
        ]
    )
    current_proposal = _load_object(proposal_path)
    proposal_binary_unchanged = bool(
        prior_proposal is not None
        and _font_binary_signature(prior_proposal)
        == _font_binary_signature(current_proposal)
    )
    cache_current, cache_reason = _font_component_cache_is_current(
        release,
        allow_proposal_rebind=(
            strict_cache_current and proposal_binary_unchanged
        ),
    )
    if cache_current and prior_proposal != current_proposal:
        cache_reason = "font binary proposal unchanged; selection metadata rebound"
    if cache_current:
        print(f"[cache] release font component reused: {cache_reason}", flush=True)
    else:
        print(f"[cache] release font component rebuild: {cache_reason}", flush=True)
        _run_python(
            [
                "tools/build_zh_font_component.py",
                "--font-config",
                raw_release,
                "--proposal",
                str(outputs["proposal"]),
                "--raster-input",
                raster_handoff,
                "--allocation-registry",
                str(snapshot["path"]),
                "--output-root",
                str(outputs["component_root"]),
                "--force",
            ]
        )
    verify = [
        "tools/verify_zh_release_font.py",
        "--config",
        raw_release,
        "--force",
    ]
    if refresh_manifests:
        verify.append("--refresh-manifest")
    _run_python(verify)
    return {
        "reused": cache_current,
        "reason": cache_reason,
        "proposal_binary_unchanged": proposal_binary_unchanged,
    }


def _rebuild_story_and_library(
    *,
    story_workers: int,
    library_workers: int,
    refresh_manifests: bool,
    build_story: bool = True,
    build_library: bool = True,
) -> dict[str, bool]:
    story = [
        "tools/build_story_component.py",
        "--incremental",
        "--config",
        "config/story-component.json",
        "--workers",
        str(story_workers),
        "--force",
    ]
    library = [
        "tools/build_library_v02_component.py",
        "--workers",
        str(library_workers),
        "--force",
    ]
    if refresh_manifests:
        library.append("--refresh-manifest")
    commands = []
    if build_story:
        commands.append(story)
    else:
        print("[cache] story component reused", flush=True)
    if build_library:
        commands.append(library)
    else:
        print("[cache] reviewed LIBRARY component reused", flush=True)
    if len(commands) == 2:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_run_python, command) for command in commands]
            for future in futures:
                future.result()
    elif commands:
        _run_python(commands[0])
    return {"story_rebuilt": build_story, "library_rebuilt": build_library}


def _timed(
    timings: list[dict[str, object]],
    label: str,
    action: Callable[[], object],
) -> object:
    print(f"\n[phase] {label}", flush=True)
    started = time.perf_counter()
    status = "passed"
    try:
        return action()
    except Exception:
        status = "failed"
        raise
    finally:
        seconds = round(time.perf_counter() - started, 3)
        timings.append({"phase": label, "seconds": seconds, "status": status})
        print(f"[timing] {label}: {seconds:.3f}s ({status})", flush=True)


def _write_timing_report(path: Path, report: Mapping[str, object]) -> None:
    path = path.resolve()
    try:
        path.relative_to((PROJECT_ROOT / "work").resolve())
    except ValueError as error:
        raise TextUpdateBuildError("timing report must stay below work/") from error
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_object(path, report)


def build(args: argparse.Namespace) -> dict[str, object]:
    started = time.perf_counter()
    timings: list[dict[str, object]] = []
    git_start = _git_state()
    iso_config_path = args.iso_config.resolve()
    chain_path = args.chain_config.resolve()
    iso_config = _load_object(iso_config_path)
    chain = _load_object(chain_path)
    original_iso_cache: dict[str, object] | None = None
    font_component_cache: dict[str, object] | None = None
    text_component_cache: dict[str, object] | None = None
    source_iso = _project_path(iso_config.get("source_iso", {}).get("path"))

    if args.release_proof:
        _timed(
            timings,
            "reject untracked production JSON",
            _assert_no_untracked_production_json,
        )

    original_iso_cache = _timed(
        timings,
        "verify hash-locked original ISO",
        lambda: _verify_original_iso(
            source_iso,
            iso_config["source_iso"],
            force=args.release_proof,
        ),
    )
    tracked_configs = _tracked_config_paths()
    original_locks = collect_original_member_locks(tracked_configs)

    def prepare_original_members() -> None:
        repairs = [
            member
            for member, reference in original_locks.items()
            if not _reference_matches(reference)
        ]
        if repairs:
            if shutil.which("7z") is None:
                raise TextUpdateBuildError("7z is required to extract original members")
            _run_python(
                [
                    "tools/extract_iso_member.py",
                    "--iso",
                    str(source_iso),
                    "--output",
                    str(PROJECT_ROOT / "work/disc"),
                    "--force",
                    *repairs,
                ]
            )
        stale = [
            member
            for member, reference in original_locks.items()
            if not _reference_matches(reference)
        ]
        if stale:
            raise TextUpdateBuildError(
                "extracted original members do not match tracked locks: "
                + ", ".join(stale)
            )
        print(
            f"[OK] original-member cache: {len(original_locks)} files; "
            f"recreated={len(repairs)}"
        )

    _timed(timings, "verify or extract original members", prepare_original_members)
    _timed(
        timings,
        "build repository-owned Rust codec",
        lambda: _run_python(["tools/build_rust_compressor.py", "--force"]),
    )
    _timed(
        timings,
        "bootstrap pinned mkps2iso",
        lambda: _run_python(
            ["tools/bootstrap_mkps2iso.py", "--config", str(iso_config_path)]
        ),
    )
    font_arguments = ["tools/fetch_zh_font.py", "--flavor", str(chain["font_flavor"])]
    if _font_cache_requires_force(chain):
        font_arguments.append("--force")
    _timed(
        timings,
        "verify or fetch pinned fonts",
        lambda: _run_python(font_arguments),
    )

    if args.prepare_only:
        return {
            "schema_version": 1,
            "status": "prerequisites_ready",
            "mode": "prepare-only",
            "git_start": git_start,
            "git_end": _git_state(),
            "original_member_count": len(original_locks),
            "original_iso_cache": original_iso_cache,
            "phases": timings,
            "total_seconds": round(time.perf_counter() - started, 3),
        }

    _timed(
        timings,
        "refresh or verify text input locks",
        lambda: (
            _refresh_release_menu_selection_lock(
                refresh=args.refresh_manifests
            ),
            _refresh_text_locks(TEXT_LOCK_CONFIGS, refresh=args.refresh_manifests),
            _audit_other_text_locks(tracked_configs),
        ),
    )
    cache_current, cache_reason = _timed(
        timings,
        "validate reusable rendered UI assets",
        lambda: _ui_atlas_cache_is_current(
            chain, reconstruct=args.release_proof,
            verified_files={iso_config["source_iso"]["path"]: iso_config["source_iso"]["sha256"]},
        ),
    )
    existing_ui_output = _ui_atlas_output_exists(chain)
    if not cache_current and existing_ui_output and not args.force_full:
        raise TextUpdateBuildError(
            "rendered UI asset cache drifted: "
            f"{cache_reason}; resolve/refreeze the asset change or rerun with "
            "--force-full instead of silently turning a text build into a full build"
        )
    full_mode = args.force_full or not existing_ui_output
    if full_mode:
        print(f"[build-mode] full asset bootstrap: {cache_reason}", flush=True)
        arguments = [
            "tools/rebuild_zh_font.py",
            "--config",
            str(chain_path),
            "--skip-fetch",
            "--force-rebuild",
            "--atlas-workers",
            str(args.atlas_workers),
        ]
        if args.refresh_manifests:
            arguments.append("--refresh-manifests")
        _timed(
            timings,
            "rebuild font and all component consumers",
            lambda: _run_python(arguments),
        )
    else:
        print(f"[build-mode] text-only: {cache_reason}", flush=True)
        prior_font_manifest = _load_object(
            _project_path(_load_object(_project_path(chain["release_profile"]))["outputs"]["manifest"])
        )
        changed_translation_sources = _changed_translation_sources(
            prior_font_manifest
        )
        story_current, story_reason = _story_component_cache_is_current(
            changed_translation_sources
        )
        library_current, library_reason = _library_component_cache_is_current(
            ignore_font_manifest=True
        )
        font_component_cache = _timed(
            timings,
            "refresh font coverage and reuse unchanged font component",
            lambda: _rebuild_release_font(
                chain,
                refresh_manifests=args.refresh_manifests,
            ),
        )
        rebuild_story = not story_current or not font_component_cache["reused"]
        rebuild_library = not library_current or not font_component_cache["reused"]
        print(
            f"[cache] story decision: rebuild={rebuild_story}; {story_reason}",
            flush=True,
        )
        print(
            f"[cache] LIBRARY decision: rebuild={rebuild_library}; {library_reason}",
            flush=True,
        )
        text_component_cache = _timed(
            timings,
            "rebuild only changed story or reviewed LIBRARY components",
            lambda: _rebuild_story_and_library(
                story_workers=args.story_workers,
                library_workers=args.library_workers,
                refresh_manifests=args.refresh_manifests,
                build_story=rebuild_story,
                build_library=rebuild_library,
            ),
        )
        if not rebuild_story:
            _timed(
                timings,
                "rebind unchanged STAGE to current font selection",
                lambda: _rebind_story_font_proposal(refresh_manifests=args.refresh_manifests),
            )
        if not rebuild_library and font_component_cache["reused"]:
            _timed(
                timings,
                "rebind unchanged LIBRARY to current font proof",
                lambda: _rebind_library_font_manifest(
                    refresh_manifests=args.refresh_manifests,
                    allow_proposal_rebind=bool(
                        font_component_cache["proposal_binary_unchanged"]
                    ),
                ),
            )
        _timed(
            timings,
            "bind rebuilt font, story, and library dependencies",
            lambda: _update_full_component_dependencies(
                refresh=args.refresh_manifests
            ),
        )
        full_arguments = _incremental_component_arguments(
            refresh_manifest=args.refresh_manifests
        )
        _timed(
            timings,
            "rebuild integrated text components from original members",
            lambda: _run_python(full_arguments),
        )
        _timed(
            timings,
            "rebuild frozen AID battle prompts",
            lambda: _run_python(["tools/build_aid_battle_prompts.py", "--force"]),
        )
        _timed(
            timings,
            "rebuild frozen TRICMN battle overlays",
            lambda: _run_python(
                ["tools/build_tricmn_battle_overlays.py", "--force"]
            ),
        )
        _timed(
            timings,
            "compose validated component set",
            lambda: _run_python(
                ["tools/compose_full_story_library_components.py"]
            ),
        )

    _timed(
        timings,
        "verify all derived dependency locks",
        _assert_full_component_dependencies_current,
    )
    component_root = PROJECT_ROOT / "work/build/zh-release-full-story/components"
    endpoint = _timed(
        timings,
        "verify SLPS and MTV_PROS coupled layout",
        lambda: verify_mtv_pros_endpoint(
            component_root / "SLPS_258.87",
            component_root / "DATA/MTV_PROS.BIN",
        ),
    )

    if getattr(args, "components_only", False):
        return {
            "schema_version": 1, "status": "components_validated_runtime_pending",
            "mode": "full-assets" if full_mode else "incremental-components",
            "phases": timings, "total_seconds": round(time.perf_counter() - started, 3),
        }

    iso_arguments = ["tools/build_iso.py", "--config", str(iso_config_path)]
    if not args.release_proof and not args.force_full:
        iso_arguments.append("--incremental")
    if args.refresh_manifests:
        iso_arguments.append("--refresh-output-locks")
    _timed(
        timings,
        "build and structurally validate ISO",
        lambda: _run_python(iso_arguments),
    )
    current_iso_config = _load_object(iso_config_path)
    current_output_path = _project_path(current_iso_config["output"]["path"])
    if args.release_proof:
        readback_arguments = [
            "tools/verify_full_story_iso_content.py",
            "--iso",
            str(current_output_path),
            "--build-config",
            str(iso_config_path),
            "--force",
        ]
        if args.refresh_manifests:
            readback_arguments.append("--refresh-manifest")
        _timed(
            timings,
            "reread localized content from final ISO",
            lambda: _run_python(readback_arguments),
        )
        _timed(
            timings,
            "repeat ISO build for deterministic lock proof",
            lambda: _run_python(
                ["tools/build_iso.py", "--config", str(iso_config_path)]
            ),
        )

    final_config = _load_object(iso_config_path)
    output_path = _project_path(final_config["output"]["path"])
    # The ISO builder has just read back the image and recorded its full hash.
    # Rehashing the same 3.7 GB a second time adds no independent evidence.
    iso_report = _load_object(_project_path(final_config["output"]["report"]))
    output_size = iso_report["output_iso"]["size"]
    output_digest = iso_report["output_iso"]["sha256"]
    return {
        "schema_version": 1,
        "status": (
            "static_iso_validated_runtime_pending"
            if args.release_proof
            else "structural_iso_validated_content_readback_pending"
        ),
        "mode": "full-assets" if full_mode else "text-only",
        "git_start": git_start,
        "git_end": _git_state(),
        "original_member_count": len(original_locks),
        "original_iso_cache": original_iso_cache,
        "ui_asset_cache": {
            "reused": not full_mode,
            "reason": cache_reason,
        },
        "font_component_cache": font_component_cache,
        "text_component_cache": text_component_cache,
        "mtv_pros_layout": endpoint,
        "iso": {
            "path": str(output_path.relative_to(PROJECT_ROOT)),
            "size": output_size,
            "sha256": output_digest,
        },
        "validation": {
            "fixed_lba_and_structure": "passed",
            "full_content_readback": (
                "passed" if args.release_proof else "pending"
            ),
            "deterministic_second_build": (
                "passed" if args.release_proof else "pending"
            ),
        },
        "phases": timings,
        "total_seconds": round(time.perf_counter() - started, 3),
        "runtime": "pending; this script does not execute PCSX2",
    }


def main() -> int:
    args = parse_args()
    report_path = args.timing_report.resolve()
    started = time.perf_counter()
    try:
        report = build(args)
        _write_timing_report(report_path, report)
        print(
            f"\n[OK] {report['status']}; mode={report['mode']}; "
            f"total={report['total_seconds']:.3f}s"
        )
        print(f"[OK] timing report: {report_path.relative_to(PROJECT_ROOT)}")
        if "iso" in report:
            print(
                f"[OK] ISO: {report['iso']['path']} "
                f"sha256={report['iso']['sha256']}"
            )
        return 0
    except (OSError, KeyError, subprocess.SubprocessError, TextUpdateBuildError) as error:
        failed = {
            "schema_version": 1,
            "status": "failed",
            "error": str(error),
            "total_seconds": round(time.perf_counter() - started, 3),
        }
        try:
            _write_timing_report(report_path, failed)
        except (OSError, TextUpdateBuildError):
            pass
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
