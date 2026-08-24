#!/usr/bin/env python3
"""Fetch and build the pinned GPL mkps2iso toolchain under ignored work/."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    PROJECT_ROOT / "config" / "iso" / "zh-release-current-build.json"
)


class BootstrapError(RuntimeError):
    """The pinned toolchain could not be prepared exactly."""


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as source:
        config = json.load(source)
    if config.get("schema_version") != 2:
        raise BootstrapError("unsupported ISO build config schema")
    return config


def project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise BootstrapError(f"path escapes project root: {value}") from exc
    return path


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=capture,
        text=True,
    )


def first_output_line(executable: Path) -> str:
    process = subprocess.run(
        [str(executable), "--help"],
        capture_output=True,
        text=True,
    )
    return next(
        (
            line.strip()
            for line in (process.stdout + process.stderr).splitlines()
            if line.strip()
        ),
        "",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the pinned open-source mkps2iso toolchain."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config.resolve())
        toolchain = config["toolchain"]
        source_dir = project_path(toolchain["source_dir"])
        git = shutil.which("git")
        cmake = shutil.which("cmake")
        if git is None or cmake is None:
            raise BootstrapError("git and cmake are required")

        if not source_dir.exists():
            source_dir.parent.mkdir(parents=True, exist_ok=True)
            print(
                f"[FETCH] {toolchain['repository']} "
                f"{toolchain['tag']} -> {source_dir}"
            )
            run(
                [
                    git,
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    toolchain["tag"],
                    toolchain["repository"],
                    str(source_dir),
                ]
            )
        elif not (source_dir / ".git").is_dir():
            raise BootstrapError(
                f"existing toolchain path is not a git checkout: {source_dir}"
            )

        commit = run(
            [git, "rev-parse", "HEAD"],
            cwd=source_dir,
            capture=True,
        ).stdout.strip()
        if commit != toolchain["commit"]:
            raise BootstrapError(
                f"mkps2iso commit {commit}, expected {toolchain['commit']}"
            )
        print(f"[OK] pinned source commit: {commit}")

        run([cmake, "--preset", "release"], cwd=source_dir)
        run(
            [cmake, "--build", "--preset", "release", "--parallel"],
            cwd=source_dir,
        )

        for name in ("mkps2iso", "dumps2iso"):
            item = toolchain[name]
            executable = project_path(item["default_path"])
            if not executable.is_file():
                raise BootstrapError(f"missing built executable: {executable}")
            line = first_output_line(executable)
            if line != item["version_line"]:
                raise BootstrapError(
                    f"{name} version line {line!r}, expected "
                    f"{item['version_line']!r}"
                )
            print(f"[OK] {line}")

        print("[OK] mkps2iso toolchain ready")
        return 0
    except (BootstrapError, OSError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
