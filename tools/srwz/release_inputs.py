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

from .language import SP_REGIONAL_CONFIGS
from .edition import EditionError, json_bytes, load_json, project_path
from .file_identity import record_clone, sha256_file


SOURCE_ROOTS = ("config", "corpus", "manifests", "tools", "vendor/upstream-python", "shared/text-layout")
SKIP_PARTS = {".git", "__pycache__", "target", ".DS_Store", ".pytest_cache"}
SKIP_PREFIXES = ("config/editorial/", "manifests/editions/")
# Build definitions only. Documentation, authoring aids and runtime tooling
# under the source roots do not change any produced byte; keeping them out of
# the frozen input set stops a README edit from forcing a full rebuild.
SKIP_SUFFIXES = (".md", ".DS_Store")
SKIP_SOURCE_PREFIXES = (
    "tools/zh_hant/fill_corpora.py",  # preflight only; the resolved corpus bytes are captured below
    "tools/editorial_review/",
    "tools/templates/",
    "tools/native/battle-square-skip/",
    "tools/text_layout/rebalance_story_dialogue.py",
    "tools/text_layout/build_story_unbroken_words.py",
    "tools/export_explanatory_text.py",
    "tools/export_misc_text.py",
    "tools/select_misc_text_export.py",
    "tools/render_misc_review.py",
    "tools/run_lrps2_validation.py",
    "tools/srwz/lrps2_runtime.py",
    "tools/prune_edition_workspaces.py",
)


def is_build_input(relative: str) -> bool:
    """True for files that belong in the frozen build-definition snapshot."""
    if relative.startswith("shared/text-layout/"):
        return relative in {"shared/text-layout/"+name for name in ("engine.mjs","contracts.mjs","cli.mjs","cli-handler.mjs","proportional-selection.mjs","proportional-metrics.mjs","story-ink.mjs","story-ink-data.mjs")}
    name = relative.rsplit("/", 1)[-1]
    if name in SKIP_PARTS or name.endswith((".pyc", ".pyo")) or relative.endswith(SKIP_SUFFIXES):
        return False
    return not relative.startswith(SKIP_PREFIXES + SKIP_SOURCE_PREFIXES)


def copy_file(source: Path | str, target: Path | str) -> str:
    """APFS clone when available; copying fallback, never a writable hardlink.

    A kernel clone is byte-identical by construction, so the digests already
    verified for the source are carried to the clone instead of being recomputed.
    """
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.stat().st_size >= 1024 * 1024 and sys.platform == "darwin":
        if _clonefile(source, target):
            shutil.copystat(source, target)
            record_clone(source, target)
            return str(target)
    try:
        shutil.copy2(source, target)
    except PermissionError:
        # A read-only file of an earlier copy (a git pack in a seeded toolchain) is being replaced, not edited.
        if not target.is_file() or target.is_symlink():
            raise
        target.unlink()
        shutil.copy2(source, target)
    return str(target)


_CLONEFILE = None


def _clonefile(source: Path, target: Path) -> bool:
    """APFS clone by the system call `cp -c` makes (no process per file); False when it cannot clone."""
    global _CLONEFILE
    if _CLONEFILE is None:
        try:
            import ctypes
            import ctypes.util
            function = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True).clonefile
            function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
            function.restype = ctypes.c_int
            _CLONEFILE = function
        except (OSError, AttributeError):
            _CLONEFILE = False
    sys.audit("srwz.clonefile", str(source), str(target))     # a read of source (srwz.step_memo's record)
    if _CLONEFILE:
        if target.is_symlink() or target.exists():
            target.unlink()          # clonefile does not replace; cp -c did
        if _CLONEFILE(os.fsencode(source.resolve()), os.fsencode(target), 0) == 0:
            return True
    result = subprocess.run(["cp", "-c", str(source), str(target)], capture_output=True)
    return result.returncode == 0


def source_inventory(root: Path, additional_paths: tuple[str, ...] = (), *, language: str | None = None) -> list[dict]:
    root = root.resolve()
    rows = []
    variant = {"zh-hant-hk": "hk", "zh-hant-tw": "tw"}.get(language)
    shared = set()
    if variant == "hk":
        manifest = load_json(root / "config/zh-hant/hk-uses-taiwan.json")
        shared = {"corpus/zh-hant/" + path for path in manifest["files"]}
        shared.add("corpus/zh-hant/menu/stage-names.json")
    for name in SOURCE_ROOTS:
        start = project_path(root, name)
        if not start.is_dir():
            raise EditionError(f"missing build input tree: {name}")
        for directory, children, files in os.walk(start, followlinks=False):
            children[:] = sorted(c for c in children if c not in SKIP_PARTS)
            if Path(directory) == root / "corpus" and language is not None:
                if language != "zh-hant-hk":
                    children[:] = [c for c in children if c not in ("zh-hant-hk", "glossary-zh-hant-hk", "runtime-zh-hant-hk")]
                if variant:
                    children[:] = [c for c in children if c not in ("zh", "glossary", "runtime")]
                if variant == "hk":
                    children[:] = [c for c in children if c not in ("glossary-zh-hant", "runtime-zh-hant")]
                if not language:
                    children[:] = [c for c in children if c not in ("zh-hant", "glossary-zh-hant", "runtime-zh-hant")]
            for child in children:
                if (Path(directory) / child).is_symlink():
                    raise EditionError(f"build input directory is a symlink: {Path(directory) / child}")
            for name in sorted(files):
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix()
                if variant and relative in SP_REGIONAL_CONFIGS:
                    continue
                if variant == "hk" and relative.startswith("corpus/zh-hant/") and relative not in shared:
                    continue
                if language is not None and relative.startswith("config/zh-hant/"):
                    parts = relative.split("/")
                    if parts[2] in ("main-text", "sp-configs", "sp-strings", "tool-literals"):
                        if parts[3].removesuffix(".json") != variant:
                            continue
                    if parts[2] in ("text-layout", "text-layout-hk"):
                        if variant != ("hk" if parts[2].endswith("-hk") else "tw"):
                            continue
                if not is_build_input(relative):
                    continue
                if path.is_symlink():
                    raise EditionError(f"build input is a symlink: {relative}")
                rows.append({"path": relative, "size": path.stat().st_size,
                             "sha256": sha256_file(path), "mode": path.stat().st_mode & 0o777})
    existing = {row["path"] for row in rows}
    for relative in additional_paths:
        if relative in existing or (variant and relative in SP_REGIONAL_CONFIGS):
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


def freeze_inputs(root: Path, additional_paths: tuple[str, ...] = (), *, language: str = "",
                  view=None, view_identity: str = "") -> InputSnapshot:
    """Capture the build inputs once. With ``language``, capture that language's view of them instead:
    ``view(project)`` rewrites a private copy of the inputs in place (srwz.language) and the snapshot, its
    digest and every later identity check are those of the rewritten tree."""
    root = root.resolve()
    rows = source_inventory(root, additional_paths, language=language)
    shared = project_path(root, "work/build/shared", "work/build")
    shared.mkdir(parents=True, exist_ok=True)
    if language:
        return _freeze_language_view(root, rows, additional_paths, shared, language, view, view_identity)
    digest = hashlib.sha256(json_bytes(rows)).hexdigest()
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
        if source_inventory(root, additional_paths, language=language) != rows:
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


def _keep_only(project: Path, keep: set[str]) -> None:
    """Drop everything a view left in its private copy besides the frozen files (support trees, caches)."""
    for directory, children, files in os.walk(project, topdown=False, followlinks=False):
        here = Path(directory)
        for name in files:
            if (here / name).relative_to(project).as_posix() not in keep:
                (here / name).unlink()
        for name in children:
            child = here / name
            if child.is_symlink():
                child.unlink()
            elif not any(child.iterdir()) and child.relative_to(project).as_posix() not in SOURCE_ROOTS:
                child.rmdir()


def _freeze_language_view(root: Path, rows: list[dict], additional_paths: tuple[str, ...], shared: Path,
                          language: str, view, view_identity: str) -> InputSnapshot:
    source_digest = hashlib.sha256(json_bytes(rows)).hexdigest()
    # A view is a function of the captured inputs and of what ``view_identity`` names (the Original builds an SP
    # view takes its inherited text from). The same key finds the view made before, verified file by file.
    memo = shared / ".views" / (hashlib.sha256(f"{source_digest} {language} {view_identity}".encode()).hexdigest() + ".json")
    if memo.is_file():
        known = load_json(memo)
        destination = shared / known["input_digest"]
        if (destination / "inputs.json").is_file():
            existing = load_json(destination / "inputs.json")
            if existing.get("input_digest") == known["input_digest"] and existing.get("language") == language:
                try:
                    verify_files(destination / "project", existing["files"])
                except EditionError:
                    pass
                else:
                    os.utime(destination)      # in use: workspace pruning keeps recent snapshots
                    return InputSnapshot(destination, existing["input_digest"], existing["source_head"],
                                         tuple(existing["files"]), tuple(known["additional_paths"]))
    source_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    temporary = Path(tempfile.mkdtemp(prefix=f".capture-{language}-", dir=shared))
    try:
        project = temporary / "project"
        for name in SOURCE_ROOTS:
            project_path(project, name).mkdir(parents=True, exist_ok=True)
        for row in rows:
            copy_file(root / row["path"], project / row["path"])
        verify_files(project, rows)
        # The view names its own frozen dependencies outside the source trees (it may rebuild them).
        view_additional = tuple(view(project) or ())
        if source_inventory(root, additional_paths, language=language) != rows:
            raise EditionError("build inputs changed during snapshot capture; retry with the new inputs")
        additional_paths = view_additional
        view_rows = source_inventory(project, additional_paths)
        _keep_only(project, {row["path"] for row in view_rows})
        digest = hashlib.sha256(json_bytes(view_rows)).hexdigest()
        destination = shared / digest
        document = {
            "schema_version": 1, "input_digest": digest, "source_head": source_head, "language": language,
            "source_input_digest": source_digest, "files": view_rows,
            "scope": "one language's view of the working-tree build definitions; output receipts and editorial state excluded",
        }
        if not destination.exists():
            (temporary / "inputs.json").write_bytes(json_bytes(document))
            try:
                temporary.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
        existing = load_json(destination / "inputs.json")
        if existing.get("files") != view_rows or existing.get("language") != language:
            raise EditionError("shared input snapshot identity drift")
        verify_files(destination / "project", view_rows)
        memo.parent.mkdir(parents=True, exist_ok=True)
        memo.write_bytes(json_bytes({"input_digest": digest, "additional_paths": list(additional_paths)}))
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return InputSnapshot(destination, digest, source_head, tuple(view_rows), additional_paths)


# The integrated full-story component root carries a two-phase incremental
# state. It is only a valid seed when it comes from the previous validated run
# of the same pipeline; the main checkout's copy may hold an unpromoted direct
# run, which the integrated builder would refuse to promote.
INTEGRATED_COMPONENT_BUILD_DIRS = ("zh-release-full-story",)


def seed_original_caches(source: Path, target: Path, *, overwrite_cache: bool = False,
                         exclude_build_dirs: tuple[str, ...] = ()) -> None:
    """Optional caches only; production builders still verify their locked inputs.

    Seed the legacy production namespaces, excluding edition workspaces,
    experiments, runtime captures, saves and analysis. Authoritative source
    files have already been materialized from the frozen snapshot.
    ``exclude_build_dirs`` names ``work/build`` children that must not be
    seeded; without them the component pipeline bootstraps a full build.
    """
    directories = [source / "work" / name for name in ("disc", "font-source", "toolchain", "writeback")]
    build = source / "work/build"
    if build.is_dir():
        skipped = ("best-", "zh-release-original", "zh-release-best", "zh-release-sp", "shared", "stage-canary", "special-disc", "sp-multilang-resources")
        directories.extend(path for path in build.iterdir() if path.is_dir()
                           and not path.name.startswith(skipped) and path.name not in exclude_build_dirs)
    directories.extend(source / "work/review" / name for name in ("aid-battle-prompts-zh", "tricmn-battle-overlays-zh"))
    for directory in directories:
        if directory.is_dir():
            destination = target / directory.relative_to(source)
            if overwrite_cache or not destination.exists():
                shutil.copytree(directory, destination, copy_function=copy_file, dirs_exist_ok=overwrite_cache)
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
