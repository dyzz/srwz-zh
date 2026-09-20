"""Shared inputs for the Special Disc machine-translation drafts (story dialogue and new battle lines).

Sources, all read-only:
  - the module export (work/review/special-disc/text-export/out): SD lines, speakers, episode texts
  - corpus/glossary: the project's term registry
  - the review site data (srwz-community-web/public/data): the main game's reviewed dialogue with
    speakers and portraits, and the character library (work, profile) used for voice samples
"""
from __future__ import annotations

import collections
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "work/authoring/special-disc/translation"
SITE = ROOT.parent / "srwz-community-web" / "public" / "data"
EXPORT = ROOT / "work/review/special-disc/text-export/out"
sys.path.insert(0, str(ROOT / "tools"))

KANA = re.compile(r"[ぁ-ヿ]")
# the protagonist's portraits in the main game: which one speaks a "$n" line
SETSUKO_VISUALS = {702, 703, 704, 705, 913}
RAND_VISUALS = {713, 918}
# speaker labels that are also common nouns (the Titans pilot of GSR4, bandits, citizens)
SPEAKER_LABELS_ONLY = {"ティターンズ", "ブレーカー", "市民", "エマーン兵", "エルダー兵", "連邦軍兵", "チラム兵", "百人衆"}
NOT_NAMES = {"大尉", "中尉", "少尉", "大佐", "中佐", "少佐", "艦長", "隊長", "博士", "司令", "社長", "先生"}
PROTAGONISTS = {
    "setsuko": dict(jp="セツコ", zh="节子", full_zh="小原节子", gender="女",
                    profile="《机战Z》女主人公，荣耀之星小队的新人驾驶员（军衔少尉），驾驶巴尔戈拉。性格温和内向、认真，"
                            "说话礼貌，常用敬语，自称“我”；称上级为“队长”“中尉”。"),
    "rand": dict(jp="ランド", zh="兰德", full_zh="兰德·特拉维斯", gender="男",
                 profile="《机战Z》男主人公，流浪修理屋“比特维修公司”的社长，驾驶钢狮子。豪爽直率、江湖气重，说话粗声粗气，"
                         "自称“我”（俺），称梅尔为“梅尔”，被梅尔称作“达令”。"),
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_env() -> tuple[str, str]:
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"')
    return env["DASHSCOPE_BASE_URL"].rstrip("/"), env["DASHSCOPE_API_KEY"]


# ---------------------------------------------------------------- glossary
def glossary_terms() -> list[dict]:
    """Every registry term: source forms, the canonical Chinese, whether it is binding."""
    from srwz.glossary import global_glossary_by_id, load_global_glossary
    terms = global_glossary_by_id(load_global_glossary(ROOT / "corpus/glossary"))
    out = []
    for t in terms.values():
        sources = [s for s in t["source_terms"] if s and len(s) >= 2]
        if not sources or not t.get("translation"):
            continue
        out.append(dict(id=t["id"], sources=sources, zh=t["translation"], status=t.get("status"),
                        required=bool(t.get("enforce") and t.get("status") == "approved"
                                      and t.get("registry_match") != "explicit_only"),
                        explicit_only=t.get("registry_match") == "explicit_only",
                        category=t.get("category")))
    return out


def relevant_terms(texts: list[str], terms: list[dict], limit: int = 400) -> list[dict]:
    """Terms whose Japanese appears in the given texts, longest source first (so 強攻型アクエリオン beats アクエリオン).

    A katakana-only source must stand as a word (ガイ must not hit ガイゾック)."""
    blob = "\n".join(texts)
    hits = {}
    for t in terms:
        for s in t["sources"]:
            if s not in blob or t["explicit_only"]:
                continue
            if re.fullmatch(r"[ァ-ヺー・]+", s) and not re.search(rf"(?<![ァ-ヺー]){re.escape(s)}(?![ァ-ヺー])", blob):
                continue
            hits.setdefault((s, t["zh"]), dict(jp=s, zh=t["zh"], required=t["required"],
                                              **({"source": "正篇数据名"} if t.get("status") == "reference" else {})))
    ordered = sorted(hits.values(), key=lambda h: (-len(h["jp"]), h["jp"]))
    # drop a term that only occurs inside a longer listed one (カウンター inside ディアナ・カウンター)
    kept, reduced = [], blob
    for h in ordered:
        if h["jp"] in reduced:
            kept.append(h)
        reduced_next = reduced.replace(h["jp"], "\0")
        reduced = reduced_next
    return kept[:limit]


# ---------------------------------------------------------------- main-game dialogue (voice samples)
def main_game_dialogue() -> dict[str, list[dict]]:
    """speaker (Japanese) -> reviewed main-game lines; "$n" is split into $n@setsuko / $n@rand by portrait."""
    by_speaker = collections.defaultdict(list)
    for path in sorted(glob.glob(str(SITE / "stages/stage-*.json"))):
        for r in load_json(Path(path))["dialogues"]:
            sp = r.get("speaker") or {}
            name = sp.get("sourceText")
            if not name or not r.get("translation"):
                continue
            if name == "$n":
                visual = (sp.get("portraitEvent") or {}).get("visualId")
                name = "$n@setsuko" if visual in SETSUKO_VISUALS else "$n@rand" if visual in RAND_VISUALS else "$n"
            by_speaker[name].append(dict(jp=r["sourceText"], zh=r["translation"], status=r.get("editorialStatus"),
                                         id=r["id"]))
    return by_speaker


def voice_samples(lines: list[dict], count: int = 6, partners: tuple[str, ...] = ()) -> list[dict]:
    """Representative reviewed lines of the current Chinese release: first up to half the budget from lines
    naming someone else present in the scene (how this character addresses them), then a spread of the rest."""
    pool = [l for l in lines if l["status"] == "reviewed" and 8 <= len(l["jp"]) <= 70 and "$" not in l["jp"]]
    if len(pool) < count:
        pool = [l for l in lines if 6 <= len(l["jp"]) <= 80]
    picked, seen = [], set()

    def take(l):
        if l["jp"] not in seen and len(picked) < count:
            seen.add(l["jp"])
            picked.append(dict(jp=l["jp"], zh=l["zh"]))

    names = [p for p in partners if len(p) >= 2]
    if names:
        about = [l for l in pool if any(p in l["jp"] for p in names)]
        step = max(1, len(about) // (count // 2 or 1))
        for l in about[::step][: count // 2]:
            take(l)
    step = max(1, len(pool) // count)
    for l in pool[::step]:
        take(l)
    return picked


# ---------------------------------------------------------------- character library
def library_characters() -> dict[str, dict]:
    """Japanese name forms -> work title and the Chinese profile from the character library."""
    doc = load_json(SITE / "library/character.json")
    by_name = {}
    for e in doc["entries"]:
        fields = {f["tag"]: f for f in e["fields"]}
        desc = (fields.get("DSCR") or {}).get("translation") or ""
        info = dict(zh=e.get("title"), work=e.get("workTitle"), profile=desc[:160])
        he, she = desc.count("他"), desc.count("她")
        if she > he:
            info["gender"] = "女"
        elif he > she:
            info["gender"] = "男"
        for tag in ("CHNN", "CHFN"):
            f = fields.get(tag)
            if f and f.get("sourceText"):
                by_name.setdefault(f["sourceText"], info)
        if e.get("sourceTitle"):
            by_name.setdefault(e["sourceTitle"], info)
    return by_name


def speaker_translations() -> dict[str, str]:
    doc = load_json(ROOT / "corpus/zh/story-speakers.json")
    return {e["source_text_sha256"]: e["translation"] for e in doc["entries"] if e.get("translation")}


class CharacterSheets:
    """Builds the per-speaker context block the prompts carry."""

    def __init__(self):
        self.dialogue = main_game_dialogue()
        self.library = library_characters()
        self.speakers = speaker_translations()
        self.terms = {s: t["zh"] for t in glossary_terms() for s in t["sources"] if t["id"].startswith("people/")}
        roster = HERE / "roster.json"  # reviewed pre-pass: gender/identity/new names the library lacks
        self.roster = load_json(roster) if roster.exists() else {}
        # every name form a line may mention -> (zh, gender), for pronouns about people not in the scene
        self.names = {}
        for jp, info in self.library.items():
            if len(jp) >= 2:
                self.names[jp] = (info.get("zh"), info.get("gender"))
        for jp, zh in self.terms.items():
            if len(jp) >= 3:
                self.names.setdefault(jp, (zh, (self.library.get(jp) or {}).get("gender")))
        for jp, row in self.roster.items():
            if len(jp) >= 2 and not jp.startswith("？") and jp not in SPEAKER_LABELS_ONLY:
                self.names[jp] = (row["zh"], row["gender"])

    def zh_name(self, jp: str) -> str | None:
        row = self.roster.get(jp)
        if row and row.get("zh"):
            return row["zh"] + ("（新译名，暂定）" if row.get("zh_status") == "proposed" else "")
        return self.speakers.get(sha(jp)) or self.terms.get(jp) or (self.library.get(jp) or {}).get("zh")

    def mentioned(self, texts: list[str], exclude: set[str], limit: int = 30) -> list[dict]:
        """People named in the lines who are not speakers here: name and gender only."""
        blob = "\n".join(texts)
        hits = {}
        for jp in sorted(self.names, key=len, reverse=True):
            if jp in exclude or jp not in blob or jp in NOT_NAMES or any(jp.startswith(x) for x in exclude):
                continue
            # a katakana name must not be part of a longer katakana word (ライラ in イライラ)
            if not re.search(rf"(?<![ァ-ヺー・]){re.escape(jp)}(?![ァ-ヺー])", blob):
                continue
            zh, gender = self.names[jp]
            if not zh or any(jp in longer for longer in hits):
                continue
            hits[jp] = dict(jp=jp, zh=zh, gender=gender or "不明")
        return list(hits.values())[:limit]

    def sheet(self, jp: str, *, protagonist: str | None = None, partners: tuple[str, ...] = ()) -> dict:
        if jp == "$n":
            options = [protagonist] if protagonist else ["setsuko", "rand"]
            return dict(jp="$n", zh="$n（主人公名，保留变量）",
                        note="主人公，玩家可改名；台词里写作$n。" + (
                            "本话的主人公是：" if protagonist else "本话可能是任一位，按台词语气和在场人物判断："),
                        candidates=[dict(**{k: PROTAGONISTS[p][k] for k in ("zh", "full_zh", "gender", "profile")},
                                         voice_samples=voice_samples(self.dialogue.get(f"$n@{p}", []),
                                                                     partners=partners))
                                    for p in options])
        info = self.library.get(jp, {})
        row = self.roster.get(jp, {})
        sheet = dict(jp=jp, zh=self.zh_name(jp) or "（新角色，译名待定）")
        if info.get("work"):
            sheet["work"] = info["work"]
        if row.get("gender") or info.get("gender"):
            sheet["gender"] = row.get("gender") or info["gender"]
        if row.get("identity"):
            sheet["identity"] = row["identity"]
        if info.get("profile"):
            sheet["profile"] = info["profile"]
        samples = voice_samples(self.dialogue.get(jp, []), partners=tuple(p for p in partners if p != jp))
        if samples:
            sheet["voice_samples"] = samples
        return sheet
