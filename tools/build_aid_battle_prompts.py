#!/usr/bin/env python3
"""Build the localized AIDDATA battle-prompt component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srwz.aid_battle_prompts import AidBattlePromptError, build_aid_battle_prompts
from srwz.imagemagick import require_imagemagick, write_deterministic_rgba8_png


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config/assets/aid-battle-prompts-zh.json"


def _path(root: Path, raw: str) -> Path:
    path = (root / raw).resolve()
    path.relative_to(root.resolve())
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--refresh-manifest", action="store_true")
    parser.add_argument("--no-enforce-expected", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    outputs = config["outputs"]
    component_path = _path(PROJECT_ROOT, outputs["component_root"]) / config["source"]["member"]
    report_path = _path(PROJECT_ROOT, outputs["report"])
    if (component_path.exists() or report_path.exists()) and not args.force:
        raise SystemExit("AID battle-prompt output exists; use --force")
    try:
        payload, reference, localized, report = build_aid_battle_prompts(
            PROJECT_ROOT,
            config_path,
            enforce_expected=not args.no_enforce_expected,
        )
    except (AidBattlePromptError, OSError, KeyError, ValueError) as error:
        raise SystemExit(f"AID battle-prompt build failed: {error}") from error
    component_path.parent.mkdir(parents=True, exist_ok=True)
    component_path.write_bytes(payload)
    magick = require_imagemagick()
    for raw_path, pixels in (
        (outputs["reference_png"], reference),
        (outputs["localized_png"], localized),
    ):
        path = _path(PROJECT_ROOT, raw_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_deterministic_rgba8_png(magick, pixels, path, width=512, height=1024)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = _path(PROJECT_ROOT, outputs["manifest"])
    if args.refresh_manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif not manifest_path.is_file() or json.loads(manifest_path.read_text(encoding="utf-8")) != report:
        raise SystemExit("AID battle-prompt manifest drift; review report and rerun with --refresh-manifest")
    print(
        "AID battle prompts:",
        f"labels={len(report['atlas']['labels'])}",
        f"changed_pixels={report['atlas']['changed_logical_pixel_count']}",
        f"encoded={report['atlas']['output_encoded_size']}/{report['atlas']['stored_slot_size']}",
        "runtime=pending",
    )
    print(f"component: {component_path.relative_to(PROJECT_ROOT)}")
    print(f"report: {report_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
