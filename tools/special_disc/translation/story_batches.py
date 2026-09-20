"""Cut every SD story episode / challenge mission into request batches with full scene context.

A batch is a run of whole sections (scenes) in data order with at most MAX_TODO lines to translate.
It carries: the episode frame (title, group, synopsis, chart summary), a character sheet for every
speaker in it (Chinese name, work, gender hint, library profile, main-game voice samples), the
glossary terms its Japanese contains, the last lines before it as read-only context, and the script
itself, where lines the main game already translated are shown with their fixed Chinese.

Output: batches/story/<file>-<nn>.json
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

from common import EXPORT, HERE, CharacterSheets, load_json, relevant_terms
from terms import all_terms

MAX_TODO = 80
CONTEXT_BEFORE = 12
FIXED_WINDOW = 4  # already-translated lines kept around each new line; longer fixed runs are elided
GROUP_PROTAGONIST = {"グローリー・スター　レポート": "setsuko", "ビーター・サービス　業務日誌": "rand"}
GROUP_NOTE = {
    "アナザーサイド　レコード": "新地球连邦军“013特命部队”（队长尼奥·罗阿诺克上校）追捕神秘敌人“BG”的外传，时间在正篇中期。",
    "バックストーリー　メモリー": "正篇终盘时空修复前夜，ZEUTH 队员在UN空间站回顾过往战斗的单篇故事集。",
    "グローリー・スター　レポート": "节子（荣耀之星3号）记录的作战报告，ZEUTH 一分为二后横穿加利亚大陆的那一路。",
    "ビーター・サービス　業務日誌": "梅尔记录的比特维修公司业务日志，ZEUTH 另一路在特雷佐亚技研落脚时期。",
    "シークレット　エピローグ": "正篇结局（时空修复）之后的后日谈，ZEUTH 再次集结。",
}


def episode_files(which: str) -> list[Path]:
    folder = {"story": "01-剧情模式", "challenge": "02-挑战模式"}[which]
    return sorted(Path(p) for p in glob.glob(str(EXPORT / folder / ("ep*.json" if which == "story" else "m*.json"))))


def group_intros() -> dict[str, str]:
    """The group's own introduction (VT1 chunk 40), by its heading."""
    common = load_json(EXPORT / "01-剧情模式/00-通用.json")
    return {r["heading"]: r["source"] for r in common["sections"]["intros"]}


GROUP_INTROS = group_intros()


def frame(doc: dict, which: str) -> dict:
    meta = {r["kind"]: r for r in doc["sections"]["meta"]}
    info = doc["info"]
    out = dict(file=doc["file"], title=doc["title"])
    if which == "story":
        group = info.get("group", "")
        out.update(group_jp=group, group_note=GROUP_NOTE.get(group, ""), chapter=info.get("chapter"))
        if group in GROUP_INTROS:
            out["group_intro_jp"] = GROUP_INTROS[group]
    else:
        out.update(mode="挑战模式（战斗任务，与正篇剧情无直接关联的特别战斗）", difficulty=info.get("difficulty"))
        if "vt1_page" in meta:
            out["briefing_jp"] = meta["vt1_page"]["source"]
    if "synopsis" in meta:
        out["synopsis_jp"] = meta["synopsis"]["source"]
    summaries = [r["source"] for r in doc["sections"]["meta"] if r["kind"] == "chart_summary"]
    if summaries:
        out["chart_summary_jp"] = summaries
    return out


PUNCTUATION_ONLY = re.compile(r"[「（][…！？・　—]+[」）]")


def punctuation_zh(jp: str) -> str:
    """The main game's rendering of 「………」「！」「…！」 lines: “”, and every … run as ……."""
    return re.sub(r"…+", "……", jp.replace("「", "“").replace("」", "”"))


def is_location_caption(r: dict) -> bool:
    """Centred place captions (〜イズモ艦　ブリッジ〜) stored as dialogue with a blank speaker."""
    return r["kind"] == "dialogue" and not (r.get("speaker") or "").strip() and r["source"].lstrip("　").startswith("〜")


def script_row(r: dict) -> dict:
    row = dict(id=r["id"], kind=r["kind"], section=r.get("section"), jp=r["source"])
    if r.get("speaker"):
        row["speaker"] = r["speaker"]
    if r["kind"] == "scene_label":
        row["speaker"] = "（场景标签）"
    if is_location_caption(r):
        row.update(kind="location_caption", speaker="（地点字幕）", jp=r["source"].lstrip("　"))
    if r["status"] != "新译":
        row["fixed_zh"] = r["translation"]  # the main game's reviewed Chinese; context only
    elif PUNCTUATION_ONLY.fullmatch(r["source"]):
        row["fixed_zh"] = punctuation_zh(r["source"])
        row["auto"] = True  # filled by rule, not sent for translation
    return row


def trim(script: list[dict]) -> list[dict]:
    """Drop fixed lines far from any new line; keep place labels/captions; mark each gap once."""
    todo = [n for n, r in enumerate(script) if "fixed_zh" not in r]
    keep = set()
    for n in todo:
        keep.update(range(n - FIXED_WINDOW, n + FIXED_WINDOW + 1))
    out, gap = [], 0
    for n, r in enumerate(script):
        if n in keep or r["kind"] in ("scene_label", "location_caption"):
            if gap:
                out.append(dict(kind="omitted", jp=f"（此处略去 {gap} 行已定稿台词）"))
                gap = 0
            out.append(r)
        else:
            gap += 1
    if gap:
        out.append(dict(kind="omitted", jp=f"（此处略去 {gap} 行已定稿台词）"))
    return out


def split_section(sec: list[dict]) -> list[list[dict]]:
    """A section with more new lines than MAX_TODO is cut into runs of about equal size."""
    todo = sum(1 for r in sec if r["status"] == "新译")
    if todo <= MAX_TODO:
        return [sec]
    parts = -(-todo // MAX_TODO)
    size = -(-todo // parts)
    out, cur, n = [], [], 0
    for r in sec:
        if r["status"] == "新译" and n == size:
            out.append(cur)
            cur, n = [], 0
        cur.append(r)
        n += r["status"] == "新译"
    out.append(cur)
    return out


def build(which: str, only: set[str] | None = None) -> list[Path]:
    sheets = CharacterSheets()
    terms = all_terms()
    out_dir = HERE / "batches" / which
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for path in episode_files(which):
        doc = load_json(path)
        if only and doc["file"] not in only:
            continue
        group = doc["info"].get("group", "")
        protagonist = GROUP_PROTAGONIST.get(group)
        rows, last_label = [], None
        for r in doc["sections"]["dialogue"]:
            if r["kind"] == "scene_label":  # each label is stored three times in a row
                if last_label == (r.get("section"), r["source"]):
                    continue
                last_label = (r.get("section"), r["source"])
            rows.append(r)
        # whole sections, at most MAX_TODO lines to translate per batch
        sections, current, key = [], [], None
        for r in rows:
            if (r.get("chunk"), r.get("section")) != key and current:
                sections.append(current)
                current = []
            key = (r.get("chunk"), r.get("section"))
            current.append(r)
        if current:
            sections.append(current)
        sections = [part for sec in sections for part in split_section(sec)]
        batches, batch = [], []
        for sec in sections:
            todo = sum(1 for r in batch if r["status"] == "新译")
            if batch and todo + sum(1 for r in sec if r["status"] == "新译") > MAX_TODO:
                batches.append(batch)
                batch = []
            batch.extend(sec)
        if batch:
            batches.append(batch)
        for old in out_dir.glob(f"{doc['file']}-*.json"):
            old.unlink()
        previous: list[dict] = []
        n = 0
        for batch in batches:
            full = [script_row(r) for r in batch]
            if not any("fixed_zh" not in r for r in full):
                previous = [dict(id=r["id"], speaker=r.get("speaker"), jp=r["jp"], zh=r["fixed_zh"])
                            for r in full if r["kind"] != "scene_label"]
                continue
            script = trim(full)
            labels = ("（场景标签）", "（地点字幕）")
            speakers = sorted({r["speaker"] for r in script if r.get("speaker") and r["speaker"] not in labels})
            active = {r["speaker"] for r in script if "fixed_zh" not in r and r.get("speaker")}
            texts = [r["jp"] for r in script] + [r["jp"] for r in previous]
            characters = []
            for sp in speakers:
                sheet = sheets.sheet(sp, protagonist=protagonist, partners=tuple(speakers))
                if sp not in active:  # speaks only in already-translated lines here: name and gender suffice
                    sheet = {k: sheet[k] for k in ("jp", "zh", "gender", "candidates") if k in sheet}
                characters.append(sheet)
            n += 1
            payload = dict(
                episode=frame(doc, which),
                characters=characters,
                mentioned=sheets.mentioned([r["jp"] for r in script], set(speakers)),
                terms=relevant_terms(texts + speakers, terms),
                context_before=previous[-CONTEXT_BEFORE:],
                script=script,
            )
            todo = [r["id"] for r in script if "fixed_zh" not in r and r["kind"] != "omitted"]
            auto = {r["id"]: r["fixed_zh"] for r in full if r.get("auto")}
            target = out_dir / f"{doc['file']}-{n:02d}.json"
            target.write_text(json.dumps(dict(batch_id=target.stem, kind=which, episode_file=doc["file"], index=n,
                                              todo_ids=todo, auto=auto, payload=payload),
                                         ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            written.append(target)
            previous = [dict(id=r["id"], speaker=r.get("speaker"), jp=r["jp"], **({"zh": r["fixed_zh"]} if "fixed_zh" in r else {}))
                        for r in full if r["kind"] != "scene_label"]
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("which", choices=("story", "challenge"))
    parser.add_argument("--only", action="append")
    args = parser.parse_args()
    files = build(args.which, set(args.only) if args.only else None)
    todo = sum(len(load_json(f)["todo_ids"]) for f in files)
    print(f"{len(files)} batches, {todo} lines to translate")
