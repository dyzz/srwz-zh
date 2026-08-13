#!/usr/bin/env python3
"""Explicitly render and freeze the runtime NISVDATA LIBRARY menu labels."""

from __future__ import annotations

import argparse
import base64
import json
import zlib
from pathlib import Path

try:
    from srwz.font_flavor import (
        load_font_flavor_reference,
        verify_font_flavor_files,
    )
    from srwz.nisv_library_menu import build_nisv_library_menu
except ModuleNotFoundError:
    from tools.srwz.font_flavor import (
        load_font_flavor_reference,
        verify_font_flavor_files,
    )
    from tools.srwz.nisv_library_menu import build_nisv_library_menu


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/library/v0.2.0.json"
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "config/library/library-menu-runtime-render-snapshot.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explicitly rerender and freeze the runtime LIBRARY menu."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output.resolve()
    if output_path.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite without --force: {output_path}")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    contract = config["library_menu_runtime_tim2"]
    member_lock = config["source_member_locks"]["DATA/NISVDATA.BIN"]
    source = (PROJECT_ROOT / member_lock["path"]).read_bytes()
    flavor = load_font_flavor_reference(
        PROJECT_ROOT,
        contract["writeback"]["font_flavor"],
    )
    _lock, files, _fallbacks, _reports = verify_font_flavor_files(
        PROJECT_ROOT,
        WORK_ROOT,
        flavor,
    )
    snapshot: dict = {}
    _output, report = build_nisv_library_menu(
        source,
        contract,
        font_path=files["font"],
        project_root=PROJECT_ROOT,
        live_render=True,
        render_snapshot_sink=snapshot,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    preview_data = zlib.decompress(
        base64.b64decode(snapshot["preview_png"]["zlib_base64"])
    )
    preview = WORK_ROOT / "refreeze/library-menu/library-menu-runtime.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(preview_data)
    print(f"output={output_path}")
    print(f"label_count={len(report['labels'])}")
    print(f"preview={preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
