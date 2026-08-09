#!/usr/bin/env python3
"""Build and verify individual or composed KVMDATA UI atlases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.diagnostics import require_work_output
from srwz.ui_atlas_localization import build_ui_atlas_localization
from srwz.ui_atlas_suite import UiAtlasSuiteError, build_ui_atlas_suite


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_ATLAS_CONFIG = PROJECT_ROOT / "config/assets/ui-info-atlas-zh.json"
DEFAULT_SUITE_CONFIG = PROJECT_ROOT / "config/assets/ui-atlas-suite-zh.json"


def _load_config(path: Path) -> tuple[Path, dict]:
    resolved = path.resolve()
    document = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SystemExit(f"config root is not an object: {resolved}")
    return resolved, document


def _command_build(args: argparse.Namespace) -> int:
    config_path, config = _load_config(args.config)
    outputs = config["outputs"]
    component_root = require_work_output(
        PROJECT_ROOT / outputs["component_root"],
        WORK_ROOT,
    )
    archive_path = component_root / config["target"]["member"]
    reference_path = require_work_output(
        PROJECT_ROOT / outputs["reference_png"],
        WORK_ROOT,
    )
    localized_path = require_work_output(
        PROJECT_ROOT / outputs["localized_png"],
        WORK_ROOT,
    )
    report_path = component_root / "component-validation.json"
    existing = [
        path
        for path in (
            archive_path,
            reference_path,
            localized_path,
            report_path,
        )
        if path.exists()
    ]
    if existing and not args.force and not args.print_output_locks:
        raise SystemExit(f"output exists; use --force: {existing[0]}")
    try:
        payloads, report = build_ui_atlas_localization(
            PROJECT_ROOT,
            WORK_ROOT,
            config_path,
            enforce_expected=not args.print_output_locks,
        )
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    if args.print_output_locks:
        print(json.dumps(report["expected_lock"], indent=2))
        return 0
    for path in (archive_path, reference_path, localized_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(payloads["archive"])
    reference_path.write_bytes(payloads["reference_png"])
    localized_path.write_bytes(payloads["localized_png"])
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI atlas localization:",
        f"profile={report['profile_id']}",
        f"chunk={report['target']['chunk_index']}",
        f"pixels={report['text_audit']['added_pixel_count']}",
        f"bytes={report['injection']['archive_diff_from_erased_base']['diff_count']}",
        "runtime=mapping-pending",
    )
    print(f"archive: {archive_path}")
    print(f"reference: {reference_path}")
    print(f"localized: {localized_path}")
    print(f"report: {report_path}")
    return 0


def _command_verify(args: argparse.Namespace) -> int:
    config_path, config = _load_config(args.config)
    outputs = config["outputs"]
    component_root = require_work_output(
        PROJECT_ROOT / outputs["component_root"],
        WORK_ROOT,
    )
    paths = {
        "archive": component_root / config["target"]["member"],
        "reference_png": require_work_output(
            PROJECT_ROOT / outputs["reference_png"],
            WORK_ROOT,
        ),
        "localized_png": require_work_output(
            PROJECT_ROOT / outputs["localized_png"],
            WORK_ROOT,
        ),
    }
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs["validation"],
        WORK_ROOT,
    )
    manifest_path = (
        args.manifest or PROJECT_ROOT / outputs["manifest"]
    ).resolve()
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        expected_payloads, report = build_ui_atlas_localization(
            PROJECT_ROOT,
            WORK_ROOT,
            config_path,
        )
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    for name, path in paths.items():
        if not path.is_file():
            raise SystemExit(
                f"localized atlas is missing; run ui_atlas.py build: {path}"
            )
        if path.read_bytes() != expected_payloads[name]:
            raise SystemExit(f"localized atlas rebuild differs: {name}")
    manifest_status = _verify_or_refresh_manifest(
        report,
        manifest_path,
        refresh=args.refresh_manifest,
        label="localized-atlas",
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI atlas localization verified:",
        f"profile={report['profile_id']}",
        f"chunk={report['target']['chunk_index']}",
        f"sha256={report['outputs']['archive']['sha256']}",
        "runtime=mapping-pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


def _verify_or_refresh_manifest(
    report: dict,
    path: Path,
    *,
    refresh: bool,
    label: str,
) -> str:
    if refresh:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return "refreshed"
    if not path.is_file():
        raise SystemExit(f"{label} manifest is missing; review and use --refresh-manifest")
    committed = json.loads(path.read_text(encoding="utf-8"))
    if committed != report:
        raise SystemExit(f"{label} manifest drift; review and use --refresh-manifest")
    return "verified"


def _command_build_suite(args: argparse.Namespace) -> int:
    config_path, config = _load_config(args.config)
    output_root = require_work_output(
        args.output_root or PROJECT_ROOT / config["outputs"]["component_root"],
        WORK_ROOT,
    )
    archive_path = output_root / "KURODATA/KVMDATA.BIN"
    report_path = output_root / "component-validation.json"
    existing = [path for path in (archive_path, report_path) if path.exists()]
    if existing and not args.force and not args.print_output_locks:
        raise SystemExit(f"output exists; use --force: {existing[0]}")
    try:
        archive, report = build_ui_atlas_suite(
            PROJECT_ROOT,
            config_path,
            enforce_expected_output=not args.print_output_locks,
        )
    except (KeyError, OSError, UiAtlasSuiteError) as error:
        raise SystemExit(str(error)) from error
    if args.print_output_locks:
        print(json.dumps(report["outputs"], indent=2))
        return 0
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI atlas suite:",
        f"profile={report['profile_id']}",
        f"chunks={report['composition']['chunk_indices']}",
        f"sha256={report['outputs']['archive']['sha256']}",
        "runtime=pending",
    )
    print(f"archive: {archive_path}")
    print(f"report: {report_path}")
    return 0


def _command_verify_suite(args: argparse.Namespace) -> int:
    config_path, config = _load_config(args.config)
    outputs = config["outputs"]
    component_root = require_work_output(
        PROJECT_ROOT / outputs["component_root"],
        WORK_ROOT,
    )
    archive_path = component_root / "KURODATA/KVMDATA.BIN"
    report_path = require_work_output(
        args.report or PROJECT_ROOT / outputs["validation"],
        WORK_ROOT,
    )
    manifest_path = (
        args.manifest or PROJECT_ROOT / outputs["manifest"]
    ).resolve()
    if report_path.exists() and not args.force:
        raise SystemExit(f"output exists; use --force: {report_path}")
    try:
        archive, report = build_ui_atlas_suite(PROJECT_ROOT, config_path)
    except (KeyError, OSError, UiAtlasSuiteError) as error:
        raise SystemExit(str(error)) from error
    if not archive_path.is_file():
        raise SystemExit(
            f"atlas suite is missing; run ui_atlas.py build-suite: {archive_path}"
        )
    if archive_path.read_bytes() != archive:
        raise SystemExit("atlas suite differs from deterministic rebuild")
    manifest_status = _verify_or_refresh_manifest(
        report,
        manifest_path,
        refresh=args.refresh_manifest,
        label="atlas suite",
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "UI atlas suite verified:",
        f"chunks={report['composition']['chunk_indices']}",
        f"sha256={report['outputs']['archive']['sha256']}",
        "runtime=pending",
    )
    print(f"manifest {manifest_status}: {manifest_path}")
    print(f"report: {report_path}")
    return 0


def _add_common_atlas_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_ATLAS_CONFIG)


def _add_verify_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--report", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--force", action="store_true")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build")
    _add_common_atlas_arguments(build)
    build.add_argument("--force", action="store_true")
    build.add_argument("--print-output-locks", action="store_true")
    build.set_defaults(handler=_command_build)

    verify = commands.add_parser("verify")
    _add_common_atlas_arguments(verify)
    _add_verify_arguments(verify)
    verify.set_defaults(handler=_command_verify)

    build_suite = commands.add_parser("build-suite")
    build_suite.add_argument("--config", type=Path, default=DEFAULT_SUITE_CONFIG)
    build_suite.add_argument("--output-root", type=Path)
    build_suite.add_argument("--force", action="store_true")
    build_suite.add_argument("--print-output-locks", action="store_true")
    build_suite.set_defaults(handler=_command_build_suite)

    verify_suite = commands.add_parser("verify-suite")
    verify_suite.add_argument("--config", type=Path, default=DEFAULT_SUITE_CONFIG)
    _add_verify_arguments(verify_suite)
    verify_suite.set_defaults(handler=_command_verify_suite)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
