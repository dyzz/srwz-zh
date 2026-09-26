"""Mechanical checks on the drafts, and a review sheet per run.

  python3 validate.py [--tag pilot]  -> results/<tag>/validation.json, results/<tag>/review.md

Checks: every todo ID answered; no kana; $-variables and <..> codes kept; quote style (“” for 「」,
（） kept); story lines have no manual breaks and fit the message window (21 cells x 3 lines,
the production story_dialogue profile shared with the main game); battle lines keep the \\n count and indent after each break; required glossary
terms used; pronouns consistent with the known genders; $n lines attributed to the group's protagonist.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys

from common import HERE, KANA, ROOT, load_json
from terms import NON_BINDING

sys.path.insert(0, str(ROOT / "tools"))
from srwz.chinese_layout import ChineseLayoutError, fit_chinese_dialogue_layout, load_layout_profiles  # noqa: E402

PROFILE = load_layout_profiles(ROOT / "config/text-layout/zh-layout-profiles.json")["story_dialogue"]
VARIABLE = re.compile(r"\$[A-Za-z]")
CODE = re.compile(r"<[^<>]+>")
GROUP_PROTAGONIST = {"グローリー・スター　レポート": "节子", "ビーター・サービス　業務日誌": "兰德"}
# Secret Epilogue: SE2 (stg_018a/b) is Setsuko's, SE3 (stg_019a/b) Rand's - the other one speaks by name there;
# SE4/SE5 switch per scene (paired Setsuko/Rand sections), judged by tone
FILE_PROTAGONIST = {"ep18-SE2-stg_018a": "节子", "ep19-SE3-stg_019a": "兰德"}


def line_terms(jp: str, terms: list[dict]) -> list[dict]:
    """Required terms in this line, ignoring a term inside a longer matched one."""
    hits = [t for t in terms if t["jp"] in jp and t["jp"] not in NON_BINDING]
    return [t for t in hits if t["required"] and not any(t["jp"] != o["jp"] and t["jp"] in o["jp"] for o in hits)]


# flags a re-request can fix; the rest are for the reviewer
HARD = ("假名残留", "变量不一致", "控制码不一致", "日式引号", "日式间隔号", "省略号不规范", "缺开引号", "独白括号丢失",
        "术语", "换行数", "换行后缺全角空格", "字幕行过长", "手工换行", "超出对话框", "主人公应为")


def hard_flags(flags: list[str]) -> list[str]:
    return [f for f in flags if f.startswith(HARD)]


def genders_of(payload: dict) -> dict[str, str]:
    genders = {c["jp"]: c.get("gender", "") for c in payload["characters"]}
    for c in payload["characters"]:
        for cand in c.get("candidates", []):
            genders[cand["zh"]] = cand["gender"]
    genders.update({m["jp"]: m["gender"] for m in payload.get("mentioned", [])})
    return genders


def check(batch: dict, item: dict, row: dict, genders: dict[str, str]) -> list[str]:
    jp, zh, flags = row["jp"], item["text"], []
    # ＜ｔｍ＞…＜／ｔｍ＞ is a runtime token (damage figure) kept verbatim
    if KANA.search(re.sub(r"＜ｔｍ＞.*?＜／ｔｍ＞", "", zh).replace("ー", "")):
        flags.append("假名残留")
    if sorted(VARIABLE.findall(jp)) != sorted(VARIABLE.findall(zh)):
        flags.append(f"变量不一致 {VARIABLE.findall(jp)}→{VARIABLE.findall(zh)}")
    if sorted(CODE.findall(jp)) != sorted(CODE.findall(zh)):
        flags.append("控制码不一致")
    if "「" in zh or "」" in zh or "『" in zh:
        flags.append("日式引号")
    if "・" in zh:
        flags.append("日式间隔号・")
    if "..." in zh or "。。" in zh:
        flags.append("省略号不规范")
    core = jp.lstrip("　")
    if core.startswith("「") and not zh.startswith("“"):
        flags.append("缺开引号")
    if core.startswith("（") and not zh.startswith("（"):
        flags.append("独白括号丢失")
    for t in line_terms(jp, batch["payload"].get("terms", [])):
        if t["zh"] not in zh:
            flags.append(f"术语 {t['jp']}={t['zh']}")
    if batch["kind"] == "battle":
        if jp.count("\\n") != zh.count("\\n"):
            flags.append(f"换行数 {jp.count(chr(92) + 'n')}→{zh.count(chr(92) + 'n')}")
        if re.search(r"\\n(?!　)", zh):
            flags.append("换行后缺全角空格")
        longest = max(len(seg.strip("“”　")) for seg in zh.split("\\n"))
        if longest > 20:
            flags.append(f"字幕行过长 {longest}字（正篇上限20）")
    else:
        if "\n" in zh or "\\n" in zh:
            flags.append("手工换行")
        if row.get("kind") == "dialogue":
            try:
                fit_chinese_dialogue_layout(zh.replace("\\n", ""), profile=PROFILE)
            except (ChineseLayoutError, AssertionError):
                flags.append("超出对话框（21字×3行）")
        if row.get("speaker") == "$n":
            group = batch["payload"]["episode"].get("group_jp", "")
            want = GROUP_PROTAGONIST.get(group) or FILE_PROTAGONIST.get(batch.get("episode_file", ""))
            if want and item.get("protagonist") != want:
                flags.append(f"主人公应为{want}")
    has = set(genders.values())
    if "她" in zh and "女" not in has:
        flags.append("用了“她”但上下文没有女性")
    if re.search(r"他(?!们|人|国|处|日|乡)", zh) and not any(g.startswith("男") for g in has):
        flags.append("用了“他”但上下文没有男性")
    return flags


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="pilot")
    args = parser.parse_args()
    base = HERE / "results" / args.tag
    report, sheet = {}, ["# SD 机翻初稿审阅表", ""]
    stats = collections.Counter()
    for kind_dir in sorted(p for p in base.iterdir() if p.is_dir() and p.name in ("story", "challenge", "battle")):
        for path in sorted(kind_dir.glob("*.json")):
            result = load_json(path)
            batch = load_json(HERE / "batches" / result["kind"] / f"{result['batch_id']}.json")
            payload = batch["payload"]
            rows = {r["id"]: r for r in payload.get("script", payload.get("lines", [])) if "id" in r}
            genders = genders_of(payload)
            sheet += [f"## {result['batch_id']}", "", "| id | 说话人 | 日文 | 初稿 | 代词 | 标记 |", "|---|---|---|---|---|---|"]
            flagged = {}
            for mid in result["missing"]:
                flagged[mid] = ["漏译"]
            for item in result["translations"]:
                row = rows[item["id"]]
                flags = check(batch, item, row, genders)
                if item.get("ambiguous"):
                    flags.append("模型标记指代不明")
                if item.get("confidence") == "low":
                    flags.append("模型低置信")
                if flags:
                    flagged[item["id"]] = flags
                stats["lines"] += 1
                stats["with_pronouns"] += bool(item.get("pronouns"))
                for f in flags:
                    stats[f.split(" ")[0]] += 1
                speaker = row.get("speaker") or "／".join(sorted({o["speaker"] for o in row.get("occurrences", [])}))
                cell = lambda s: str(s).replace("|", "\\|").replace("\n", "⏎")  # noqa: E731
                note = item.get("note") or ""
                sheet.append(f"| {item['id'].rsplit('/', 2)[-2:] if '/' in item['id'] else item['id']} | {cell(speaker)} "
                             f"| {cell(row['jp'])} | {cell(item['text'])} | {cell('、'.join(item.get('pronouns') or []))} "
                             f"| {cell('；'.join(flags + ([note] if note else [])))} |")
            sheet.append("")
            report[result["batch_id"]] = dict(flagged=flagged, usage=result["usage"], elapsed=result["elapsed"])
    (base / "validation.json").write_text(json.dumps(dict(stats=stats, batches=report), ensure_ascii=False, indent=1) + "\n",
                                          encoding="utf-8")
    (base / "review.md").write_text("\n".join(sheet) + "\n", encoding="utf-8")
    print(dict(stats))


if __name__ == "__main__":
    main()
