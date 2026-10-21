#!/usr/bin/env python3
"""Majority-and-deviation sweep of proper-noun renderings across the corpus.

For every Japanese term (glossary surface forms, maximal katakana runs and
their ・-separated parts, and Latin tokens) the sweep gathers all records
whose Japanese source contains it, finds the Chinese renderings that
co-occur with it far more often than elsewhere, picks the dominant one and
lists every record that lacks it.  A record that instead holds another
recognised rendering is an *alternative* (the 天堂基地 / 赫文斯基地 case); a
record with no recognised rendering at all is *absent* (omission, pronoun,
or a rendering the sweep did not learn).  Renderings are also tabulated per
surface and edition (main game vs Special Disc).

Japanese sources come from ``japanese_sources.py``; records are every
``corpus/zh`` entry with a translation (main) plus ``corpus/zh/special-disc``.

    python3 tools/editorial_review/term_deviation_sweep.py --jp work/review/term-sweep-20261021/jp-by-sha.json \\
        --out work/review/term-sweep-20261021/deviations.json
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from srwz.glossary import _bounded_contains, load_global_glossary, relevant_glossary_terms  # noqa: E402

CORPUS_ROOT = PROJECT_ROOT / "corpus/zh"
GLOSSARY_DIR = PROJECT_ROOT / "corpus/glossary"
KATAKANA_RUN = re.compile(r"[ァ-ヺー・]{2,}")
KANA = re.compile(r"[ぁ-ゖァ-ヺー]")
CJK = re.compile(r"[一-鿿]")
CONTROL = re.compile(r"<[A-Za-z0-9_]+:[0-9A-Fa-f]{2}>")
LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9.\-]{1,}")
VARIABLE = re.compile(r"\$[A-Za-z]+")
PARTICLES = set("的了在与和是把被从向对也都就还给让到之")
# Common loanwords: wording variance, not proper-noun inconsistency.  Hand-curated.
GENERIC_KATAKANA = set("""パーツ ユニット エネルギー バリア ステーション プレッシャー ポイント サービス サイズ タイミング マニュアル ガス オーラ
ドック アカデミー スクラップ テレビ サル コツ パーティー サングラス クロー トゲ ケラ カタパルト スイッチ エピローグ バックログ ペナント
ゲームオーバー トラウマ コンサート クローン レクチャー オプション アクション フェイズ インターミッション デモ セーブ ロード システム データ
メッセージ レベル チーム メンバー チャンス ダメージ パワー スピード タイプ モード ボタン カーソル メニュー ポーズ スタート リセット
バトル ミッション ステージ マップ エリア ターン ボーナス イベント キャラクター ストーリー シナリオ ルート チャート ライブラリー
コマンド スキル パイロット マシン ロボット メカ ビーム ミサイル ライフル キャノン ランチャー ソード ナイフ シールド アーマー""".split())
NAME_CATEGORIES = ("people", "place", "unit", "organization", "faction", "title", "group", "event", "ship", "species", "term", "concept")


def logical(text: str) -> str:
    """Visible text: no width controls, no authoring wraps or indents."""

    text = CONTROL.sub("", text).replace("\\n", "\n")
    text = re.sub(r"\n[　 ]*", "", text)
    return text.strip("　 ")


def normalized_zh(text: str) -> str:
    return unicodedata.normalize("NFKC", logical(text))


def surface_of(path: str, entry_id: str) -> str:
    if "special-disc" in path:
        return "sp:" + Path(path).stem
    if "story-dialogue/" in path:
        return "story-dialogue"
    if path.endswith("srvc-lines.json"):
        return "battle"
    if "/library/" in path:
        return "library"
    if "/menu/" in path or "/ui-atlas/" in path or "/display-names/" in path:
        return "menu:" + Path(path).stem
    return Path(path).stem


def load_records(jp_path: Path) -> list[dict]:
    japanese = json.loads(jp_path.read_text(encoding="utf-8"))
    by_sha, by_id = japanese["by_sha"], japanese["by_id"]
    records = []

    def scan(doc):
        if isinstance(doc, dict):
            if ("translation" in doc or "submitted_translation" in doc) and ("source_text_sha256" in doc or "source_text" in doc or "source" in doc):
                yield doc
                return
            for value in doc.values():
                yield from scan(value)
        elif isinstance(doc, list):
            for value in doc:
                yield from scan(value)

    for path in sorted(glob.glob(str(CORPUS_ROOT / "**/*.json"), recursive=True)):
        relative = str(Path(path).relative_to(PROJECT_ROOT))
        for entry in scan(json.loads(Path(path).read_text(encoding="utf-8"))):
            zh = entry.get("translation") or entry.get("submitted_translation")
            if not isinstance(zh, str) or not zh.strip():
                continue
            jp = entry.get("source_text") if isinstance(entry.get("source_text"), str) else None
            if jp is None and isinstance(entry.get("source"), str):
                jp = entry["source"]
            if jp is None:
                jp = by_sha.get(entry.get("source_text_sha256", "")) or by_id.get(str(entry.get("id", "")))
            if not jp:
                continue
            records.append({
                "id": str(entry.get("id", f"{relative}#{len(records)}")),
                "file": relative,
                "surface": surface_of(relative, str(entry.get("id", ""))),
                "edition": "sp" if "special-disc" in relative else "main",
                "jp": jp,
                "zh": zh,
                "zh_norm": normalized_zh(zh),
            })
    return records


def zh_candidates(zh_norm: str) -> set[str]:
    """Chinese n-grams (2..7) over CJK/middle-dot runs, plus whole Latin tokens."""

    out: set[str] = set()
    for run in re.findall(r"[一-鿿·・]+", zh_norm):
        run = run.replace("・", "·")
        for n in range(2, 8):
            for i in range(len(run) - n + 1):
                sub = run[i : i + n]
                if sub[0] != "·" and sub[-1] != "·":
                    out.add(sub)
    for token in LATIN_TOKEN.findall(zh_norm):
        if token not in {"HP", "EN", "SP", "PP", "MS", "MA", "L", "R"}:
            out.add(token)
    return out


def japanese_terms(jp: str, glossary_surfaces: set[str], glossary_by_surface: dict[str, list] | None = None) -> set[str]:
    terms: set[str] = set()
    for run in KATAKANA_RUN.findall(jp):
        if len(run.strip("ー・")) >= 2:
            terms.add(run)
            for part in run.split("・"):
                if len(part) >= 3 and part != run:
                    terms.add(part)
    normalized = unicodedata.normalize("NFKC", jp)
    for token in LATIN_TOKEN.findall(normalized):
        if len(token) >= 2:
            terms.add("latin:" + token)
    present = [surface for surface in glossary_surfaces if surface in jp]
    if present and glossary_by_surface is not None:
        candidates = [term for surface in present for term in glossary_by_surface[surface]]
        # relevant_glossary_terms applies kana boundaries and lets the longest
        # registered surface shadow a shorter one (シエロ inside デル・シエロ).
        for match in relevant_glossary_terms(jp, candidates):
            for surface in match["matched_source_terms"]:
                terms.add("gloss:" + surface)
    else:
        for surface in present:
            if _bounded_contains(jp, surface):
                terms.add("gloss:" + surface)
    return terms


def term_in(term: str, jp: str) -> bool:
    if term.startswith("latin:"):
        return term[6:] in unicodedata.normalize("NFKC", jp)
    if term.startswith("gloss:"):
        return _bounded_contains(jp, term[6:])
    for run in KATAKANA_RUN.findall(jp):
        if run == term or term in run.split("・"):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jp", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-unique", type=int, default=3, help="minimum distinct Japanese sentences for discovery")
    parser.add_argument("--dominance", type=float, default=0.5)
    args = parser.parse_args()

    glossary = load_global_glossary(GLOSSARY_DIR)
    known: dict[str, dict] = {}
    for term in glossary:
        for surface in term["source_terms"]:
            known.setdefault(str(surface), {"id": term["id"], "translation": str(term["translation"]), "deprecated": [str(d) for d in term.get("deprecated_translations", [])], "status": term.get("status"), "enforce": bool(term.get("declared_enforce", term.get("enforce")))})
    glossary_surfaces = set(known)
    glossary_by_surface: dict[str, list] = collections.defaultdict(list)
    for term in glossary:
        for surface in term["source_terms"]:
            glossary_by_surface[str(surface)].append(term)

    records = load_records(args.jp)
    # one row per distinct (jp, zh) pair; keep the record ids behind it
    pairs: dict[tuple[str, str], dict] = {}
    for record in records:
        key = (record["jp"], record["zh_norm"])
        row = pairs.setdefault(key, {"jp": record["jp"], "zh_norm": record["zh_norm"], "zh": record["zh"], "ids": [], "surfaces": collections.Counter(), "editions": collections.Counter()})
        row["ids"].append(record["id"])
        row["surfaces"][record["surface"]] += 1
        row["editions"][record["edition"]] += 1
    rows = list(pairs.values())
    candidates_by_row = [zh_candidates(row["zh_norm"]) for row in rows]
    global_df: collections.Counter = collections.Counter()
    for cands in candidates_by_row:
        global_df.update(cands)
    term_rows: dict[str, list[int]] = collections.defaultdict(list)
    for index, row in enumerate(rows):
        for term in japanese_terms(row["jp"], glossary_surfaces, glossary_by_surface):
            term_rows[term].append(index)

    findings = []
    for term, idxs in term_rows.items():
        gloss = known.get(term[6:]) if term.startswith("gloss:") else None
        distinct_jp = len({rows[i]["jp"] for i in idxs})
        if gloss is None and distinct_jp < args.min_unique:
            continue
        local_df: collections.Counter = collections.Counter()
        jp_by_cand: dict[str, set[str]] = collections.defaultdict(set)
        for i in idxs:
            local_df.update(candidates_by_row[i])
            for cand in candidates_by_row[i]:
                jp_by_cand[cand].add(rows[i]["jp"])
        n = len(idxs)
        renderings: dict[str, dict] = {}
        if gloss:
            for text in [gloss["translation"], *gloss["deprecated"]]:
                text_n = unicodedata.normalize("NFKC", logical(text))
                if text_n:
                    renderings[text_n] = {"zh": text_n, "known": "decided" if text_n == unicodedata.normalize("NFKC", logical(gloss["translation"])) else "deprecated"}
        def context_varies(cand: str) -> bool:
            """A real rendering shows up in different surroundings; a fragment of a repeated sentence never does."""
            contexts = set()
            for i in idxs:
                zh = rows[i]["zh_norm"]
                start = zh.find(cand)
                while start >= 0:
                    contexts.add((zh[start - 1] if start > 0 else "^", zh[start + len(cand)] if start + len(cand) < len(zh) else "$"))
                    start = zh.find(cand, start + 1)
                if len(contexts) > 1:
                    return True
            return len(contexts) > 1

        for cand, c in local_df.items():
            if c < 2 or c / n < 0.15 or len(jp_by_cand[cand]) < 2:
                continue
            if cand[0] in PARTICLES or cand[-1] in PARTICLES:
                continue
            if c >= 3 and not context_varies(cand):
                continue
            precision = c / global_df[cand]
            if precision < 0.5:
                continue
            renderings.setdefault(cand, {"zh": cand, "known": None})
            renderings[cand]["precision"] = round(precision, 2)
        # A shorter candidate inside a longer one is a fragment when the longer
        # form carries nearly all of its occurrences (drop the fragment); otherwise
        # the longer form is just the core plus context (drop the extension).
        for cand in sorted(list(renderings), key=len):
            if cand not in renderings or renderings[cand]["known"]:
                continue
            for other in list(renderings):
                if other == cand or cand not in other:
                    continue
                if renderings[other]["known"]:
                    del renderings[cand]
                    break
                if local_df[other] >= local_df[cand] * 0.8:
                    del renderings[cand]
                    break
                del renderings[other]
        for cand in renderings:
            renderings[cand]["lines"] = sum(1 for i in idxs if cand in rows[i]["zh_norm"])
        if not renderings:
            continue
        ordered = sorted(renderings.values(), key=lambda r: (r["known"] == "decided", r["lines"]), reverse=True)
        dominant = ordered[0]
        if gloss is None and dominant["lines"] / n < args.dominance:
            continue
        # drop renderings that are substrings of the dominant (they are the same rendering)
        others = [r for r in ordered[1:] if r["zh"] not in dominant["zh"] and dominant["zh"] not in r["zh"]]
        deviations = []
        for i in idxs:
            zh = rows[i]["zh_norm"]
            if dominant["zh"] in zh:
                continue
            alt = [r["zh"] for r in others if r["zh"] in zh]
            deviations.append({"ids": rows[i]["ids"][:6], "count": len(rows[i]["ids"]), "surfaces": dict(rows[i]["surfaces"]), "editions": dict(rows[i]["editions"]), "jp": rows[i]["jp"], "zh": rows[i]["zh"], "kind": "alternative" if alt else "absent", "alternative": alt})
        if not deviations:
            continue
        by_surface: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for i in idxs:
            zh = rows[i]["zh_norm"]
            label = dominant["zh"] if dominant["zh"] in zh else next((r["zh"] for r in others if r["zh"] in zh), "—")
            for surface, count in rows[i]["surfaces"].items():
                by_surface[surface][label] += count
        bare = term[6:] if term.startswith(("gloss:", "latin:")) else term
        findings.append({
            "term": bare,
            "kind": "glossary" if gloss else ("latin" if term.startswith("latin:") else "katakana"),
            "glossary": {k: gloss[k] for k in ("id", "status", "enforce")} if gloss else None,
            "name_like": bool(gloss and gloss["id"].split("/")[0] in NAME_CATEGORIES) or (not gloss and bare not in GENERIC_KATAKANA and not term.startswith("latin:")),
            "rows": n,
            "records": sum(len(rows[i]["ids"]) for i in idxs),
            "dominant": dominant,
            "alternatives": others,
            "alternative_deviations": sum(1 for d in deviations if d["kind"] == "alternative"),
            "absent_deviations": sum(1 for d in deviations if d["kind"] == "absent"),
            "by_surface": {s: dict(c) for s, c in sorted(by_surface.items())},
            "deviations": sorted(deviations, key=lambda d: (d["kind"] != "alternative", -d["count"]))[:60],
        })
    findings.sort(key=lambda f: (-f["alternative_deviations"], -f["absent_deviations"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"records": len(records), "rows": len(rows), "terms_examined": len(term_rows), "findings": findings}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"records {len(records)} ({len(rows)} distinct pairs); terms {len(term_rows)}; terms with deviations {len(findings)}; "
          f"with alternative renderings {sum(1 for f in findings if f['alternative_deviations'])}")
    print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
