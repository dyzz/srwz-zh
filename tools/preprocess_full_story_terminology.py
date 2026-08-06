#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pre-classify full-story terminology without changing translated corpus files.

The output is an editorial staging layer.  It deliberately keeps source evidence,
previous user decisions, automatic suggestions, and unresolved conflicts separate.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "work/review"
OUTPUT = REVIEW / "full-story-terminology"
PENDING = OUTPUT / "pending-surface-forms.tsv"
CANONICAL_MISSING = OUTPUT / "canonical-missing.tsv"
QUEUE = REVIEW / "local-model/story-dialogue-unique.jsonl"
BASELINE = REVIEW / "subtitle-sources/subtitle-terminology-baseline.json"
OUT_JSON = OUTPUT / "preprocessed-terms.json"
OUT_TSV = OUTPUT / "preprocessed-terms.tsv"
HUMAN_TSV = OUTPUT / "human-review-terms.tsv"
SUMMARY = OUTPUT / "preprocess-summary.json"

ASCII_PHRASE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*"
    r"(?:[ .'/+~:=\-]+[A-Za-z0-9]+)*(?![A-Za-z0-9])"
)

HUMAN_DISPOSITIONS = {"needs_human", "needs_human_conflict"}

UNRESOLVED_METADATA: dict[str, dict[str, str]] = {
    "angel": {
        "work": "机战Z原创",
        "category": "people",
        "preferred_translation": "Angel（身份称呼待定）",
        "rationale": "终盘由不明存在直接称呼 Angel；可确定属于机战Z原创人物/身份称呼，但缺少可靠中文定名。",
    },
    "contrism": {
        "work": "高达系列（宇宙世纪）",
        "category": "ideology",
        "preferred_translation": "Contolism / 康托利主义（待确认）",
        "rationale": "当前 Contrism 是拉丁拼写错误；日文资料对应 Contolism（コントリズム），但尚未找到可直接采用的官方简中译名。",
    },
    "tam": {
        "work": "超重神 GRAVION",
        "category": "measurement",
        "preferred_translation": "Tam克拉内尔德（能量单位，待定）",
        "rationale": "可确定是 Sol Gravion 瞬间最大能量的计量表达，不是人物或机体；中文写法缺少可靠来源。",
    },
}


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_tsv(path: Path, fieldnames: list[str], rows: Iterable[Mapping[str, object]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: str(row.get(key, "")).replace("\n", " / ") for key in fieldnames})
    temporary.replace(path)


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.casefold()


def spans(value: str) -> list[str]:
    found: list[str] = []
    for match in ASCII_PHRASE.finditer(unicodedata.normalize("NFKC", value)):
        # Six dots are a normalized Chinese ellipsis, not a connector between
        # two English names (for example "MS……Freedom").
        for fragment in re.split(r"\.{2,}", match.group(0)):
            phrase = re.sub(r"\s+", " ", fragment).strip(" .")
            if phrase and normalized(phrase) not in {"c", "n", "f"}:
                found.append(phrase)
    return found


def rule(
    rule_id: str,
    work: str,
    category: str,
    japanese: list[str],
    aliases: list[str],
    preferred: str,
    disposition: str,
    confidence: str,
    rationale: str,
    evidence: list[dict[str, str]],
    *,
    priority: str = "normal",
) -> dict[str, object]:
    return {
        "id": rule_id,
        "work": work,
        "category": category,
        "japanese_patterns": japanese,
        "aliases": aliases,
        "preferred_translation": preferred,
        "disposition": disposition,
        "confidence": confidence,
        "priority": priority,
        "rationale": rationale,
        "evidence": evidence,
    }


def local(path: str, claim: str) -> dict[str, str]:
    return {"tier": "local", "source": path, "claim": claim}


def official(url: str, claim: str) -> dict[str, str]:
    return {"tier": "official", "source": url, "claim": claim}


def wiki(url: str, claim: str) -> dict[str, str]:
    return {"tier": "wiki", "source": url, "claim": claim}


USER_PATTERNS: dict[str, list[str]] = {
    "U01": ["オーバースキル"],
    "U02": ["ビーター・サービス", "ビーターサービス"],
    "U03": ["ザ・ヒート"],
    "U04": ["ファットマン"],
    "U05": ["アクエリオンルナ"],
    "U06": ["メガデウス"],
    "U07": ["カットバックドロップターン"],
    "U08": ["リフボーダー", "リフ"],
    "U09": ["センター・フォーメーション"],
    "U10": ["オーバーマン"],
    "U11": ["キングゲイナー"],
    "U12": ["ラッシュロッド"],
    "U13": ["ザ・クラッシャー", "ザ・ヒート・クラッシャー"],
    "U14": ["シルエットエンジン"],
    "U15": ["アクエリオン"],
    "U16": ["アーキタイプ"],
    "U17": ["メモリー"],
    "U18": ["ターンエー"],
    "U19": ["LFO", "KLF", "typeZERO", "type ZERO"],
    "U20": ["ray=out"],
    "U21": ["ゴッドシグマ"],
    "U22": ["超合金ニューZ"],
    "U23": ["ボン・マルシェ"],
    "U24": ["中ボス"],
    "U25": ["ヤーパンの天井"],
    "U26": ["ホワイトドール"],
    "U27": ["キングの称号"],
    "U28": ["リスペクトです"],
    "U29": ["ドミュナス"],
    "U30": ["コマンドマシン"],
    "U31": ["シウダデス・デル・シエロ"],
    "U32": ["ボスボロット"],
    "U34": ["紅エイジ"],
    "U35": ["アトランディア"],
    "U36": ["グレートブースター"],
    "U37": ["ジェットパイルダー"],
    "U38": ["グレートタイフーン"],
    "U39": ["大尉"],
    "U40": ["ユニバーサル・ネットワーク", "UN", "ＵＮ"],
    "U41": ["VWFS"],
    "U42": ["アイラビュ"],
    "U43": ["オペレーション・クルセイド"],
    "U44": ["ザ・ストーム"],
    "U45": ["タンホイザー"],
    "U46": ["パラダイムシティ"],
    "U47": ["ジェノサイドロンシステム"],
    "U48": ["グランファントムシステム"],
}

USER_ALIASES: dict[str, list[str]] = {
    "U01": ["Over Skill", "OverSkill"],
    "U02": ["Beater Service", "BEATER SERVICE"],
    "U03": ["The Heat", "THE HEAT", "Heat", "HEAT", "The", "THE"],
    "U05": ["Aquarion Luna"],
    "U06": ["Megadeus"],
    "U07": ["Cut Back Drop Turn"],
    "U09": ["Center"],
    "U10": ["Overman"],
    "U11": ["King Gainer"],
    "U12": ["Rush Rod"],
    "U13": ["The Crusher", "THE CRUSHER", "Crusher", "CRUSHER", "The", "THE"],
    "U15": ["Aquarion"],
    "U18": ["Turn A"],
    "U19": ["LFO", "KLF", "type ZERO"],
    "U20": ["ray=out"],
    "U21": ["God Sigma"],
    "U24": ["BOSS"],
    "U26": ["White Doll"],
    "U27": ["King"],
    "U29": ["Dominus"],
    "U31": ["Ciudades del Cielo"],
    "U36": ["Great Booster"],
    "U37": ["Jet Pilder"],
    "U38": ["Great Typhoon"],
    "U40": ["UN", "Universal Network"],
    "U41": ["VWFS"],
    "U42": ["I love you", "forever", "Forever"],
    "U44": ["The Storm"],
    "U46": ["Paradigm City"],
    "U47": ["Genocide Ron System", "Genocide Ron"],
}

PREFERRED_OVERRIDES = {
    "U03": "THE HEAT",
    "U17": "记忆……Memory",
    "U19": "LFO / KLF / type ZERO",
    "U20": "ray=out",
    "U32": "波士 / 波士机器人",
    "U39": "大尉",
    "U41": "VWFS",
}


def user_rules(baseline: Mapping[str, object]) -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    for entry in baseline["terms"]:
        if not isinstance(entry, Mapping) or not entry.get("recorded_translation"):
            continue
        term_id = str(entry["id"])
        preferred = PREFERRED_OVERRIDES.get(term_id, str(entry["recorded_translation"]))
        rules.append(
            rule(
                "user-" + term_id.lower(),
                str(entry.get("work") or ""),
                str(entry.get("category") or "unclassified"),
                USER_PATTERNS.get(term_id, [str(entry["japanese"])]),
                USER_ALIASES.get(term_id, []),
                preferred,
                "locked_user",
                "locked",
                "沿用用户已经确认的 U01-U49 决定；其他证据只用于解释，不得反向覆盖。",
                [local("work/review/subtitle-sources/subtitle-terminology-baseline.json#" + term_id, "用户已确认")],
            )
        )
    return rules


def curated_rules() -> list[dict[str, object]]:
    gundam_mechanics = "https://gundaminfo.cn/series/seed/category/mechanics/"
    return [
        rule("official-logos", "高达 SEED DESTINY", "organization", ["ロゴス"], ["Logos", "LOGOS"], "LOGOS", "auto_official", "high", "官方页面以 Logos 作为固有组织名，项目说话人词表和中文 Wiki 也统一大写。", [official("https://gundaminfo.cn/series/seeddestiny/nightmare/", "官方拉丁拼写 Logos"), local("corpus/glossary/story-speakers-v1.json", "项目规范译名 LOGOS")]),
        rule("official-zeta", "机动战士Z高达", "unit", ["ゼータ"], ["Zeta"], "Z高达", "auto_official", "high", "后续机战官方简中和高达官方简中均使用 Z高达。", [official("https://srw30-thirty.suparobo.jp/sc/character/char03/", "官方作品名 机动战士Z高达"), official("https://gundaminfo.cn/content/mgka/zeta/", "官方机体名 Z高达")]),
        rule("official-freedom", "高达 SEED DESTINY", "unit", ["フリーダム"], ["Freedom"], "自由高达", "auto_official", "high", "采用高达官方简中机体名。", [official("https://gundaminfo.cn/series/seed/zgmf-x10a-freedom-gundam/", "自由高达")]),
        rule("official-justice", "高达 SEED DESTINY", "unit", ["ジャスティス"], ["Justice"], "正义高达", "auto_official", "high", "采用高达官方简中机体名。", [official(gundam_mechanics, "正义高达")]),
        rule("official-eternal", "高达 SEED DESTINY", "unit", ["エターナル"], ["Eternal"], "永恒号", "auto_official", "high", "采用高达官方简中舰名。", [official(gundam_mechanics, "永恒号")]),
        rule("official-meteor", "高达 SEED DESTINY", "unit", ["ミーティア"], ["Meteor"], "流星", "auto_official", "high", "采用高达官方简中装备名。", [official(gundam_mechanics, "流星")]),
        rule("official-g-falcon", "机动新世纪高达X", "unit", ["Gファルコン", "Ｇファルコン"], ["G Falcon", "G"], "G猎鹰", "auto_official", "high", "采用万代魂商店官方简中名称。", [official("https://tamashiiweb.com/item/10461/?dmode=pc&wovn=zh-CHS", "G猎鹰")]),
        rule("official-psycho", "高达系列", "unit", ["サイコ"], ["Psycho"], "精神感应高达", "auto_official", "high", "采用高达官方简中机体名。", [official("https://gundaminfo.cn/about-gundam/series-pages/gquuuuuux/mecha/29/", "精神感应高达")]),
        rule("conflict-destroy", "高达 SEED DESTINY", "unit", ["デストロイ"], ["Destroy"], "毁坏高达 / 毁灭高达", "needs_human_conflict", "conflict", "高达官方现行简中写“毁坏高达”，项目显示名、条件文本及中文 Wiki 长期使用“毁灭高达”；先保留冲突，不自动写回。", [official("https://gundaminfo.cn/series/seeddestiny/gfas-x1-destroy-gundam/", "毁坏高达"), local("corpus/zh/display-names/units-full.json", "项目既有 毁灭高达")], priority="high"),
        rule("wiki-requiem", "高达 SEED DESTINY", "weapon", ["レクイエム"], ["Requiem"], "镇魂曲", "auto_wiki_subtitle", "medium", "中文 Wiki/项目资料采用镇魂曲；下载字幕以 Requiem 为主，存在一处镇魂曲，故保留证据等级而非冒充官方。", [local("work/review/sources/biligame", "中文 Wiki 使用 镇魂曲"), local("work/review/subtitle-sources/gundam-seed-destiny", "字幕 Requiem 28 次、镇魂曲 1 次")]),
        rule("wiki-scab-coral", "交响诗篇", "place", ["スカブコーラル", "スカブ"], ["Scab Coral", "Scab"], "珊瑚岩", "auto_wiki_subtitle", "high", "中文 Wiki 与下载字幕的中文形态一致。", [wiki("https://zh.wikipedia.org/wiki/交响诗篇", "珊瑚岩"), local("work/review/subtitle-sources/eureka-seven/extracted-cht", "字幕稳定使用 珊瑚岩")]),
        rule("wiki-vodarak", "交响诗篇", "organization", ["ヴォダラク"], ["Vodarak"], "补陀落", "auto_wiki_subtitle", "high", "中文 Wiki 与下载字幕一致。", [wiki("https://zh.wikipedia.org/wiki/交响诗篇", "补陀落"), local("work/review/subtitle-sources/eureka-seven/extracted-cht", "字幕检出 补陀落 70 次")]),
        rule("subtitle-great-wall", "交响诗篇", "place", ["グレートウォール"], ["Great Wall"], "Great Wall", "auto_wiki_subtitle", "high", "下载字幕稳定保留英文，未发现后续官方中文冲突。", [local("work/review/subtitle-sources/eureka-seven/extracted-cht", "字幕检出 Great Wall 32 次")]),
        rule("subtitle-oratorio", "交响诗篇", "weapon", ["オラトリオ"], ["Oratorio", "Oratorio No.8"], "Oratorio", "auto_wiki_subtitle", "high", "下载字幕稳定保留英文，并以 Oratorio 8号组合。", [local("work/review/subtitle-sources/eureka-seven/extracted-cht", "字幕检出 Oratorio 8 次")]),
        rule("subtitle-compac", "交响诗篇", "technology", ["コンパク"], ["Compac Drive", "Compact", "compac"], "魂魄驱动器（短称“魂魄”）", "auto_wiki_subtitle", "medium", "字幕用魂魄驱动器，中文 Wiki 用魂魄启动器；按字幕与语义预填“驱动器”，短称需按句处理。", [wiki("https://zh.wikipedia.org/wiki/交响诗篇", "魂魄启动器"), local("work/review/subtitle-sources/eureka-seven/extracted-cht", "字幕稳定使用 魂魄驱动器")]),
        rule("project-seventh-swell", "交响诗篇", "event", ["セブンスウェル"], ["Seventh Swell"], "第七波动", "auto_project", "medium", "项目武器名已经使用第七波动；作为跨剧情统一候选。", [local("corpus/zh/menu/weapons.json", "项目既有 第七波动")]),
        rule("project-big-o", "THE Big O", "unit", ["ビッグオー"], ["Big O"], "Big O", "auto_project", "high", "项目显示名和关卡条件均稳定使用 Big O。", [local("corpus/zh/display-names/units-full.json", "项目显示名 Big O")]),
        rule("project-big-duo", "THE Big O", "unit", ["ビッグ・デュオ", "ビッグデュオ"], ["Big Duo"], "Big Duo", "auto_project", "high", "项目显示名与关卡条件一致。", [local("corpus/zh/display-names/units-full.json", "项目显示名 Big Duo")]),
        rule("project-big-fau", "THE Big O", "unit", ["ビッグファウ"], ["Big Fau"], "Big Fau", "auto_project", "high", "项目显示名与关卡条件一致。", [local("corpus/zh/display-names/units-full.json", "项目显示名 Big Fau")]),
        rule("project-the-big", "THE Big O", "unit", ["ザ・ビッグ"], ["The Big"], "The Big", "auto_project", "high", "项目结构化词表已研究并保留 The Big。", [local("corpus/glossary/story-conditions-v1.json", "项目规范 The Big")]),
        rule("project-daitarn", "无敌钢人泰坦3", "unit", ["ダイターン3", "ダイターン３"], ["Daitarn 3"], "泰坦3", "auto_project", "high", "项目显示名与中文资料一致。", [local("corpus/zh/display-names/units-full.json", "项目显示名 泰坦3")]),
        rule("project-panther", "返乡战士", "unit", ["パンサー"], ["Panther"], "豹式", "auto_project", "high", "项目显示名已有规范中文。", [local("corpus/zh/display-names/units-full.json", "项目显示名 豹式")]),
        rule("project-empelanza", "返乡战士", "unit", ["エンペランザ"], ["Empelanza"], "埃姆佩兰扎", "auto_project", "high", "项目显示名已有规范中文。", [local("corpus/zh/display-names/units-full.json", "项目显示名 埃姆佩兰扎")]),
        rule("project-dominator", "返乡战士", "unit", ["ドミネーター"], ["Dominator"], "支配者", "auto_project", "high", "项目显示名已有规范中文。", [local("corpus/zh/display-names/units-full.json", "项目显示名 支配者")]),
        rule("user-overman-battle", "返乡战士", "event", ["オーバーマンバトル"], ["Overman Battle", "King"], "超限人对战", "auto_project", "high", "沿用用户已定“超限人”和剧情中的游戏含义组合，不再单独保留英文。", [local("work/review/subtitle-sources/subtitle-terminology-baseline.json#U10", "用户已定 超限人")]),
        rule("project-schwarzvalt", "THE Big O", "people", ["シュバルツバルト"], ["Schwarzvalt"], "施瓦兹·瓦尔德", "auto_project", "high", "项目说话人短名已统一为施瓦兹，完整称号按原文补全。", [local("corpus/glossary/story-speakers-v1.json", "施瓦兹；注记完整名施瓦兹·瓦尔德")]),
        rule("project-g-bit", "机动新世纪高达X", "unit", ["Gビット", "Ｇビット"], ["G-Bit"], "G比特", "auto_project", "high", "项目显示名已有 D.O.M.E.G比特，正文短称统一为 G比特。", [local("corpus/zh/display-names/units-full.json", "项目显示名 D.O.M.E.G比特")]),
        rule("project-gundam", "高达系列", "unit", ["ガンダム"], ["Gundam"], "高达", "auto_official", "high", "采用高达官方简中系列通名。", [official("https://gundaminfo.cn/", "官方简中统一使用 高达")]),
        rule("project-gx", "机动新世纪高达X", "unit", ["GX", "ＧＸ"], ["GX"], "高达X", "auto_project", "high", "项目显示名已有高达X。", [local("corpus/zh/display-names/units-full.json", "项目显示名 高达X")]),
        rule("project-dx", "机动新世纪高达X", "unit", ["DX", "ＤＸ"], ["DX"], "高达DX", "auto_project", "high", "项目显示名已有高达DX。", [local("corpus/zh/display-names/units-full.json", "项目显示名 高达DX")]),
        rule("project-great-mazinger", "大魔神", "unit", ["グレート"], ["Great"], "大魔神", "auto_project", "medium", "该段以简称“グレート”指大魔神，按项目作品名补全。", [local("corpus/zh/display-names/units-full.json", "项目显示名 大魔神")]),
        rule("project-getter", "盖塔机器人G", "unit", ["ゲッター"], ["Getter"], "盖塔", "auto_project", "medium", "剧情中的机体系列短称，项目名称统一使用盖塔。", [local("corpus/zh/display-names/units-full.json", "项目显示名 盖塔龙/盖塔莱格/盖塔波塞冬")]),
        rule("project-getter-liger", "盖塔机器人G", "unit", ["ライガー"], ["Liger"], "盖塔莱格", "auto_project", "medium", "项目显示名已有盖塔莱格。", [local("corpus/zh/display-names/units-full.json", "项目显示名 盖塔莱格")]),
        rule("project-fixer-1", "宇宙战士巴尔迪奥斯", "unit", ["フィクサー1", "フィクサー１"], ["Fixer 1"], "菲克萨1号", "auto_project", "high", "项目显示名已有菲克萨1号。", [local("corpus/zh/display-names/units-full.json", "项目显示名 菲克萨1号")]),
        rule("project-elder", "宇宙大帝神西格玛", "faction", ["エルダー"], ["Elder"], "伊尔塔", "auto_project", "medium", "项目势力词表采用旧中文引进译名伊尔塔星人；短称同步为伊尔塔。", [local("corpus/glossary/terms-v1.json", "项目规范 伊尔塔星人")]),
        rule("wiki-pulsabane", "宇宙战士巴尔迪奥斯", "unit", ["パルサバーン"], ["Pulsabane"], "巴罗沙邦", "auto_wiki_subtitle", "medium", "RoboInfo 中日对齐资料使用巴罗沙邦，作为非官方但可追溯的中文候选。", [local("work/review/sources/robinfo-works/67-zh-TW.md", "巴罗沙邦")]),
        rule("project-geo-mirage", "超重神 GRAVION", "unit", ["Geoミラージュ", "GEOミラージュ"], ["Geo Mirage"], "Geo幻影", "auto_project", "high", "项目显示名已有 Geo幻影。", [local("corpus/zh/display-names/units-full.json", "项目显示名 Geo幻影")]),
        rule("wiki-ergo", "超重神 GRAVION", "technology", ["エルゴ"], ["Ergo"], "工学", "user_confirmed", "high", "用户确认按下载字幕统一使用“工学”；裸词不再保留 Ergo。", [local("work/review/subtitle-sources/gravion", "字幕稳定使用 工学之力 / 工学值 / 工学能源")]),
        rule("subtitle-ergo-form", "超重神 GRAVION", "technology", ["エルゴフォーム", "エルゴ・フォォォォォォム", "エルゴ・フォォォォォム", "エルゴ・フォォォォムッ", "エルゴフォオオオオオオムッ"], ["Ergo Form", "Ergo Fooooooorm"], "工学形态", "auto_wiki_subtitle", "high", "下载字幕统一译作工学形态。", [local("work/review/subtitle-sources/gravion", "字幕使用 工学形态")]),
        rule("subtitle-ergo-end", "超重神 GRAVION", "technology", ["エルゴ・エンド", "エルゴ・エェェェンド"], ["Ergo End"], "工学终结", "auto_wiki_subtitle", "high", "下载字幕统一译作工学终结。", [local("work/review/subtitle-sources/gravion", "字幕使用 工学终结")]),
        rule("subtitle-ergo-break", "超重神 GRAVION", "technology", ["エルゴブレイク"], ["Ergo Break"], "工学分解", "auto_wiki_subtitle", "high", "下载字幕对应台词使用工学分解。", [local("work/review/subtitle-sources/gravion", "字幕使用 工学分解")]),
        rule("subtitle-ergo-storm", "超重神 GRAVION", "technology", ["エルゴストォォォム"], ["Ergo Storm"], "工学风暴", "auto_wiki_subtitle", "high", "下载字幕对应台词使用工学风暴。", [local("work/review/subtitle-sources/gravion", "字幕使用 工学风暴")]),
        rule("subtitle-phantom-system", "超重神 GRAVION", "system", ["ファントムシステム"], ["Phantom System"], "幻影系统", "auto_wiki_subtitle", "medium", "字幕组用幽灵系统；为与用户已定“格兰幻影系统”保持词根一致，预处理建议用幻影系统。", [local("work/review/subtitle-sources/gravion", "字幕用 幽灵系统"), local("work/review/subtitle-sources/subtitle-terminology-baseline.json#U48", "用户已定 格兰幻影系统")]),
        rule("user-genocide-ron-short", "超重神 GRAVION", "system", ["ジェノサイドロン"], ["Genocide Ron"], "杰诺赛德隆", "auto_project", "high", "用户已定完整系统名“杰诺赛德隆系统”，裸词按同一词根处理。", [local("work/review/subtitle-sources/subtitle-terminology-baseline.json#U47", "用户已定 杰诺赛德隆系统")]),
        rule("project-aquarion-greek", "创圣的大天使", "unit", ["アルファ", "オメガ", "デルタ"], ["Alpha", "Omega", "Delta"], "阿尔法 / 欧米伽 / 德尔塔", "auto_project", "high", "项目机体显示名已经将三个形态统一音译。", [local("corpus/zh/display-names/units-full.json", "阿尔法/欧米伽/德尔塔机械天使及战机")]),
        rule("project-aquarion-vectors", "创圣的大天使", "unit", ["ベクター"], ["Vector", "Vector Alpha", "Vector Omega", "Vector Mars", "Vector Sol", "Luna"], "战机；按后缀译为太阳/火星/月亮/阿尔法/欧米伽/德尔塔战机", "auto_project", "high", "项目显示名已建立完整 Vector 机族，正文按后缀展开。", [local("corpus/zh/display-names/units-full.json", "太阳/火星/月亮/阿尔法/欧米伽/德尔塔战机")]),
        rule("subtitle-aquarion-element", "创圣的大天使", "people", ["エレメント"], ["Element"], "元素人", "auto_wiki_subtitle", "medium", "下载字幕保留 Element，中文 Wiki 的系统名使用元素；正文人物类别预填元素人。", [local("work/review/subtitle-sources/aquarion", "字幕检出 Element 118 次"), wiki("https://zh.wikipedia.org/wiki/超級機器人大戰Z", "元素系统")]),
        rule("project-aquarion-angel", "创圣的大天使", "unit", ["アクエリオンエンジェル", "アクエリオン、エンジェル"], ["Aquarion Angel", "Angel"], "天使亚库艾里翁", "auto_project", "medium", "沿用用户已定“亚库艾里翁”，并按项目显示名的形态顺序组合。", [local("work/review/subtitle-sources/subtitle-terminology-baseline.json#U15", "用户已定 亚库艾里翁"), local("corpus/zh/display-names/units-full.json", "项目显示名 天使机械天使")]),
        rule("wiki-sphere", "机战Z原创", "technology", ["スフィア"], ["Sphere"], "天体", "auto_wiki_subtitle", "high", "中文 Wiki 明确记录后续《机战30》官方中文名为“天体”。", [wiki("https://zh.wikipedia.org/wiki/超級機器人大戰Z", "天体；注明名称来自后续机战官方中文")]),
        rule("wiki-origin-law", "机战Z原创", "technology", ["オリジン・ロー"], ["Origin Law", "Origin", "Low"], "源理之力", "auto_wiki_subtitle", "high", "中文 Wiki 在同一设定条目中使用源理之力。", [wiki("https://zh.wikipedia.org/wiki/超級機器人大戰Z", "源理之力（Origin Law）")]),
        rule("project-terminus-303", "交响诗篇", "unit", ["ターミナス303", "ターミナス３０３"], ["Terminus 303"], "塔米纳斯303", "auto_project", "high", "项目显示名已有塔米纳斯303。", [local("corpus/zh/display-names/units-full.json", "项目显示名 塔米纳斯303")]),
        rule("wiki-devil-fish", "交响诗篇", "unit", ["デビルフィッシュ"], ["Devil Fish"], "魔鬼鱼", "auto_wiki_subtitle", "high", "中文 Wiki 使用 B303 魔鬼鱼。", [wiki("https://zh.wikipedia.org/wiki/交响诗篇", "B303 魔鬼鱼")]),
        rule("project-the-end", "交响诗篇", "unit", ["ジ・エンド"], ["The End"], "尼尔瓦修终式", "user_confirmed", "high", "用户确认统一采用尼尔瓦修终式。", [local("work/review/full-story-terminology/imported-decisions.json", "用户定稿 尼尔瓦修终式")]),
        rule("project-spec2", "交响诗篇", "unit", ["スペック2", "スペック２"], ["Spec2"], "spec2", "auto_project", "high", "项目显示名使用小写 spec2。", [local("corpus/zh/display-names/units-full.json", "项目显示名 尼尔瓦修 spec2")]),
        rule("ui-library", "超级机器人大战 Z 系统", "system", ["LIBRARY", "Q&A", "Q＆A"], ["LIBRARY", "A", "Q", "RPG"], "LIBRARY / Q&A / RPG", "auto_retain_ui", "high", "界面标签和通用缩写不进入术语人工队列。", [local("work/review/full-story-terminology/pending-surface-forms.tsv", "游戏教学上下文")]),
        rule("ui-rpg", "超级机器人大战 Z 系统", "system", ["ロールプレイングゲーム"], ["RPG"], "RPG", "auto_retain_ui", "high", "通用类型缩写，不进入专名校对。", [local("work/review/full-story-terminology/pending-surface-forms.tsv", "普通名词上下文")]),
        rule("ui-difficulty", "超级机器人大战 Z 系统", "system", ["イージー", "ノーマル", "ハード"], ["Easy", "Normal", "Hard"], "简单 / 普通 / 困难", "auto_project", "high", "难度名直接按界面语义统一中文。", [local("work/review/full-story-terminology/pending-surface-forms.tsv", "难度教学上下文")]),
        rule("wiki-cosmic-era", "高达 SEED DESTINY", "era", ["コズミックイラ"], ["Cosmic Era"], "C.E.纪元（宇宙历）", "auto_wiki_subtitle", "medium", "中文高达 Wiki 索引使用 C.E.纪元/宇宙历，避免机器稿裸留 Cosmic Era。", [local("work/review/sources/biligame/indexes/E5_85_A8_E6_9C_BA_E4_BD_93_E8_B5_84_E6_96_99__wiki.biligame.com.md", "C.E.纪元（宇宙历——Cosmic Era）")]),
        rule("project-side", "高达系列", "place", ["サイド1", "サイド１", "サイド7", "サイド７"], ["Side 1", "Side1", "Side 7"], "Side 1 / Side 7", "auto_project", "high", "项目世界史已使用 Side + 空格 + 编号，统一格式即可。", [local("corpus/zh/summary.json", "项目既有 Side 3")]),
        rule("project-turn-x-short", "∀高达", "unit", ["ターンX", "ターンＸ"], ["X"], "倒X", "auto_project", "high", "项目显示名已有倒X。", [local("corpus/zh/display-names/units-full.json", "项目显示名 倒X")]),
        rule("project-paradigm-company", "THE Big O", "organization", ["パラダイム社"], ["Paradigm"], "帕拉达伊姆公司", "auto_project", "high", "沿用用户已定帕拉达伊姆城的词根。", [local("work/review/subtitle-sources/subtitle-terminology-baseline.json#U46", "用户已定 帕拉达伊姆城")]),
        rule("project-big-o-weapons", "THE Big O", "weapon", ["Oサンダー", "Ｏサンダー", "プラズマギミック"], ["O Thunder", "Plasma Gimmick"], "O雷霆 / 等离子机关", "auto_project", "medium", "项目武器词表已有两项中文候选。", [local("corpus/glossary/weapons-v1.json", "O雷霆 / 等离子机关")]),
        rule("project-kids-munto", "返乡战士", "people", ["キッズ・ムント"], ["Kids Munto"], "基兹·蒙特", "auto_project", "medium", "项目说话人短名已统一为基兹，完整姓名按原文补全。", [local("corpus/glossary/story-speakers-v1.json", "项目短名 基兹")]),
        rule("wiki-silhouette-machine", "返乡战士", "unit", ["シルエットマシン"], ["Silhouette Machine"], "剪影机 / 轮廓驱动器", "needs_human_conflict", "conflict", "下载字幕沿用英文，中文 Wiki 写轮廓驱动器；用户确认的“剪影引擎”仅对应シルエットエンジン，不能直接套用到机体类别。", [wiki("https://zh.wikipedia.org/wiki/帝皇戰紀", "轮廓驱动器"), local("work/review/subtitle-sources/king-gainer", "字幕保留 Silhouette Machine")], priority="high"),
        rule("project-garia", "战斗机甲萨芬格尔", "unit", ["ギャリア"], ["Garia", "Gallia"], "伽利亚", "user_confirmed", "high", "用户确认按下载字幕采用伽利亚；字幕第26集还明确注明 GALLIA 统一译为伽利亚。", [local("work/review/subtitle-sources/xabungle", "第26集字幕注记：GALLIA 统一译为伽利亚")]),
        rule("project-walker-garia", "战斗机甲萨芬格尔", "unit", ["ウォーカー・ギャリア", "ウォーカーギャリア"], ["Walker Gallia"], "沃克·伽利亚", "user_confirmed", "high", "完整机体名沿用既有沃克前缀，并按用户确认将ギャリア定为伽利亚。", [local("corpus/zh/display-names/units-full.json", "项目完整机体显示名")]),
        rule("project-gear-gear", "战斗机甲萨芬格尔", "unit", ["ギア・ギア"], ["Gear Gear"], "基亚·基亚", "auto_project", "high", "项目显示名已有规范中文。", [local("corpus/zh/display-names/units-full.json", "项目显示名 基亚·基亚")]),
        rule("project-doran", "战斗机甲萨芬格尔", "unit", ["ドラン"], ["Doran"], "多兰", "auto_project", "high", "项目显示名已有规范中文。", [local("corpus/zh/display-names/units-full.json", "项目显示名 多兰")]),
        rule("subtitle-zola", "战斗机甲萨芬格尔", "place", ["ゾラ"], ["Zola"], "佐拉", "auto_wiki_subtitle", "high", "下载字幕稳定使用佐拉。", [local("work/review/subtitle-sources/xabungle", "字幕检出 佐拉 47 次")]),
        rule("subtitle-buffalo", "战斗机甲萨芬格尔", "unit", ["バッファロー"], ["Buffalo"], "水牛", "auto_wiki_subtitle", "high", "下载字幕与项目显示名一致。", [local("work/review/subtitle-sources/xabungle", "字幕检出 水牛 10 次"), local("corpus/zh/display-names/units-full.json", "项目显示名 水牛")]),
        rule("conflict-trad-11", "战斗机甲萨芬格尔", "unit", ["トラッド11", "トラッド１１"], ["Trad 11"], "特拉德11 / 特拉多11", "needs_human_conflict", "conflict", "项目显示名为特拉德11，下载字幕为特拉多11；两者只差尾音，交给人工一次性定稿。", [local("corpus/zh/display-names/units-full.json", "项目显示名 特拉德11"), local("work/review/subtitle-sources/xabungle", "字幕使用 特拉多11")], priority="high"),
        rule("project-walker-machine", "战斗机甲萨芬格尔", "unit", ["ウォーカーマシン"], ["Walker Machine"], "WM", "user_confirmed", "high", "用户确认剧情与战斗台词使用字幕组后续稳定采用的简称 WM；设定说明首次出现可写 Walker Machine（WM）。", [local("work/review/subtitle-sources/xabungle", "第1集首次写 Walker Machine (WM)，后续大量使用 WM")]),
        rule("user-ji-edel", "超级机器人大战Z原创", "people", ["ジ・エーデル・ベルナル", "ジ・エーデル"], ["The Edel Bernal", "The Edel"], "极·艾岱尔·贝鲁那尔 / 极·艾岱尔", "user_confirmed", "high", "用户确认完整姓名为极·艾岱尔·贝鲁那尔，简称极·艾岱尔；普通エーデル・ベルナル不在本规则范围。", [local("work/review/full-story-terminology/user-decision-overrides.json", "用户定稿")]),
        rule("project-god-gravion", "超重神 GRAVION", "unit", ["ゴッドグラヴィオン"], ["God Gravion"], "God Gravion", "auto_project", "medium", "项目结构化机体词表已研究并保留英文。", [local("corpus/glossary/story-conditions-v1.json", "项目规范 God Gravion")]),
        rule("project-sol-gravion", "超重神 GRAVION", "unit", ["ソルグラヴィオン"], ["Sol Gravion"], "Sol Gravion", "auto_project", "medium", "项目结构化机体词表已存在。", [local("corpus/glossary/story-conditions-v1.json", "项目规范 Sol Gravion")]),
        rule("project-ms", "高达系列", "system", ["モビルスーツ"], ["MS"], "MS", "auto_official", "high", "后续机战官方简中正文直接使用 MS。", [official("https://srw30-thirty.suparobo.jp/sc/character/char05/", "官方正文使用 MS")]),
        rule("project-dome", "机动新世纪高达X", "technology", ["D.O.M.E", "D.O.M.E."], ["D.O.M.E"], "D.O.M.E.", "auto_project", "high", "项目研究词表使用带末点的官方拉丁写法。", [local("corpus/glossary/story-conditions-v1.json", "项目规范 D.O.M.E.")]),
        rule("project-plant", "高达 SEED DESTINY", "organization", ["プラント"], ["PLANT"], "PLANT", "auto_project", "high", "项目组织词表已保留官方缩写。", [local("corpus/glossary/story-conditions-v1.json", "项目规范 PLANT")]),
        rule("project-zaft", "高达 SEED DESTINY", "organization", ["ザフト"], ["ZAFT"], "ZAFT", "auto_project", "high", "项目组织词表已保留官方缩写。", [local("corpus/glossary/story-conditions-v1.json", "项目规范 ZAFT")]),
        rule("subtitle-big-wing", "宇宙大帝神西格玛", "unit", ["ビッグウイング"], ["Big Wing"], "巨神飞翼", "auto_wiki_subtitle", "medium", "中文对齐资料把神西格玛的合体无人战机译作巨神飞翼；日文资料也确认其机体性质。", [local("work/review/sources/robinfo-works/66-zh-TW.md", "巨神飞翼（ビッグウイング）"), local("work/review/sources/robinfo-works/66-ja.md", "神西格玛合体用无人战斗机")]),
        rule("source-black-doll", "机战Z原创", "unit", ["ブラックドール"], ["Black Doll"], "黑色人偶", "auto_project", "medium", "此处指黑色复制机军团，下一句原文直接换称“黒い人形”，按同段语义统一为黑色人偶。", [local("work/review/local-model/story-dialogue-unique.jsonl#140:120", "同段语义为黒い人形")]),
        rule("subtitle-cpc", "高达 SEED DESTINY", "system", ["CPC", "ＣＰＣ"], ["CPC"], "CPC", "auto_wiki_subtitle", "high", "下载的异域-11番小队/POPGO-FREEWIND 简中字幕在同一启动台词中原样保留 CPC。", [local("work/review/subtitle-sources/gundam-seed-destiny/extracted", "CPC设定完成")]),
        rule("subtitle-diva", "超重神 GRAVION", "technology", ["ディーヴァ"], ["Diva"], "女神", "auto_wiki_subtitle", "medium", "下载字幕在对应台词和标题中把 Diva 处理为女神；这里不是人物名。", [local("work/review/subtitle-sources/gravion/supplemental/zwei/extracted", "对应台词使用 女神；标题注明ディーヴァ")]),
        rule("source-final-together", "THE Big O", "system", ["ファイナル・トゥギャザー"], ["Final Together"], "Final Together", "auto_project", "medium", "贝克大胜利 RX3 的戏仿式合体口令，作为刻意英语口号保留。", [local("work/review/full-story-terminology/pending-surface-forms.tsv", "单次合体口令上下文")]),
        rule("conflict-fire-great-gravion", "超重神 GRAVION", "unit", ["ファイア", "グレートグラヴィオン"], ["Fire", "Great Gravion"], "火焰……不，是 Great Gravion 吗！", "needs_human", "unresolved", "角色先说 Fire、再误认成 Great Gravion，下一句才由桑德曼订正为 Sol Gravion；建议按误认台词原样翻译，不把两词登记成正式机体名。", [local("work/review/local-model/story-dialogue-unique.jsonl#107:242", "误认后被下一句订正为 Sol Gravion")]),
        rule("source-g-soldier", "超重神 GRAVION", "organization", ["Gソルジャー隊", "Ｇソルジャー隊"], ["G-Soldier"], "G-Soldier队", "auto_project", "medium", "万代频道日文官方页确认它是量产型 Gravion 的驾驶员队伍；未找到官方中文，暂保留拉丁写法。", [official("https://www.b-ch.com/titles/297/?ttl_c=297", "Gソルジャー隊是量产型グラヴィオン搭乘队伍")]),
        rule("wiki-mountain-cycle", "∀高达", "place", ["マウンテン・サイクル", "マウンテンサイクル"], ["Mountain Cycle"], "环形山", "auto_wiki_subtitle", "medium", "中文 Wiki 使用环形山；下载字幕常按句译作环状山或山脉，作为设定名预填环形山。", [wiki("https://zh.wikipedia.org/wiki/黑历史", "マウンテンサイクル写作环形山"), local("work/review/subtitle-sources/turn-a-gundam/extracted", "字幕出现环状山/山脉等语境译法")]),
        rule("subtitle-sand-rat", "战斗机甲萨芬格尔", "organization", ["サンドラット"], ["Sand Rat"], "沙漠老鼠", "auto_wiki_subtitle", "high", "下载的全套字幕在拉格及团体语境中稳定使用沙漠老鼠。", [local("work/review/subtitle-sources/xabungle/extracted", "字幕多集稳定使用 沙漠老鼠")]),
        rule("subtitle-shining-finger", "∀高达", "weapon", ["シャイニングフィンガー"], ["Shining Finger"], "Shining Finger", "auto_wiki_subtitle", "high", "下载字幕在 Turn X 对应台词中保留 Shining Finger。", [local("work/review/subtitle-sources/turn-a-gundam/extracted/[VCB-Studio] Turn A Gundam [45][Ma10p_1080p][x265_flac].chs.ass", "这就是Shining Finger啊")]),
        rule("user-silhouette-mammoth", "返乡战士", "unit", ["シルエットマンモス", "シルエット・マンモス"], ["Silhouette Mammoth"], "剪影猛犸", "auto_project", "medium", "日文官方网站确认这是牵引都市单元的大型剪影引擎；词根沿用用户已定的剪影引擎。", [official("https://www.king-gainer.net/world/words.html", "大型シルエット・エンジン称为シルエット・マンモス"), local("work/review/subtitle-sources/subtitle-terminology-baseline.json#U14", "用户已定 剪影引擎")]),
        rule("project-formations", "超级机器人大战 Z 系统", "system", ["トライ・フォーメーション", "ワイド・フォーメーション"], ["TRI", "Wide"], "TRI队形 / Wide队形", "auto_project", "high", "项目结构化词表已经分别规定 TRI队形 与 Wide队形；Center 另沿用用户 U09 的中央队形。", [local("corpus/glossary/terms-v1.json", "项目规范 TRI队形 / Wide队形"), local("work/review/subtitle-sources/subtitle-terminology-baseline.json#U09", "用户已定 中央队形")]),
        rule("source-turn-type", "∀高达", "unit", ["ターンタイプ", "ターン・タイプ"], ["Turn Type"], "Turn Type", "auto_project", "medium", "官方日文资料把 ∀高达与 Turn X 归为 Turn Type；当前中文资料也常直接保留该分类名。", [official("https://www.gundam.info/news/publications/01_4014.html", "Turn X 是ターンタイプ之一"), official("https://www.turn-a-gundam.net/story/43.html", "官方剧情页使用ターン・タイプ")]),
        rule("wiki-zonda-epta", "机动新世纪高达X", "place", ["ゾンダーエプタ"], ["Zonder Epta"], "佐达·艾普塔", "auto_wiki_subtitle", "medium", "当前机器稿把官方拉丁拼写 Zonda 写成 Zonder；中文资料使用佐达·艾普塔，先纠正拼写并预填中文。", [wiki("https://gundam.wiki.cre.jp/wiki/ゾンダーエプタ", "拉丁拼写 Zonda Epta，人工岛"), local("work/review/sources", "中文资料使用 佐达·艾普塔")]),
        rule("ui-controls", "超级机器人大战 Z 系统", "system", ["START", "SELECT", "HELP", "R1", "R2", "L1", "L2", "スタート", "セレクト"], ["START", "Start", "SELECT", "Select", "HELP", "R1", "R2", "L1", "L2"], "沿用按键标记大写", "auto_retain_ui", "high", "这些是实体按键或界面标签，不是待翻译专名；统一大写即可。", [local("work/review/full-story-terminology/pending-surface-forms.tsv", "游戏教学上下文")]),
        rule("ui-weapon-tags", "超级机器人大战 Z 系统", "system", ["PLA", "ALL", "TRI", "DVE", "SRポイント"], ["PLA", "ALL", "TRI", "DVE", "SR"], "保留 PLA / ALL / TRI / DVE / SR", "auto_retain_ui", "high", "游戏内属性、事件及点数缩写，统一大写。", [local("work/review/full-story-terminology/pending-surface-forms.tsv", "游戏教学上下文")]),
        rule("ui-lesson", "超级机器人大战 Z 系统", "system", ["LESSON"], ["LESSON", "LESSON1", "LESSON2", "LESSON3"], "LESSON + 编号", "auto_retain_ui", "high", "教学章节标题保留原界面标签并统一编号格式。", [local("work/review/full-story-terminology/pending-surface-forms.tsv", "教学章节标签")]),
        rule("style-catchphrases", "多作品", "style", ["イエス", "イエ", "プリーズ", "グッバ", "アウチ", "サンキュー", "アイ・キャン", "アーイ・キャーン", "レッツゴー", "ハッピーエンド", "ショータイム", "アクション", "アァァクション", "フォーエバー", "アイラブミー", "アイラブミ", "メタル", "ノンノン", "コスプレ", "こすぷれ", "GUY", "ヒートスマイル", "マグナモード", "ミスター・オーバーヒート", "イッツ・グランドフィナーレ", "CIVELIA", "SIBERIA", "キングゲイナー♪"], ["Yes", "babies", "Please", "Goodbye", "Ouch", "Thank you very much", "THANK YOU VERY MUCHO", "I", "CAN", "I CAN FLY", "FLYYYYYYYY", "LET", "LET'S GO", "S GO", "Happy Ending", "Show Time", "Action", "Actiooon", "forever", "Forever", "I love me", "Metal", "Over", "Man", "Metal~O~ver~man", "Metal~Over~Man", "King~King~King Gainer", "Non non", "Cosplay", "GUY", "HEAT SMILE", "MAGNA", "Mr.Overheat", "It's Grand Finale", "CIVELIA", "SIBERIA"], "非术语：转入台词风格校对", "ignore_style", "high", "口头禅、英文感叹、歌词片段、拼写笑话和拟声不是术语表条目；从术语人工队列移除，但保留行号供后续台词风格审校。", [local("work/review/full-story-terminology/pending-surface-forms.tsv", "逐句上下文判定")]),
    ]


def source_matches(rule_row: Mapping[str, object], source: str) -> bool:
    haystack = unicodedata.normalize("NFKC", source)
    return any(unicodedata.normalize("NFKC", value) in haystack for value in rule_row["japanese_patterns"])


def occurrence_matches(rule_row: Mapping[str, object], phrase: str, source: str) -> bool:
    if not source_matches(rule_row, source):
        return False
    aliases = {normalized(value) for value in rule_row["aliases"]}
    return not aliases or normalized(phrase) in aliases


def make_examples(rows: list[dict[str, object]], limit: int = 5) -> list[dict[str, object]]:
    seen: set[tuple[int, int]] = set()
    examples: list[dict[str, object]] = []
    for row in rows:
        key = int(row["stage_index"]), int(row["unique_index"])
        if key in seen:
            continue
        seen.add(key)
        examples.append(
            {
                "key": f"{key[0]:03d}:{key[1]}",
                "source": row["source_text"],
                "translation": row["current_translation"],
                "before": row.get("context_before_source") or None,
                "after": row.get("context_after_source") or None,
            }
        )
        if len(examples) >= limit:
            break
    return examples


def concept_items(
    pending: list[dict[str, str]],
    queue: Mapping[tuple[int, int], Mapping[str, object]],
    rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    assigned: dict[str, list[dict[str, object]]] = defaultdict(list)
    unmatched: list[dict[str, object]] = []
    for row in pending:
        key = int(row["stage_index"]), int(row["unique_index"])
        source = str(row["source_text"])
        extracted = spans(str(row["current_translation"]))
        if not extracted:
            continue
        for phrase in extracted:
            matches = [candidate for candidate in rules if occurrence_matches(candidate, phrase, source)]
            if matches:
                # A specific user decision always wins; otherwise the first curated rule is deterministic.
                matches.sort(key=lambda value: 0 if value["disposition"] == "locked_user" else 1)
                selected = matches[0]
                assigned[str(selected["id"])].append({**row, "observed_phrase": phrase, "occurrence_count": int(queue[key]["occurrence_count"])})
            else:
                unmatched.append({**row, "observed_phrase": phrase, "occurrence_count": int(queue[key]["occurrence_count"])})

    items: list[dict[str, object]] = []
    for candidate in rules:
        rows = assigned.get(str(candidate["id"]), [])
        if not rows:
            continue
        unique_keys = {(int(row["stage_index"]), int(row["unique_index"])) for row in rows}
        expanded = sum(
            int(queue[key]["occurrence_count"])
            for key in unique_keys
        )
        item = dict(candidate)
        item.update(
            {
                "id": "P:" + str(candidate["id"]),
                "item_type": "preprocessed",
                "source_terms": list(candidate["japanese_patterns"]),
                "observed_forms": dict(Counter(str(row["observed_phrase"]) for row in rows).most_common()),
                "usage": {
                    "unique_rows": len(unique_keys),
                    "expanded_occurrences": expanded,
                    "stage_count": len({key[0] for key in unique_keys}),
                },
                "examples": make_examples(rows),
                "seeded_decision": None
                if candidate["disposition"] in HUMAN_DISPOSITIONS
                else {
                    "action": "accept",
                    "chosen_translation": candidate["preferred_translation"],
                    "custom_translation": "",
                    "note": "",
                    "seeded_from": candidate["disposition"],
                },
            }
        )
        items.append(item)

    by_phrase: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in unmatched:
        by_phrase[normalized(str(row["observed_phrase"]))].append(row)
    for key, rows in by_phrase.items():
        forms = Counter(str(row["observed_phrase"]) for row in rows)
        unique_keys = {(int(row["stage_index"]), int(row["unique_index"])) for row in rows}
        label = forms.most_common(1)[0][0]
        metadata = UNRESOLVED_METADATA.get(key, {})
        japanese = Counter()
        for row in rows:
            japanese.update(re.findall(r"[ァ-ヿー・＝]{2,}", unicodedata.normalize("NFKC", str(row["source_text"]))))
        items.append(
            {
                "id": "P:unresolved-" + re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:80],
                "item_type": "preprocessed",
                "work": metadata.get("work", "待关联"),
                "category": metadata.get("category", "unclassified"),
                "source_terms": [term for term, _ in japanese.most_common(6)],
                "japanese_patterns": [term for term, _ in japanese.most_common(6)],
                "observed_forms": dict(forms.most_common()),
                "aliases": list(forms),
                "preferred_translation": metadata.get("preferred_translation", label),
                "disposition": "needs_human",
                "confidence": "unresolved",
                "priority": "high" if len(unique_keys) >= 5 else "normal",
                "rationale": metadata.get("rationale", "尚未被用户决定、官方中文、中文 Wiki、下载字幕或项目规范词表可靠覆盖。"),
                "evidence": [local("work/review/full-story-terminology/pending-surface-forms.tsv", "当前机器稿表面写法")],
                "usage": {
                    "unique_rows": len(unique_keys),
                    "expanded_occurrences": sum(int(queue[row_key]["occurrence_count"]) for row_key in unique_keys),
                    "stage_count": len({row_key[0] for row_key in unique_keys}),
                },
                "examples": make_examples(rows),
                "seeded_decision": None,
            }
        )
    return items, unmatched


CANONICAL_CLASSIFICATION = {
    "people/kira": ("false_positive", "基拉的日文短词在“キラー・ザ・ブッチャー”中发生子串误命中。"),
    "system/turn": ("false_positive", "ターン在ティターンズ中发生子串误命中；这些行不是回合数。"),
    "skill/guard": ("false_positive", "剧情中的ガード是保镖，不是技能“防护”。"),
    "system/evasion": ("false_positive", "剧情中的回避是普通动词“避免”，不是战斗数值。"),
    "skill/commander": ("false_positive", "指揮官機是指挥机，不是技能名“指挥官”。"),
    "people/killer-the-butcher": ("auto_project", "仅为中文间隔号格式差异，人物识别和译名没有冲突。"),
    "people/spacenoid": ("needs_human_conflict", "后续机战官方简中同时按语境使用“宇宙居民/宇宙移民”；当前词表强制单一形式过严。"),
    "people/speaker-238791253f52": ("needs_human_conflict", "项目规范为“捷利特”，机器稿出现“杰利特”；未找到可直接覆盖本项目的后续官方角色表。"),
    "place/space-colony": ("needs_human", "“宇宙殖民卫星”是描述性异译，是否统一成“宇宙殖民地”需结合句意。"),
    "system/bogey-one": ("needs_human", "机器稿误译成黑方/白方，属于正文错误而非一般术语异体。"),
}

CANONICAL_WORKS = {
    "people/spacenoid": "高达系列（宇宙世纪）",
    "people/speaker-238791253f52": "机动战士Z高达",
    "place/space-colony": "高达系列",
    "system/bogey-one": "高达 SEED DESTINY",
}


def canonical_items(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in rows:
        disposition, rationale = CANONICAL_CLASSIFICATION[row["term_id"]]
        result.append(
            {
                "id": "C:" + row["term_id"],
                "item_type": "canonical_missing",
                "work": CANONICAL_WORKS.get(row["term_id"], "项目结构化词表"),
                "category": row["category"],
                "source_terms": [value.strip() for value in row["source_terms"].split(" | ")],
                "observed_forms": {},
                "preferred_translation": row["canonical_translation"],
                "disposition": disposition,
                "confidence": "high" if disposition == "false_positive" else "conflict",
                "priority": "high" if disposition in HUMAN_DISPOSITIONS else "normal",
                "rationale": rationale,
                "evidence": [local("work/review/full-story-terminology/canonical-missing.tsv", row["canonical_missing_examples"])],
                "usage": {
                    "unique_rows": int(row["canonical_missing_unique_rows"]),
                    "expanded_occurrences": int(row["canonical_missing_unique_rows"]),
                    "stage_count": 1,
                },
                "examples": [],
                "seeded_decision": None
                if disposition in HUMAN_DISPOSITIONS
                else {
                    "action": "accept",
                    "chosen_translation": row["canonical_translation"],
                    "custom_translation": "",
                    "note": "",
                    "seeded_from": disposition,
                },
            }
        )
    return result


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    pending = read_tsv(PENDING)
    queue_rows = read_jsonl(QUEUE)
    queue = {(int(row["stage_index"]), int(row["unique_index"])): row for row in queue_rows}
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    rules = user_rules(baseline) + curated_rules()
    concepts, unmatched = concept_items(pending, queue, rules)
    canonical = canonical_items(read_tsv(CANONICAL_MISSING))
    items = concepts + canonical
    disposition_counts = Counter(str(item["disposition"]) for item in items)
    human = [item for item in items if item["disposition"] in HUMAN_DISPOSITIONS]
    human.sort(key=lambda item: (0 if item["priority"] == "high" else 1, -int(item["usage"]["unique_rows"]), str(item["id"])))
    items.sort(key=lambda item: (0 if item["disposition"] in HUMAN_DISPOSITIONS else 1, 0 if item["priority"] == "high" else 1, str(item["id"])))

    document = {
        "schema_version": 1,
        "kind": "srwz_full_story_terminology_preprocessing",
        "policy": {
            "source_priority": ["recorded_user_decision", "official_chinese", "chinese_wiki", "downloaded_subtitles", "existing_project_glossary"],
            "writes_back_formal_translation": False,
            "video_analysis_used": False,
            "browser_ui_used": False,
        },
        "summary": {
            "pending_surface_rows": len(pending),
            "preprocessed_item_count": len(items),
            "human_review_item_count": len(human),
            "disposition_counts": dict(disposition_counts),
            "unmatched_surface_occurrence_count": len(unmatched),
        },
        "items": items,
    }
    write_json(OUT_JSON, document)
    write_json(SUMMARY, document["summary"])
    fields = ["id", "item_type", "work", "category", "source_terms", "observed_forms", "preferred_translation", "disposition", "confidence", "priority", "unique_rows", "expanded_occurrences", "rationale", "evidence"]
    table_rows = []
    for item in items:
        table_rows.append(
            {
                **item,
                "source_terms": " | ".join(item["source_terms"]),
                "observed_forms": " | ".join(f"{key} ({value})" for key, value in item["observed_forms"].items()),
                "unique_rows": item["usage"]["unique_rows"],
                "expanded_occurrences": item["usage"]["expanded_occurrences"],
                "evidence": " | ".join(f"{evidence['tier']}:{evidence['source']}:{evidence['claim']}" for evidence in item["evidence"]),
            }
        )
    write_tsv(OUT_TSV, fields, table_rows)
    write_tsv(HUMAN_TSV, fields, [row for row in table_rows if row["disposition"] in HUMAN_DISPOSITIONS])
    print(
        f"items={len(items)} human={len(human)} "
        + " ".join(f"{key}={value}" for key, value in sorted(disposition_counts.items()))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
