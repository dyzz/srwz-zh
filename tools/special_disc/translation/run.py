"""Send the prepared batches to DashScope and keep every draft, resumably.

  python3 run.py story --only ep01-ASR1-stg_001 [--tag pilot] [--thinking] [--workers 4]
  python3 run.py battle

Story/challenge batches of one episode run in order: each batch's context_before is filled with the
drafts of the batch before it. Episodes run in parallel. A result is kept per batch under
results/<tag>/<kind>/<batch>.json with the parsed translations, usage and any IDs the model missed;
a batch whose result has no missing IDs is not requested again.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import re
import sys
import time
from pathlib import Path

from api import MODEL, chat, parse_json
from common import HERE, load_json
from prompts import PROMPT_VERSION, battle_messages, story_messages
from validate import check, genders_of, hard_flags


def result_path(tag: str, kind: str, batch_id: str) -> Path:
    return HERE / "results" / tag / kind / f"{batch_id}.json"


def translations_of(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {t["id"]: t for t in load_json(path)["translations"]}


def normalize(batch: dict, item: dict) -> dict:
    """Battle subtitles carry literal \\n markers; the model often answers with real line breaks."""
    if batch["kind"] == "battle":
        item["text"] = item["text"].replace("\r", "").replace("\n", "\\n")
    else:  # dialogue is reflowed at writeback: drop copied breaks and their indent (logical_dialogue_text)
        item["text"] = re.sub(r"(?:\r?\n|\\n)[　 ]*", "", item["text"])
    return item


def request(batch: dict, *, model: str, thinking: bool) -> dict:
    payload = batch["payload"]
    base = battle_messages(payload) if batch["kind"] == "battle" else story_messages(payload)
    messages = base
    wanted = batch["todo_ids"]
    got, usage, raw_failures = {}, collections.Counter(), []
    started = time.time()
    for attempt in range(3):
        call = chat(messages, model=model, thinking=thinking)
        usage.update(prompt=call.prompt_tokens, completion=call.completion_tokens, cached=call.cached_tokens,
                      reasoning=call.reasoning_tokens, calls=1)
        try:
            items = parse_json(call.text)["translations"]
        except (ValueError, KeyError, TypeError) as exc:
            raw_failures.append(dict(error=str(exc), finish_reason=call.finish_reason, text=call.text[-2000:]))
            continue
        for item in items:
            if isinstance(item, dict) and item.get("id") in wanted and item.get("text"):
                got.setdefault(item["id"], normalize(batch, item))
        missing = [i for i in wanted if i not in got]
        if not missing:
            break
        # ask again for what is missing only, with the same context
        note = "上次输出漏了以下 id，请只翻译这些行（其余行已完成，只作上下文）：" + "、".join(missing)
        messages = [base[0], {"role": "user", "content": base[1]["content"] + "\n\n" + note}]
    order = {i: n for n, i in enumerate(wanted)}
    return dict(
        batch_id=batch["batch_id"], kind=batch["kind"], model=model, thinking=thinking, prompt_version=PROMPT_VERSION,
        elapsed=round(time.time() - started, 1), usage=dict(usage),
        translations=sorted(got.values(), key=lambda t: order[t["id"]]),
        missing=[i for i in wanted if i not in got], failures=raw_failures,
    )


def run_chain(paths: list[Path], *, tag: str, model: str, thinking: bool, force: bool) -> list[dict]:
    """One episode's batches in order, each with the previous drafts as context."""
    done = []
    previous_zh: dict[str, dict] = {}
    for path in paths:
        batch = load_json(path)
        target = result_path(tag, batch["kind"], batch["batch_id"])
        if target.exists() and not force and not load_json(target)["missing"]:
            result = load_json(target)
        else:
            for row in batch["payload"].get("context_before", []):
                if "zh" not in row and row["id"] in previous_zh:
                    row["zh"] = previous_zh[row["id"]]["text"]
            result = request(batch, model=model, thinking=thinking)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        previous_zh = {t["id"]: t for t in result["translations"]}
        u = result["usage"]
        print(f"{batch['batch_id']}: {len(result['translations'])}/{len(batch['todo_ids'])} "
              f"missing {len(result['missing'])} tokens {u.get('prompt', 0)}+{u.get('completion', 0)} "
              f"{result['elapsed']}s", file=sys.stderr)
        done.append(result)
    return done


def repair(path: Path, *, model: str) -> dict:
    """Re-request the lines of one result that fail a mechanical check, telling the model what is wrong."""
    result = load_json(path)
    batch = load_json(HERE / "batches" / result["kind"] / f"{result['batch_id']}.json")
    payload = batch["payload"]
    rows = {r["id"]: r for r in payload.get("script", payload.get("lines", [])) if "id" in r}
    genders = genders_of(payload)
    current = {t["id"]: t for t in result["translations"]}
    problems = {i: ["漏译"] for i in result["missing"]}
    for i, item in current.items():
        flags = hard_flags(check(batch, item, rows[i], genders))
        if flags:
            problems[i] = flags
    if not problems:
        return result
    note = ("请只重译下列行（其余行已定稿，只作上下文），并修正所列问题；输出格式不变，只包含这些 id：\n"
            + "\n".join(f"{i}：{'；'.join(f)}（上一稿：{current[i]['text'] if i in current else '无'}）"
                        for i, f in problems.items()))
    base = battle_messages(payload) if batch["kind"] == "battle" else story_messages(payload)
    call = chat([base[0], {"role": "user", "content": base[1]["content"] + "\n\n" + note}], model=model)
    usage = collections.Counter(result["usage"])
    usage.update(prompt=call.prompt_tokens, completion=call.completion_tokens, cached=call.cached_tokens, calls=1)
    fixed = []
    try:
        items = parse_json(call.text)["translations"]
    except (ValueError, KeyError, TypeError):
        items = []
    for item in items:
        i = item.get("id") if isinstance(item, dict) else None
        if i not in problems or not item.get("text"):
            continue
        item = normalize(batch, item)
        if len(hard_flags(check(batch, item, rows[i], genders))) < len(problems[i]) or i not in current:
            current[i] = item
            fixed.append(i)
    order = {i: n for n, i in enumerate(batch["todo_ids"])}
    result.update(translations=sorted(current.values(), key=lambda t: order[t["id"]]),
                  missing=[i for i in batch["todo_ids"] if i not in current], usage=dict(usage),
                  repaired=sorted(set(result.get("repaired", [])) | set(fixed)))
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{result['batch_id']}: {len(problems)} flagged, {len(fixed)} fixed", file=sys.stderr)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("story", "challenge", "battle"))
    parser.add_argument("--only", action="append", help="batch file prefix (an episode file name)")
    parser.add_argument("--tag", default="pilot")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--repair", action="store_true", help="re-request lines failing mechanical checks")
    args = parser.parse_args()
    if args.repair:
        paths = sorted((HERE / "results" / args.tag / args.kind).glob("*.json"))
        if args.only:
            paths = [p for p in paths if any(p.name.startswith(o) for o in args.only)]
        with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
            list(pool.map(lambda p: repair(p, model=args.model), paths))
        return
    files = sorted((HERE / "batches" / args.kind).glob("*.json"))
    if args.only:
        files = [f for f in files if any(f.name.startswith(o) for o in args.only)]
    chains = collections.OrderedDict()
    for f in files:
        key = f.name if args.kind == "battle" else f.name.rsplit("-", 1)[0]
        chains.setdefault(key, []).append(f)
    results = []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(run_chain, chain, tag=args.tag, model=args.model, thinking=args.thinking,
                               force=args.force) for chain in chains.values()]
        for fut in concurrent.futures.as_completed(futures):
            results.extend(fut.result())
    total = collections.Counter()
    for r in results:
        total.update(r["usage"])
    lines = sum(len(r["translations"]) for r in results)
    missing = sum(len(r["missing"]) for r in results)
    print(f"{len(results)} batches, {lines} lines, missing {missing}, tokens {dict(total)}")


if __name__ == "__main__":
    main()
