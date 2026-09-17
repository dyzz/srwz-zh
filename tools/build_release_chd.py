#!/usr/bin/env python3
"""Build parent/child CHD pairs for a release.

The child CHD stores only the hunks that differ from the untranslated parent,
so a full-disc translation ships in tens of megabytes. Emulators list parent and
child as two separate games and resolve the parent by hash from the same
directory, which lets players switch between the Japanese and translated discs
without repatching.

Codec and hunk size are chosen for compatibility rather than peak ratio:
zlib is the only general-purpose codec the libchdr revision bundled with
AetherSX2/NetherSX2 understands (it lacks both zstd and the non-CD lzma codec),
and 16384 sits at the shallow optimum for child size on these discs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/release/v0.4.2.json"
HASH_CHUNK_SIZE = 4 * 1024 * 1024

# See module docstring: both values are compatibility choices, not tuning knobs.
CODEC = "zlib"
HUNK_SIZE = 16384


class ChdBuildError(RuntimeError):
    """Raised when a CHD input or generated artifact fails verification."""


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as source:
        while chunk := source.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChdBuildError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ChdBuildError(f"expected JSON object: {path}")
    return value


def resolve_chdman(explicit: str | None) -> str:
    candidate = explicit or "chdman"
    found = shutil.which(candidate)
    if not found:
        raise ChdBuildError(
            f"chdman not found: {candidate}\n"
            "Homebrew's mame bottle does not ship chdman; build it from the MAME "
            "sources or install a distribution that includes it."
        )
    return found


def run_chdman(chdman: str, args: list[str], *, quiet: bool) -> None:
    result = subprocess.run(
        [chdman, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # chdman writes progress to stdout and real diagnostics to stderr.
        detail = (result.stderr or result.stdout or "").strip()
        raise ChdBuildError(f"chdman {args[0]} failed: {detail}")
    if not quiet:
        for line in (result.stdout or "").replace("\r", "\n").splitlines():
            if "final ratio" in line:
                print(f"    {line.strip()}")


def chd_info(chdman: str, path: Path) -> dict[str, str]:
    # `info` reads the header only, so a child does not need its parent here.
    result = subprocess.run(
        [chdman, "info", "-i", str(path)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ChdBuildError(f"chdman info failed for {path.name}")
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if match := re.match(r"^([A-Za-z0-9 ]+?):\s+(.*)$", line.strip()):
            fields[match.group(1).strip()] = match.group(2).strip()
    return fields


def verify_source(iso: Path, spec: dict[str, Any]) -> None:
    """Check an input ISO against the size and hash locked in the release config."""
    if not iso.is_file():
        raise ChdBuildError(f"missing ISO: {iso}")
    expected_size = spec.get("size")
    if expected_size is not None and iso.stat().st_size != expected_size:
        raise ChdBuildError(
            f"{iso.name}: size {iso.stat().st_size} != locked {expected_size}"
        )
    expected_sha256 = spec.get("sha256")
    if expected_sha256:
        actual = sha256_file(iso)
        if actual != expected_sha256:
            raise ChdBuildError(
                f"{iso.name}: sha256 {actual} != locked {expected_sha256}"
            )


def build_edition(
    *,
    chdman: str,
    name: str,
    source_iso: Path,
    target_iso: Path,
    out_dir: Path,
    version: str,
    verify: bool,
    quiet: bool,
    variant_suffix: str = "",
    create_parent: bool = True,
) -> dict[str, Any]:
    parent_chd = out_dir / f"srwz-jp-{name}.chd"
    child_chd = out_dir / f"srwz-zh-v{version}-{name}{variant_suffix}.chd"

    if create_parent:
        print(f"  parent: {parent_chd.name}")
        run_chdman(
            chdman,
            [
                "createdvd",
                "-i", str(source_iso),
                "-o", str(parent_chd),
                "-c", CODEC,
                "-hs", str(HUNK_SIZE),
                "-f",
            ],
            quiet=quiet,
        )

    print(f"  child : {child_chd.name}")
    run_chdman(
        chdman,
        [
            "createdvd",
            "-i", str(target_iso),
            "-op", str(parent_chd),
            "-o", str(child_chd),
            "-c", CODEC,
            "-hs", str(HUNK_SIZE),
            "-f",
        ],
        quiet=quiet,
    )

    # The child records the parent's overall CHD SHA1. That value covers logical
    # content plus metadata but not the compressed bytes, so any codec or hunk
    # size produces the same digest -- players may rebuild the parent with
    # whatever parameters they like, as long as the ISO itself matches.
    child_fields = chd_info(chdman, child_chd)
    parent_fields = chd_info(chdman, parent_chd)
    wanted = child_fields.get("Parent SHA1", "")
    got = parent_fields.get("SHA1", "")
    if not wanted or not got or wanted != got:
        raise ChdBuildError(
            f"{child_chd.name}: parent link {wanted} != parent {got}"
        )

    source_sha1 = sha1_file(source_iso)
    if parent_fields.get('Data SHA1') != source_sha1:
        raise ChdBuildError(f'{parent_chd.name}: parent logical content differs from source ISO')
    info: dict[str, Any] = {
        "edition": name,
        "variant": "skip" if variant_suffix else "no-skip",
        "parent_chd": parent_chd.name,
        "parent_chd_size": parent_chd.stat().st_size,
        "parent_chd_sha1": got,
        "child_chd": child_chd.name,
        "child_chd_size": child_chd.stat().st_size,
        "child_chd_sha256": sha256_file(child_chd),
        "source_iso_sha1": source_sha1,
        "target_iso_sha256": sha256_file(target_iso),
    }

    if verify:
        print("  verify: extracting child and comparing to translated ISO")
        restored = out_dir / f".verify-{name}.iso"
        try:
            run_chdman(
                chdman,
                [
                    "extractdvd",
                    "-i", str(child_chd),
                    "-ip", str(parent_chd),
                    "-o", str(restored),
                    "-f",
                ],
                quiet=True,
            )
            expected = sha1_file(target_iso)
            actual = sha1_file(restored)
            if expected != actual:
                raise ChdBuildError(
                    f"{child_chd.name}: restored sha1 {actual} != {expected}"
                )
            actual_sha256 = sha256_file(restored)
            if restored.stat().st_size != target_iso.stat().st_size or actual_sha256 != info['target_iso_sha256']:
                raise ChdBuildError(f'{child_chd.name}: extracted ISO identity mismatch')
            info["verified_sha1"] = actual
            info["verified_sha256"] = actual_sha256
        finally:
            restored.unlink(missing_ok=True)

    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build parent/child CHD pairs for a release."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"release config (default: {DEFAULT_CONFIG.relative_to(PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="output directory (default: build/chd/v<version>)",
    )
    parser.add_argument(
        "--edition",
        action="append",
        choices=["original", "best"],
        help="build only this edition (repeatable; default: all)",
    )
    parser.add_argument(
        "--chdman", default=None, help="path to chdman (default: from PATH)"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip extracting the child back and comparing hashes",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="suppress chdman ratio lines"
    )
    args = parser.parse_args(argv)

    try:
        chdman = resolve_chdman(args.chdman)
        config = load_config(args.config)
        version = config.get("version")
        if not version:
            raise ChdBuildError(f"no version in {args.config}")

        editions = config.get("editions")
        if not isinstance(editions, dict) or not editions:
            raise ChdBuildError(f"no editions in {args.config}")
        selected = args.edition or sorted(editions)

        out_dir = args.out_dir or (PROJECT_ROOT / f"build/chd/v{version}")
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"chdman  : {chdman}")
        print(f"codec   : {CODEC}, hunk size {HUNK_SIZE}")
        print(f"output  : {out_dir}")

        results = []
        for name in selected:
            spec = editions.get(name)
            if not isinstance(spec, dict):
                raise ChdBuildError(f"unknown edition: {name}")
            source_spec = spec.get("source_iso", {})
            target_spec = spec.get("target_iso", {})
            source_iso = PROJECT_ROOT / source_spec["path"]
            target_iso = PROJECT_ROOT / target_spec["path"]

            print(f"\n[{name}]")
            verify_source(source_iso, source_spec)
            verify_source(target_iso, target_spec)

            results.append(
                build_edition(
                    chdman=chdman,
                    name=name,
                    source_iso=source_iso,
                    target_iso=target_iso,
                    out_dir=out_dir,
                    version=version,
                    verify=not args.no_verify,
                    quiet=args.quiet,
                )
            )

            if config.get('schema_version') == 3:
                skip_spec = spec['skip_variant']['target_iso']
                skip_iso = PROJECT_ROOT / skip_spec['path']
                verify_source(skip_iso, skip_spec)
                results.append(build_edition(chdman=chdman, name=name, source_iso=source_iso,
                    target_iso=skip_iso, out_dir=out_dir, version=version, verify=not args.no_verify,
                    quiet=args.quiet, variant_suffix='-skip', create_parent=False))

        print("\n=== summary ===")
        for info in results:
            child_mb = info["child_chd_size"] / (1024 * 1024)
            parent_mb = info["parent_chd_size"] / (1024 * 1024)
            print(f"[{info['edition']}]")
            print(f"  {info['child_chd']}  {child_mb:.2f} MB")
            print(f"  {info['parent_chd']}  {parent_mb:.2f} MB")
            print(f"  source ISO sha1 : {info['source_iso_sha1']}")
            print(f"  child sha256    : {info['child_chd_sha256']}")

        manifest = out_dir / "chd-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": version,
                    "codec": CODEC,
                    "hunk_size": HUNK_SIZE,
                    "editions": results,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {manifest.relative_to(PROJECT_ROOT)}")
    except ChdBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
