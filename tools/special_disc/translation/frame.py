"""SD frame text (everything around the dialogue), sorted by category and drafted in one pass per category.

Categories: map legends (win/loss conditions, map names), squad names, episode titles, speaker labels,
group names, flowchart summaries, synopses, group intros / Data Link / challenge briefings (VT1 fixed
pages), narration, menu strings, image labels. Each item carries its slot limit (bytes or cells) and the
episode it belongs to; each category request carries the main game's renderings of the same kind as style
examples, and the names and terms the texts use.

  python3 frame.py build          -> batches/frame/<category>.json
  python3 frame.py run [--tag T]  -> results/<T>/frame/<category>.json (+ layout and capacity checks)
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import glob
import json
import re
import sys

from api import chat, parse_json
from common import EXPORT, HERE, KANA, ROOT, CharacterSheets, load_json, relevant_terms
from terms import all_terms

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/special_disc/writeback"))
from srwz.chinese_layout import load_layout_profiles, partition_chinese_text, reflow_chinese_paragraph  # noqa: E402
from write_frame_text import flow_synopsis
from srwz.text import encode_text, normalize_original_fullwidth_ascii, two_byte_visible_spaces  # noqa: E402

PROFILES = load_layout_profiles(ROOT / "config/text-layout/zh-layout-profiles.json")
CATEGORIES = {  # category -> (Chinese label, export kinds, rule)
    "map-legend": ("地图图例：胜败条件与地图名", ("condition", "map_name"),
                   "胜败条件照正篇格式：“击坠XX。”“XX被击坠。”“敌全灭。”等，简短；原文有几行就输出几行（行间用 \\n），逐行对应。地图名简短。"),
    "squad-name": ("小队名（地图上的部队名）", ("formation_name",),
                   "小队（部队）名，简短，必须在字数上限内；组织名按术语。"),
    "episode-title": ("话名", ("episode_title", "chart_title"),
                      "话名（关卡标题）。字数不能超过上限（与日文同宽）；英文歌名、英文原文照《机战Z》正篇惯例保留英文（半角）。"),
    "speaker": ("说话人名", ("speaker",), "对话框的说话人名，简短。"),
    "group-name": ("剧情组名", ("group_name",), "五个剧情组的组名，按 terms 中已定的译名。"),
    "chart-summary": ("HSFC短简介（独立固定槽）", ("chart_summary",),
                      "HSFC短简介：独立于STAGE流程图详情长梗概，一段话排入3个固定槽，每槽最多32个全角字（66字节含结束符）。完整保留该简介的信息；段首不加空格。槽容量不代表详情窗口的显示上限。"),
    "synopsis": ("剧情梗概（资料库「剧情流程」）", ("synopsis",),
                 "本话梗概：保留原文分段，每段以一个全角空格开头，段与段之间用 \\n 分隔，段内不要换行；总字数不超过日文字数。"),
    "vt1-page": ("固定格说明页：剧情组简介、数据链接说明、挑战模式任务简报", ("vt1_page",),
                 "固定格页面：每行 28 个全角格，正文行数固定（见 limit）。保留原文分段，每段以一个全角空格开头，段与段之间用 \\n 分隔，段内不要换行；原文最后一行若是提问句（如“要游玩这段剧情吗？”），单独成段。总长度要能排进 limit 给的行数。"),
    "narration": ("开场／结尾旁白", ("narration",),
                  "旁白：保留原文分段（段首全角空格），段间用 \\n；原文的空行（只有全角空格的行）用单独的 \\n　 表示保留；段内不要换行。"),
    "menu": ("界面文字（剧情模式菜单、挑战模式、数据链接）", ("ui",),
             "界面字符串，必须在字节上限内（limit 已换算成汉字数）；原文有几行（\\n）就输出几行；原文带「」的保留为“”；原文末尾的全角空格保留。"),
    "image-label": ("图片文字（结算提示图集等，后续绘制）", ("image_text",), "图片上的短文字，简短。"),
}
KIND_TO_CATEGORY = {k: c for c, (_l, kinds, _r) in CATEGORIES.items() for k in kinds}
GROUP_OF_FILE = {}


def limit_of(r: dict) -> str | None:
    kind = r["kind"]
    if r.get("max_bytes") and kind in ("episode_title", "formation_name", "ui", "chart_title"):
        return f"最多 {(int(r['max_bytes']) - 1) // 2} 个汉字（全角字符与字母各算 1 个）"
    if kind == "vt1_page":
        rows = re.search(r"（(\d+) 行×28", r.get("location", ""))
        body = int(rows.group(1)) - (1 if r.get("heading") else 0) if rows else 8
        return f"正文最多 {body} 行，每行 28 格（段首空格占 1 格）"
    if kind == "chart_summary":
        return "不超过 60 字（3 行×21 字）"
    if kind == "synopsis":
        return f"不超过 {len(r['source'].replace(chr(10), ''))} 字"
    return None


def cells(limit: str) -> int:
    m = re.search(r"\d+", limit)
    return int(m.group()) if m else 10 ** 6


def style_examples() -> dict[str, list]:
    """The main game's renderings of the same kind, from the export rows that already have them."""
    pairs = collections.defaultdict(list)
    for folder in ("01-剧情模式", "02-挑战模式"):
        for path in sorted(glob.glob(str(EXPORT / folder / "*.json"))):
            for rows in load_json(path)["sections"].values():
                for r in rows:
                    if r.get("status") != "新译" and r.get("translation") and r["kind"] in KIND_TO_CATEGORY:
                        pairs[KIND_TO_CATEGORY[r["kind"]]].append(dict(jp=r["source"], zh=r["translation"]))
    out = {c: v[:: max(1, len(v) // 12)][:12] for c, v in pairs.items()}
    zh_only = {
        "synopsis": ROOT / "corpus/zh/menu/stage-overviews.json",
        "chart-summary": ROOT / "corpus/zh/menu/hsfc-overviews.json",
        "episode-title": ROOT / "corpus/zh/menu/stage-names.json",
    }
    for c, path in zh_only.items():
        entries = [e["translation"] for e in load_json(path)["entries"] if e.get("translation")]
        step = max(1, len(entries) // (3 if c != "episode-title" else 15))
        out.setdefault(c, []).extend(dict(zh=z) for z in entries[::step][: (3 if c != "episode-title" else 15)])
    return out


def collect() -> dict[str, list[dict]]:
    items = collections.defaultdict(dict)
    for folder in ("01-剧情模式", "02-挑战模式"):
        for path in sorted(glob.glob(str(EXPORT / folder / "*.json"))):
            doc = load_json(path)
            info = doc.get("info", {})
            meta = {r["kind"]: r["source"] for r in doc["sections"].get("meta", [])}
            for rows in doc["sections"].values():
                for r in rows:
                    if r.get("status") != "新译" or r["kind"] not in KIND_TO_CATEGORY:
                        continue
                    cat = KIND_TO_CATEGORY[r["kind"]]
                    item = items[cat].setdefault(r["source"], dict(
                        id=f"{cat}/{len(items[cat]):03d}", jp=r["source"], kind=r["kind"], ids=[], limit=limit_of(r),
                        **{k: r[k] for k in ("heading", "context", "note", "section", "category") if r.get(k)}))
                    item["ids"].append(r["id"])
                    # one text in two slots (COMPDATA title and flowchart title): the stricter limit wins
                    new = limit_of(r)
                    if new and (not item["limit"] or cells(new) < cells(item["limit"])):
                        item.update(limit=new, kind=r["kind"])
                    if doc["file"] != "00-通用":
                        item.setdefault("episode", dict(file=doc["file"], title_jp=doc["title"],
                                                        group_jp=info.get("group", "") or "挑战模式",
                                                        synopsis_jp=meta.get("synopsis") or meta.get("vt1_page", "")))
    return {c: list(v.values()) for c, v in items.items()}


def build() -> None:
    sheets = CharacterSheets()
    terms = all_terms()
    examples = style_examples()
    out_dir = HERE / "batches" / "frame"
    out_dir.mkdir(parents=True, exist_ok=True)
    for cat, items in collect().items():
        label, _kinds, rule = CATEGORIES[cat]
        texts = [i["jp"] for i in items]
        episodes = {}
        for i in items:  # the episode context once per episode, not per item
            ep = i.pop("episode", None)
            if ep:
                episodes.setdefault(ep["file"], ep)
                i["episode_file"] = ep["file"]
        if cat not in ("chart-summary", "synopsis", "vt1-page", "narration"):
            for ep in episodes.values():
                ep.pop("synopsis_jp", None)
        payload = dict(category=label, rule=rule, examples=examples.get(cat, []), episodes=list(episodes.values()),
                       mentioned=sheets.mentioned(texts, set()), terms=relevant_terms(texts, terms),
                       items=[{k: v for k, v in i.items() if k != "ids"} for i in items])
        (out_dir / f"{cat}.json").write_text(json.dumps(dict(batch_id=cat, kind="frame", items=items, payload=payload),
                                                        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(cat, len(items), "items", len(json.dumps(payload, ensure_ascii=False)), "chars")


SYSTEM = """你是《超级机器人大战Z 特别篇》的日译中本地化译者，延续正篇《超级机器人大战Z》已发布汉化的术语和文风。这次翻译的是剧情对白以外的界面与框架文字，输入是一个类别的全部条目。

输入 JSON：
- category、rule：本类别是什么、显示在哪里、格式要求（必须遵守）；
- examples：正篇同类文字的译例（有 jp 的是日中对照，只有 zh 的是正篇中文样本），照它们的格式、长度和措辞习惯；
- episodes：条目所属各话的标题、剧情组、梗概（日文），用来理解内容；
- mentioned：文字里出现的人物中文名；terms：术语，required=true 的必须原样使用，其余优先采用；
- items：待译条目。limit 是显示空间上限，必须遵守；超不过去就精简措辞，不能省掉关键信息（人名、机体名、条件）。

通用规则：
- 「」改“”，『』改‘’或《》（作品名）；省略号……，破折号——；全角标点；数字用半角阿拉伯数字（正篇习惯，如“第3回合”“013特命部队”）；
- 不得输出日文假名；
- 人名、机体名、组织名按 terms 与 mentioned；带“（新译名，暂定）”的只写括号前的名字；
- note 里写出新译名、取舍或疑点，没有就空字符串。

只输出一个 JSON 对象：{"translations":[{"id":"…","text":"…","note":""}]}，按 items 顺序每条恰好一次，id 原样照抄。"""


def encoded_length(text: str, table, story) -> int | None:
    try:
        return len(encode_text(two_byte_visible_spaces(normalize_original_fullwidth_ascii(text)), table,
                               overrides=story, terminate=True))
    except Exception:  # noqa: BLE001 - a glyph the codebook lacks
        return None


def tidy(item: dict, zh: str, table, story) -> str:
    """Deterministic clean-up: summaries are one paragraph (laid out later); conditions follow the main
    game's wording (进入第6回合。 without 的情况); padded menu strings lose trailing spaces until they fit."""
    zh = zh.replace("\\n", "\n").strip("\n") if item["kind"] != "narration" else zh.replace("\\n", "\n")
    if item["kind"] == "chart_summary":
        zh = zh.replace("\n", "").replace("\u3000", "")
    if item["kind"] in ("narration", "synopsis", "vt1_page"):
        # a line not starting with the paragraph indent continues the paragraph: rejoin copied line breaks
        out = []
        for line in zh.split("\n"):
            if out and line and not line.startswith("\u3000") and out[-1].strip("\u3000"):
                out[-1] += line
            else:
                out.append(line)
        zh = "\n".join(out)
    if item["kind"] == "condition":
        zh = zh.replace("的情况。", "。").replace("的情况", "").replace("击坠敌全灭", "使敌全灭")
    m = re.match(r"最多 (\d+) 个汉字", item.get("limit") or "")
    if m:
        cap = 2 * int(m.group(1)) + 1
        while zh.endswith("\u3000") and (encoded_length(zh, table, story) or 0) > cap:
            zh = zh[:-1]
    return zh


def checks(item: dict, zh: str, table, story, terms: list[dict]) -> tuple[list[str], str]:
    flags, laid = [], zh
    if KANA.search(zh.replace("ー", "")):
        flags.append("假名残留")
    if "「" in zh or "」" in zh:
        flags.append("日式引号")
    for t in relevant_terms([item["jp"].replace("\n", "")], terms):
        if t["required"] and t["zh"] not in zh:
            flags.append(f"术语 {t['jp']}={t['zh']}")
    n = encoded_length(zh, table, story)
    if n is None:
        flags.append("码表缺字")
    limit = item.get("limit") or ""
    m = re.match(r"最多 (\d+) 个汉字", limit)
    if m and n is not None and n > 2 * int(m.group(1)) + 1:
        flags.append(f"超出字节上限（{n}>{2 * int(m.group(1)) + 1}）")
    if item["kind"] == "condition" and zh.count("\n") != item["jp"].count("\n"):
        flags.append("条件行数不一致")
    if item["kind"] == "chart_summary":
        try:
            laid = reflow_chinese_paragraph(zh.replace("\n", ""), profile=PROFILES["sp_hsfc_summary"],
                                            exact_lines=3).text
        except Exception:  # noqa: BLE001
            flags.append("排不进 3 行×32 字")
    if item["kind"] == "synopsis":
        try:
            laid = flow_synopsis(zh)
        except ValueError as error:
            flags.append(f"流程详情排版超限：{error}")
    if item["kind"] in ("vt1_page", "narration"):
        width = {"synopsis": 29, "vt1_page": 28, "narration": 21}[item["kind"]]
        out = []
        for para in zh.split("\n"):
            if not para.strip("\u3000"):
                out.append(para)
                continue
            try:
                out.extend(partition_chinese_text(para, line_width=width, max_lines=40, line_packing="fill",
                                                  allow_oversized_token_split=True))
            except Exception:  # noqa: BLE001
                out.append(para)
                flags.append("预排失败")
        laid = "\n".join(out)
        rows = re.search(r"正文最多 (\d+) 行", limit)
        if rows and len(out) > int(rows.group(1)):
            flags.append(f"超出行数（{len(out)}>{rows.group(1)}）")
    return flags, laid


def run(tag: str) -> None:
    sys.path.insert(0, str(ROOT / "tools/special_disc/writeback"))
    import migrate_slps_text as mst
    table, _menu, story, _readback = mst.encoding_tables()
    terms = all_terms()
    out_dir = HERE / "results" / tag / "frame"
    out_dir.mkdir(parents=True, exist_ok=True)

    def one(path):
        batch = load_json(path)
        target = out_dir / path.name
        if target.exists() and not load_json(target)["missing"]:
            return load_json(target)
        payload, got, usage = batch["payload"], {}, collections.Counter()
        items = payload["items"]
        for start in range(0, len(items), 40):
            part = dict(payload, items=items[start:start + 40])
            for _attempt in range(3):
                call = chat([{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": json.dumps(part, ensure_ascii=False)}])
                usage.update(prompt=call.prompt_tokens, completion=call.completion_tokens, calls=1)
                try:
                    for t in parse_json(call.text)["translations"]:
                        if isinstance(t, dict) and t.get("text"):
                            got.setdefault(t["id"], t)
                except (ValueError, KeyError, TypeError):
                    continue
                if all(i["id"] in got for i in part["items"]):
                    break
        rows = []
        for i in batch["items"]:
            t = got.get(i["id"])
            if not t:
                continue
            text = tidy(i, t["text"], table, story)
            flags, laid = checks(i, text, table, story, terms)
            rows.append(dict(id=i["id"], ids=i["ids"], kind=i["kind"], jp=i["jp"], text=text, layout=laid,
                             limit=i.get("limit"), note=t.get("note", ""), flags=flags,
                             episode_file=i.get("episode_file")))
        result = dict(batch_id=batch["batch_id"], usage=dict(usage), translations=rows,
                      missing=[i["id"] for i in batch["items"] if i["id"] not in got])
        target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        flagged = sum(1 for r in rows if r["flags"])
        print(f"{batch['batch_id']}: {len(rows)}/{len(batch['items'])} flagged {flagged} {dict(usage)}", file=sys.stderr)
        return result

    paths = sorted((HERE / "batches" / "frame").glob("*.json"))
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        list(pool.map(one, paths))


HARD = ("假名残留", "日式引号", "术语", "超出字节上限", "条件行数不一致", "排不进", "超出行数")


def repair(tag: str) -> None:
    """Re-request flagged items with what is wrong; keep the new text when it has fewer problems."""
    import migrate_slps_text as mst
    table, _menu, story, _readback = mst.encoding_tables()
    terms = all_terms()
    for path in sorted((HERE / "results" / tag / "frame").glob("*.json")):
        result = load_json(path)
        batch = load_json(HERE / "batches" / "frame" / path.name)
        items = {i["id"]: i for i in batch["payload"]["items"]}
        bad = {t["id"]: t for t in result["translations"]
               if not t.get("manual") and any(f.startswith(HARD) for f in t["flags"])}
        if not bad:
            continue
        note = "请只重译下列条目并修正所列问题，输出格式不变，只包含这些 id：\n" + "\n".join(
            f"{i}：{'；'.join(t['flags'])}（上一稿：{t['text']}）" for i, t in bad.items())
        part = dict(batch["payload"], items=[items[i] for i in bad])
        call = chat([{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": json.dumps(part, ensure_ascii=False) + "\n\n" + note}])
        fixed = 0
        try:
            got = {t["id"]: t for t in parse_json(call.text)["translations"] if isinstance(t, dict)}
        except (ValueError, KeyError, TypeError):
            got = {}
        for row in result["translations"]:
            new = got.get(row["id"])
            if row["id"] not in bad or not new or not new.get("text"):
                continue
            text = tidy(items[row["id"]], new["text"], table, story)
            flags, laid = checks(items[row["id"]] | {"jp": row["jp"]}, text, table, story, terms)
            if sum(f.startswith(HARD) for f in flags) < sum(f.startswith(HARD) for f in row["flags"]):
                row.update(text=text, layout=laid, flags=flags, note=new.get("note", row["note"]), repaired=True)
                fixed += 1
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{path.stem}: {len(bad)} flagged, {fixed} fixed", file=sys.stderr)


def retidy(tag: str) -> None:
    """Apply tidy() and the checks again to stored drafts (after a rule change)."""
    import migrate_slps_text as mst
    table, _menu, story, _readback = mst.encoding_tables()
    terms = all_terms()
    for path in sorted((HERE / "results" / tag / "frame").glob("*.json")):
        result = load_json(path)
        items = {i["id"]: i for i in load_json(HERE / "batches" / "frame" / path.name)["payload"]["items"]}
        for row in result["translations"]:
            row["text"] = tidy(items[row["id"]], row["text"], table, story)
            row["flags"], row["layout"] = checks(items[row["id"]], row["text"], table, story, terms)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "run", "repair", "retidy"))
    parser.add_argument("--tag", default="full")
    args = parser.parse_args()
    {"build": build, "run": lambda: run(args.tag), "repair": lambda: repair(args.tag),
     "retidy": lambda: retidy(args.tag)}[args.action]()
