#!/usr/bin/env python3
"""Battle-line follow-ups to the 2026-11-09 polish, decided by the user on 2026-11-10.

Three groups, one write:
  choices   the lines the user picked on the review page
  greta     グレタ's 父ちゃん / あんた = her late husband (老伴, as the story now says)
  tags      remove every <width:..><space:..> pair; Latin and digits are laid out by
            the proportional renderer, as everywhere else

Dry run unless --apply. A line is skipped, never forced, when the corpus no longer
holds the expected text, the stored geometry gate rejects it, its last row would be one
character, it needs a glyph the font lacks, or (wording changes only) the review site
has a suggestion on it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_battle_polish_20261109 as polish  # noqa: E402

REVIEW = polish.REVIEW
CORPUS = polish.CORPUS
RECEIPT = ROOT / "config/editorial/battle-followup-20261110.json"
TAG = re.compile(r"<(?:width|space):[0-9A-Fa-f]{2}>")
BREAK = "\\n\u3000"

CHOICES = {  # review-page picks, read from the page on 2026-11-10
    "battle:01720": "嗯、嗯…/多亏阿波罗，我才得救了…！",  # pick + 「は、はい…」 is a flustered reply, not 是、是的
    "battle:08731": "这总不会就是你的全力吧，/卡洛德·兰？",
    "battle:12967": "我的攻势，/可不能化解哦，鸫！",
    "battle:14680": "陪丽花的人是我！/不是你！",
    "battle:14698": "丽花！只要是为了你——！",
}
GRETA = {
    "battle:05703": "抱歉，论老练，/你比我老伴差远了！",
    "battle:05704": "你这男人挺不赖嘛。/虽然比不上我老伴！",
    "battle:05708": "老伴，我一定替你报仇！",
    "battle:05710": "都是你们害死了我老伴！/老~伴~！",
    "battle:05711": "老伴的仇，由我来报！",
    "battle:05712": "老伴，可要保护好我啊！",
    "battle:05719": "老伴，我爱你~！",
    "battle:05721": "呜哇啊啊啊！老~伴~！",
    "battle:05724": "啊呜！/老伴，借我点力气吧！",
    "battle:05726": "吉隆！别以为我/会那么轻易去找老伴！",
    "battle:05742": "老伴…/你保护了我呢…",
    "battle:05746": "老伴在保护着我呢！",
}


# Apostrophes gained contextual metrics on 2026-11-10; the three previous holds
# were explicitly authorized, written back and checked with ARMSX2.
HOLD_TAGS: set[str] = set()


def stored(text: str) -> str:
    return "“" + BREAK.join(part.strip() for part in text.split("/")) + "”"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", default="choices,greta,tags")
    parser.add_argument("--authorization", default="")
    parser.add_argument("--report", type=Path, default=REVIEW / "followup-dry-run.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.authorization:
        raise SystemExit("--apply needs --authorization")
    groups = set(args.groups.split(","))

    raw = CORPUS.read_bytes()
    document = json.loads(raw)
    if polish.dump(document).encode("utf-8") != raw:
        raise SystemExit("battle corpus is not in canonical serialisation")
    entries = {entry["id"]: entry for entry in document["entries"]}
    charset = set(json.loads((REVIEW / "recheck/charset.json").read_text(encoding="utf-8")))

    planned = []
    for group, table in (("choices", CHOICES), ("greta", GRETA)):
        if group in groups:
            for identity, text in table.items():
                planned.append(dict(id=identity, group=group, before=entries[identity]["translation"], after=stored(text)))
    if "tags" in groups:
        taken = {row["id"] for row in planned}
        for entry in document["entries"]:
            if TAG.search(entry["translation"]) and entry["id"] not in taken and entry["id"] not in HOLD_TAGS:
                planned.append(dict(id=entry["id"], group="tags", before=entry["translation"], after=TAG.sub("", entry["translation"])))
    for row in planned:  # a wording change also drops any tags the line carries
        row["after"] = TAG.sub("", row["after"])

    online = polish.fetch_online()
    (REVIEW / "online-snapshot-followup.json").write_text(polish.dump(online), encoding="utf-8")
    direct = {row["targetId"] for row in online["all"] if row["targetType"] == "battle-line"}

    from srwz.build_layout import stored_geometry_issues
    geometry = stored_geometry_issues([(row["id"], row["after"], False) for row in planned], "battle")
    write, skipped, notes = [], [], []
    for row in planned:
        reasons = []
        if row["after"] == row["before"]:
            reasons.append("no change")
        if "<" in row["after"]:
            reasons.append("another control tag remains")
        if row["group"] != "tags" and row["id"] in direct:
            reasons.append("online suggestion on this line")
        if row["after"].count("\\n") != row["before"].count("\\n"):
            reasons.append("row count differs from the current line")
        if polish.short_last_row(row["after"]) and not polish.short_last_row(row["before"]):
            reasons.append("last row is one character or punctuation only")
        missing = sorted({ch for ch in row["after"].replace("\\n", "") if ch not in charset})
        if missing:
            reasons.append("new glyphs: " + "".join(missing))
        reasons.extend(geometry.get(row["id"], ()))
        if reasons:
            skipped.append(dict(row, reasons=reasons))
        else:
            write.append(row)
            if row["group"] == "tags" and row["id"] in direct:
                notes.append(row["id"])
    summary = dict(planned=len(planned), write=len(write), skipped=len(skipped),
                   by_group={group: sum(row["group"] == group for row in write) for group in sorted(groups)},
                   tagged_lines_with_online_suggestions=len(notes),
                   online_snapshot_at=online["fetched_at"], online_snapshot_total=online["total"])
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for row in skipped:
        print("skip", row["id"], row["reasons"], row["after"])
    if not args.apply:
        args.report.write_text(polish.dump(dict(summary=summary, write=write, skipped=skipped)), encoding="utf-8")
        print(f"dry run: {args.report.relative_to(ROOT)}")
        return 0

    for row in write:
        entries[row["id"]]["translation"] = row["after"]
    after = polish.dump(document).encode("utf-8")
    before_lock = dict(path=polish.CORPUS_REF, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    after_lock = dict(path=polish.CORPUS_REF, size=len(after), sha256=hashlib.sha256(after).hexdigest())
    refreshed = polish.refresh_battle_input_lock(before_lock, after_lock)
    CORPUS.write_bytes(after)
    RECEIPT.write_text(polish.dump(dict(
        schema_version=1, review_id="battle-followup-20261110", translation_writeback=True,
        purpose="润色后的跟进：用户在审阅页点选的 5 条；格蕾塔的 父ちゃん／あんた 查证为亡夫，统一作老伴；去掉战斗台词里全部宽度与间距标签。",
        authorization=args.authorization, feedback_snapshot_at=online["fetched_at"], feedback_snapshot_total=online["total"],
        summary=summary, application=dict(files=[dict(path=polish.CORPUS_REF, before_sha256=before_lock["sha256"], after_sha256=after_lock["sha256"])],
                                          input_lock_refresh=dict(before=before_lock, after=after_lock, files=refreshed), site_writeback=False),
        entries=write, skipped=skipped, tagged_lines_with_online_suggestions=notes)), encoding="utf-8")
    print(f"wrote {len(write)} lines; receipt {RECEIPT.relative_to(ROOT)}; refreshed {len(refreshed)} lock files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
