#!/usr/bin/env python3
"""Render the whole GB2312 level-1 Han set with the production font policy."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics

from srwz.canary import rasterize_character
from srwz.diagnostics import require_work_output
from srwz.font import glyph_raster_metrics, render_glyph_grid, sha256_bytes
from srwz.font_profile import load_font_profile
from srwz.font_source import load_font_lock, verify_font_lock_files


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_CONFIG = PROJECT_ROOT / "config/fonts/first-five-font.json"
DEFAULT_OUTPUT = WORK_ROOT / "review/font/common-han-gb2312-level1.png"


def gb2312_level1_characters() -> tuple[str, ...]:
    """Return the 3,755 level-1 Han characters in GB2312 byte order."""

    characters = []
    for lead in range(0xB0, 0xD8):
        for trail in range(0xA1, 0xFF):
            try:
                character = bytes((lead, trail)).decode("gb2312")
            except UnicodeDecodeError:
                continue
            if len(character) == 1:
                characters.append(character)
    result = tuple(characters)
    if len(result) != 3755 or len(set(result)) != len(result):
        raise ValueError("GB2312 level-1 character inventory drift")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render all GB2312 level-1 Han glyphs through the exact production "
            "raster path and emit a machine-readable geometry audit."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--columns", type=int, default=64)
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--gap", type=int, default=2)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = require_work_output(args.output, WORK_ROOT)
    metadata_output = output.with_suffix(".json")
    order_output = output.with_suffix(".txt")
    existing = [
        path for path in (output, metadata_output, order_output) if path.exists()
    ]
    if existing and not args.force:
        raise SystemExit(f"output exists; use --force: {existing[0]}")
    if args.columns <= 0 or args.scale <= 0 or args.gap < 0:
        raise SystemExit("preview grid geometry is invalid")
    if args.workers <= 0:
        raise SystemExit("--workers must be positive")

    config_path = args.config.resolve()
    profile = load_font_profile(PROJECT_ROOT, config_path)
    rasterizer = profile["rasterizer"]
    normalization = rasterizer.get("cjk_bbox_normalization")
    fixed_canvas = rasterizer.get("cjk_fixed_canvas")
    if (normalization is None) == (fixed_canvas is None):
        raise SystemExit(
            "font profile must enable exactly one uniform CJK raster policy"
        )
    if rasterizer.get("optical_corrections"):
        raise SystemExit("character-specific optical corrections are forbidden")

    font_lock = load_font_lock(PROJECT_ROOT / profile["font_lock"])
    locked_paths = verify_font_lock_files(PROJECT_ROOT, WORK_ROOT, font_lock)
    font_path = locked_paths["font"]
    characters = gb2312_level1_characters()

    def render(character: str) -> tuple[str, bytes, bytes, dict]:
        _, pixels, packed = rasterize_character(
            rasterizer["executable"],
            font_path,
            character,
            rasterizer,
        )
        return character, pixels, packed, glyph_raster_metrics(pixels)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        rendered = list(executor.map(render, characters))

    packed_font = b"".join(item[2] for item in rendered)
    preview = render_glyph_grid(
        packed_font,
        range(len(rendered)),
        columns=args.columns,
        scale=args.scale,
        gap=args.gap,
    )
    metrics = [item[3] for item in rendered]
    widths = [item["bbox_width"] for item in metrics]
    heights = [item["bbox_height"] for item in metrics]
    ink_counts = [item["ink_pixel_count"] for item in metrics]
    empty = [
        character
        for character, _, _, metric in rendered
        if metric["ink_pixel_count"] == 0
    ]
    edge = [
        character
        for character, _, _, metric in rendered
        if metric["outer_edge_touch"]
    ]
    records = [
        {
            "character": character,
            "packed_glyph_sha256": sha256_bytes(packed),
            "metrics": metric,
        }
        for character, _, packed, metric in rendered
    ]
    profile_bytes = config_path.read_bytes()
    metadata = {
        "schema_version": 1,
        "status": "offline_common_han_preview_validated_runtime_not_tested",
        "inventory": {
            "id": "gb2312-level-1",
            "character_count": len(characters),
            "unique_character_count": len(set(characters)),
            "order": "GB2312 byte order B0A1-D7F9",
        },
        "font_profile": {
            "path": str(config_path.relative_to(PROJECT_ROOT)),
            "sha256": sha256_bytes(profile_bytes),
            "font_source_family": font_lock["family"],
            "font_source_sha256": font_lock["font"]["sha256"],
        },
        "rendering_policy": {
            "mode": (
                "uniform_bbox_normalized"
                if normalization is not None
                else "uniform_fixed_canvas"
            ),
            "config": (
                normalization if normalization is not None else fixed_canvas
            ),
        },
        "character_specific_exception_count": 0,
        "grid": {
            "columns": args.columns,
            "scale": args.scale,
            "gap": args.gap,
            "png_sha256": sha256_bytes(preview),
        },
        "audit": {
            "empty_glyph_count": len(empty),
            "empty_characters": "".join(empty),
            "outer_edge_touch_count": len(edge),
            "outer_edge_touch_characters": "".join(edge),
            "bbox_width_counts": dict(sorted(Counter(widths).items())),
            "bbox_height_counts": dict(sorted(Counter(heights).items())),
            "bbox_width_min": min(widths),
            "bbox_width_median": statistics.median(widths),
            "bbox_width_max": max(widths),
            "bbox_height_min": min(heights),
            "bbox_height_median": statistics.median(heights),
            "bbox_height_max": max(heights),
            "ink_pixel_count_min": min(ink_counts),
            "ink_pixel_count_median": statistics.median(ink_counts),
            "ink_pixel_count_max": max(ink_counts),
        },
        "records": records,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(preview)
    metadata_output.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = [
        "".join(characters[start : start + args.columns])
        for start in range(0, len(characters), args.columns)
    ]
    order_output.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(
        "common Han preview:",
        f"characters={len(characters)}",
        f"empty={len(empty)}",
        f"edge={len(edge)}",
        "exceptions=0",
    )
    print(f"png: {output}")
    print(f"metadata: {metadata_output}")
    print(f"row order: {order_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
