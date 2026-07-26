"""Build a self-contained local HTML dashboard for exported SRWZ images."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from typing import Iterable, Mapping


class ImageDashboardError(ValueError):
    """The image export cannot be represented by the dashboard."""


REQUIRED_ROW_FIELDS = {
    "member",
    "chunk_index",
    "view",
    "stored_start",
    "record_index",
    "record_offset",
    "record_size",
    "record_sha256",
    "picture_index",
    "width",
    "height",
    "bits_per_pixel",
    "clut_color_count",
    "uses_shared_clut",
    "tim2_path",
    "png_path",
    "render_status",
    "palette_bank_index",
    "palette_bank_count",
    "png_sha256",
}


def _integer(
    row: Mapping[str, str],
    field: str,
    *,
    optional: bool = False,
) -> int | None:
    raw = row[field]
    if optional and raw == "":
        return None
    try:
        value = int(raw)
    except ValueError as error:
        raise ImageDashboardError(
            f"{field} must be an integer, got {raw!r}"
        ) from error
    if value < 0:
        raise ImageDashboardError(f"{field} must not be negative")
    return value


def _boolean(row: Mapping[str, str], field: str) -> bool:
    raw = row[field]
    if raw == "True":
        return True
    if raw == "False":
        return False
    raise ImageDashboardError(f"{field} must be True or False, got {raw!r}")


def _manifest_total(manifest: Mapping[str, object], field: str) -> int:
    totals = manifest.get("totals")
    if not isinstance(totals, Mapping):
        raise ImageDashboardError("manifest totals must be an object")
    value = totals.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ImageDashboardError(
            f"manifest totals.{field} must be a non-negative integer"
        )
    return value


def build_dashboard_payload(
    manifest: Mapping[str, object],
    source_rows: Iterable[Mapping[str, str]],
) -> dict:
    """Normalize the CSV export into compact, browser-ready data."""

    rows = list(source_rows)
    if not rows:
        raise ImageDashboardError("images.csv contains no image rows")

    missing = REQUIRED_ROW_FIELDS - set(rows[0])
    if missing:
        raise ImageDashboardError(
            "images.csv is missing fields: " + ", ".join(sorted(missing))
        )

    expected_picture_count = _manifest_total(manifest, "picture_count")
    if expected_picture_count != len(rows):
        raise ImageDashboardError(
            f"manifest picture_count {expected_picture_count} != "
            f"CSV rows {len(rows)}"
        )

    hashes = Counter(row["png_sha256"] for row in rows)
    if "" in hashes:
        raise ImageDashboardError("every dashboard image needs a PNG hash")

    first_hash_row: set[str] = set()
    member_images: Counter[str] = Counter()
    member_records: dict[str, set[str]] = defaultdict(set)
    member_palette_views: Counter[str] = Counter()
    images = []

    for identifier, row in enumerate(rows):
        row_missing = REQUIRED_ROW_FIELDS - set(row)
        if row_missing:
            raise ImageDashboardError(
                f"row {identifier} is missing fields: "
                + ", ".join(sorted(row_missing))
            )
        if row["render_status"] != "rendered":
            raise ImageDashboardError(
                f"row {identifier} is not rendered: {row['render_status']}"
            )
        if not row["member"] or not row["png_path"] or not row["tim2_path"]:
            raise ImageDashboardError(
                f"row {identifier} has an empty source or output path"
            )

        width = _integer(row, "width")
        height = _integer(row, "height")
        bits_per_pixel = _integer(row, "bits_per_pixel")
        palette_banks = _integer(row, "palette_bank_count")
        assert width is not None
        assert height is not None
        assert bits_per_pixel is not None
        assert palette_banks is not None
        if width == 0 or height == 0:
            raise ImageDashboardError(
                f"row {identifier} has zero image dimensions"
            )
        if bits_per_pixel not in {4, 8, 16, 24, 32}:
            raise ImageDashboardError(
                f"row {identifier} has unsupported bpp {bits_per_pixel}"
            )

        png_hash = row["png_sha256"]
        is_primary = png_hash not in first_hash_row
        first_hash_row.add(png_hash)

        image = {
            "id": identifier,
            "member": row["member"],
            "chunk": _integer(row, "chunk_index", optional=True),
            "view": row["view"],
            "storedStart": _integer(row, "stored_start"),
            "recordIndex": _integer(row, "record_index"),
            "recordOffset": _integer(row, "record_offset"),
            "recordSize": _integer(row, "record_size"),
            "recordHash": row["record_sha256"],
            "pictureIndex": _integer(row, "picture_index"),
            "width": width,
            "height": height,
            "bpp": bits_per_pixel,
            "clutColors": _integer(row, "clut_color_count"),
            "sharedClut": _boolean(row, "uses_shared_clut"),
            "tim2": row["tim2_path"],
            "png": row["png_path"],
            "paletteBank": _integer(
                row,
                "palette_bank_index",
                optional=True,
            ),
            "paletteBanks": palette_banks,
            "pngHash": png_hash,
            "duplicateCount": hashes[png_hash],
            "primary": is_primary,
        }
        images.append(image)
        member_images[row["member"]] += 1
        member_records[row["member"]].add(row["tim2_path"])
        member_palette_views[row["member"]] += max(palette_banks, 1)

    members = [
        {
            "name": member,
            "pictures": count,
            "records": len(member_records[member]),
            "paletteViews": member_palette_views[member],
        }
        for member, count in sorted(
            member_images.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    totals = {
        "pictures": expected_picture_count,
        "records": _manifest_total(manifest, "tim2_record_count"),
        "members": _manifest_total(manifest, "members_with_valid_tim2"),
        "payloads": _manifest_total(manifest, "payload_count"),
        "paletteViews": _manifest_total(
            manifest,
            "available_palette_bank_view_count",
        ),
        "renderFailures": _manifest_total(manifest, "render_failure_count"),
        "uniquePngs": len(hashes),
        "duplicateRows": len(rows) - len(hashes),
    }
    if totals["members"] != len(members):
        raise ImageDashboardError(
            f"manifest members_with_valid_tim2 {totals['members']} != "
            f"CSV members {len(members)}"
        )

    return {
        "meta": {
            "title": "SRWZ 图片资源总览",
            "scope": manifest.get("scope", ""),
            "completionStatus": manifest.get("completion_status", "unknown"),
            "totals": totals,
        },
        "members": members,
        "images": images,
    }


def render_dashboard_html(
    manifest: Mapping[str, object],
    source_rows: Iterable[Mapping[str, str]],
) -> str:
    """Render a dashboard that works directly from a local file URL."""

    payload = build_dashboard_payload(manifest, source_rows)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    encoded = (
        encoded.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return DASHBOARD_HTML.replace("__DASHBOARD_DATA__", encoded)


DASHBOARD_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>SRWZ 图片资源总览</title>
  <style>
    :root {
      --bg: #080c0f;
      --surface: #10161a;
      --surface-raised: #151d22;
      --surface-soft: #1a242a;
      --line: #29343a;
      --line-bright: #41515a;
      --text: #f3f6f4;
      --muted: #98a8ae;
      --muted-2: #6f8188;
      --acid: #d9ff66;
      --acid-soft: #b8d951;
      --cyan: #6ed8d0;
      --orange: #ff9d66;
      --danger: #ff7070;
      --shadow: 0 18px 50px rgba(0, 0, 0, .34);
      --radius-lg: 22px;
      --radius-md: 14px;
      --radius-sm: 9px;
      --mono: "SFMono-Regular", "Cascadia Code", "Roboto Mono", monospace;
      --sans: Inter, "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
    }

    * {
      box-sizing: border-box;
    }

    html {
      scroll-behavior: smooth;
    }

    body {
      margin: 0;
      min-width: 320px;
      background:
        radial-gradient(circle at 78% -10%, rgba(110, 216, 208, .12), transparent 35rem),
        radial-gradient(circle at 5% 12%, rgba(217, 255, 102, .08), transparent 27rem),
        var(--bg);
      color: var(--text);
      font-family: var(--sans);
      -webkit-font-smoothing: antialiased;
    }

    button,
    input,
    select {
      font: inherit;
    }

    button,
    a {
      -webkit-tap-highlight-color: transparent;
    }

    button:focus-visible,
    a:focus-visible,
    input:focus-visible,
    select:focus-visible {
      outline: 2px solid var(--acid);
      outline-offset: 2px;
    }

    a {
      color: inherit;
    }

    .page-shell {
      width: min(1680px, calc(100% - 40px));
      margin: 0 auto;
      padding: 34px 0 70px;
    }

    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      color: var(--acid);
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .13em;
      text-transform: uppercase;
    }

    .eyebrow::before {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--acid);
      box-shadow: 0 0 18px rgba(217, 255, 102, .8);
      content: "";
    }

    .hero {
      position: relative;
      overflow: hidden;
      padding: 40px 42px 34px;
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      background:
        linear-gradient(115deg, rgba(255, 255, 255, .035), transparent 42%),
        var(--surface);
      box-shadow: var(--shadow);
    }

    .hero::after {
      position: absolute;
      top: -86px;
      right: -60px;
      width: 310px;
      height: 310px;
      border: 1px solid rgba(110, 216, 208, .18);
      border-radius: 50%;
      box-shadow:
        0 0 0 38px rgba(110, 216, 208, .025),
        0 0 0 78px rgba(110, 216, 208, .018);
      content: "";
      pointer-events: none;
    }

    .hero-copy {
      position: relative;
      z-index: 1;
      max-width: 850px;
    }

    h1 {
      margin: 18px 0 12px;
      max-width: 840px;
      font-size: clamp(38px, 5vw, 72px);
      font-weight: 720;
      letter-spacing: -.055em;
      line-height: .98;
    }

    h1 span {
      color: var(--acid);
    }

    .hero p {
      max-width: 720px;
      margin: 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.75;
    }

    .hero-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 24px;
    }

    .hero-link {
      display: inline-flex;
      align-items: center;
      min-height: 38px;
      padding: 0 14px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 255, 255, .025);
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-decoration: none;
      transition: border-color .18s ease, color .18s ease, background .18s ease;
    }

    .hero-link:hover {
      border-color: var(--line-bright);
      background: rgba(255, 255, 255, .05);
      color: var(--text);
    }

    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin: 14px 0;
    }

    .metric {
      min-height: 128px;
      padding: 22px;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: var(--surface);
    }

    .metric-label {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 680;
      letter-spacing: .04em;
      text-transform: uppercase;
    }

    .metric-label::before {
      width: 6px;
      height: 6px;
      border-radius: 2px;
      background: var(--cyan);
      content: "";
    }

    .metric:nth-child(2) .metric-label::before {
      background: var(--acid);
    }

    .metric:nth-child(3) .metric-label::before {
      background: var(--orange);
    }

    .metric-value {
      display: block;
      margin-top: 16px;
      font-family: var(--mono);
      font-size: clamp(26px, 3vw, 40px);
      font-weight: 700;
      letter-spacing: -.045em;
      line-height: 1;
    }

    .metric-note {
      display: block;
      margin-top: 9px;
      color: var(--muted-2);
      font-size: 11px;
    }

    .source-panel {
      margin-bottom: 14px;
      padding: 22px;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: var(--surface);
    }

    .section-heading {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
    }

    .section-heading h2 {
      margin: 0;
      font-size: 16px;
      letter-spacing: -.015em;
    }

    .section-heading p {
      margin: 5px 0 0;
      color: var(--muted);
      font-size: 12px;
    }

    .source-stack {
      display: flex;
      overflow: hidden;
      height: 9px;
      margin-bottom: 18px;
      border-radius: 999px;
      background: var(--surface-soft);
    }

    .source-segment {
      min-width: 2px;
      border: 0;
      border-right: 1px solid rgba(8, 12, 15, .7);
      background: var(--segment-color);
      cursor: pointer;
      opacity: .82;
      transition: opacity .15s ease, filter .15s ease;
    }

    .source-segment:hover,
    .source-segment.active {
      filter: brightness(1.25);
      opacity: 1;
    }

    .member-cloud {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .member-chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 32px;
      padding: 0 11px;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font-family: var(--mono);
      font-size: 10px;
      transition: border-color .15s ease, color .15s ease, background .15s ease;
    }

    .member-chip strong {
      color: var(--text);
      font-weight: 650;
    }

    .member-chip:hover {
      border-color: var(--line-bright);
      color: var(--text);
    }

    .member-chip.active {
      border-color: rgba(217, 255, 102, .55);
      background: rgba(217, 255, 102, .1);
      color: var(--acid);
    }

    .browser-panel {
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      background: rgba(16, 22, 26, .93);
      box-shadow: var(--shadow);
    }

    .filters {
      position: sticky;
      z-index: 10;
      top: 0;
      display: grid;
      grid-template-columns: minmax(260px, 1.6fr) repeat(4, minmax(120px, .72fr));
      gap: 10px;
      padding: 18px;
      border-bottom: 1px solid var(--line);
      border-radius: var(--radius-lg) var(--radius-lg) 0 0;
      background: rgba(16, 22, 26, .94);
      backdrop-filter: blur(18px);
    }

    .control {
      min-width: 0;
    }

    .control label {
      display: block;
      margin: 0 0 7px 2px;
      color: var(--muted-2);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
    }

    .control input,
    .control select {
      width: 100%;
      height: 42px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #0c1114;
      color: var(--text);
      padding: 0 12px;
      font-size: 12px;
    }

    .control input::placeholder {
      color: #536168;
    }

    .control input:hover,
    .control select:hover {
      border-color: var(--line-bright);
    }

    .browser-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 16px 18px 6px;
    }

    .result-summary {
      color: var(--muted);
      font-size: 12px;
    }

    .result-summary strong {
      color: var(--text);
      font-family: var(--mono);
      font-size: 13px;
    }

    .toolbar-actions {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .toggle {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      cursor: pointer;
      font-size: 11px;
      user-select: none;
    }

    .toggle input {
      width: 15px;
      height: 15px;
      accent-color: var(--acid);
    }

    .clear-button {
      border: 0;
      background: none;
      color: var(--cyan);
      cursor: pointer;
      font-size: 11px;
      font-weight: 650;
    }

    .clear-button:hover {
      color: var(--text);
    }

    .asset-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
      gap: 12px;
      padding: 14px 18px 18px;
    }

    .asset-card {
      display: block;
      overflow: hidden;
      width: 100%;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 13px;
      background: var(--surface-raised);
      color: var(--text);
      cursor: pointer;
      text-align: left;
      box-shadow: 0 8px 22px rgba(0, 0, 0, .14);
      transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
    }

    .asset-card:hover {
      transform: translateY(-2px);
      border-color: var(--line-bright);
      box-shadow: 0 13px 28px rgba(0, 0, 0, .26);
    }

    .thumb-stage,
    .viewer-stage {
      background-color: #c8ccca;
      background-image:
        linear-gradient(45deg, #aeb5b2 25%, transparent 25%),
        linear-gradient(-45deg, #aeb5b2 25%, transparent 25%),
        linear-gradient(45deg, transparent 75%, #aeb5b2 75%),
        linear-gradient(-45deg, transparent 75%, #aeb5b2 75%);
      background-position: 0 0, 0 8px, 8px -8px, -8px 0;
      background-size: 16px 16px;
    }

    .thumb-stage {
      position: relative;
      display: grid;
      height: 166px;
      place-items: center;
      overflow: hidden;
      border-bottom: 1px solid var(--line);
    }

    .thumb-stage img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
    }

    .thumb-badges {
      position: absolute;
      top: 8px;
      right: 8px;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 5px;
      pointer-events: none;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 21px;
      padding: 0 7px;
      border: 1px solid rgba(255, 255, 255, .12);
      border-radius: 6px;
      background: rgba(8, 12, 15, .82);
      color: #f5f7f5;
      font-family: var(--mono);
      font-size: 9px;
      font-weight: 700;
      backdrop-filter: blur(7px);
    }

    .badge.acid {
      border-color: rgba(217, 255, 102, .35);
      color: var(--acid);
    }

    .badge.cyan {
      border-color: rgba(110, 216, 208, .35);
      color: var(--cyan);
    }

    .card-copy {
      padding: 13px 13px 12px;
    }

    .card-member {
      overflow: hidden;
      color: var(--text);
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 700;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .card-context {
      overflow: hidden;
      margin-top: 7px;
      color: var(--muted-2);
      font-family: var(--mono);
      font-size: 9px;
      line-height: 1.5;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .card-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-top: 11px;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 9px;
    }

    .empty-state {
      display: none;
      padding: 82px 20px 96px;
      text-align: center;
    }

    .empty-state.visible {
      display: block;
    }

    .empty-state strong {
      display: block;
      margin-bottom: 10px;
      font-size: 18px;
    }

    .empty-state span {
      color: var(--muted);
      font-size: 12px;
    }

    .load-area {
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 8px 18px 24px;
    }

    .load-more {
      min-width: 190px;
      height: 42px;
      border: 1px solid var(--line-bright);
      border-radius: 999px;
      background: transparent;
      color: var(--text);
      cursor: pointer;
      font-size: 11px;
      font-weight: 680;
      transition: background .15s ease, border-color .15s ease;
    }

    .load-more:hover {
      border-color: var(--acid-soft);
      background: rgba(217, 255, 102, .08);
    }

    .load-more[hidden] {
      display: none;
    }

    .page-footer {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      padding: 22px 3px 0;
      color: var(--muted-2);
      font-size: 10px;
      line-height: 1.6;
    }

    dialog {
      width: min(1180px, calc(100vw - 36px));
      max-height: calc(100vh - 36px);
      padding: 0;
      overflow: hidden;
      border: 1px solid var(--line-bright);
      border-radius: 20px;
      background: var(--surface);
      color: var(--text);
      box-shadow: 0 28px 90px rgba(0, 0, 0, .72);
    }

    dialog::backdrop {
      background: rgba(2, 5, 7, .84);
      backdrop-filter: blur(7px);
    }

    .viewer {
      display: grid;
      grid-template-columns: minmax(0, 1.65fr) minmax(300px, .72fr);
      min-height: min(720px, calc(100vh - 38px));
    }

    .viewer-stage {
      position: relative;
      display: grid;
      min-height: 440px;
      place-items: center;
      overflow: hidden;
    }

    .viewer-stage img {
      display: block;
      width: 100%;
      height: 100%;
      max-height: calc(100vh - 38px);
      object-fit: contain;
    }

    .viewer-nav {
      position: absolute;
      top: 50%;
      display: grid;
      width: 40px;
      height: 54px;
      border: 1px solid rgba(255, 255, 255, .18);
      border-radius: 10px;
      background: rgba(8, 12, 15, .78);
      color: var(--text);
      cursor: pointer;
      font-size: 22px;
      place-items: center;
      transform: translateY(-50%);
      backdrop-filter: blur(8px);
    }

    .viewer-nav:hover {
      border-color: rgba(217, 255, 102, .55);
      color: var(--acid);
    }

    .viewer-nav:disabled {
      cursor: default;
      opacity: .25;
    }

    .viewer-prev {
      left: 14px;
    }

    .viewer-next {
      right: 14px;
    }

    .viewer-panel {
      position: relative;
      overflow-y: auto;
      max-height: calc(100vh - 38px);
      padding: 28px;
      border-left: 1px solid var(--line);
    }

    .dialog-close {
      position: absolute;
      z-index: 2;
      top: 14px;
      right: 14px;
      display: grid;
      width: 34px;
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 50%;
      background: #0c1114;
      color: var(--muted);
      cursor: pointer;
      font-size: 18px;
      place-items: center;
    }

    .dialog-close:hover {
      border-color: var(--line-bright);
      color: var(--text);
    }

    .viewer-kicker {
      padding-right: 32px;
      color: var(--acid);
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
    }

    .viewer-title {
      overflow-wrap: anywhere;
      margin: 11px 0 8px;
      font-family: var(--mono);
      font-size: 18px;
      line-height: 1.35;
    }

    .viewer-subtitle {
      margin: 0 0 22px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.6;
    }

    .viewer-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 22px;
    }

    .viewer-chip {
      padding: 6px 8px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--surface-soft);
      color: var(--muted);
      font-family: var(--mono);
      font-size: 9px;
    }

    .detail-list {
      margin: 0;
      border-top: 1px solid var(--line);
    }

    .detail-row {
      display: grid;
      grid-template-columns: 106px minmax(0, 1fr);
      gap: 12px;
      padding: 11px 0;
      border-bottom: 1px solid var(--line);
    }

    .detail-row dt {
      color: var(--muted-2);
      font-size: 10px;
    }

    .detail-row dd {
      min-width: 0;
      margin: 0;
      overflow-wrap: anywhere;
      color: var(--text);
      font-family: var(--mono);
      font-size: 9px;
      line-height: 1.55;
    }

    .viewer-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 22px;
    }

    .viewer-action {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 39px;
      padding: 0 12px;
      border: 1px solid var(--line-bright);
      border-radius: 9px;
      background: transparent;
      color: var(--text);
      cursor: pointer;
      font-size: 10px;
      font-weight: 680;
      text-decoration: none;
    }

    .viewer-action.primary {
      border-color: var(--acid-soft);
      background: var(--acid);
      color: #11170e;
    }

    .viewer-action:hover {
      filter: brightness(1.1);
    }

    .copy-status {
      min-height: 18px;
      margin-top: 10px;
      color: var(--cyan);
      font-size: 9px;
      text-align: center;
    }

    @media (max-width: 1050px) {
      .metrics {
        grid-template-columns: 1fr 1fr;
      }

      .filters {
        grid-template-columns: 1.4fr repeat(2, 1fr);
      }

      .viewer {
        grid-template-columns: 1fr;
      }

      .viewer-stage {
        min-height: 48vh;
        max-height: 58vh;
      }

      .viewer-stage img {
        max-height: 58vh;
      }

      .viewer-panel {
        max-height: none;
        border-top: 1px solid var(--line);
        border-left: 0;
      }
    }

    @media (max-width: 690px) {
      .page-shell {
        width: min(100% - 22px, 1680px);
        padding-top: 12px;
      }

      .hero {
        padding: 28px 23px;
      }

      h1 {
        font-size: 42px;
      }

      .metrics {
        gap: 8px;
      }

      .metric {
        min-height: 108px;
        padding: 17px;
      }

      .metric-value {
        font-size: 25px;
      }

      .source-panel {
        padding: 18px;
      }

      .filters {
        position: static;
        grid-template-columns: 1fr 1fr;
      }

      .control.search-control {
        grid-column: 1 / -1;
      }

      .browser-toolbar {
        align-items: flex-start;
        flex-direction: column;
      }

      .asset-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        padding: 12px;
      }

      .thumb-stage {
        height: 128px;
      }

      .card-copy {
        padding: 10px;
      }

      .card-footer {
        align-items: flex-start;
        flex-direction: column;
      }

      .viewer-panel {
        padding: 24px 20px;
      }

      .viewer-actions {
        grid-template-columns: 1fr;
      }

      .page-footer {
        flex-direction: column;
      }
    }

    @media (max-width: 430px) {
      .metrics {
        grid-template-columns: 1fr;
      }

      .filters {
        grid-template-columns: 1fr;
      }

      .control.search-control {
        grid-column: auto;
      }

      .asset-grid {
        grid-template-columns: 1fr;
      }

      .thumb-stage {
        height: 190px;
      }
    }

    @media (prefers-reduced-motion: reduce) {
      html {
        scroll-behavior: auto;
      }

      *,
      *::before,
      *::after {
        transition-duration: .01ms !important;
      }
    }
  </style>
</head>
<body>
  <div class="page-shell">
    <header class="hero">
      <div class="hero-copy">
        <div class="eyebrow">TIM2 archive browser</div>
        <h1><span>SRWZ</span> 图片资源总览</h1>
        <p>
          把分散在 BIN、归档 chunk 和多 picture TIM2 中的资源放进一个视图。
          按来源、像素格式、尺寸和调色板筛选；缩略图按批加载，不会一次打开全部文件。
        </p>
        <nav class="hero-links" aria-label="数据文件">
          <a class="hero-link" href="manifest.json">查看 manifest.json</a>
          <a class="hero-link" href="images.csv">查看 images.csv</a>
          <a class="hero-link" href="README.md">导出范围说明</a>
        </nav>
      </div>
    </header>

    <section class="metrics" aria-label="图片资源统计">
      <article class="metric">
        <span class="metric-label">全部 picture</span>
        <strong class="metric-value" id="metricPictures">—</strong>
        <span class="metric-note" id="metricPictureNote">—</span>
      </article>
      <article class="metric">
        <span class="metric-label">唯一 PNG</span>
        <strong class="metric-value" id="metricUnique">—</strong>
        <span class="metric-note" id="metricUniqueNote">—</span>
      </article>
      <article class="metric">
        <span class="metric-label">来源 BIN</span>
        <strong class="metric-value" id="metricMembers">—</strong>
        <span class="metric-note" id="metricMemberNote">—</span>
      </article>
      <article class="metric">
        <span class="metric-label">调色板视图</span>
        <strong class="metric-value" id="metricPalettes">—</strong>
        <span class="metric-note">当前 PNG 使用 bank 0</span>
      </article>
    </section>

    <section class="source-panel" aria-labelledby="sourceHeading">
      <div class="section-heading">
        <div>
          <h2 id="sourceHeading">来源分布</h2>
          <p>点击任意 BIN 直接过滤；长条宽度代表 picture 数量。</p>
        </div>
      </div>
      <div class="source-stack" id="sourceStack" aria-label="来源数量分布"></div>
      <div class="member-cloud" id="memberCloud"></div>
    </section>

    <main class="browser-panel">
      <section class="filters" aria-label="图片筛选器">
        <div class="control search-control">
          <label for="searchInput">搜索路径或编号</label>
          <input id="searchInput" type="search" placeholder="例如 TWP、chunk-0042、record-003">
        </div>
        <div class="control">
          <label for="memberSelect">来源 BIN</label>
          <select id="memberSelect">
            <option value="">全部来源</option>
          </select>
        </div>
        <div class="control">
          <label for="bppSelect">像素格式</label>
          <select id="bppSelect">
            <option value="">全部 BPP</option>
          </select>
        </div>
        <div class="control">
          <label for="dimensionSelect">图片尺寸</label>
          <select id="dimensionSelect">
            <option value="">全部尺寸</option>
          </select>
        </div>
        <div class="control">
          <label for="paletteSelect">调色板</label>
          <select id="paletteSelect">
            <option value="">全部类型</option>
            <option value="truecolor">无 CLUT / 直色</option>
            <option value="single">单一 CLUT bank</option>
            <option value="multi">多个 CLUT bank</option>
            <option value="shared">共享 CLUT</option>
          </select>
        </div>
        <div class="control">
          <label for="viewSelect">数据视图</label>
          <select id="viewSelect">
            <option value="">stored + decoded</option>
            <option value="decoded">decoded</option>
            <option value="stored">stored</option>
          </select>
        </div>
        <div class="control">
          <label for="sortSelect">排序</label>
          <select id="sortSelect">
            <option value="source">导出顺序</option>
            <option value="member">来源名称</option>
            <option value="area-desc">图片面积：大到小</option>
            <option value="area-asc">图片面积：小到大</option>
            <option value="palette-desc">调色板数量：多到少</option>
          </select>
        </div>
      </section>

      <div class="browser-toolbar">
        <div class="result-summary" id="resultSummary" aria-live="polite"></div>
        <div class="toolbar-actions">
          <label class="toggle">
            <input id="uniqueToggle" type="checkbox">
            仅显示唯一 PNG
          </label>
          <button class="clear-button" id="clearFilters" type="button">清除筛选</button>
        </div>
      </div>

      <section class="asset-grid" id="assetGrid" aria-label="图片结果"></section>
      <div class="empty-state" id="emptyState">
        <strong>没有符合条件的图片</strong>
        <span>尝试清除搜索词或减少筛选条件。</span>
      </div>
      <div class="load-area">
        <button class="load-more" id="loadMore" type="button">继续加载</button>
      </div>
    </main>

    <footer class="page-footer">
      <span>本地只读 Dashboard · 图片文件保持在原导出目录</span>
      <span id="footerStatus"></span>
    </footer>
  </div>

  <dialog id="viewerDialog" aria-labelledby="viewerTitle">
    <div class="viewer">
      <div class="viewer-stage">
        <img id="viewerImage" alt="">
        <button class="viewer-nav viewer-prev" id="viewerPrev" type="button" aria-label="上一张">‹</button>
        <button class="viewer-nav viewer-next" id="viewerNext" type="button" aria-label="下一张">›</button>
      </div>
      <aside class="viewer-panel">
        <button class="dialog-close" id="dialogClose" type="button" aria-label="关闭">×</button>
        <div class="viewer-kicker" id="viewerKicker"></div>
        <h2 class="viewer-title" id="viewerTitle"></h2>
        <p class="viewer-subtitle" id="viewerSubtitle"></p>
        <div class="viewer-chips" id="viewerChips"></div>
        <dl class="detail-list" id="detailList"></dl>
        <div class="viewer-actions">
          <a class="viewer-action primary" id="openPng" target="_blank" rel="noopener">打开原 PNG</a>
          <a class="viewer-action" id="openTim2" target="_blank" rel="noopener">打开 record.tm2</a>
          <button class="viewer-action" id="copyPath" type="button">复制 PNG 路径</button>
          <button class="viewer-action" id="copyHash" type="button">复制 PNG SHA-256</button>
        </div>
        <div class="copy-status" id="copyStatus" aria-live="polite"></div>
      </aside>
    </div>
  </dialog>

  <noscript>此 Dashboard 需要启用 JavaScript 才能筛选和浏览图片。</noscript>
  <script type="application/json" id="dashboardData">__DASHBOARD_DATA__</script>
  <script>
    (() => {
      "use strict";

      const DATA = JSON.parse(document.getElementById("dashboardData").textContent);
      const PAGE_SIZE = 72;
      const colors = [
        "#d9ff66", "#6ed8d0", "#ff9d66", "#88a9ff", "#d88cff",
        "#ff758c", "#ffd166", "#70c1ff", "#a1e887", "#c4a7ff"
      ];
      const number = new Intl.NumberFormat("zh-CN");
      const state = {
        filtered: DATA.images.slice(),
        visible: PAGE_SIZE,
        activeIndex: -1
      };

      const elements = {
        metricPictures: document.getElementById("metricPictures"),
        metricPictureNote: document.getElementById("metricPictureNote"),
        metricUnique: document.getElementById("metricUnique"),
        metricUniqueNote: document.getElementById("metricUniqueNote"),
        metricMembers: document.getElementById("metricMembers"),
        metricMemberNote: document.getElementById("metricMemberNote"),
        metricPalettes: document.getElementById("metricPalettes"),
        sourceStack: document.getElementById("sourceStack"),
        memberCloud: document.getElementById("memberCloud"),
        search: document.getElementById("searchInput"),
        member: document.getElementById("memberSelect"),
        bpp: document.getElementById("bppSelect"),
        dimension: document.getElementById("dimensionSelect"),
        palette: document.getElementById("paletteSelect"),
        view: document.getElementById("viewSelect"),
        sort: document.getElementById("sortSelect"),
        unique: document.getElementById("uniqueToggle"),
        clear: document.getElementById("clearFilters"),
        summary: document.getElementById("resultSummary"),
        grid: document.getElementById("assetGrid"),
        empty: document.getElementById("emptyState"),
        loadMore: document.getElementById("loadMore"),
        footer: document.getElementById("footerStatus"),
        dialog: document.getElementById("viewerDialog"),
        dialogClose: document.getElementById("dialogClose"),
        viewerImage: document.getElementById("viewerImage"),
        viewerPrev: document.getElementById("viewerPrev"),
        viewerNext: document.getElementById("viewerNext"),
        viewerKicker: document.getElementById("viewerKicker"),
        viewerTitle: document.getElementById("viewerTitle"),
        viewerSubtitle: document.getElementById("viewerSubtitle"),
        viewerChips: document.getElementById("viewerChips"),
        details: document.getElementById("detailList"),
        openPng: document.getElementById("openPng"),
        openTim2: document.getElementById("openTim2"),
        copyPath: document.getElementById("copyPath"),
        copyHash: document.getElementById("copyHash"),
        copyStatus: document.getElementById("copyStatus")
      };

      function formatHex(value, width = 8) {
        return "0x" + Number(value).toString(16).padStart(width, "0");
      }

      function chunkLabel(item) {
        return item.chunk === null
          ? "direct"
          : "chunk-" + String(item.chunk).padStart(4, "0");
      }

      function recordLabel(item) {
        return "record-" + String(item.recordIndex).padStart(3, "0");
      }

      function pictureLabel(item) {
        return "picture-" + String(item.pictureIndex).padStart(3, "0");
      }

      function paletteLabel(item) {
        if (item.paletteBanks === 0) return "直色";
        if (item.paletteBanks === 1) return "1 CLUT";
        return number.format(item.paletteBanks) + " CLUT";
      }

      function addOption(select, value, label) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        select.append(option);
      }

      function populateControls() {
        DATA.members.forEach((member) => {
          addOption(
            elements.member,
            member.name,
            member.name + " · " + number.format(member.pictures)
          );
        });

        const bppCounts = new Map();
        const dimensionCounts = new Map();
        DATA.images.forEach((item) => {
          bppCounts.set(item.bpp, (bppCounts.get(item.bpp) || 0) + 1);
          const key = item.width + "×" + item.height;
          dimensionCounts.set(key, (dimensionCounts.get(key) || 0) + 1);
        });
        [...bppCounts.entries()]
          .sort((a, b) => a[0] - b[0])
          .forEach(([bpp, count]) => {
            addOption(elements.bpp, String(bpp), bpp + "-bpp · " + number.format(count));
          });
        [...dimensionCounts.entries()]
          .sort((a, b) => {
            const areaA = a[0].split("×").reduce((x, y) => x * Number(y), 1);
            const areaB = b[0].split("×").reduce((x, y) => x * Number(y), 1);
            return areaB - areaA;
          })
          .forEach(([size, count]) => {
            addOption(elements.dimension, size, size + " · " + number.format(count));
          });
      }

      function setMember(member) {
        elements.member.value = member;
        applyFilters();
      }

      function renderSourceOverview() {
        const total = DATA.meta.totals.pictures;
        DATA.members.forEach((member, index) => {
          const segment = document.createElement("button");
          segment.className = "source-segment";
          segment.type = "button";
          segment.style.flexGrow = String(member.pictures);
          segment.style.setProperty("--segment-color", colors[index % colors.length]);
          segment.dataset.member = member.name;
          segment.title = member.name + " · " + number.format(member.pictures) +
            " (" + (member.pictures / total * 100).toFixed(1) + "%)";
          segment.setAttribute("aria-label", segment.title);
          segment.addEventListener("click", () => setMember(member.name));
          elements.sourceStack.append(segment);

          const chip = document.createElement("button");
          chip.className = "member-chip";
          chip.type = "button";
          chip.dataset.member = member.name;
          const name = document.createElement("strong");
          name.textContent = member.name;
          const count = document.createElement("span");
          count.textContent = number.format(member.pictures);
          chip.append(name, count);
          chip.addEventListener("click", () => setMember(member.name));
          elements.memberCloud.append(chip);
        });
      }

      function updateMemberHighlights() {
        const selected = elements.member.value;
        document.querySelectorAll("[data-member]").forEach((node) => {
          node.classList.toggle("active", node.dataset.member === selected);
        });
      }

      function matchesPalette(item, filter) {
        if (!filter) return true;
        if (filter === "truecolor") return item.paletteBanks === 0;
        if (filter === "single") return item.paletteBanks === 1;
        if (filter === "multi") return item.paletteBanks > 1;
        if (filter === "shared") return item.sharedClut;
        return true;
      }

      function sortImages(items, order) {
        if (order === "source") return items.sort((a, b) => a.id - b.id);
        if (order === "member") {
          return items.sort((a, b) =>
            a.member.localeCompare(b.member) || a.id - b.id
          );
        }
        if (order === "area-desc") {
          return items.sort((a, b) =>
            (b.width * b.height) - (a.width * a.height) || a.id - b.id
          );
        }
        if (order === "area-asc") {
          return items.sort((a, b) =>
            (a.width * a.height) - (b.width * b.height) || a.id - b.id
          );
        }
        if (order === "palette-desc") {
          return items.sort((a, b) =>
            b.paletteBanks - a.paletteBanks || a.id - b.id
          );
        }
        return items;
      }

      function applyFilters() {
        const query = elements.search.value.trim().toLowerCase();
        const member = elements.member.value;
        const bpp = elements.bpp.value;
        const dimension = elements.dimension.value;
        const palette = elements.palette.value;
        const view = elements.view.value;
        const unique = elements.unique.checked;

        const filtered = DATA.images.filter((item) => {
          if (member && item.member !== member) return false;
          if (bpp && String(item.bpp) !== bpp) return false;
          if (dimension && item.width + "×" + item.height !== dimension) return false;
          if (view && item.view !== view) return false;
          if (unique && !item.primary) return false;
          if (!matchesPalette(item, palette)) return false;
          if (query) {
            const haystack = [
              item.member,
              item.png,
              item.tim2,
              chunkLabel(item),
              recordLabel(item),
              pictureLabel(item),
              item.pngHash
            ].join(" ").toLowerCase();
            if (!haystack.includes(query)) return false;
          }
          return true;
        });

        state.filtered = sortImages(filtered, elements.sort.value);
        state.visible = PAGE_SIZE;
        state.activeIndex = -1;
        updateMemberHighlights();
        renderGrid();
      }

      function makeBadge(text, className = "") {
        const badge = document.createElement("span");
        badge.className = "badge" + (className ? " " + className : "");
        badge.textContent = text;
        return badge;
      }

      function makeCard(item) {
        const card = document.createElement("button");
        card.className = "asset-card";
        card.type = "button";
        card.setAttribute(
          "aria-label",
          item.member + " " + item.width + "×" + item.height + " " + item.bpp + "-bpp"
        );

        const stage = document.createElement("div");
        stage.className = "thumb-stage";
        const image = document.createElement("img");
        image.src = item.png;
        image.loading = "lazy";
        image.decoding = "async";
        image.alt = item.member + " " + pictureLabel(item);
        stage.append(image);

        const badges = document.createElement("div");
        badges.className = "thumb-badges";
        if (item.paletteBanks > 1) {
          badges.append(makeBadge(paletteLabel(item), "acid"));
        }
        if (item.duplicateCount > 1) {
          badges.append(makeBadge("×" + item.duplicateCount, "cyan"));
        }
        stage.append(badges);

        const copy = document.createElement("div");
        copy.className = "card-copy";
        const member = document.createElement("div");
        member.className = "card-member";
        member.textContent = item.member;
        member.title = item.member;
        const context = document.createElement("div");
        context.className = "card-context";
        context.textContent = chunkLabel(item) + " / " + recordLabel(item) +
          " / " + pictureLabel(item);
        context.title = context.textContent;
        const footer = document.createElement("div");
        footer.className = "card-footer";
        const size = document.createElement("span");
        size.textContent = item.width + "×" + item.height + " · " + item.bpp + "-bpp";
        const palette = document.createElement("span");
        palette.textContent = paletteLabel(item);
        footer.append(size, palette);
        copy.append(member, context, footer);
        card.append(stage, copy);
        card.addEventListener("click", () => openViewer(item.id));
        return card;
      }

      function renderGrid() {
        elements.grid.replaceChildren();
        const shown = state.filtered.slice(0, state.visible);
        const fragment = document.createDocumentFragment();
        shown.forEach((item) => fragment.append(makeCard(item)));
        elements.grid.append(fragment);

        elements.empty.classList.toggle("visible", state.filtered.length === 0);
        elements.loadMore.hidden = state.visible >= state.filtered.length;
        elements.loadMore.textContent = "继续加载 " +
          number.format(Math.min(PAGE_SIZE, state.filtered.length - state.visible)) +
          " 张";
        elements.summary.innerHTML = "符合条件 <strong>" +
          number.format(state.filtered.length) + "</strong> 张 · 当前显示 <strong>" +
          number.format(shown.length) + "</strong> 张";
      }

      function addViewerChip(text) {
        const chip = document.createElement("span");
        chip.className = "viewer-chip";
        chip.textContent = text;
        elements.viewerChips.append(chip);
      }

      function addDetail(label, value) {
        const row = document.createElement("div");
        row.className = "detail-row";
        const term = document.createElement("dt");
        term.textContent = label;
        const detail = document.createElement("dd");
        detail.textContent = value;
        row.append(term, detail);
        elements.details.append(row);
      }

      function showActiveViewerItem() {
        const item = state.filtered[state.activeIndex];
        if (!item) return;
        elements.viewerImage.src = item.png;
        elements.viewerImage.alt = item.member + " " + pictureLabel(item);
        elements.viewerKicker.textContent =
          "Result " + number.format(state.activeIndex + 1) +
          " / " + number.format(state.filtered.length);
        elements.viewerTitle.textContent = item.member;
        elements.viewerSubtitle.textContent =
          chunkLabel(item) + " / " + item.view + " / " +
          recordLabel(item) + " / " + pictureLabel(item);
        elements.viewerChips.replaceChildren();
        addViewerChip(item.width + "×" + item.height);
        addViewerChip(item.bpp + "-bpp");
        addViewerChip(paletteLabel(item));
        if (item.sharedClut) addViewerChip("共享 CLUT");
        if (item.duplicateCount > 1) {
          addViewerChip("相同 PNG ×" + item.duplicateCount);
        }

        elements.details.replaceChildren();
        addDetail("PNG 路径", item.png);
        addDetail("TIM2 路径", item.tim2);
        addDetail("成员内位置", chunkLabel(item) + " · stored " + formatHex(item.storedStart));
        addDetail("记录 offset", formatHex(item.recordOffset));
        addDetail("记录大小", number.format(item.recordSize) + " bytes");
        addDetail("CLUT 颜色", number.format(item.clutColors));
        addDetail(
          "调色板 bank",
          item.paletteBanks === 0
            ? "无"
            : String(item.paletteBank ?? 0) + " / " + item.paletteBanks
        );
        addDetail("PNG SHA-256", item.pngHash);
        addDetail("记录 SHA-256", item.recordHash);

        elements.openPng.href = item.png;
        elements.openTim2.href = item.tim2;
        elements.viewerPrev.disabled = state.activeIndex <= 0;
        elements.viewerNext.disabled =
          state.activeIndex >= state.filtered.length - 1;
        elements.copyStatus.textContent = "";
      }

      function openViewer(identifier) {
        state.activeIndex = state.filtered.findIndex((item) => item.id === identifier);
        if (state.activeIndex < 0) return;
        showActiveViewerItem();
        if (typeof elements.dialog.showModal === "function") {
          elements.dialog.showModal();
        } else {
          elements.dialog.setAttribute("open", "");
        }
      }

      function stepViewer(delta) {
        const next = state.activeIndex + delta;
        if (next < 0 || next >= state.filtered.length) return;
        state.activeIndex = next;
        showActiveViewerItem();
      }

      async function copyText(value, message) {
        try {
          if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(value);
          } else {
            const area = document.createElement("textarea");
            area.value = value;
            area.style.position = "fixed";
            area.style.opacity = "0";
            document.body.append(area);
            area.select();
            document.execCommand("copy");
            area.remove();
          }
          elements.copyStatus.textContent = message;
        } catch (error) {
          elements.copyStatus.textContent = "复制失败，请从详情中手动选择。";
        }
      }

      function activeItem() {
        return state.filtered[state.activeIndex];
      }

      function clearFilters() {
        elements.search.value = "";
        elements.member.value = "";
        elements.bpp.value = "";
        elements.dimension.value = "";
        elements.palette.value = "";
        elements.view.value = "";
        elements.sort.value = "source";
        elements.unique.checked = false;
        applyFilters();
      }

      function bindEvents() {
        let searchTimer;
        elements.search.addEventListener("input", () => {
          clearTimeout(searchTimer);
          searchTimer = setTimeout(applyFilters, 120);
        });
        [
          elements.member,
          elements.bpp,
          elements.dimension,
          elements.palette,
          elements.view,
          elements.sort,
          elements.unique
        ].forEach((element) => element.addEventListener("change", applyFilters));
        elements.clear.addEventListener("click", clearFilters);
        elements.loadMore.addEventListener("click", () => {
          state.visible += PAGE_SIZE;
          renderGrid();
        });
        elements.dialogClose.addEventListener("click", () => elements.dialog.close());
        elements.viewerPrev.addEventListener("click", () => stepViewer(-1));
        elements.viewerNext.addEventListener("click", () => stepViewer(1));
        elements.copyPath.addEventListener("click", () => {
          const item = activeItem();
          if (item) copyText(item.png, "PNG 相对路径已复制。");
        });
        elements.copyHash.addEventListener("click", () => {
          const item = activeItem();
          if (item) copyText(item.pngHash, "PNG SHA-256 已复制。");
        });
        elements.dialog.addEventListener("click", (event) => {
          if (event.target === elements.dialog) elements.dialog.close();
        });
        document.addEventListener("keydown", (event) => {
          if (!elements.dialog.open) return;
          if (event.key === "ArrowLeft") stepViewer(-1);
          if (event.key === "ArrowRight") stepViewer(1);
        });
      }

      function renderMetrics() {
        const totals = DATA.meta.totals;
        elements.metricPictures.textContent = number.format(totals.pictures);
        elements.metricPictureNote.textContent =
          number.format(totals.records) + " 个 TIM2 记录";
        elements.metricUnique.textContent = number.format(totals.uniquePngs);
        elements.metricUniqueNote.textContent =
          number.format(totals.duplicateRows) + " 个重复引用";
        elements.metricMembers.textContent = number.format(totals.members);
        elements.metricMemberNote.textContent =
          number.format(totals.payloads) + " 个 payload";
        elements.metricPalettes.textContent = number.format(totals.paletteViews);
        elements.footer.textContent =
          totals.renderFailures === 0
            ? number.format(totals.pictures) + " 张导出预览 · 渲染失败 0"
            : "渲染失败 " + number.format(totals.renderFailures);
      }

      renderMetrics();
      populateControls();
      renderSourceOverview();
      bindEvents();
      applyFilters();
    })();
  </script>
</body>
</html>
"""
