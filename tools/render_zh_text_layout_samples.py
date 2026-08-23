#!/usr/bin/env python3
"""Render offline SRWZ Chinese-layout comparisons with the built VT1 glyphs."""

from __future__ import annotations

import argparse
import binascii
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

try:
    from srwz.codec import decode_production
    from srwz.diagnostics import require_work_output
    from srwz.font import (
        GLYPH_HEIGHT,
        GLYPH_WIDTH,
        ascii_glyph_index,
        decode_glyph,
        decode_vt1_font_segment,
        glyph_index_for_code,
        read_extended_glyph_table,
    )
    from srwz.text import load_text_table, original_fullwidth_ascii_overrides
except ModuleNotFoundError:  # Imported as tools.* by the unit test suite.
    from tools.srwz.codec import decode_production
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.font import (
        GLYPH_HEIGHT,
        GLYPH_WIDTH,
        ascii_glyph_index,
        decode_glyph,
        decode_vt1_font_segment,
        glyph_index_for_code,
        read_extended_glyph_table,
    )
    from tools.srwz.text import (
        load_text_table,
        original_fullwidth_ascii_overrides,
    )


WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_REPORT = WORK_ROOT / "review/zh-text-layout-audit.json"
DEFAULT_OUTPUT = WORK_ROOT / "review/zh-text-layout-render"
DEFAULT_SLPS = WORK_ROOT / "build/zh-release-font/components/SLPS_258.87"
DEFAULT_VT1 = WORK_ROOT / "build/zh-release-font/components/DATA/VT1.BIN"
ASSIGNMENTS = PROJECT_ROOT / "config/encoding/zh-release-font-assignments.json"
TABLE_PATH = PROJECT_ROOT / "vendor/upstream-python/project/tbl_all.json"
WORLD_HISTORY_SUMMARY = PROJECT_ROOT / "corpus/zh/summary.json"

CELL = GLYPH_WIDTH
LINE_HEIGHT = 30
BACKGROUND = (5, 17, 27)
PANEL = (7, 36, 48)
PANEL_ALT = (10, 43, 54)
GRID = (22, 66, 76)
BORDER = (55, 156, 157)
TEXT = (221, 232, 229)
MUTED = (126, 169, 169)
ACCENT = (91, 232, 201)
WARNING = (255, 174, 83)
ERROR = (244, 104, 91)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--slps", type=Path, default=DEFAULT_SLPS)
    parser.add_argument("--vt1", type=Path, default=DEFAULT_VT1)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"JSON document is not an object: {path}")
    return document


class RGBImage:
    def __init__(self, width: int, height: int, color: tuple[int, int, int]):
        self.width = width
        self.height = height
        self.pixels = bytearray(color * (width * height))

    def _offset(self, x: int, y: int) -> int:
        return (y * self.width + x) * 3

    def set(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if not 0 <= x < self.width or not 0 <= y < self.height:
            return
        offset = self._offset(x, y)
        self.pixels[offset : offset + 3] = bytes(color)

    def blend(
        self,
        x: int,
        y: int,
        color: tuple[int, int, int],
        alpha: int,
    ) -> None:
        if alpha <= 0 or not 0 <= x < self.width or not 0 <= y < self.height:
            return
        offset = self._offset(x, y)
        inverse = 255 - alpha
        for channel in range(3):
            self.pixels[offset + channel] = (
                self.pixels[offset + channel] * inverse + color[channel] * alpha + 127
            ) // 255

    def rectangle(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        color: tuple[int, int, int],
    ) -> None:
        left = max(0, x)
        top = max(0, y)
        right = min(self.width, x + width)
        bottom = min(self.height, y + height)
        row = bytes(color * max(0, right - left))
        for current_y in range(top, bottom):
            offset = self._offset(left, current_y)
            self.pixels[offset : offset + len(row)] = row

    def border(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        color: tuple[int, int, int],
        thickness: int = 1,
    ) -> None:
        self.rectangle(x, y, width, thickness, color)
        self.rectangle(x, y + height - thickness, width, thickness, color)
        self.rectangle(x, y, thickness, height, color)
        self.rectangle(x + width - thickness, y, thickness, height, color)

    def png(self) -> bytes:
        def chunk(kind: bytes, payload: bytes) -> bytes:
            checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
            return (
                struct.pack(">I", len(payload))
                + kind
                + payload
                + struct.pack(">I", checksum)
            )

        stride = self.width * 3
        rows = b"".join(
            b"\x00" + self.pixels[y * stride : (y + 1) * stride]
            for y in range(self.height)
        )
        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows, 9))
            + chunk(b"IEND", b"")
        )


class RuntimeFont:
    def __init__(self, *, slps_path: Path, vt1_path: Path):
        slps = slps_path.read_bytes()
        vt1 = vt1_path.read_bytes()
        self.font = decode_vt1_font_segment(
            slps,
            vt1,
            decoder=decode_production,
        ).decoded
        self.extended = read_extended_glyph_table(slps)
        snapshot = load_json(ASSIGNMENTS)
        self.primary = {
            row["character"]: int(row["glyph_index"])
            for row in snapshot["primary_assignments"]
        }
        table = load_text_table(TABLE_PATH)
        self.ascii_overrides = original_fullwidth_ascii_overrides(table)
        self.table_codes: dict[str, int] = {}
        for code, character in sorted(table.characters.items()):
            self.table_codes.setdefault(character, code)
        self._glyph_cache: dict[str, bytes] = {}
        self.missing: set[str] = set()

    def _glyph_index(self, character: str) -> int | None:
        if character in self.primary:
            return self.primary[character]
        if character in self.ascii_overrides:
            return glyph_index_for_code(
                self.ascii_overrides[character],
                self.extended,
            )
        if len(character) == 1 and 0x20 <= ord(character) <= 0x7E:
            return ascii_glyph_index(ord(character))
        code = self.table_codes.get(character)
        if code is not None:
            try:
                return glyph_index_for_code(code, self.extended)
            except ValueError:
                pass
        self.missing.add(character)
        return None

    def glyph(self, character: str) -> bytes | None:
        if character in {" ", "　"}:
            return None
        if character not in self._glyph_cache:
            index = self._glyph_index(character)
            if index is None:
                return None
            self._glyph_cache[character] = decode_glyph(self.font, index)
        return self._glyph_cache[character]

    @staticmethod
    def display_cells(text: str) -> list[str]:
        cells = []
        offset = 0
        while offset < len(text):
            if text.startswith("$c", offset):
                cells.extend("ZEUTH ")
                offset += 2
                continue
            cells.append(text[offset])
            offset += 1
        return cells

    def draw_text(
        self,
        image: RGBImage,
        text: str,
        x: int,
        y: int,
        *,
        color: tuple[int, int, int] = TEXT,
        scale: int = 1,
        shadow: bool = True,
    ) -> int:
        cursor = x
        for character in self.display_cells(text):
            glyph = self.glyph(character)
            if glyph is not None:
                if shadow:
                    self._draw_glyph(
                        image,
                        glyph,
                        cursor + scale,
                        y + scale,
                        (0, 0, 0),
                        scale,
                        alpha_scale=150,
                    )
                self._draw_glyph(
                    image,
                    glyph,
                    cursor,
                    y,
                    color,
                    scale,
                )
            cursor += CELL * scale
        return cursor

    @staticmethod
    def _draw_glyph(
        image: RGBImage,
        glyph: bytes,
        x: int,
        y: int,
        color: tuple[int, int, int],
        scale: int,
        *,
        alpha_scale: int = 255,
    ) -> None:
        for source_y in range(GLYPH_HEIGHT):
            for source_x in range(GLYPH_WIDTH):
                value = glyph[source_y * GLYPH_WIDTH + source_x]
                alpha = value * 17 * alpha_scale // 255
                for dy in range(scale):
                    for dx in range(scale):
                        image.blend(
                            x + source_x * scale + dx,
                            y + source_y * scale + dy,
                            color,
                            alpha,
                        )


def find_change(report: dict, surface: str, entry_id: str, domain: str = "") -> dict:
    for row in report["surfaces"][surface]["changes"]:
        if row["id"] == entry_id and (not domain or row.get("domain") == domain):
            return row
    raise ValueError(f"layout sample is absent from report: {surface}/{entry_id}")


def draw_header(
    image: RGBImage,
    font: RuntimeFont,
    title: str,
    subtitle: str,
) -> None:
    image.rectangle(0, 0, image.width, 64, (8, 29, 43))
    image.rectangle(0, 62, image.width, 2, ACCENT)
    font.draw_text(image, title, 28, 10, color=ACCENT)
    font.draw_text(image, subtitle, 28, 36, color=MUTED)


def draw_label(
    image: RGBImage,
    font: RuntimeFont,
    text: str,
    x: int,
    y: int,
    *,
    color: tuple[int, int, int] = MUTED,
) -> None:
    font.draw_text(image, text, x, y, color=color, shadow=False)


def draw_text_panel(
    image: RGBImage,
    font: RuntimeFont,
    *,
    x: int,
    y: int,
    text: str,
    maximum_cells: int,
    visible_cells: int | None = None,
    line_slots: int | None = None,
    highlight: str = "normal",
) -> tuple[int, int]:
    lines = text.splitlines()
    line_slots = line_slots or len(lines)
    visible_cells = visible_cells or maximum_cells
    width = visible_cells * CELL + 24
    height = line_slots * LINE_HEIGHT + 24
    fill = PANEL_ALT if highlight == "after" else PANEL
    image.rectangle(x, y, width, height, fill)
    image.border(
        x,
        y,
        width,
        height,
        ACCENT if highlight == "after" else BORDER,
        2,
    )
    content_x = x + 12
    content_y = y + 12
    for column in range(1, visible_cells):
        grid_x = content_x + column * CELL
        image.rectangle(grid_x, content_y, 1, line_slots * LINE_HEIGHT, GRID)
    limit_x = content_x + maximum_cells * CELL
    if maximum_cells < visible_cells:
        image.rectangle(limit_x, content_y, 2, line_slots * LINE_HEIGHT, ERROR)
    for index, line in enumerate(lines):
        font.draw_text(
            image,
            line,
            content_x,
            content_y + index * LINE_HEIGHT,
            color=TEXT,
        )
    return width, height


def metric_label(widths: Iterable[int]) -> str:
    return "行宽 " + "／".join(str(width) for width in widths)


def render_story(report: dict, font: RuntimeFont) -> RGBImage:
    image = RGBImage(1360, 650, BACKGROUND)
    draw_header(
        image,
        font,
        "剧情对话排版测试",
        "实际字模 一格二十四像素 红线为二十一格内容上限",
    )
    draw_label(image, font, "当前文本", 44, 82, color=WARNING)
    draw_label(image, font, "重排建议", 718, 82, color=ACCENT)

    overflow = find_change(
        report,
        "story_dialogue",
        "story/001/dialogue/01.08/0001",
    )
    draw_label(image, font, "样例一 行长失衡", 44, 116)
    draw_text_panel(
        image,
        font,
        x=44,
        y=146,
        text=overflow["before"],
        maximum_cells=21,
        visible_cells=22,
        line_slots=2,
        highlight="before",
    )
    draw_label(
        image,
        font,
        metric_label(overflow["before_metrics"]["line_widths"]),
        44,
        238,
        color=ERROR,
    )
    draw_text_panel(
        image,
        font,
        x=718,
        y=146,
        text=overflow["after"],
        maximum_cells=21,
        visible_cells=22,
        line_slots=2,
        highlight="after",
    )
    draw_label(
        image,
        font,
        metric_label(overflow["after_metrics"]["line_widths"]),
        718,
        238,
        color=ACCENT,
    )

    punctuation = find_change(
        report,
        "story_dialogue",
        "story/001/dialogue/01.02/0006",
    )
    draw_label(image, font, "样例二 行首标点修复", 44, 304)
    draw_text_panel(
        image,
        font,
        x=44,
        y=334,
        text=punctuation["before"],
        maximum_cells=21,
        visible_cells=22,
        line_slots=2,
        highlight="before",
    )
    draw_label(
        image,
        font,
        metric_label(punctuation["before_metrics"]["line_widths"]),
        44,
        426,
        color=ERROR,
    )
    draw_text_panel(
        image,
        font,
        x=718,
        y=334,
        text=punctuation["after"],
        maximum_cells=21,
        visible_cells=22,
        line_slots=2,
        highlight="after",
    )
    draw_label(
        image,
        font,
        metric_label(punctuation["after_metrics"]["line_widths"]),
        718,
        426,
        color=ACCENT,
    )

    draw_label(
        image,
        font,
        "说明 变量小队名以 ZEUTH 加一格空位预览",
        44,
        542,
    )
    return image


def render_library(report: dict, font: RuntimeFont) -> RGBImage:
    image = RGBImage(1400, 470, BACKGROUND)
    draw_header(
        image,
        font,
        "图鉴正文排版测试",
        "机体图鉴 二十六格宽 当前贪心换行与均衡换行对照",
    )
    row = find_change(
        report,
        "library",
        "library-text/339071947f1e8a7a",
        "robot",
    )
    draw_label(image, font, "当前文本", 34, 82, color=WARNING)
    draw_label(image, font, "均衡建议", 730, 82, color=ACCENT)
    draw_text_panel(
        image,
        font,
        x=34,
        y=116,
        text=row["before"],
        maximum_cells=26,
        line_slots=3,
        highlight="before",
    )
    draw_text_panel(
        image,
        font,
        x=730,
        y=116,
        text=row["after"],
        maximum_cells=26,
        line_slots=3,
        highlight="after",
    )
    draw_label(
        image,
        font,
        metric_label(row["before_metrics"]["line_widths"]),
        34,
        242,
        color=WARNING,
    )
    draw_label(
        image,
        font,
        metric_label(row["after_metrics"]["line_widths"]),
        730,
        242,
        color=ACCENT,
    )
    draw_label(
        image,
        font,
        "观察点 原排版末行仅三格 新排版三行均为十八格",
        34,
        342,
    )
    return image


def render_overviews(report: dict, font: RuntimeFont) -> RGBImage:
    image = RGBImage(1360, 730, BACKGROUND)
    draw_header(
        image,
        font,
        "关卡概要排版测试",
        "上 三行概要均衡 下 关卡概要列表行首标点修复",
    )
    draw_label(image, font, "当前文本", 44, 82, color=WARNING)
    draw_label(image, font, "重排建议", 718, 82, color=ACCENT)

    chart = find_change(
        report,
        "scenario_chart_overview",
        "hsfc-overview:118",
    )
    draw_text_panel(
        image,
        font,
        x=44,
        y=120,
        text=chart["before"],
        maximum_cells=21,
        line_slots=3,
        highlight="before",
    )
    draw_text_panel(
        image,
        font,
        x=718,
        y=120,
        text=chart["after"],
        maximum_cells=21,
        line_slots=3,
        highlight="after",
    )
    draw_label(
        image,
        font,
        metric_label(chart["before_metrics"]["line_widths"]),
        44,
        246,
        color=WARNING,
    )
    draw_label(
        image,
        font,
        metric_label(chart["after_metrics"]["line_widths"]),
        718,
        246,
        color=ACCENT,
    )

    scroll = find_change(
        report,
        "stage_scroll_overview",
        "overview:011",
    )
    before_lines = "\n".join(scroll["before"].rstrip("\n").splitlines()[:2])
    after_lines = "\n".join(scroll["after"].rstrip("\n").splitlines()[:2])
    draw_label(image, font, "关卡概要列表样例", 44, 326)
    draw_text_panel(
        image,
        font,
        x=44,
        y=360,
        text=before_lines,
        maximum_cells=29,
        line_slots=2,
        highlight="before",
    )
    draw_text_panel(
        image,
        font,
        x=718,
        y=360,
        text=after_lines,
        maximum_cells=29,
        line_slots=2,
        highlight="after",
    )
    draw_label(
        image,
        font,
        "当前第二行以逗号开头",
        44,
        452,
        color=ERROR,
    )
    draw_label(
        image,
        font,
        "修复后逗号留在上一行",
        718,
        452,
        color=ACCENT,
    )
    return image


def draw_world_history_viewport(
    image: RGBImage,
    font: RuntimeFont,
    *,
    x: int,
    y: int,
    text: str,
    start_line: int,
) -> None:
    width = 624
    height = 390
    for py in range(height):
        vertical = py / max(1, height - 1)
        for px in range(width):
            dx = px - width * 0.50
            dy = py - height * 0.38
            radius = (dx * dx + dy * dy) ** 0.5
            haze = int(13 * (1.0 - min(1.0, radius / 430.0)))
            wave = ((px * 17 + py * 11 + (px * py) // 97) % 23) // 6
            image.set(
                x + px,
                y + py,
                (7 + haze // 3, 20 + haze + wave, 24 + haze + wave),
            )
    image.border(x, y, width, height, BORDER, 2)
    lines = text.splitlines()[start_line : start_line + 11]
    text_x = x + 48
    text_y = y + 30
    for index, line in enumerate(lines):
        font.draw_text(
            image,
            line,
            text_x,
            text_y + index * LINE_HEIGHT,
            color=TEXT,
        )


def render_world_history_scroll(report: dict, font: RuntimeFont) -> RGBImage:
    image = RGBImage(1328, 560, BACKGROUND)
    draw_header(
        image,
        font,
        "女主第一关开场滚动剧情",
        "MTV PROS 世界历史 二十二格宽 保留段落与滚动总行数",
    )
    summary = load_json(WORLD_HISTORY_SUMMARY)
    entry = next(
        row for row in summary["entries"] if row["id"] == "summary/00/000"
    )
    text = entry["translation"]
    draw_label(image, font, "滚入前段", 24, 80, color=ACCENT)
    draw_label(image, font, "继续上移", 680, 80, color=ACCENT)
    draw_world_history_viewport(
        image,
        font,
        x=24,
        y=110,
        text=text,
        start_line=0,
    )
    draw_world_history_viewport(
        image,
        font,
        x=680,
        y=110,
        text=text,
        start_line=11,
    )
    draw_label(
        image,
        font,
        "当前换行已通过二十二格检查 此处展示同一正文的两个滚动位置",
        24,
        516,
    )
    return image


def main() -> int:
    args = parse_args()
    output = require_work_output(args.output, WORK_ROOT)
    if output.exists() and any(output.iterdir()) and not args.force:
        raise ValueError(f"render output is not empty; use --force: {output}")
    output.mkdir(parents=True, exist_ok=True)
    report = load_json(args.report.resolve())
    font = RuntimeFont(
        slps_path=args.slps.resolve(),
        vt1_path=args.vt1.resolve(),
    )
    renders = {
        "story-dialogue-comparison.png": render_story(report, font),
        "library-comparison.png": render_library(report, font),
        "overview-comparison.png": render_overviews(report, font),
        "opening-world-history-scroll-sequence.png": (
            render_world_history_scroll(report, font)
        ),
    }
    for filename, image in renders.items():
        temporary = output / f"{filename}.tmp"
        temporary.write_bytes(image.png())
        temporary.replace(output / filename)
    manifest = {
        "schema_version": 1,
        "classification": "offline_vt1_pixel_preview_not_runtime_proof",
        "font_source": {
            "slps": str(args.slps.resolve().relative_to(PROJECT_ROOT)),
            "vt1": str(args.vt1.resolve().relative_to(PROJECT_ROOT)),
        },
        "layout_report": str(args.report.resolve().relative_to(PROJECT_ROOT)),
        "renders": list(renders),
        "missing_glyphs": sorted(font.missing),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if font.missing:
        raise ValueError(f"render has missing glyphs: {sorted(font.missing)}")
    print(f"rendered {len(renders)} layout comparisons: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Chinese layout render failed: {error}", file=sys.stderr)
        raise SystemExit(1)
