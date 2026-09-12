#!/usr/bin/env python3
"""Build both the frozen UI heading atlas and its drawing references."""

import argparse
import json
from pathlib import Path

from srwz.ui_headings import build_ui_headings

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/assets/ui-headings-zh.json")
    parser.add_argument("--refresh-manifest", action="store_true")
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text())
    outputs, report = build_ui_headings(ROOT, config_path)
    manifest = ROOT / config["manifest"]
    if not args.refresh_manifest and (not manifest.is_file() or json.loads(manifest.read_text()) != report):
        raise SystemExit("UI heading manifest drift; review and use --refresh-manifest")
    for member, payload in outputs.items():
        path = ROOT / config["output_root"] / member
        if not path.resolve().is_relative_to(ROOT / "work"):
            raise SystemExit("UI heading output must remain under work/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        if path.read_bytes() != payload:
            raise SystemExit(f"UI heading readback differs: {member}")
    if args.refresh_manifest:
        manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"UI headings: {report['heading_count']} headings, {report['drawing_patch_count']} drawing references; static readback passed, runtime pending")


if __name__ == "__main__":
    main()
