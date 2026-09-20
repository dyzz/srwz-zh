"""Freeze build definitions once; never share writable files between targets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .edition import EditionError, json_bytes, load_json, project_path


SOURCE_ROOTS = ("config", "corpus", "manifests", "tools", "vendor/upstream-python")
SKIP_PARTS = {".git", "__pycache__", "target", ".DS_Store", ".pytest_cache"}
SKIP_PREFIXES = ("config/editorial/", "manifests/editions/")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def copy_file(source: Path | str, target: Path | str) -> str:
    """APFS clone when available; copying fallback, never a writable hardlink."""
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.stat().st_size >= 1024 * 1024 and sys.platform == "darwin":
        result = subprocess.run(["cp", "-c", str(source), str(target)], capture_output=True)
        if result.returncode == 0:
            shutil.copystat(source, target)
            return str(target)
    shutil.copy2(source, target)
    return str(target)


def source_inventory(root: Path, additional_paths: tuple[str, ...] = ()) -> list[dict]:
    root = root.resolve()
    rows = []
    for name in SOURCE_ROOTS:
        start = project_path(root, name)
        if not start.is_dir():
            raise EditionError(f"missing build input tree: {name}")
        for directory, children, files in os.walk(start, followlinks=False):
            children[:] = sorted(c for c in children if c not in SKIP_PARTS)
            for child in children:
                if (Path(directory) / child).is_symlink():
                    raise EditionError(f"build input directory is a symlink: {Path(directory) / child}")
            for name in sorted(files):
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix()
                if name in SKIP_PARTS or name.endswith((".pyc", ".pyo")) or relative.startswith(SKIP_PREFIXES):
                    continue
                if path.is_symlink():
                    raise EditionError(f"build input is a symlink: {relative}")
                rows.append({"path": relative, "size": path.stat().st_size,
                             "sha256": sha256_file(path), "mode": path.stat().st_mode & 0o777})
    existing = {row["path"] for row in rows}
    for relative in additional_paths:
        if relative in existing:
            continue
        path = project_path(root, relative)
        if (root / relative).is_symlink() or not path.is_file():
            raise EditionError(f"missing or symlinked frozen dependency: {relative}")
        rows.append({"path": relative, "size": path.stat().st_size,
                     "sha256": sha256_file(path), "mode": path.stat().st_mode & 0o777})
        existing.add(relative)
    return sorted(rows, key=lambda row: row["path"])


def verify_files(root: Path, rows: list[dict]) -> None:
    for row in rows:
        path = project_path(root, row["path"])
        if (not path.is_file() or path.is_symlink() or path.stat().st_size != row["size"]
                or sha256_file(path) != row["sha256"] or path.stat().st_mode & 0o777 != row["mode"]):
            raise EditionError(f"frozen input drift: {row['path']}")


@dataclass(frozen=True)
class InputSnapshot:
    root: Path
    digest: str
    source_head: str
    files: tuple[dict, ...]
    additional_paths: tuple[str, ...] = ()

    @property
    def project_root(self) -> Path:
        return self.root / "project"

    def materialize(self, target: Path) -> None:
        verify_files(self.project_root, list(self.files))
        for name in SOURCE_ROOTS:
            project_path(target, name).mkdir(parents=True, exist_ok=True)
        for row in self.files:
            copy_file(self.project_root / row["path"], project_path(target, row["path"]))
        verify_files(target, list(self.files))
        if source_inventory(target, self.additional_paths) != list(self.files):
            raise EditionError("private project contains inputs outside the frozen snapshot")


def freeze_inputs(root: Path, additional_paths: tuple[str, ...] = ()) -> InputSnapshot:
    root = root.resolve()
    rows = source_inventory(root, additional_paths)
    digest = hashlib.sha256(json_bytes(rows)).hexdigest()
    shared = project_path(root, "work/build/shared", "work/build")
    shared.mkdir(parents=True, exist_ok=True)
    destination = shared / digest
    if destination.exists():
        existing = load_json(destination / "inputs.json")
        if existing.get("input_digest") != digest or existing.get("files") != rows:
            raise EditionError("shared input snapshot identity drift")
        snapshot = InputSnapshot(destination, digest, existing["source_head"], tuple(rows), additional_paths)
        verify_files(snapshot.project_root, rows)
        return snapshot
    source_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    temporary = Path(tempfile.mkdtemp(prefix=".capture-", dir=shared))
    try:
        for row in rows:
            copy_file(root / row["path"], temporary / "project" / row["path"])
        verify_files(temporary / "project", rows)
        # Detect edits and newly added input files during capture, before using it.
        if source_inventory(root, additional_paths) != rows:
            raise EditionError("build inputs changed during snapshot capture; retry with the new inputs")
        (temporary / "inputs.json").write_bytes(json_bytes({
            "schema_version": 1, "input_digest": digest, "source_head": source_head,
            "files": rows, "scope": "actual working-tree build definitions; output receipts and editorial state excluded",
        }))
        try:
            temporary.rename(destination)
        except OSError:
            # A concurrent capture is usable only after exact identity checks.
            if not destination.is_dir() or load_json(destination / "inputs.json").get("files") != rows:
                raise
            verify_files(destination / "project", rows)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return InputSnapshot(destination, digest, source_head, tuple(rows), additional_paths)


def seed_original_caches(source: Path, target: Path) -> None:
    """Optional caches only; production builders still verify their locked inputs.

    Seed the legacy production namespaces, excluding edition workspaces,
    experiments, runtime captures, saves and analysis. Authoritative source
    files have already been materialized from the frozen snapshot.
    """
    directories = [source / "work" / name for name in ("disc", "font-source", "toolchain", "writeback")]
    build = source / "work/build"
    if build.is_dir():
        directories.extend(path for path in build.iterdir() if path.is_dir()
                           and not path.name.startswith(("best-", "zh-release-original", "zh-release-best", "zh-release-sp", "shared", "stage-canary", "special-disc")))
    directories.extend(source / "work/review" / name for name in ("aid-battle-prompts-zh", "tricmn-battle-overlays-zh"))
    for directory in directories:
        if directory.is_dir():
            destination = target / directory.relative_to(source)
            if not destination.exists():
                shutil.copytree(directory, destination, copy_function=copy_file)
    # Some fixed reviewed inputs are individual JSON/binary locks, not directories.
    def references(value):
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                yield value
            for child in value.values():
                yield from references(child)
        elif isinstance(value, list):
            for child in value:
                yield from references(child)
    for base in ("config", "manifests"):
        for path in (target / base).rglob("*.json"):
            for lock in references(json.loads(path.read_text(encoding="utf-8"))):
                raw = lock["path"]
                if not raw.startswith("work/"):
                    continue
                cached = project_path(source, raw, "work")
                destination = project_path(target, raw, "work")
                if cached.is_file() and not destination.exists() and sha256_file(cached) == lock["sha256"]:
                    copy_file(cached, destination)
