"""Collect the drafts into corpus/zh/special-disc/ and write per-episode review sheets.

  python3 assemble.py [--tag full]

Outputs (all editorial_status "draft", origin names the model and prompt version):
  corpus/zh/special-disc/story-dialogue.json      剧情模式对白（含场景标签、地点字幕）
  corpus/zh/special-disc/challenge-dialogue.json  挑战模式对白
  corpus/zh/special-disc/battle-lines.json        新增战斗台词（附触发场景）
  corpus/zh/special-disc/frame-text.json          框架文字，按类别（地图图例、小队名、话名、梗概……）
  results/<tag>/review/<file>.md                  逐话审阅表：说话人、日文、初稿、补的代词、标记
"""
from __future__ import annotations

import argparse
import collections
import datetime
import glob
import hashlib
import json

from common import EXPORT, HERE, ROOT, load_json
from validate import check, genders_of

OUT = ROOT / "corpus/zh/special-disc"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def caption(jp: str, zh: str) -> str:
    """Keep a centred place caption centred: shift the source's indent by half the length change."""
    lead = len(jp) - len(jp.lstrip("　"))
    core_jp, core_zh = jp.lstrip("　"), zh.lstrip("　")
    return "　" * max(0, lead + (len(core_jp) - len(core_zh)) // 2) + core_zh


def dialogue(tag: str, kind: str) -> tuple[list[dict], dict]:
    entries, sheets = [], collections.defaultdict(list)
    for path in sorted((HERE / "batches" / kind).glob("*.json")):
        batch = load_json(path)
        result_path = HERE / "results" / tag / kind / path.name
        if not result_path.exists():
            continue
        result = load_json(result_path)
        payload = batch["payload"]
        rows = {r["id"]: r for r in payload["script"] if "id" in r}
        genders = genders_of(payload)
        origin = f"mt:{result['model']}:{result['prompt_version']}"
        file = batch["episode_file"]
        for rid, text in batch.get("auto", {}).items():
            r = rows.get(rid)
            if r:
                entries.append(dict(id=rid, episode=file, speaker=r.get("speaker"), source_text=r["jp"],
                                    source_text_sha256=sha(r["jp"]), translation=text, editorial_status="draft",
                                    origin="rule:punctuation"))
        for t in result["translations"]:
            r = rows[t["id"]]
            flags = check(batch, t, r, genders)
            text = t["text"]
            if r["kind"] == "location_caption":
                source = next(x["source"] for x in export_rows(file) if x["id"] == t["id"])
                text = caption(source, text)
                jp = source
            else:
                jp = r["jp"]
            e = dict(id=t["id"], episode=file, section=r.get("section"), kind=r["kind"], speaker=r.get("speaker"),
                     source_text=jp, source_text_sha256=sha(jp), translation=text, editorial_status="draft",
                     origin=origin)
            for k in ("addressee", "pronouns", "protagonist", "ambiguous", "confidence", "note"):
                if t.get(k) not in (None, "", [], False, "无"):
                    e[k] = t[k]
            if flags:
                e["flags"] = flags
            entries.append(e)
            sheets[file].append(e)
    return entries, sheets


_EXPORT_CACHE: dict[str, list] = {}


def export_rows(file: str) -> list[dict]:
    if file not in _EXPORT_CACHE:
        path = next(iter(glob.glob(str(EXPORT / "*" / f"{file}.json"))))
        _EXPORT_CACHE[file] = load_json(path)["sections"]["dialogue"]
    return _EXPORT_CACHE[file]


def battle(tag: str) -> list[dict]:
    triggers = {r["id"]: r for r in load_json(HERE / "battle-lines.json")}
    entries = []
    for path in sorted((HERE / "results" / tag / "battle").glob("*.json")):
        result = load_json(path)
        batch = load_json(HERE / "batches" / "battle" / path.name)
        rows = {r["id"]: r for r in batch["payload"]["lines"]}
        genders = genders_of(batch["payload"])
        for t in result["translations"]:
            row = triggers[t["id"]]
            flags = check(batch, t, rows[t["id"]], genders)
            e = dict(id=t["id"], source_text=row["jp"], source_text_sha256=row["sha256"], translation=t["text"],
                     editorial_status="draft", origin=f"mt:{result['model']}:{result['prompt_version']}",
                     voice_group=sorted({o["speaker"] for o in row["occurrences"]}),
                     speaker_guess=t.get("speaker_guess"), addressee=t.get("addressee"),
                     triggers=[dict(chunk=o["chunk"], record=o["record"], scene=o["scene"], conditions=o["conditions"])
                               for o in row["occurrences"]])
            for k in ("pronouns", "ambiguous", "confidence", "note"):
                if t.get(k) not in (None, "", [], False):
                    e[k] = t[k]
            if flags:
                e["flags"] = flags
            entries.append(e)
    return entries


FRAME_LABELS = {
    "map-legend": "地图图例（胜败条件、地图名）", "squad-name": "小队名", "episode-title": "话名",
    "speaker": "说话人名", "group-name": "剧情组名", "chart-summary": "流程图节点简介", "synopsis": "剧情梗概",
    "vt1-page": "固定格说明页（组简介、数据链接、任务简报）", "narration": "旁白", "menu": "界面文字",
    "image-label": "图片文字（待绘制）",
}


def frame(tag: str) -> list[dict]:
    entries = []
    for cat in FRAME_LABELS:
        path = HERE / "results" / tag / "frame" / f"{cat}.json"
        if not path.exists():
            continue
        for t in load_json(path)["translations"]:
            e = dict(id=t["id"], category=cat, category_label=FRAME_LABELS[cat], kind=t["kind"], locations=t["ids"],
                     source_text=t["jp"], source_text_sha256=sha(t["jp"]), translation=t["text"],
                     editorial_status="draft", origin="mt:deepseek-v4.1-flash:frame-v1" + (":manual" if t.get("manual") else ""))
            if t.get("layout") and t["layout"] != t["text"]:
                e["layout_preview"] = t["layout"]
            for k in ("limit", "note", "episode_file"):
                if t.get(k):
                    e[k] = t[k]
            if t["flags"]:
                e["flags"] = t["flags"]
            entries.append(e)
    return entries


def write(name: str, entries: list[dict], description: str) -> None:
    doc = dict(schema_version=1, description=description, generated=datetime.date.today().isoformat(),
               entry_count=len(entries), flagged_count=sum(1 for e in entries if e.get("flags")), entries=entries)
    (OUT / name).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{name}: {len(entries)} entries, {doc['flagged_count']} flagged")


def review_sheets(tag: str, sheets: dict) -> None:
    out = HERE / "results" / tag / "review"
    out.mkdir(parents=True, exist_ok=True)
    cell = lambda s: str(s or "").replace("|", "\\|").replace("\n", "⏎")  # noqa: E731
    for file, entries in sheets.items():
        lines = [f"# {file} 初稿审阅", "", f"{len(entries)} 句；标记 {sum(1 for e in entries if e.get('flags') or e.get('ambiguous'))} 句。",
                 "", "| 段 | 说话人 | 日文 | 初稿 | 补的代词 | 标记／备注 |", "|---|---|---|---|---|---|"]
        for e in entries:
            marks = list(e.get("flags", [])) + (["指代不明"] if e.get("ambiguous") else []) + \
                    ([f"主人公={e['protagonist']}"] if e.get("protagonist") else []) + ([e["note"]] if e.get("note") else [])
            lines.append(f"| {cell(e.get('section'))} | {cell(e.get('speaker'))} | {cell(e['source_text'])} "
                         f"| {cell(e['translation'])} | {cell('、'.join(e.get('pronouns', [])))} | {cell('；'.join(marks))} |")
        (out / f"{file}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def frame_sheet(tag: str, entries: list[dict]) -> None:
    cell = lambda s: str(s or "").replace("|", "\\|").replace("\n", "⏎")  # noqa: E731
    lines = ["# 框架文字初稿审阅（按类别）", ""]
    by = collections.defaultdict(list)
    for e in entries:
        by[e["category_label"]].append(e)
    for label, rows in by.items():
        lines += [f"## {label}（{len(rows)} 条）", "", "| 日文 | 初稿 | 上限 | 标记／备注 |", "|---|---|---|---|"]
        for e in rows:
            marks = list(e.get("flags", [])) + ([e["note"]] if e.get("note") else [])
            lines.append(f"| {cell(e['source_text'])} | {cell(e.get('layout_preview') or e['translation'])} "
                         f"| {cell(e.get('limit'))} | {cell('；'.join(marks))} |")
        lines.append("")
    (HERE / "results" / tag / "review" / "00-框架文字.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="full")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    story, s1 = dialogue(args.tag, "story")
    challenge, s2 = dialogue(args.tag, "challenge")
    write("story-dialogue.json", story, "特别篇剧情模式对白机翻初稿（deepseek-v4.1-flash），待审")
    write("challenge-dialogue.json", challenge, "特别篇挑战模式对白机翻初稿（deepseek-v4.1-flash），待审")
    write("battle-lines.json", battle(args.tag), "特别篇新增战斗台词机翻初稿，附触发场景与条件，待审")
    frame_entries = frame(args.tag)
    write("frame-text.json", frame_entries, "特别篇框架文字（地图图例、小队名、话名、梗概等）机翻初稿，按类别，待审")
    review_sheets(args.tag, {**s1, **s2})
    frame_sheet(args.tag, frame_entries)


if __name__ == "__main__":
    main()
