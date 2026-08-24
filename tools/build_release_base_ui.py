#!/usr/bin/env python3
"""Reconstruct the frozen release UI baseline from verified member patches."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/release-base-ui.json"
CHUNK_SIZE = 4 * 1024 * 1024


class ReleaseBaseError(ValueError):
    """Raised when a release-base dependency or output violates its lock."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def file_lock(path: Path, root: Path = PROJECT_ROOT) -> dict[str, object]:
    return {
        "path": str(path.relative_to(root)),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def project_path(reference: object, *, label: str) -> Path:
    if not isinstance(reference, str) or not reference:
        raise ReleaseBaseError(f"{label} path is missing")
    relative = Path(reference)
    if relative.is_absolute():
        raise ReleaseBaseError(f"{label} path must be project-relative")
    resolved = (PROJECT_ROOT / relative).resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise ReleaseBaseError(f"{label} path escapes the project") from error
    return resolved


def require_object(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ReleaseBaseError(f"{label} is malformed")
    return value


def verify_lock(path: Path, reference: Mapping[str, object], *, label: str) -> dict:
    if not path.is_file():
        raise ReleaseBaseError(f"{label} is missing: {path}")
    actual = file_lock(path)
    expected = {
        "path": reference.get("path"),
        "size": reference.get("size"),
        "sha256": reference.get("sha256"),
    }
    if actual != expected:
        raise ReleaseBaseError(
            f"{label} lock drift: actual={actual} expected={expected}"
        )
    return actual


def xdelta_version(executable: str) -> str:
    path = shutil.which(executable)
    if path is None:
        raise ReleaseBaseError(f"missing {executable}; install xdelta3 first")
    completed = subprocess.run(
        [path, "-V"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    lines = completed.stdout.splitlines()
    if completed.returncode != 0 or not lines:
        raise ReleaseBaseError(f"failed to query {executable} version")
    return lines[0]


def decode_patch(
    executable: str,
    source: Path,
    patch: Path,
    output: Path,
) -> None:
    completed = subprocess.run(
        [executable, "-d", "-f", "-s", str(source), str(patch), str(output)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stdout.strip()
        raise ReleaseBaseError(
            f"xdelta decode failed for {patch.name}: {detail or 'no output'}"
        )


def load_config(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseBaseError(f"cannot load release-base config: {error}") from error
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != 1
        or document.get("profile_id") != "srwz-release-base-ui-v1"
    ):
        raise ReleaseBaseError("unsupported release-base config")
    return document


def validate_manifest(config: Mapping[str, object]) -> tuple[Path, dict]:
    reference = require_object(config.get("manifest"), label="manifest lock")
    path = project_path(reference.get("path"), label="manifest")
    verify_lock(path, reference, label="release-base manifest")
    manifest = load_config_like(path, label="release-base manifest")
    if (
        manifest.get("profile_id") != config.get("profile_id")
        or manifest.get("status") != reference.get("required_status")
    ):
        raise ReleaseBaseError("release-base manifest identity drift")
    return path, manifest


def load_config_like(path: Path, *, label: str) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseBaseError(f"cannot load {label}: {error}") from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ReleaseBaseError(f"unsupported {label}")
    return document


def build_release_base(config_path: Path, *, force: bool) -> dict:
    config = load_config(config_path)
    config_lock = file_lock(config_path)
    manifest_path, manifest = validate_manifest(config)

    xdelta = require_object(config.get("xdelta"), label="xdelta config")
    executable_name = xdelta.get("executable")
    if not isinstance(executable_name, str) or not executable_name:
        raise ReleaseBaseError("xdelta executable is missing")
    executable = shutil.which(executable_name)
    if executable is None:
        raise ReleaseBaseError(f"missing {executable_name}; install xdelta3 first")
    version = xdelta_version(executable_name)
    if version != xdelta.get("version_line"):
        raise ReleaseBaseError(
            f"xdelta version drift: expected={xdelta.get('version_line')!r} "
            f"actual={version!r}"
        )

    members = require_object(config.get("members"), label="member registry")
    manifest_outputs = require_object(
        manifest.get("outputs"), label="manifest outputs"
    )
    if set(members) != set(manifest_outputs) or not members:
        raise ReleaseBaseError("release-base member registry drift")

    prepared = []
    existing = []
    for member_id, raw_member in members.items():
        member = require_object(raw_member, label=f"{member_id} member")
        source_ref = require_object(member.get("source"), label=f"{member_id} source")
        patch_ref = require_object(member.get("patch"), label=f"{member_id} patch")
        output_ref = require_object(member.get("output"), label=f"{member_id} output")
        source_path = project_path(source_ref.get("path"), label=f"{member_id} source")
        patch_path = project_path(patch_ref.get("path"), label=f"{member_id} patch")
        output_path = project_path(output_ref.get("path"), label=f"{member_id} output")
        try:
            output_path.relative_to(WORK_ROOT)
        except ValueError as error:
            raise ReleaseBaseError(
                f"{member_id} output must stay under ignored work/"
            ) from error
        verify_lock(source_path, source_ref, label=f"{member_id} original member")
        verify_lock(patch_path, patch_ref, label=f"{member_id} xdelta patch")
        if dict(output_ref) != manifest_outputs.get(member_id):
            raise ReleaseBaseError(f"{member_id} output disagrees with the manifest")
        if output_path.exists() and not force:
            existing.append(output_path)
        prepared.append(
            (member_id, source_path, patch_path, output_path, output_ref)
        )
    if existing:
        raise ReleaseBaseError(f"output exists; use --force: {existing[0]}")

    build_root = WORK_ROOT / "build/release-base-ui"
    build_root.mkdir(parents=True, exist_ok=True)
    staged_outputs = []
    with tempfile.TemporaryDirectory(prefix=".rebuild-", dir=build_root) as temporary:
        temporary_root = Path(temporary)
        for member_id, source_path, patch_path, output_path, output_ref in prepared:
            staged_path = temporary_root / member_id
            decode_patch(executable, source_path, patch_path, staged_path)
            actual = {
                "path": output_ref.get("path"),
                "size": staged_path.stat().st_size,
                "sha256": sha256_file(staged_path),
            }
            if actual != dict(output_ref):
                raise ReleaseBaseError(
                    f"{member_id} reconstructed output drift: "
                    f"actual={actual} expected={dict(output_ref)}"
                )
            staged_outputs.append((member_id, staged_path, output_path, actual))

        for _member_id, staged_path, output_path, _actual in staged_outputs:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, output_path)

    report_reference = config.get("report")
    report_path = project_path(report_reference, label="validation report")
    try:
        report_path.relative_to(WORK_ROOT)
    except ValueError as error:
        raise ReleaseBaseError("validation report must stay under ignored work/") from error
    report = {
        "schema_version": 1,
        "status": "release_base_ui_reconstructed_exact",
        "profile_id": config["profile_id"],
        "inputs": {
            "config": config_lock,
            "manifest": file_lock(manifest_path),
            "xdelta_version": version,
            "members": {
                member_id: {
                    "source": file_lock(source_path),
                    "patch": file_lock(patch_path),
                }
                for member_id, source_path, patch_path, _output_path, _output_ref
                in prepared
            },
        },
        "outputs": {
            member_id: actual
            for member_id, _staged_path, _output_path, actual in staged_outputs
        },
        "acceptance": {
            "all_original_members_locked": True,
            "all_patches_locked": True,
            "all_outputs_match_frozen_manifest": True,
            "complete_iso_written": False,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{report_path.name}.",
        suffix=".partial",
        dir=report_path.parent,
        delete=False,
    ) as output:
        temporary_report = Path(output.name)
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    os.replace(temporary_report, report_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct the frozen release-base-ui members from verified "
            "original-disc members and tracked xdelta patches."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = build_release_base(args.config.resolve(), force=args.force)
    except ReleaseBaseError as error:
        raise SystemExit(str(error)) from error
    print(
        "release-base-ui reconstructed:",
        f"members={len(report['outputs'])}",
        "hashes=exact",
    )
    for member_id, output in report["outputs"].items():
        print(f"{member_id}: {output['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
