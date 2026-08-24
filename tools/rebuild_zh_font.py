#!/usr/bin/env python3
"""Rebuild the single global Chinese release font and its consumers."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from srwz.ui_atlas_suite import build_ui_atlas_suite


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHAIN_CONFIG = PROJECT_ROOT / "config/fonts/zh-font-build-chain.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the global font, build one flattened release VT1, then "
            "rebuild every registered atlas and integrated consumer."
        )
    )
    parser.add_argument("--config", type=Path, default=CHAIN_CONFIG)
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--skip-assets", action="store_true")
    parser.add_argument("--refresh-manifests", action="store_true")
    parser.add_argument(
        "--refresh-asset-ratchets",
        action="store_true",
        help=(
            "Recompute deterministic atlas output locks after an "
            "intentional global font change. Requires --refresh-manifests."
        ),
    )
    return parser.parse_args()


def _run(*arguments: str) -> None:
    subprocess.run(
        [sys.executable, *arguments],
        cwd=PROJECT_ROOT,
        check=True,
    )


def _run_json(*arguments: str) -> dict:
    completed = subprocess.run(
        [sys.executable, *arguments],
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    document = json.loads(completed.stdout)
    if not isinstance(document, dict):
        raise SystemExit(f"command did not return a JSON object: {arguments}")
    return document


def _load(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise SystemExit("unsupported Chinese font build-chain config")
    return document


def _write(path: Path, document: dict) -> None:
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


def _file_lock(reference: str) -> dict:
    path = PROJECT_ROOT / reference
    return {
        "path": reference,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _assignment_mapping_sha256(assignments: object) -> str:
    if not isinstance(assignments, list) or any(
        not isinstance(item, dict)
        or any(key not in item for key in ("character", "code", "glyph_index"))
        for item in assignments
    ):
        raise SystemExit("font proposal assignments are malformed")
    rows = sorted(
        (item["character"], item["code"], item["glyph_index"])
        for item in assignments
    )
    return hashlib.sha256(
        json.dumps(
            rows,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _refresh_atlas_ratchet(reference: str) -> None:
    config_path = PROJECT_ROOT / reference
    config = _load(config_path)
    config["expected"] = _run_json(
        "tools/ui_atlas.py",
        "build",
        "--config",
        reference,
        "--print-output-locks",
    )
    _write(config_path, config)


def _build_atlas(reference: str, *, refresh_manifest: bool) -> None:
    _run(
        "tools/ui_atlas.py",
        "build",
        "--config",
        reference,
        "--force",
    )
    arguments = [
        "tools/ui_atlas.py",
        "verify",
        "--config",
        reference,
        "--force",
    ]
    if refresh_manifest:
        arguments.append("--refresh-manifest")
    _run(*arguments)


def _sync_suite_components(suite: dict, atlas_references: list[str]) -> None:
    atlas_by_profile = {
        _load(PROJECT_ROOT / reference)["profile_id"]: reference
        for reference in atlas_references
    }
    for component in suite["components"]:
        profile_id = component["profile_id"]
        reference = atlas_by_profile.get(profile_id)
        if reference is None:
            raise SystemExit(f"atlas suite has an unregistered component: {profile_id}")
        atlas = _load(PROJECT_ROOT / reference)
        manifest_reference = atlas["outputs"]["manifest"]
        archive_reference = (
            f"{atlas['outputs']['component_root']}/{atlas['target']['member']}"
        )
        config_lock = _file_lock(reference)
        component["config"]["path"] = reference
        component["config"]["sha256"] = config_lock["sha256"]
        if "size" in component["config"]:
            component["config"]["size"] = config_lock["size"]
        manifest_lock = _file_lock(manifest_reference)
        component["manifest"] = {
            **component["manifest"],
            "path": manifest_reference,
            "sha256": manifest_lock["sha256"],
        }
        if "size" in component["manifest"]:
            component["manifest"]["size"] = manifest_lock["size"]
        component["archive"] = _file_lock(archive_reference)


def _refresh_suite_ratchets(
    reference: str,
    atlas_references: list[str],
) -> None:
    config_path = PROJECT_ROOT / reference
    suite = _load(config_path)
    _sync_suite_components(suite, atlas_references)
    _write(config_path, suite)
    _archive, report = build_ui_atlas_suite(
        PROJECT_ROOT,
        config_path,
        enforce_expected_output=False,
    )
    component_reports = {
        component["profile_id"]: component
        for component in report["inputs"]["components"]
    }
    for component in suite["components"]:
        actual = component_reports[component["profile_id"]]["diff"]
        component["expected_changed_byte_count"] = actual["diff_count"]
        component["expected_changed_range_count"] = actual["range_count"]
    suite["composition"] = {
        key: report["composition"][key]
        for key in (
            "mode",
            "component_count",
            "chunk_indices",
            "ownership_overlap_count",
            "changed_byte_count",
            "changed_range_count",
        )
    }
    suite["expected_output"] = report["outputs"]["archive"]
    _write(config_path, suite)


def _build_assets(chain: dict, args: argparse.Namespace) -> None:
    atlas_references = list(chain.get("localized_atlases", []))
    suite_reference = chain.get("atlas_suite")
    story_reference = chain.get("story_component")
    if (
        not atlas_references
        or any(not isinstance(item, str) for item in atlas_references)
        or not isinstance(suite_reference, str)
        or not isinstance(story_reference, str)
    ):
        raise SystemExit("Chinese font asset registry is empty or malformed")

    print(f"[font-assets] {story_reference}", flush=True)
    _run(
        "tools/build_story_component.py",
        "--config",
        story_reference,
        "--force",
    )

    for reference in atlas_references:
        print(f"[font-assets] {reference}", flush=True)
        if args.refresh_asset_ratchets:
            _refresh_atlas_ratchet(reference)
        _build_atlas(reference, refresh_manifest=args.refresh_manifests)

    if args.refresh_asset_ratchets:
        _refresh_suite_ratchets(suite_reference, atlas_references)
    _run(
        "tools/ui_atlas.py",
        "build-suite",
        "--config",
        suite_reference,
        "--force",
    )
    suite_verify = [
        "tools/ui_atlas.py",
        "verify-suite",
        "--config",
        suite_reference,
        "--force",
    ]
    if args.refresh_manifests:
        suite_verify.append("--refresh-manifest")
    _run(*suite_verify)

    integrated_reference = chain.get("integrated_component")
    if not isinstance(integrated_reference, str):
        raise SystemExit("Chinese font integrated component is not registered")
    integrated_path = PROJECT_ROOT / integrated_reference
    integrated = _load(integrated_path)
    font_reference = integrated["full_story_font"]
    dependency_locks = (
        (font_reference["manifest"], font_reference["manifest"]["path"]),
        (font_reference["slps"], font_reference["slps"]["path"]),
        (font_reference["vt1"], font_reference["vt1"]["path"]),
        (
            integrated["full_story_stage"]["report"],
            integrated["full_story_stage"]["report"]["path"],
        ),
        (
            integrated["full_story_stage"]["stage"],
            integrated["full_story_stage"]["stage"]["path"],
        ),
        (
            integrated["full_story_stage"]["hb"],
            integrated["full_story_stage"]["hb"]["path"],
        ),
        (integrated["kvmdata"], integrated["kvmdata"]["path"]),
        (
            integrated["runtime_keywords"]["library_component_manifest"],
            integrated["runtime_keywords"]["library_component_manifest"][
                "path"
            ],
        ),
    )
    dependency_drift = False
    for target, dependency_reference in dependency_locks:
        actual = _file_lock(dependency_reference)
        if target.get("size") != actual["size"] or target.get("sha256") != actual[
            "sha256"
        ]:
            dependency_drift = True
            target["size"] = actual["size"]
            target["sha256"] = actual["sha256"]
    font_manifest = _load(PROJECT_ROOT / font_reference["manifest"]["path"])
    proposal_reference = font_manifest.get("proposal")
    compatibility = integrated.get("composition", {}).get("release_codebook")
    if not isinstance(proposal_reference, dict) or not isinstance(
        compatibility, dict
    ):
        raise SystemExit("integrated release codebook compatibility is missing")
    proposal_path = PROJECT_ROOT / proposal_reference["path"]
    if _sha256(proposal_path) != proposal_reference.get("sha256"):
        raise SystemExit("global release proposal lock drift")
    proposal = _load(proposal_path)
    assignments = proposal.get("assignments")
    mapping_sha256 = _assignment_mapping_sha256(assignments)
    snapshot = compatibility.get("release_snapshot")
    release_profile = _load(PROJECT_ROOT / chain["release_profile"])
    current_snapshot = release_profile.get("allocation_snapshot")
    if not isinstance(current_snapshot, dict) or not isinstance(
        current_snapshot.get("path"), str
    ):
        raise SystemExit("global release snapshot reference is malformed")
    snapshot_document = _load(PROJECT_ROOT / current_snapshot["path"])
    clean_contracts = [
        extension["clean_default_width_cjk_primary_migration"]
        for extension in snapshot_document.get("extensions", [])
        if isinstance(extension, dict)
        and "clean_default_width_cjk_primary_migration" in extension
    ]
    if len(clean_contracts) != 1:
        raise SystemExit("clean CJK-primary migration contract is absent")
    clean_migration_by_character = {
        row["character"]: row
        for row in clean_contracts[0].get("migrations", [])
        if isinstance(row, dict)
    }
    compatibility_drift = (
        not isinstance(snapshot, dict)
        or snapshot.get("path") != current_snapshot.get("path")
        or snapshot.get("sha256") != current_snapshot.get("sha256")
        or len(assignments) != compatibility.get("release_assignment_count")
        or mapping_sha256
        != compatibility.get("release_assignment_mapping_sha256")
        or snapshot_document.get("primary_mapping_sha256")
        != compatibility.get("release_snapshot_primary_mapping_sha256")
    )
    if (
        compatibility.get("mode") != "direct-original-writeback"
        or _sha256(PROJECT_ROOT / current_snapshot["path"])
        != current_snapshot.get("sha256")
    ):
        raise SystemExit("global release assignment snapshot is invalid")

    menu_reference = integrated.get("menu_text_release", {}).get("codebook")
    if not isinstance(menu_reference, dict) or not isinstance(
        menu_reference.get("path"), str
    ):
        raise SystemExit("release menu codebook reference is malformed")
    menu_path = PROJECT_ROOT / menu_reference["path"]
    menu_lock = _file_lock(menu_reference["path"])
    if (
        menu_reference.get("size") != menu_lock["size"]
        or menu_reference.get("sha256") != menu_lock["sha256"]
    ):
        raise SystemExit("release menu codebook lock drift")
    menu_codebook = _load(menu_path)
    menu_assignments = menu_codebook.get("assignments")
    menu_mapping_sha256 = _assignment_mapping_sha256(menu_assignments)
    if (
        menu_codebook.get("codebook_id")
        != menu_reference.get("required_codebook_id")
        or menu_codebook.get("status") != "current_release_menu_codebook"
        or len(menu_assignments) != compatibility.get("menu_assignment_count")
        or menu_mapping_sha256
        != compatibility.get("menu_assignment_mapping_sha256")
        or menu_codebook.get("assignment_count") != len(menu_assignments)
        or menu_codebook.get("mapping_sha256") != menu_mapping_sha256
    ):
        raise SystemExit("release menu codebook contract is invalid")

    release_by_character = {
        item["character"]: (item["code"], item["glyph_index"])
        for item in assignments
    }

    def menu_assignment_is_current_or_migrated(item: dict) -> bool:
        character = item["character"]
        current = release_by_character.get(character)
        menu_pair = (item["code"], item["glyph_index"])
        if current == menu_pair:
            return True
        migration = clean_migration_by_character.get(character)
        return bool(
            migration
            and menu_pair
            == (
                migration.get("from_code"),
                migration.get("from_glyph_index"),
            )
            and current
            == (
                migration.get("to_code"),
                migration.get("to_glyph_index"),
            )
        )

    if any(
        not menu_assignment_is_current_or_migrated(item)
        for item in menu_assignments
    ):
        raise SystemExit(
            "release menu codebook is incompatible with the current font"
        )
    if compatibility_drift:
        if not args.refresh_manifests:
            raise SystemExit(
                "global release mapping changed; rerun with --refresh-manifests"
            )
        compatibility["release_snapshot"] = dict(current_snapshot)
        compatibility["release_snapshot_primary_mapping_sha256"] = (
            snapshot_document["primary_mapping_sha256"]
        )
        compatibility["release_assignment_count"] = len(assignments)
        compatibility["release_assignment_mapping_sha256"] = mapping_sha256
        dependency_drift = True
    if dependency_drift and not args.refresh_manifests:
        raise SystemExit(
            "integrated full-story component follows rebuilt font/assets; "
            "rerun with --refresh-manifests"
        )
    if dependency_drift:
        _write(integrated_path, integrated)
    integrated_args = [
        "tools/build_full_story_components.py",
        "--config",
        integrated_reference,
        "--force",
    ]
    if args.refresh_manifests:
        integrated_args.append("--refresh-manifest")
    print(f"[font-assets] {integrated_reference}", flush=True)
    _run(*integrated_args)


def main() -> int:
    args = parse_args()
    if args.refresh_asset_ratchets and not args.refresh_manifests:
        raise SystemExit(
            "--refresh-asset-ratchets requires --refresh-manifests"
        )
    chain = _load(args.config.resolve())
    if not args.skip_fetch:
        _run("tools/fetch_zh_font.py", "--flavor", chain["font_flavor"])
    refresh = ["--refresh-manifest"] if args.refresh_manifests else []
    release_reference = chain.get("release_profile")
    base_reference = chain.get("base_profile")
    if not isinstance(release_reference, str) or not isinstance(
        base_reference, str
    ):
        raise SystemExit("Chinese font base/release registry is malformed")
    release = _load(PROJECT_ROOT / release_reference)
    outputs = release.get("outputs")
    snapshot = release.get("allocation_snapshot")
    if not isinstance(outputs, dict) or not isinstance(snapshot, dict):
        raise SystemExit("Chinese release font outputs are malformed")
    print(f"[font-release] {release['font_profile_id']}", flush=True)
    _run("tools/prepare_zh_release_font.py", "--config", release_reference, "--force")
    _run(
        "tools/build_zh_font_component.py",
        "--font-config",
        release_reference,
        "--proposal",
        outputs["proposal"],
        "--allocation-registry",
        snapshot["path"],
        "--output-root",
        outputs["component_root"],
        "--force",
    )
    _run(
        "tools/verify_zh_release_font.py",
        "--config",
        release_reference,
        *refresh,
        "--force",
    )
    library_args = [
        "tools/build_library_v02_component.py",
        "--force",
    ]
    if args.refresh_manifests:
        library_args.append("--refresh-manifest")
    print("[font-consumer] reviewed LIBRARY component", flush=True)
    _run(*library_args)
    if not args.skip_assets:
        _build_assets(chain, args)
        print("[font-consumer] compose full-story + LIBRARY", flush=True)
        _run("tools/compose_full_story_library_components.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
