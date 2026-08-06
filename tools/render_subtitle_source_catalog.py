#!/usr/bin/env python3
"""Render the SRWZ subtitle-source manifest as a standalone review page."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


STATUS_LABELS = {
    "standalone_chinese_source_found": "中文外挂",
    "complete_chinese_muxed_source_found": "中文内封",
    "complete_non_chinese_fallback_only": "外语兜底",
}

DOWNLOAD_LABELS = {
    "downloaded_and_extracted": "已下载解包",
    "source_page_verified": "已核对来源页",
    "not_downloaded": "未下载",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def link(url: str, label: str) -> str:
    return f'<a href="{esc(url)}" target="_blank" rel="noreferrer">{esc(label)}</a>'


def render_sources(work: dict[str, object]) -> str:
    primary = work["primary"]
    assert isinstance(primary, dict)
    urls = primary.get("urls") or [primary.get("url")]
    links = [link(str(url), f"主源 {index}") for index, url in enumerate(urls, 1) if url]
    for index, item in enumerate(work.get("supplements", []), 1):
        assert isinstance(item, dict)
        links.append(link(str(item["url"]), f"补源 {index}"))
    return " · ".join(links)


def render_local_paths(work: dict[str, object]) -> str:
    paths = work.get("local_paths", [])
    if not paths:
        return "—"
    return "<br>".join(f"<code>{esc(path)}</code>" for path in paths)


def render(manifest: dict[str, object]) -> str:
    summary = manifest["summary"]
    assert isinstance(summary, dict)
    rows: list[str] = []
    for index, work in enumerate(manifest["works"], 1):
        assert isinstance(work, dict)
        primary = work["primary"]
        assert isinstance(primary, dict)
        status = str(work["status"])
        download_status = str(work["download_status"])
        languages = " / ".join(str(value) for value in primary.get("languages", []))
        rows.append(
            "<tr "
            f'data-status="{esc(status)}" data-download="{esc(download_status)}" '
            f'data-search="{esc((str(work["title_zh"]) + " " + str(work["title_ja"]) + " " + str(primary.get("group", ""))).lower())}">'
            f"<td>{index}</td>"
            f'<td><strong>{esc(work["title_zh"])}</strong><small>{esc(work["title_ja"])}</small></td>'
            f'<td><span class="pill {esc(status)}">{esc(STATUS_LABELS[status])}</span>'
            f'<span class="pill download">{esc(DOWNLOAD_LABELS[download_status])}</span></td>'
            f"<td>{esc(primary.get('group', ''))}<small>{esc(languages)} · {esc(primary.get('format', ''))}</small></td>"
            f"<td>{esc(primary.get('coverage', ''))}</td>"
            f"<td>{render_sources(work)}</td>"
            f"<td>{render_local_paths(work)}</td>"
            f"<td>{esc(work.get('notes', ''))}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SRWZ 参战作品字幕源</title>
<style>
:root {{ color-scheme: dark; --bg:#0b1020; --panel:#151c31; --line:#2a3656; --text:#eef3ff; --muted:#9aa8c7; --blue:#66a7ff; --green:#66d19e; --amber:#f3c46b; --rose:#ff8f9f; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ max-width:1800px; margin:auto; padding:28px; }}
h1 {{ margin:0 0 6px; font-size:28px; }}
p {{ color:var(--muted); margin:6px 0 18px; }}
.summary {{ display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:12px; margin:20px 0; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
.card strong {{ display:block; font-size:24px; }}
.controls {{ display:flex; gap:10px; flex-wrap:wrap; margin:18px 0; }}
input,select {{ background:var(--panel); color:var(--text); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }}
input {{ min-width:280px; flex:1; }}
.table-wrap {{ overflow:auto; border:1px solid var(--line); border-radius:12px; }}
table {{ width:100%; border-collapse:collapse; min-width:1500px; background:var(--panel); }}
th,td {{ padding:12px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
th {{ position:sticky; top:0; background:#1b2540; z-index:1; }}
tr:last-child td {{ border-bottom:0; }}
small {{ display:block; color:var(--muted); margin-top:4px; }}
a {{ color:var(--blue); }}
code {{ color:#c8d7ff; font-size:12px; overflow-wrap:anywhere; }}
.pill {{ display:inline-block; margin:0 5px 5px 0; padding:2px 8px; border-radius:999px; white-space:nowrap; color:#07111d; font-weight:700; }}
.standalone_chinese_source_found {{ background:var(--green); }}
.complete_chinese_muxed_source_found {{ background:var(--amber); }}
.complete_non_chinese_fallback_only {{ background:var(--rose); }}
.pill.download {{ background:#9fb1d4; }}
.hidden {{ display:none; }}
@media (max-width:800px) {{ main {{ padding:16px; }} .summary {{ grid-template-columns:1fr 1fr; }} }}
</style>
</head>
<body>
<main>
<h1>SRWZ 参战作品字幕源</h1>
<p>优先 POPGO/FREEWIND，其次完整中文外挂。字幕只作为名词审核证据，不自动写入正式 corpus。</p>
<section class="summary">
  <div class="card"><strong>{esc(summary['works'])}</strong>参战动画作品</div>
  <div class="card"><strong>{esc(summary['standalone_chinese_source_found'])}</strong>中文外挂源</div>
  <div class="card"><strong>{esc(summary['complete_chinese_muxed_source_found'])}</strong>完整中文内封源</div>
  <div class="card"><strong>{esc(summary['complete_non_chinese_fallback_only'])}</strong>暂仅外语兜底</div>
</section>
<div class="controls">
  <input id="search" type="search" placeholder="搜索作品名或字幕组">
  <select id="status"><option value="">全部来源状态</option><option value="standalone_chinese_source_found">中文外挂</option><option value="complete_chinese_muxed_source_found">中文内封</option><option value="complete_non_chinese_fallback_only">外语兜底</option></select>
  <select id="download"><option value="">全部本地状态</option><option value="downloaded_and_extracted">已下载解包</option><option value="source_page_verified">已核对来源页</option><option value="not_downloaded">未下载</option></select>
</div>
<div class="table-wrap"><table>
<thead><tr><th>#</th><th>作品</th><th>状态</th><th>字幕组 / 语言</th><th>覆盖</th><th>来源</th><th>本地路径</th><th>备注</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table></div>
</main>
<script>
const search = document.querySelector('#search');
const status = document.querySelector('#status');
const download = document.querySelector('#download');
const rows = [...document.querySelectorAll('tbody tr')];
function filterRows() {{
  const q = search.value.trim().toLowerCase();
  for (const row of rows) {{
    const visible = (!q || row.dataset.search.includes(q)) && (!status.value || row.dataset.status === status.value) && (!download.value || row.dataset.download === download.value);
    row.classList.toggle('hidden', !visible);
  }}
}}
search.addEventListener('input', filterRows);
status.addEventListener('change', filterRows);
download.addEventListener('change', filterRows);
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(manifest), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
