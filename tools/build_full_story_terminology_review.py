#!/usr/bin/env python3
"""Build a standalone offline review page for full-story terminology."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "work/review"
INVENTORY = REVIEW / "full-story-terminology"
QUEUE = REVIEW / "local-model/story-dialogue-unique.jsonl"
TEXT_INDEX = INVENTORY / "full-text-index.jsonl"
GLOSSARY = INVENTORY / "glossary-usage.tsv"
CANONICAL_MISSING = INVENTORY / "canonical-missing.tsv"
PENDING_FORMS = INVENTORY / "pending-surface-forms.tsv"
PENDING_GROUPS = INVENTORY / "pending-surface-groups.tsv"
SUMMARY = INVENTORY / "summary.json"
SUBTITLE = REVIEW / "subtitle-sources/subtitle-terminology-baseline.json"
PREPROCESSED = INVENTORY / "preprocessed-terms.json"
DECISION_OVERRIDES = INVENTORY / "user-decision-overrides.json"
OUTPUT = INVENTORY / "review.html"
WORK_PATTERN = re.compile(r"《([^》]+)》")
KATAKANA_PATTERN = re.compile(r"[ァ-ヿー・＝]{2,}")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def split_values(value: str, separator: str = " | ") -> list[str]:
    return [item.strip() for item in value.split(separator) if item.strip()]


def context_maps(
    queue: list[dict[str, object]], translations: Mapping[tuple[int, int], str]
) -> tuple[
    dict[tuple[int, int], tuple[str | None, str | None]],
    dict[str, list[dict[str, object]]],
]:
    by_stage: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in queue:
        by_stage[int(row["stage_index"])].append(row)
    neighbors: dict[tuple[int, int], tuple[str | None, str | None]] = {}
    term_examples: dict[str, list[dict[str, object]]] = defaultdict(list)
    for stage, rows in by_stage.items():
        rows.sort(key=lambda row: int(row["unique_index"]))
        for position, row in enumerate(rows):
            index = int(row["unique_index"])
            key = stage, index
            before = str(rows[position - 1]["source_text"]) if position else None
            after = str(rows[position + 1]["source_text"]) if position + 1 < len(rows) else None
            neighbors[key] = before, after
            for term in row.get("glossary_terms", []):
                if not isinstance(term, Mapping):
                    continue
                term_id = str(term["id"])
                examples = term_examples[term_id]
                if len(examples) >= 4:
                    continue
                examples.append(
                    {
                        "key": f"{stage:03d}:{index}",
                        "source": row["source_text"],
                        "translation": translations[key],
                        "before": before,
                        "after": after,
                    }
                )
    return neighbors, term_examples


def glossary_items(
    rows: list[dict[str, str]], term_examples: Mapping[str, list[dict[str, object]]]
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for row in rows:
        term_id = row["term_id"]
        notes = row["notes"]
        works = sorted(set(WORK_PATTERN.findall(notes)))
        missing = int(row["canonical_missing_unique_rows"])
        items.append(
            {
                "id": f"G:{term_id}",
                "item_type": "glossary",
                "term_id": term_id,
                "label": " / ".join(split_values(row["source_terms"])),
                "source_terms": split_values(row["source_terms"]),
                "proposed_translation": row["canonical_translation"],
                "alternate_translation": None,
                "category": row["category"] or "unclassified",
                "status": row["status"] or "unknown",
                "work_hints": works,
                "priority": "high" if missing else "normal",
                "conflict": bool(missing),
                "usage": {
                    "unique_rows": int(row["matched_unique_rows"]),
                    "expanded_occurrences": int(row["matched_expanded_occurrences"]),
                    "canonical_missing_rows": missing,
                    "exception_rows": int(row["exception_unique_rows"]),
                },
                "notes": notes,
                "evidence": "项目结构化词表；规范译名未落地行数为 " + str(missing),
                "examples": term_examples.get(term_id, []),
                "seeded_decision": None,
            }
        )
    return items


def surface_items(
    group_rows: list[dict[str, str]],
    form_rows: list[dict[str, str]],
    queue_by_key: Mapping[tuple[int, int], dict[str, object]],
    neighbors: Mapping[tuple[int, int], tuple[str | None, str | None]],
) -> list[dict[str, object]]:
    members: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in form_rows:
        terms = sorted(
            (item.strip() for item in row["ascii_terms"].split(",") if item.strip()),
            key=str.casefold,
        )
        members[" + ".join(terms)].append(row)

    items: list[dict[str, object]] = []
    for row in group_rows:
        group = row["ascii_terms"]
        group_members = members[group]
        categories: set[str] = set()
        works: set[str] = set()
        japanese_tokens: Counter[str] = Counter()
        examples: list[dict[str, object]] = []
        for member in group_members:
            key = int(member["stage_index"]), int(member["unique_index"])
            source = queue_by_key[key]
            for token in KATAKANA_PATTERN.findall(str(source["source_text"])):
                japanese_tokens[token.strip("・")] += 1
            for term in source.get("glossary_terms", []):
                if not isinstance(term, Mapping):
                    continue
                if term.get("category"):
                    categories.add(str(term["category"]))
                works.update(WORK_PATTERN.findall(str(term.get("notes", ""))))
            if len(examples) < 4:
                before, after = neighbors[key]
                examples.append(
                    {
                        "key": f"{key[0]:03d}:{key[1]}",
                        "source": source["source_text"],
                        "translation": member["current_translation"].replace(" / ", "\n"),
                        "before": before,
                        "after": after,
                    }
                )
        likely_source_terms = [
            token for token, _ in japanese_tokens.most_common(8) if token
        ]
        items.append(
            {
                "id": "S:" + group,
                "item_type": "surface",
                "term_id": None,
                "label": group,
                "source_terms": likely_source_terms,
                "proposed_translation": group,
                "alternate_translation": None,
                "category": " | ".join(sorted(categories)) if categories else "unclassified",
                "status": "pending_surface_form",
                "work_hints": sorted(works),
                "priority": "normal",
                "conflict": True,
                "usage": {
                    "unique_rows": int(row["unique_row_count"]),
                    "expanded_occurrences": int(row["expanded_occurrence_count"]),
                    "stage_count": int(row["stage_count"]),
                },
                "notes": "机器稿中的英文专名、口号或写法；尚未决定保留英文还是统一为中文。",
                "evidence": "出现段：" + row["stages"],
                "examples": examples,
                "seeded_decision": None,
            }
        )
    return items


def subtitle_items(document: Mapping[str, object]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for row in document.get("terms", []):
        if not isinstance(row, Mapping):
            continue
        recorded = row.get("recorded_translation")
        subtitle_form = str(row.get("subtitle_form", ""))
        subtitle_has_translation = bool(
            subtitle_form
            and subtitle_form != "—"
            and not subtitle_form.startswith("未")
            and not re.match(r"^前\d+集未", subtitle_form)
        )
        alternate = (
            subtitle_form
            if subtitle_has_translation and subtitle_form != recorded
            else None
        )
        seeded = None
        if recorded:
            seeded = {
                "action": "accept",
                "chosen_translation": str(recorded),
                "custom_translation": "",
                "note": str(row.get("recorded_note") or ""),
                "seeded_from": "recorded_user_decision",
            }
        items.append(
            {
                "id": "U:" + str(row["id"]),
                "item_type": "subtitle",
                "term_id": row["id"],
                "label": row["japanese"],
                "source_terms": [row["japanese"]],
                "proposed_translation": str(recorded or ""),
                "alternate_translation": alternate,
                "category": row.get("category") or "unclassified",
                "status": row.get("evidence_status") or "unknown",
                "work_hints": [row["work"]] if row.get("work") else [],
                "priority": "high"
                if row.get("alignment") == "conflict" or not recorded
                else "normal",
                "conflict": row.get("alignment") == "conflict",
                "usage": {},
                "notes": str(row.get("recorded_note") or ""),
                "evidence": f"{row.get('source', '')}：{row.get('evidence_summary', '')}",
                "examples": [],
                "seeded_decision": seeded,
            }
        )
    return items


def preprocessed_items(document: Mapping[str, object]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for row in document.get("items", []):
        if not isinstance(row, Mapping):
            continue
        evidence = "；".join(
            f"{entry.get('tier', '')}：{entry.get('claim', '')}（{entry.get('source', '')}）"
            for entry in row.get("evidence", [])
            if isinstance(entry, Mapping)
        )
        disposition = str(row.get("disposition", "needs_human"))
        observed = row.get("observed_forms", {})
        observed_label = " / ".join(str(value) for value in observed) if isinstance(observed, Mapping) else ""
        source_terms = [str(value) for value in row.get("source_terms", [])]
        items.append(
            {
                "id": str(row["id"]),
                "item_type": str(row.get("item_type", "preprocessed")),
                "term_id": str(row["id"]).split(":", 1)[-1],
                "label": " / ".join(source_terms) or observed_label or str(row["id"]),
                "source_terms": source_terms,
                "proposed_translation": str(row.get("preferred_translation", "")),
                "alternate_translation": None,
                "category": str(row.get("category") or "unclassified"),
                "status": disposition,
                "review_state": "human"
                if disposition in {"needs_human", "needs_human_conflict"}
                else "automatic",
                "work_hints": [str(row.get("work"))] if row.get("work") else [],
                "priority": str(row.get("priority", "normal")),
                "conflict": disposition == "needs_human_conflict",
                "usage": dict(row.get("usage", {})),
                "notes": str(row.get("rationale") or ""),
                "evidence": evidence,
                "examples": list(row.get("examples", [])),
                "seeded_decision": row.get("seeded_decision"),
            }
        )
    return items


def pending_subtitle_items(
    document: Mapping[str, object],
    queue: list[dict[str, object]],
    translations: Mapping[tuple[int, int], str],
    neighbors: Mapping[tuple[int, int], tuple[str | None, str | None]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in document.get("terms", []):
        if not isinstance(row, Mapping) or row.get("recorded_translation"):
            continue
        japanese = str(row["japanese"])
        examples: list[dict[str, object]] = []
        for source in queue:
            if japanese not in str(source["source_text"]):
                continue
            key = int(source["stage_index"]), int(source["unique_index"])
            before, after = neighbors[key]
            examples.append(
                {
                    "key": f"{key[0]:03d}:{key[1]}",
                    "source": source["source_text"],
                    "translation": translations[key],
                    "before": before,
                    "after": after,
                }
            )
            if len(examples) >= 5:
                break
        result.append(
            {
                "id": "U:" + str(row["id"]),
                "item_type": "subtitle",
                "term_id": row["id"],
                "label": japanese,
                "source_terms": [japanese],
                "proposed_translation": "",
                "alternate_translation": None,
                "category": row.get("category") or "unclassified",
                "status": "needs_human",
                "review_state": "human",
                "work_hints": [row["work"]] if row.get("work") else [],
                "priority": "high",
                "conflict": True,
                "usage": {"unique_rows": len(examples), "expanded_occurrences": len(examples)},
                "notes": "U01–U49 中尚未确认的项目。",
                "evidence": f"{row.get('source', '')}：{row.get('evidence_summary', '')}",
                "examples": examples,
                "seeded_decision": None,
            }
        )
    return result


def add_canonical_examples(
    items: list[dict[str, object]],
    queue: list[dict[str, object]],
    translations: Mapping[tuple[int, int], str],
    neighbors: Mapping[tuple[int, int], tuple[str | None, str | None]],
) -> None:
    targets = {
        str(item["id"]).removeprefix("C:"): item
        for item in items
        if item["item_type"] == "canonical_missing"
    }
    queue_by_key = {
        (int(source["stage_index"]), int(source["unique_index"])): source
        for source in queue
    }
    for row in read_tsv(CANONICAL_MISSING):
        item = targets.get(row["term_id"])
        if item is None:
            continue
        keys = [
            (int(stage), int(index))
            for stage, index in re.findall(r"(\d{3}):(\d+)", row["canonical_missing_examples"])
        ]
        for key in keys[:5]:
            source = queue_by_key.get(key)
            if source is None:
                raise ValueError(f"canonical-missing example is absent from queue: {key}")
            before, after = neighbors[key]
            item["examples"].append(
                {
                    "key": f"{key[0]:03d}:{key[1]}",
                    "source": source["source_text"],
                    "translation": translations[key],
                    "before": before,
                    "after": after,
                }
            )


def apply_decision_overrides(items: list[dict[str, object]]) -> None:
    if not DECISION_OVERRIDES.exists():
        return
    document = json.loads(DECISION_OVERRIDES.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("unsupported decision override schema")
    by_id = {str(item["id"]): item for item in items}
    seen: set[str] = set()
    for row in document.get("decisions", []):
        if not isinstance(row, Mapping):
            raise ValueError("decision override must be an object")
        item_id = str(row.get("id", ""))
        if item_id in seen:
            raise ValueError(f"duplicate decision override: {item_id}")
        seen.add(item_id)
        item = by_id.get(item_id)
        if item is None:
            raise ValueError(f"decision override does not match review item: {item_id}")
        action = str(row.get("action", ""))
        custom = str(row.get("custom_translation") or "").strip()
        if action != "custom" or not custom:
            raise ValueError(f"decision override must be a non-empty custom choice: {item_id}")
        item["seeded_decision"] = {
            "action": "custom",
            "chosen_translation": custom,
            "custom_translation": custom,
            "note": str(row.get("note") or ""),
            "seeded_from": "recorded_user_decision_override",
        }


def html_document(data: Mapping[str, object]) -> str:
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SRWZ 术语冲突校对</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='12' fill='%239d382d'/><text x='32' y='44' text-anchor='middle' font-size='38' fill='white'>Z</text></svg>">
  <style>
    :root{--bg:#f4f1ea;--paper:#fffdf8;--ink:#24231f;--muted:#6f6a60;--line:#d9d2c4;--accent:#9d382d;--blue:#255f7a;--green:#38714d;--amber:#9a6517;--shadow:0 12px 35px rgba(61,47,29,.09)}
    *{box-sizing:border-box} body{margin:0;background:linear-gradient(135deg,#ece7dd,#f8f5ef 46%,#eee7da);color:var(--ink);font:15px/1.58 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans CJK SC",sans-serif}
    header{position:sticky;top:0;z-index:4;background:rgba(255,253,248,.94);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
    .head{max-width:1500px;margin:auto;padding:18px 24px 14px}.title-row{display:flex;gap:18px;align-items:flex-end;justify-content:space-between;flex-wrap:wrap}h1{margin:0;font:700 29px/1.15 Georgia,"Noto Serif CJK SC",serif}.subtitle{color:var(--muted);margin-top:5px}.stats{display:flex;gap:8px;flex-wrap:wrap}.stat{background:#eee8db;border:1px solid #ded5c5;border-radius:999px;padding:5px 10px;font-size:13px}.stat strong{font-size:15px;color:var(--accent)}
    .toolbar{margin-top:14px;display:grid;grid-template-columns:minmax(230px,2fr) repeat(3,minmax(130px,1fr)) auto auto;gap:8px}input,select,textarea,button{font:inherit}input,select,textarea{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff;padding:8px 10px;color:var(--ink)}button,.button{border:1px solid var(--line);border-radius:8px;background:#fff;padding:8px 12px;cursor:pointer;color:var(--ink);text-decoration:none;white-space:nowrap}button:hover,.button:hover{border-color:var(--accent)}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
    main{max-width:1500px;margin:auto;padding:22px 24px 60px}.notice{background:#fff7dc;border:1px solid #ead494;border-radius:10px;padding:12px 15px;margin-bottom:16px}.progress{display:flex;gap:14px;align-items:center;margin:12px 0 16px;color:var(--muted)}.bar{height:8px;flex:1;background:#ddd5c7;border-radius:9px;overflow:hidden}.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--green),#77a063);width:0}
    .list{display:grid;gap:12px}.card{background:var(--paper);border:1px solid var(--line);border-radius:13px;box-shadow:var(--shadow);padding:16px}.card.high{border-left:5px solid var(--accent)}.card.decided{background:#fbfff9}.card-head{display:flex;gap:12px;justify-content:space-between}.term{font-size:20px;font-weight:700}.arrow{color:var(--muted);font-weight:400;margin:0 8px}.translation{color:var(--blue)}.badges{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.badge{font-size:12px;padding:2px 7px;border:1px solid var(--line);border-radius:999px;background:#f3eee4}.badge.high{color:#fff;background:var(--accent);border-color:var(--accent)}.badge.conflict{color:#7b4100;background:#fff0c9;border-color:#e3c06f}.meta{color:var(--muted);font-size:13px;margin:7px 0}.evidence{margin-top:7px}.examples{margin-top:9px;border-top:1px dashed var(--line);padding-top:8px}details summary{cursor:pointer;color:var(--blue)}.example{margin:9px 0;padding:9px 11px;background:#f4f0e8;border-radius:8px;white-space:pre-wrap}.example .src{font-family:"Hiragino Mincho ProN","Yu Mincho",serif}.example .zh{color:var(--blue);margin-top:4px}.context{color:var(--muted);font-size:12px;margin-top:5px}
    .decision{display:grid;grid-template-columns:auto auto auto auto minmax(190px,1fr) minmax(180px,1fr);gap:7px;margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}.choice{padding:7px 9px}.choice.active{border-color:var(--green);background:#e7f3e8;color:#245533}.choice.defer.active{border-color:var(--amber);background:#fff2d7;color:#754c0e}.custom-input[disabled]{opacity:.55}.empty{text-align:center;padding:60px;color:var(--muted)}.hidden{display:none!important}
    @media(max-width:980px){.toolbar{grid-template-columns:1fr 1fr}.decision{grid-template-columns:1fr 1fr}.card-head{display:block}.badges{justify-content:flex-start;margin-top:8px}}@media(max-width:600px){.head,main{padding-left:12px;padding-right:12px}.toolbar{grid-template-columns:1fr}.decision{grid-template-columns:1fr}.term{font-size:18px}}
  </style>
</head>
<body>
<header><div class="head">
  <div class="title-row"><div><h1>SRWZ 术语冲突校对</h1><div class="subtitle">官方中文 → 中文 Wiki → 下载字幕 → 项目词表 · 默认只显示真正需要人工确认的项目</div></div><div class="stats" id="stats"></div></div>
  <div class="toolbar">
    <input id="search" type="search" placeholder="搜索日文、中文、作品、ID、备注……">
    <select id="type-filter"><option value="all">全部来源</option><option value="preprocessed">综合证据项</option><option value="canonical_missing">词表命中异常</option><option value="subtitle">U33 / U49</option></select>
    <select id="category-filter"><option value="all">全部类别</option></select>
    <select id="review-filter"><option value="human" selected>待人工确认</option><option value="unreviewed">尚未操作</option><option value="conflict">来源冲突</option><option value="automatic">已自动处理</option><option value="decided">已决定</option><option value="deferred">暂缓</option><option value="all">全部状态</option></select>
    <button id="export" class="primary">导出决定</button><button id="import">导入决定</button><input id="import-file" class="hidden" type="file" accept="application/json">
  </div>
</div></header>
<main>
  <div class="notice">自动层只做预填和分类，尚未写回正式译文。先确认红色冲突项；其余低频项可以暂缓。每项都保留作品、日文、现译、前后文和证据来源。</div>
  <div class="progress"><span id="progress-text"></span><div class="bar"><i id="progress-bar"></i></div><button id="reset">恢复预填决定</button><a class="button" href="../local-model/aliyun/remaining-stages/editorial-batches/stage-016-025/review.html">旧版详细字幕页</a></div>
  <div id="list" class="list"></div>
</main>
<script id="review-data" type="application/json">""" + data_json + """</script>
<script>
(() => {
  const data = JSON.parse(document.getElementById('review-data').textContent);
  const KEY = 'srwz-full-story-terminology-review-v1';
  const esc = value => String(value ?? '').replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const typeNames = {preprocessed:'综合证据',canonical_missing:'词表异常',subtitle:'未决基准'};
  const categoryNames = {people:'人物',unit:'机体',weapon:'武器',place:'地点',organization:'组织',faction:'阵营',event:'事件',system:'系统/能力',technology:'技术',species:'种族',era:'时代',ideology:'思想',measurement:'计量单位',unclassified:'待归类'};
  let state = {};
  try { state = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (_) {}
  for (const item of data.items) if (state[item.id]?.action === 'accept' && !item.proposed_translation) delete state[item.id];
  for (const item of data.items) if (!state[item.id] && item.seeded_decision) state[item.id] = {...item.seeded_decision};
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) {} };
  save();
  const $ = id => document.getElementById(id);
  const categories = [...new Set(data.items.flatMap(item => String(item.category).split(' | ')))].sort();
  for (const value of categories) { const option=document.createElement('option'); option.value=value; option.textContent=categoryNames[value]||value; $('category-filter').append(option); }
  const chosen = (item, decision) => {
    if (!decision) return '';
    if (decision.action === 'accept') return item.proposed_translation;
    if (decision.action === 'subtitle') return item.alternate_translation;
    if (decision.action === 'custom') return decision.custom_translation || '';
    return '';
  };
  const exampleHtml = examples => !examples?.length ? '' : `<details class="examples"><summary>查看原文与上下文（${examples.length}例）</summary>${examples.map(ex => `<div class="example"><div><b>${esc(ex.key)}</b></div>${ex.before?`<div class="context">前：${esc(ex.before)}</div>`:''}<div class="src">${esc(ex.source)}</div><div class="zh">现：${esc(ex.translation)}</div>${ex.after?`<div class="context">后：${esc(ex.after)}</div>`:''}</div>`).join('')}</details>`;
  const cardHtml = item => {
    const d = state[item.id] || {};
    const selected = chosen(item,d);
    const works = item.work_hints?.length ? item.work_hints.join(' / ') : '作品待关联';
    const usage = item.usage?.unique_rows ? `${item.usage.unique_rows}条去重文本 / ${item.usage.expanded_occurrences}次实际出现` : '字幕/人工证据项';
    const cats = String(item.category).split(' | ').map(c => categoryNames[c]||c).join(' / ');
    return `<article class="card ${item.priority==='high'?'high':''} ${d.action&&d.action!=='defer'?'decided':''}" data-id="${esc(item.id)}">
      <div class="card-head"><div><div class="term">${esc(item.label||item.source_terms?.join(' / ')||item.id)}<span class="arrow">→</span><span class="translation">${esc(item.proposed_translation||'待定')}</span></div><div class="meta">${esc(item.term_id||item.id)} · ${esc(works)} · ${esc(cats)} · ${esc(usage)}</div></div><div class="badges"><span class="badge">${esc(typeNames[item.item_type])}</span><span class="badge">${esc(item.status)}</span>${item.priority==='high'?'<span class="badge high">高优先级</span>':''}${item.conflict?'<span class="badge conflict">需统一</span>':''}</div></div>
      ${item.source_terms?.length?`<div><b>原词：</b>${esc(item.source_terms.join(' / '))}</div>`:''}
      <div class="evidence"><b>依据：</b>${esc(item.evidence||'—')}</div>${item.notes?`<div class="meta">备注：${esc(item.notes)}</div>`:''}
      ${exampleHtml(item.examples)}
      <div class="decision">
        <button class="choice ${d.action==='accept'?'active':''}" data-action="accept" ${item.proposed_translation?'':'disabled'}>${item.proposed_translation?(item.item_type==='surface'?'保留当前写法':'采用建议'):'无建议可采用'}</button>
        ${item.alternate_translation?`<button class="choice ${d.action==='subtitle'?'active':''}" data-action="subtitle">采用字幕：${esc(item.alternate_translation)}</button>`:'<button class="choice" disabled>无第二候选</button>'}
        <button class="choice ${d.action==='custom'?'active':''}" data-action="custom">自定义</button>
        <button class="choice defer ${d.action==='defer'?'active':''}" data-action="defer">暂缓</button>
        <input class="custom-input" data-field="custom_translation" value="${esc(d.custom_translation||'')}" placeholder="自定义最终译名" ${d.action==='custom'?'':'disabled'}>
        <input data-field="note" value="${esc(d.note||'')}" placeholder="校对备注">
      </div>
      ${selected?`<div class="meta"><b>当前决定：</b>${esc(selected)}</div>`:''}
    </article>`;
  };
  const matches = item => {
    const q=$('search').value.trim().toLowerCase(), type=$('type-filter').value, category=$('category-filter').value, review=$('review-filter').value, d=state[item.id];
    if (type!=='all' && item.item_type!==type) return false;
    if (category!=='all' && !String(item.category).split(' | ').includes(category)) return false;
    if (review==='human' && item.review_state!=='human') return false;
    if (review==='automatic' && item.review_state!=='automatic') return false;
    if (review==='unreviewed' && (d?.action || item.review_state!=='human')) return false;
    if (review==='decided' && (!d?.action || d.action==='defer')) return false;
    if (review==='deferred' && d?.action!=='defer') return false;
    if (review==='conflict' && !item.conflict) return false;
    return !q || JSON.stringify(item).toLowerCase().includes(q);
  };
  const render = () => {
    const items=data.items.filter(matches); $('list').innerHTML=items.length?items.map(cardHtml).join(''):'<div class="empty">没有符合条件的术语</div>';
    const decided=data.items.filter(i=>state[i.id]?.action && state[i.id].action!=='defer').length, deferred=data.items.filter(i=>state[i.id]?.action==='defer').length;
    $('progress-text').textContent=`已决定 ${decided}/${data.items.length} · 暂缓 ${deferred} · 当前显示 ${items.length}`;
    $('progress-bar').style.width=`${decided/data.items.length*100}%`;
    $('stats').innerHTML=`<span class="stat"><strong>${data.summary.chinese_character_counts.expanded_in_game_han_occurrences.toLocaleString()}</strong> 汉字</span><span class="stat"><strong>${data.counts.human}</strong> 待人工</span><span class="stat"><strong>${data.counts.automatic}</strong> 已预处理</span><span class="stat"><strong>${data.counts.conflict}</strong> 来源冲突</span>`;
  };
  $('list').addEventListener('click', event => { const button=event.target.closest('[data-action]'); if(!button||button.disabled)return; const card=button.closest('[data-id]'), id=card.dataset.id; state[id]=state[id]||{}; state[id].action=button.dataset.action; if(button.dataset.action!=='custom') state[id].chosen_translation=chosen(data.items.find(i=>i.id===id),state[id]); save(); render(); });
  $('list').addEventListener('input', event => { const field=event.target.dataset.field; if(!field)return; const id=event.target.closest('[data-id]').dataset.id; state[id]=state[id]||{}; state[id][field]=event.target.value; if(field==='custom_translation') state[id].chosen_translation=event.target.value; save(); });
  for (const id of ['search','type-filter','category-filter','review-filter']) $(id).addEventListener(id==='search'?'input':'change',render);
  $('export').addEventListener('click',()=>{ const decisions=data.items.filter(i=>state[i.id]?.action).map(item=>{const d=state[item.id];return {id:item.id,item_type:item.item_type,term_id:item.term_id,source_terms:item.source_terms,action:d.action,chosen_translation:chosen(item,d),custom_translation:d.custom_translation||'',note:d.note||'',seeded_from:d.seeded_from||null};}); const out={schema_version:1,kind:'srwz_full_story_terminology_review_decisions',exported_at:new Date().toISOString(),source_summary:data.summary.scope,decision_count:decisions.length,decisions}; const blob=new Blob([JSON.stringify(out,null,2)+'\\n'],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='srwz-full-story-terminology-decisions.json';a.click();URL.revokeObjectURL(a.href);});
  $('import').addEventListener('click',()=>$('import-file').click()); $('import-file').addEventListener('change',async event=>{const file=event.target.files[0];if(!file)return;try{const doc=JSON.parse(await file.text());if(!Array.isArray(doc.decisions))throw new Error('缺少 decisions 数组');for(const d of doc.decisions)if(data.items.some(i=>i.id===d.id))state[d.id]={action:d.action,custom_translation:d.custom_translation||'',note:d.note||'',seeded_from:d.seeded_from||null};save();render();alert(`已导入 ${doc.decisions.length} 条决定`);}catch(error){alert('导入失败：'+error.message);}event.target.value='';});
  $('reset').addEventListener('click',()=>{if(!confirm('确定清空当前编辑，并恢复自动预处理决定吗？'))return;state={};for(const item of data.items)if(item.seeded_decision)state[item.id]={...item.seeded_decision};save();render();});
  render();
})();
</script>
</body></html>
"""


def main() -> int:
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    queue = read_jsonl(QUEUE)
    queue_by_key = {
        (int(row["stage_index"]), int(row["unique_index"])): row for row in queue
    }
    translations = {
        (int(row["stage_index"]), int(row["unique_index"])): str(row["translation"])
        for row in read_jsonl(TEXT_INDEX)
    }
    if set(queue_by_key) != set(translations):
        raise ValueError("full-text index does not cover terminology queue")
    neighbors, _term_examples = context_maps(queue, translations)
    preprocessing = json.loads(PREPROCESSED.read_text(encoding="utf-8"))
    items = preprocessed_items(preprocessing)
    items.extend(
        pending_subtitle_items(
            json.loads(SUBTITLE.read_text(encoding="utf-8")),
            queue,
            translations,
            neighbors,
        )
    )
    apply_decision_overrides(items)
    add_canonical_examples(items, queue, translations, neighbors)
    review_counts = Counter(str(item["review_state"]) for item in items)
    review_counts["conflict"] = sum(bool(item["conflict"]) for item in items)
    if review_counts["human"] != int(preprocessing["summary"]["human_review_item_count"]) + 2:
        raise ValueError(f"unexpected human review count: {review_counts}")
    items.sort(
        key=lambda item: (
            0 if item["review_state"] == "human" else 1,
            0 if item["priority"] == "high" else 1,
            0 if item["conflict"] else 1,
            str(item["label"]).casefold(),
        )
    )
    data = {
        "schema_version": 1,
        "kind": "srwz_full_story_terminology_review",
        "summary": summary,
        "counts": dict(review_counts),
        "preprocessing_summary": preprocessing["summary"],
        "items": items,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".html.tmp")
    temporary.write_text(html_document(data), encoding="utf-8")
    temporary.replace(OUTPUT)
    print(
        f"review_items={len(items)} human={review_counts['human']} "
        f"automatic={review_counts['automatic']} conflict={review_counts['conflict']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
