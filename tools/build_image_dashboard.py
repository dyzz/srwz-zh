#!/usr/bin/env python3
"""Build the local SRWZ image browser from the full TIM2 export."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

try:
    from srwz.image_dashboard import (
        ImageDashboardError,
        render_dashboard_html,
    )
except ModuleNotFoundError:
    from tools.srwz.image_dashboard import (
        ImageDashboardError,
        render_dashboard_html,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPORT_ROOT = PROJECT_ROOT / "work" / "assets" / "images-by-bin"


class ImageDashboardCliError(ValueError):
    """The requested dashboard output is unsafe or unavailable."""


def require_export_root(path: Path) -> Path:
    root = path.resolve()
    for filename in ("manifest.json", "images.csv"):
        if not (root / filename).is_file():
            raise ImageDashboardCliError(
                f"image export is missing {root / filename}"
            )
    if not (root / "by-member").is_dir():
        raise ImageDashboardCliError(
            f"image export is missing {root / 'by-member'}"
        )
    return root


def require_output_path(export_root: Path, path: Path) -> Path:
    output = path.resolve()
    try:
        output.relative_to(export_root)
    except ValueError as error:
        raise ImageDashboardCliError(
            f"dashboard output must stay under {export_root}"
        ) from error
    if output.suffix.lower() != ".html":
        raise ImageDashboardCliError("dashboard output must be an HTML file")
    return output


def build_dashboard(export_root: Path, output: Path, *, force: bool) -> dict:
    root = require_export_root(export_root)
    destination = require_output_path(root, output)
    if destination.exists() and not force:
        raise FileExistsError(
            f"refusing to replace existing dashboard: {destination}"
        )

    manifest = json.loads(
        (root / "manifest.json").read_text(encoding="utf-8")
    )
    with (root / "images.csv").open(
        newline="",
        encoding="utf-8",
    ) as source:
        rows = list(csv.DictReader(source))

    html = render_dashboard_html(manifest, rows)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return {
        "output": destination.relative_to(root).as_posix(),
        "output_size": destination.stat().st_size,
        "picture_count": len(rows),
        "member_count": len({row["member"] for row in rows}),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a self-contained local HTML dashboard for the complete "
            "SRWZ TIM2 image export."
        )
    )
    parser.add_argument(
        "--export-root",
        type=Path,
        default=DEFAULT_EXPORT_ROOT,
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Defaults to <export-root>/index.html.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    export_root = args.export_root.resolve()
    output = (
        args.output.resolve()
        if args.output is not None
        else export_root / "index.html"
    )
    try:
        report = build_dashboard(
            export_root,
            output,
            force=args.force,
        )
    except (
        FileExistsError,
        ImageDashboardCliError,
        ImageDashboardError,
        json.JSONDecodeError,
        OSError,
    ) as error:
        raise SystemExit(f"error: {error}") from error
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
