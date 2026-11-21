"""Reuse the files a build step wrote when nothing it read has changed.

A step is a command run in a project directory. The first time, every Python process of the step records the
files it opens for reading and the directories it lists (an audit hook, step_trace/sitecustomize.py). The record
keeps, for each of those, the content it had: for a file of the project, its content when the step began; for a
file elsewhere in the repository or in a named root (an Original build's workspace), its content at the end.
The files the step added or changed in the project are kept beside it.

Later, in a fresh project, the step is not run when a record's reads all still have the same content: the kept
files are placed instead. What a step read is found by observation, so a record is only trusted within the
`scope` its caller gives: the caller puts there everything a step can depend on without opening it through
Python (the tool sources, the interpreter, the names of the project's files, the settings in the environment).

Not seen by the hook, and therefore the caller's to cover by `scope`: files read by non-Python programs, and
decisions taken from a file's existence alone. `verify=True` runs the step even when a record matches and
compares what it wrote with the record.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from .file_identity import sha256_file
from .release_inputs import copy_file

TRACE_PATH = Path(__file__).resolve().parent / "step_trace"
ENV_TRACE = "SRWZ_STEP_TRACE"
SKIP_PARTS = {"__pycache__", ".git"}
KEEP_RECORDS = 4


class StepError(RuntimeError):
    pass


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _walk(project: Path):
    """(relative path, lstat) of every file and symlink of the project."""
    for directory, children, files in os.walk(project, followlinks=False):
        relative = os.path.relpath(directory, project)
        relative = "" if relative == "." else relative + "/"
        kept = []
        for child in children:
            path = relative + child
            if child in SKIP_PARTS:
                continue
            if os.path.islink(os.path.join(directory, child)):
                yield path, os.lstat(os.path.join(directory, child))
            else:
                kept.append(child)
        children[:] = kept
        for name in files:
            path = relative + name
            if name.endswith((".pyc", ".pyo")):
                continue
            yield path, os.lstat(os.path.join(directory, name))


def _state(project: Path, untracked: tuple[str, ...]) -> tuple[dict, dict]:
    """(identity, content) per path: identity tells what a step wrote (anywhere in the project, its tool
    sources included: a step may rewrite a constant in one), content what it could have read."""
    identity, content = {}, {}
    for path, stat in _walk(project):
        full = project / path
        if os.path.islink(full):
            identity[path] = ["link", os.readlink(full)]
            continue
        identity[path] = [stat.st_size, stat.st_mtime_ns, stat.st_ino]
        if not path.startswith(untracked):
            content[path] = sha256_file(full)
    return identity, content


def _content(path: Path):
    if path.is_file():
        return sha256_file(path)
    if path.is_dir():
        return "dir"
    return None


def _answer(documents: dict, path: Path, selector: list) -> str:
    """Digest of what a JSON file answers for one selector (srwz.build_language._asked computes the same)."""
    if selector == ["?exists"]:
        value = path.is_file()
    else:
        if path not in documents:
            try:
                documents[path] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                documents[path] = None
        value = documents[path]
        for part in selector:
            value = value.get(part) if isinstance(value, dict) else None
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _listing(path: Path):
    try:
        return _digest(sorted(os.listdir(path)))
    except OSError:
        return None


class Step:
    """One memoized command. ``roots`` are named directories outside the project whose location changes
    between builds (name -> path); ``ignore`` are repository-relative prefixes that are caches or outputs."""

    def __init__(self, name: str, store: Path, project: Path, repository: Path, *, scope, roots=None,
                 ignore=(), wholesale=("tools/", "shared/", "vendor/"), untracked=(), probes=None, log=print):
        self.name, self.project, self.repository = name, project.resolve(), repository.resolve()
        self.roots = {key: Path(value).resolve() for key, value in (roots or {}).items()}
        self.ignore = tuple(ignore)
        self.wholesale = tuple(wholesale)          # project trees covered by `scope`, not read by read
        self.untracked = set(untracked)             # project files that are not the step's (the caller's log)
        # A tool may report one value in place of the files it read to compute it ("V" lines; the font
        # selection). name prefix -> function(project, name) -> the value for this project now.
        self.probes = dict(probes or {})
        self.scope = scope
        self.store = store / name
        self.log = log

    # ---- where a traced path belongs -------------------------------------------------------------
    def _place(self, path: str):
        candidate = Path(path)
        for key, root in (("project", self.project), *self.roots.items(), ("repository", self.repository)):
            try:
                return key, candidate.relative_to(root).as_posix()
            except ValueError:
                continue
        return None, None

    def _resolve(self, key: str, relative: str) -> Path:
        base = {"project": self.project, "repository": self.repository, **self.roots}[key]
        return base / relative

    # ---- lookup ----------------------------------------------------------------------------------
    def _changed(self, record: dict, content: dict) -> list[str]:
        """The reads and listings of a record that no longer have the content it kept (empty: it matches)."""
        changed = []
        for key, relative, digest in record["reads"]:
            now = content.get(relative) if key == "project" else _content(self._resolve(key, relative))
            if now != digest:
                changed.append(f"{key}:{relative}")
        changed += [f"{key}:{relative}/" for key, relative, digest in record["listings"]
                    if _listing(self._resolve(key, relative)) != digest]
        documents = {}
        # an entry asked of a project file is answered by the file as it is now, before the step
        changed += [f"{key}:{relative}#{'/'.join(selector)}" for key, relative, selector, digest
                    in record.get("lookups", [])
                    if _answer(documents, self._resolve(key, relative), selector) != digest]
        for name, digest in record.get("derived", []):
            probe = self.probes.get(name.split(" ", 1)[0])
            try:
                now = probe(self.project, name) if probe else None
            except Exception as error:  # noqa: BLE001  (the step itself will report it)
                now = f"error: {error}"
            if now != digest:
                changed.append(f"derived:{name.split(' ', 1)[0]}")
        return changed

    def _find(self, bucket: Path, content: dict):
        records = sorted(bucket.glob("*/record.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        nearest = None
        for path in records:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            changed = self._changed(record, content)
            if not changed:
                return path.parent, record
            if nearest is None or len(changed) < len(nearest):
                nearest = changed
        if nearest is not None:              # why the step runs: what its closest record read that has changed
            self.log(f"[sp-stage] {self.name}: {len(nearest)} reads changed since the closest record: "
                     + ", ".join(nearest[:8]) + (" ..." if len(nearest) > 8 else ""))
        elif not records:
            self.log(f"[sp-stage] {self.name}: no record for this scope and file set")
        return None, None

    def _restore(self, directory: Path, record: dict) -> None:
        for relative in record["removed"]:
            target = self.project / relative
            if target.is_symlink() or target.exists():
                target.unlink()
        for relative in record["files"]:
            copy_file(directory / "files" / relative, self.project / relative)
        for relative, (key, value) in record["links"].items():
            target = self.project / relative
            if target.is_symlink() or target.exists():
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(self._resolve(key, value) if key else value)
        os.utime(directory / "record.json")

    # ---- run -------------------------------------------------------------------------------------
    def run(self, command: list[str], *, cwd: Path, env=None, verify: bool = False) -> bool:
        """Run ``command`` or place what it wrote before. True when nothing was run."""
        started = time.perf_counter()
        before, content = _state(self.project, self.wholesale)
        for path in self.untracked:
            before.pop(path, None); content.pop(path, None)
        bucket = self.store / _digest([self.scope, sorted(before)])
        directory, record = self._find(bucket, content)
        if record is not None and not verify:
            self._restore(directory, record)
            self.log(f"[sp-stage] {self.name}: reused {len(record['files'])} files, "
                     f"{len(record['reads'])} reads unchanged, {time.perf_counter()-started:.2f}s")
            return True
        environment = dict(os.environ if env is None else env)
        with tempfile.TemporaryDirectory(prefix="step-trace-") as temporary:
            trace = Path(temporary) / "trace.log"
            environment[ENV_TRACE] = str(trace)
            environment["PYTHONPATH"] = os.pathsep.join(
                [str(TRACE_PATH), *filter(None, [environment.get("PYTHONPATH")])])
            result = subprocess.run(command, cwd=cwd, env=environment)
            if result.returncode:
                raise StepError(f"{self.name} failed with {result.returncode}")
            lines = trace.read_text(encoding="utf-8", errors="surrogateescape").splitlines() if trace.exists() else []
        if not lines or any(line.startswith("X\t") for line in lines):
            self.log(f"[sp-stage] {self.name}: not recorded (incomplete trace)")
            return False
        after, _ = _state(self.project, ("",))                      # identities only
        for path in self.untracked:
            after.pop(path, None)
        reads, listings, lookups, derived = [], [], [], []
        for line in dict.fromkeys(lines):
            kind, _, path = line.partition("\t")
            if kind == "V":
                root, name, digest = path.split("\t")
                if Path(root) != self.project or name.split(" ", 1)[0] not in self.probes:
                    self.log(f"[sp-stage] {self.name}: not recorded (a derived value nobody can check: {name[:60]})")
                    return False
                derived.append([name, digest])
                continue
            if kind == "K":
                path, selector, digest = path.split("\t")
                key, relative = self._place(path)
                if key is not None:
                    lookups.append([key, relative, json.loads(selector), digest])
                continue
            key, relative = self._place(path)
            if key is None or any(part in SKIP_PARTS for part in relative.split("/")) or relative.endswith(".pyc"):
                continue
            if key == "project":
                # a file of the project counts with the content it had when the step began; one that
                # was not there then is the step's own, and the project's file names are in the scope
                if kind == "R" and relative in content and not relative.startswith(self.wholesale):
                    reads.append([key, relative, content[relative]])
                continue
            if key == "repository" and relative.startswith(self.ignore):
                continue
            target = self._resolve(key, relative)
            if kind == "R":
                reads.append([key, relative, _content(target)])
            else:
                listings.append([key, relative, _listing(target)])
        files = sorted(path for path, identity in after.items()
                       if identity[0] != "link" and before.get(path) != identity)
        links = {}
        for path, identity in after.items():
            if identity[0] == "link" and before.get(path) != identity:
                key, relative = self._place(os.path.realpath(self.project / path))
                links[path] = [key, relative] if key in self.roots or key == "repository" else [None, identity[1]]
        new = dict(reads=reads, listings=listings, lookups=lookups, derived=derived, files=files, links=links,
                   removed=sorted(set(before) - set(after)))
        if record is not None:                                       # verify: the record promised these files
            wrote = {path: sha256_file(self.project / path) for path in files}
            kept = {path: sha256_file(directory / "files" / path) for path in record["files"]}
            if wrote != kept or record["removed"] != new["removed"] or record["links"] != links:
                differing = sorted(set(wrote) ^ set(kept) | {p for p in set(wrote) & set(kept) if wrote[p] != kept[p]})
                raise StepError(f"{self.name}: a matching record does not reproduce the step: {differing[:12]}")
            self.log(f"[sp-stage] {self.name}: record verified against a real run ({len(files)} files)")
            return False
        bucket.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".new-", dir=bucket))
        for relative in files:
            copy_file(self.project / relative, staging / "files" / relative)
        (staging / "record.json").write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
        staging.rename(bucket / hashlib.sha256(os.urandom(16)).hexdigest()[:16])
        for stale in sorted(bucket.glob("*/record.json"), key=lambda p: p.stat().st_mtime, reverse=True)[KEEP_RECORDS:]:
            shutil.rmtree(stale.parent, ignore_errors=True)
        self.log(f"[sp-stage] {self.name}: ran and recorded ({len(reads)} reads, {len(files)} files), "
                 f"{time.perf_counter()-started:.2f}s")
        return False
