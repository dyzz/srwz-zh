#!/usr/bin/env python3
"""Benchmark one whole story-dialogue stage on an Alibaba general LLM.

The command is deliberately review-only.  It sends a selected complete or
stage-relevant glossary, reviewed style examples, and a whole-stage payload to
one OpenAI-compatible model, records exact token/latency data, and runs the
existing fail-closed importer on every returned stable ID.  All artifacts
remain below ``work/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from srwz.diagnostics import require_work_output
    from srwz.translation_review import TranslationReviewError
except ModuleNotFoundError:  # pragma: no cover - direct checkout invocation
    from tools.srwz.diagnostics import require_work_output
    from tools.srwz.translation_review import TranslationReviewError

try:
    from import_story_dialogue_local_model_batch import (
        _validate_translation,
        load_queue,
        validate_model_output,
    )
    from run_qwen_mt_story_dialogue_stage import (
        candidate_for_row,
        load_env,
        normalize_translation,
        preserved_candidate,
        relevant_terms,
        segment_id,
        select_stage_rows,
        validate_base_url,
    )
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.import_story_dialogue_local_model_batch import (
        _validate_translation,
        load_queue,
        validate_model_output,
    )
    from tools.run_qwen_mt_story_dialogue_stage import (
        candidate_for_row,
        load_env,
        normalize_translation,
        preserved_candidate,
        relevant_terms,
        segment_id,
        select_stage_rows,
        validate_base_url,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_INPUT = WORK_ROOT / "review" / "local-model" / "story-dialogue-unique.jsonl"
DEFAULT_ENV = PROJECT_ROOT / ".env"
DEFAULT_GLOSSARY_DIR = PROJECT_ROOT / "corpus" / "glossary"
DEFAULT_TIMEOUT = 900.0
DEFAULT_MAX_TOKENS = 65_536
DEFAULT_TM_STAGE = 9
DEFAULT_TM_COUNT = 5
MODEL_PRICES_CNY = {
    # Alibaba Cloud China (Beijing) list prices checked 2026-08-03.
    "qwen3.7-plus": (2.0, 8.0),
    "deepseek-v4-flash": (1.0, 2.0),
}
CACHE_HIT_PRICE_MULTIPLIER = 0.2
MODEL_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


class GeneralStageError(ValueError):
    """The whole-stage benchmark could not be completed safely."""


@dataclass(frozen=True)
class APICall:
    response_text: str
    model: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    reasoning_tokens: int
    elapsed_seconds: float
    first_content_seconds: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--glossary-dir", type=Path, default=DEFAULT_GLOSSARY_DIR)
    parser.add_argument("--tm-stage", type=int, default=DEFAULT_TM_STAGE)
    parser.add_argument("--tm-count", type=int, default=DEFAULT_TM_COUNT)
    parser.add_argument("--row-limit", type=int)
    parser.add_argument(
        "--unique-index",
        type=int,
        action="append",
        default=[],
        help="translate only this unique_index; repeat for a targeted repair batch",
    )
    parser.add_argument(
        "--prompt-profile",
        choices=("canonical", "compact-tsv", "compact-lines"),
        default="canonical",
    )
    parser.add_argument(
        "--glossary-scope",
        choices=("complete", "stage-relevant"),
        default="complete",
    )
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--skip-probe", action="store_true")
    parser.add_argument("--nonstream", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--input-price-cny", type=float)
    parser.add_argument("--output-price-cny", type=float)
    return parser.parse_args()


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def work_output(path: Path) -> Path:
    return require_work_output(project_path(path), WORK_ROOT).resolve()


def model_slug(model: str) -> str:
    value = MODEL_SLUG.sub("-", model).strip("-")
    if not value:
        raise GeneralStageError("model name cannot be converted to a safe artifact name")
    return value


def default_output_dir(stage: int, model: str) -> Path:
    return (
        WORK_ROOT
        / "review"
        / "local-model"
        / "aliyun"
        / f"stage-{stage:03d}"
        / "general-models"
        / model_slug(model)
    )


def load_complete_glossary(glossary_dir: Path) -> list[dict[str, str]]:
    files = sorted(glossary_dir.glob("*.json"))
    if not files:
        raise GeneralStageError(f"no glossary JSON files found below {glossary_dir}")
    pairs: set[tuple[str, str]] = set()
    ids: set[str] = set()
    for path in files:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise GeneralStageError(f"cannot read glossary {path}: {error}") from error
        terms = document.get("terms") if isinstance(document, Mapping) else None
        if not isinstance(terms, list):
            raise GeneralStageError(f"glossary terms must be an array: {path}")
        for term in terms:
            if not isinstance(term, Mapping):
                raise GeneralStageError(f"glossary contains a non-object: {path}")
            term_id = term.get("id")
            sources = term.get("source_terms")
            target = term.get("translation")
            if (
                not isinstance(term_id, str)
                or not isinstance(sources, list)
                or not isinstance(target, str)
            ):
                raise GeneralStageError(f"malformed glossary term in {path}")
            ids.add(term_id)
            for source in sources:
                if not isinstance(source, str) or not source:
                    raise GeneralStageError(f"malformed glossary source in {path}")
                pairs.add((source, target))
    result = [
        {"source": source, "target": target}
        for source, target in sorted(pairs)
    ]
    if len(ids) != 1_748 or len(result) != 1_750:
        raise GeneralStageError(
            "complete glossary inventory changed: "
            f"expected 1748 IDs/1750 pairs, found {len(ids)} IDs/{len(result)} pairs"
        )
    return result


def select_translation_memory(
    queue_rows: Sequence[Mapping[str, object]], stage: int, count: int
) -> list[dict[str, str]]:
    if count < 0:
        raise GeneralStageError("--tm-count must not be negative")
    result: list[dict[str, str]] = []
    for row in queue_rows:
        if int(row["stage_index"]) != stage:
            continue
        if row.get("review_state") != "locked_reviewed":
            continue
        source = row.get("source_text")
        target = row.get("existing_translation")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        if row.get("source_quote_shape") != "dialogue_quoted":
            continue
        result.append({"source": source, "target": target})
        if len(result) == count:
            break
    if len(result) != count:
        raise GeneralStageError(
            f"requested {count} reviewed TM examples from stage {stage:03d}, found {len(result)}"
        )
    return result


def append_stage_glossary_pairs(
    glossary: Sequence[Mapping[str, str]],
    rows: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, str]], int]:
    result = [dict(item) for item in glossary]
    seen = {(item["source"], item["target"]) for item in result}
    additions: set[tuple[str, str]] = set()
    for row in rows:
        terms = row.get("glossary_terms", [])
        if not isinstance(terms, list):
            raise GeneralStageError("queue glossary_terms must be an array")
        for term in terms:
            if not isinstance(term, Mapping):
                raise GeneralStageError("queue glossary term must be an object")
            sources = term.get("source_terms")
            target = term.get("translation")
            if not isinstance(sources, list) or not isinstance(target, str):
                raise GeneralStageError("queue glossary term is malformed")
            for source in sources:
                if not isinstance(source, str) or not source:
                    raise GeneralStageError("queue glossary source is malformed")
                pair = (source, target)
                if pair not in seen:
                    additions.add(pair)
    result.extend(
        {"source": source, "target": target}
        for source, target in sorted(additions)
    )
    return result, len(additions)


def translated_stage_rows(
    stage_rows: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    return [
        row
        for row in stage_rows
        if row.get("source_quote_shape") != "control_or_punctuation"
    ]


def stage_relevant_glossary(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    pairs = {
        (item["source"], item["target"])
        for row in rows
        for item in relevant_terms([row])
    }
    return [
        {"source": source, "target": target}
        for source, target in sorted(pairs)
    ]


def build_messages(
    rows: Sequence[Mapping[str, object]],
    glossary: Sequence[Mapping[str, str]],
    memory: Sequence[Mapping[str, str]],
    *,
    profile: str = "canonical",
) -> list[dict[str, str]]:
    if profile in {"compact-tsv", "compact-lines"}:
        glossary_text = "\n".join(
            f"{item['source']}\t{item['target']}" for item in glossary
        )
        memory_text = "\n\n".join(
            f"[日文]\n{item['source']}\n[中文]\n{item['target']}"
            for item in memory
        )
        if profile == "compact-lines":
            segments_text = "\n".join(
                f"{segment_id(row)}\t"
                + json.dumps(
                    str(row["source_text"]),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                for row in rows
            )
            input_contract = (
                "输入正文每行是‘ID<TAB>JSON 字符串’，字符串中的 \\n 表示原文换行。"
            )
            input_label = "待翻译分段 TSV："
        else:
            segments_text = json.dumps(
                [
                    {"id": segment_id(row), "jp": str(row["source_text"])}
                    for row in rows
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            input_contract = "输入正文是只含 id 和 jp 字段的 JSON 数组。"
            input_label = "待翻译分段 JSON："
        system = f"""你是《超级机器人大战Z》日中本地化译者。将日文游戏对白翻译成简洁、自然、符合人物语气的简体中文。

硬性要求：
1. 必须只返回一个有效 JSON 对象，不得使用 Markdown 或解释文字。
2. 唯一允许的 JSON 格式是 {{"translations":[{{"id":"10:0","text":"中文译文"}}]}}。
3. 输出项只允许 id 和 text 两个字段，禁止回传日文原文，禁止使用 source、target 或 jp 字段。
4. 每个输入 ID 必须恰好返回一次，顺序必须与输入完全一致，不得增加、遗漏或修改 ID。
5. 日文引号对白必须改用成对中文引号“”；译文内部不得含手工换行。
6. 保留所有 XML、格式占位符和控制码；不得输出日文假名。
7. 词表每行是“日文<TAB>中文”，凡语义对应必须采用指定译名；同一源词有多个译名时按语境选择一个。
8. 翻译记忆仅用于学习风格和标点，不要复制与当前原文无关的内容。
9. {input_contract}

完整规范词表 TSV：
{glossary_text}

已审核翻译记忆：
{memory_text}"""
        user = f"""请翻译以下整章分段。只输出规定的 JSON 对象，不要回传输入原文。

{input_label}
{segments_text}"""
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    if profile != "canonical":
        raise GeneralStageError(f"unsupported prompt profile: {profile}")
    glossary_json = json.dumps(
        list(glossary), ensure_ascii=False, separators=(",", ":")
    )
    memory_json = json.dumps(
        list(memory), ensure_ascii=False, separators=(",", ":")
    )
    segments_json = json.dumps(
        [
            {"id": segment_id(row), "source": str(row["source_text"])}
            for row in rows
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    system = f"""你是《超级机器人大战Z》日中本地化译者。将日文游戏对白翻译成简洁、自然、符合人物语气的简体中文。

硬性要求：
1. 必须只返回一个有效 JSON 对象，不得使用 Markdown 或解释文字。
2. JSON 格式必须严格为 {{"translations":[{{"id":"10:0","text":"中文译文"}}]}}。
3. 每个输入 ID 必须恰好返回一次，顺序必须与输入完全一致，不得增加、遗漏或修改 ID。
4. 日文引号对白必须改用成对中文引号“”；译文内部不得含手工换行。
5. 保留所有 XML、格式占位符和控制码；不得输出日文假名。
6. 词表是项目规范，凡语义对应必须使用指定译名；若同一源词有多个译名，只按当前语境选择一个。
7. 翻译记忆仅用于学习风格和标点，不要复制与当前原文无关的内容。

完整规范词表 JSON：
{glossary_json}

已审核翻译记忆 JSON：
{memory_json}"""
    user = f"""请翻译以下整章分段。只输出规定的 JSON 对象。

待翻译分段 JSON：
{segments_json}"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def request_payload(
    model: str,
    messages: Sequence[Mapping[str, str]],
    *,
    max_tokens: int,
    stream: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": model,
        "messages": list(messages),
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "enable_thinking": False,
        "response_format": {"type": "json_object"},
        "stream": stream,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


def usage_fields(usage: object) -> tuple[int, int, int, int]:
    if not isinstance(usage, Mapping):
        return 0, 0, 0, 0
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    prompt_details = usage.get("prompt_tokens_details", {})
    completion_details = usage.get("completion_tokens_details", {})
    cached = (
        int(prompt_details.get("cached_tokens", 0) or 0)
        if isinstance(prompt_details, Mapping)
        else 0
    )
    reasoning = (
        int(completion_details.get("reasoning_tokens", 0) or 0)
        if isinstance(completion_details, Mapping)
        else 0
    )
    return prompt, completion, cached, reasoning


def call_nonstream(
    *, api_key: str, base_url: str, payload: Mapping[str, object], timeout: float
) -> APICall:
    request = Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            document = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise GeneralStageError(f"HTTP {error.code}: {detail[:1000]}") from error
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise GeneralStageError(f"API request failed: {error}") from error
    elapsed = time.perf_counter() - started
    choices = document.get("choices")
    if not isinstance(choices, list) or not choices:
        raise GeneralStageError("API response has no choices")
    choice = choices[0]
    message = choice.get("message", {}) if isinstance(choice, Mapping) else {}
    text = message.get("content", "") if isinstance(message, Mapping) else ""
    if not isinstance(text, str):
        text = ""
    prompt, completion, cached, reasoning = usage_fields(document.get("usage"))
    return APICall(
        response_text=text,
        model=str(document.get("model", payload["model"])),
        finish_reason=(
            str(choice.get("finish_reason"))
            if isinstance(choice, Mapping) and choice.get("finish_reason") is not None
            else None
        ),
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
        reasoning_tokens=reasoning,
        elapsed_seconds=elapsed,
        first_content_seconds=elapsed if text else None,
    )


def call_stream(
    *, api_key: str, base_url: str, payload: Mapping[str, object], timeout: float
) -> APICall:
    request = Request(
        base_url + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    started = time.perf_counter()
    first_content: float | None = None
    fragments: list[str] = []
    prompt = completion = cached = reasoning = 0
    response_model = str(payload["model"])
    finish_reason: str | None = None
    try:
        with urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="strict").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                document = json.loads(data)
                response_model = str(document.get("model", response_model))
                current_usage = usage_fields(document.get("usage"))
                if current_usage[0] or current_usage[1]:
                    prompt, completion, cached, reasoning = current_usage
                choices = document.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                choice = choices[0]
                if not isinstance(choice, Mapping):
                    continue
                if choice.get("finish_reason") is not None:
                    finish_reason = str(choice["finish_reason"])
                delta = choice.get("delta", {})
                content = delta.get("content") if isinstance(delta, Mapping) else None
                if isinstance(content, str) and content:
                    if first_content is None:
                        first_content = time.perf_counter() - started
                    fragments.append(content)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise GeneralStageError(f"HTTP {error.code}: {detail[:1000]}") from error
    except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GeneralStageError(f"streaming API request failed: {error}") from error
    elapsed = time.perf_counter() - started
    text = "".join(fragments)
    if not text:
        raise GeneralStageError("streaming API response content is empty")
    return APICall(
        response_text=text,
        model=response_model,
        finish_reason=finish_reason,
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
        reasoning_tokens=reasoning,
        elapsed_seconds=elapsed,
        first_content_seconds=first_content,
    )


def parse_translations(
    response_text: str, rows: Sequence[Mapping[str, object]]
) -> tuple[list[tuple[Mapping[str, object], str]], dict[str, object]]:
    try:
        document = json.loads(response_text)
    except json.JSONDecodeError as error:
        return [], {"json_valid": False, "error": str(error)}
    if not isinstance(document, Mapping):
        return [], {"json_valid": True, "error": "top-level JSON is not an object"}
    translations = document.get("translations")
    if not isinstance(translations, list):
        return [], {"json_valid": True, "error": "translations is not an array"}
    expected_ids = [segment_id(row) for row in rows]
    actual_ids: list[str] = []
    values: list[str] = []
    malformed = 0
    for item in translations:
        if not isinstance(item, Mapping):
            malformed += 1
            continue
        item_id = item.get("id")
        text = item.get("text")
        if not isinstance(item_id, str) or not isinstance(text, str):
            malformed += 1
            continue
        actual_ids.append(item_id)
        values.append(text)
    exact_ids = actual_ids == expected_ids
    details: dict[str, object] = {
        "json_valid": True,
        "translation_item_count": len(translations),
        "well_formed_item_count": len(actual_ids),
        "malformed_item_count": malformed,
        "exact_id_order": exact_ids,
        "missing_ids": sorted(set(expected_ids) - set(actual_ids)),
        "unexpected_ids": sorted(set(actual_ids) - set(expected_ids)),
        "duplicate_ids": sorted(
            item_id for item_id in set(actual_ids) if actual_ids.count(item_id) > 1
        ),
    }
    if not exact_ids:
        details["error"] = "returned IDs do not exactly match the input order"
        return [], details
    return list(zip(rows, values)), details


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def call_record(call: APICall) -> dict[str, object]:
    return {
        "model": call.model,
        "finish_reason": call.finish_reason,
        "prompt_tokens": call.prompt_tokens,
        "completion_tokens": call.completion_tokens,
        "total_tokens": call.prompt_tokens + call.completion_tokens,
        "cached_tokens": call.cached_tokens,
        "reasoning_tokens": call.reasoning_tokens,
        "elapsed_seconds": round(call.elapsed_seconds, 6),
        "first_content_seconds": (
            round(call.first_content_seconds, 6)
            if call.first_content_seconds is not None
            else None
        ),
    }


def main() -> int:
    args = parse_args()
    if args.stage < 0:
        raise GeneralStageError("--stage must be non-negative")
    if args.max_tokens <= 0:
        raise GeneralStageError("--max-tokens must be positive")
    if args.probe_only and args.skip_probe:
        raise GeneralStageError("--probe-only and --skip-probe cannot be combined")

    queue_path = project_path(args.input).resolve()
    queue_rows = load_queue(queue_path)
    stage_rows = select_stage_rows(queue_rows, args.stage)
    all_translated_rows = translated_stage_rows(stage_rows)
    if args.row_limit is not None and args.row_limit <= 0:
        raise GeneralStageError("--row-limit must be positive")
    if args.row_limit is not None and args.unique_index:
        raise GeneralStageError("--row-limit and --unique-index cannot be combined")
    if args.unique_index:
        selected = set(args.unique_index)
        if len(selected) != len(args.unique_index):
            raise GeneralStageError("--unique-index values must be unique")
        available = {int(row["unique_index"]) for row in all_translated_rows}
        missing = sorted(selected - available)
        if missing:
            raise GeneralStageError(
                f"selected unique_index values are not translatable stage rows: {missing}"
            )
        rows = [
            row
            for row in all_translated_rows
            if int(row["unique_index"]) in selected
        ]
    else:
        rows = (
            all_translated_rows[: args.row_limit]
            if args.row_limit is not None
            else all_translated_rows
        )
    full_stage_scope = len(rows) == len(all_translated_rows)
    committed_glossary = load_complete_glossary(
        project_path(args.glossary_dir).resolve()
    )
    complete_glossary, stage_glossary_addition_count = append_stage_glossary_pairs(
        committed_glossary, all_translated_rows
    )
    glossary = (
        stage_relevant_glossary(rows)
        if args.glossary_scope == "stage-relevant"
        else complete_glossary
    )
    memory = select_translation_memory(queue_rows, args.tm_stage, args.tm_count)
    messages = build_messages(
        rows, glossary, memory, profile=args.prompt_profile
    )
    prompt_json = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))

    env = load_env(project_path(args.env_file).resolve())
    api_key = env.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise GeneralStageError("DASHSCOPE_API_KEY is missing or empty")
    base_url = validate_base_url(env.get("DASHSCOPE_BASE_URL", ""))

    output_dir = work_output(
        args.output_dir or default_output_dir(args.stage, args.model)
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "response.json"
    parsed_path = output_dir / "parsed.jsonl"
    validated_path = output_dir / "validated.jsonl"
    manifest_path = output_dir / "manifest.json"
    probe_path = output_dir / "probe.json"

    probe: APICall | None = None
    if not args.skip_probe:
        probe = call_nonstream(
            api_key=api_key,
            base_url=base_url,
            payload=request_payload(
                args.model, messages, max_tokens=1, stream=False
            ),
            timeout=args.timeout,
        )
        write_json(probe_path, call_record(probe))
        print(
            f"model={args.model} probe tokens={probe.prompt_tokens}+{probe.completion_tokens} "
            f"elapsed={probe.elapsed_seconds:.3f}s finish={probe.finish_reason}",
            flush=True,
        )
    if args.probe_only:
        return 0

    full_payload = request_payload(
        args.model,
        messages,
        max_tokens=args.max_tokens,
        stream=not args.nonstream,
    )
    if args.nonstream:
        call = call_nonstream(
            api_key=api_key,
            base_url=base_url,
            payload=full_payload,
            timeout=args.timeout,
        )
    else:
        call = call_stream(
            api_key=api_key,
            base_url=base_url,
            payload=full_payload,
            timeout=args.timeout,
        )
    write_json(raw_path, {"response_text": call.response_text})
    paired, format_audit = parse_translations(call.response_text, rows)

    parsed_candidates: list[dict[str, object]] = []
    valid_candidates: list[dict[str, object]] = []
    validation_errors: dict[str, str] = {}
    for row, translation in paired:
        candidate = candidate_for_row(row, normalize_translation(row, translation))
        parsed_candidates.append(candidate)
        try:
            valid_candidates.append(_validate_translation(row, candidate))
        except TranslationReviewError as error:
            validation_errors[segment_id(row)] = str(error)

    preserved = (
        [
            _validate_translation(row, preserved_candidate(row))
            for row in stage_rows
            if row.get("source_quote_shape") == "control_or_punctuation"
        ]
        if full_stage_scope
        else []
    )
    write_jsonl(parsed_path, sorted(
        parsed_candidates + preserved,
        key=lambda item: (int(item["stage_index"]), int(item["unique_index"])),
    ))
    write_jsonl(validated_path, sorted(
        valid_candidates + preserved,
        key=lambda item: (int(item["stage_index"]), int(item["unique_index"])),
    ))

    strict_passed = (
        not validation_errors
        and len(valid_candidates) == len(rows)
        and bool(format_audit.get("exact_id_order"))
    )
    final_audit_error = ""
    if strict_passed and full_stage_scope:
        ordered = []
        by_key = {
            (int(candidate["stage_index"]), int(candidate["unique_index"])): candidate
            for candidate in valid_candidates + preserved
        }
        ordered = [
            by_key[(int(row["stage_index"]), int(row["unique_index"]))]
            for row in stage_rows
        ]
        try:
            _, validated_by_key, missing = validate_model_output(
                queue_rows, ordered, allow_partial=True
            )
            stage_missing = [
                item for item in missing if int(item["stage_index"]) == args.stage
            ]
            strict_passed = (
                not stage_missing and len(validated_by_key) == len(stage_rows)
            )
        except TranslationReviewError as error:
            final_audit_error = str(error)

    default_prices = MODEL_PRICES_CNY.get(args.model)
    input_price = args.input_price_cny
    output_price = args.output_price_cny
    if input_price is None and default_prices is not None:
        input_price = default_prices[0]
    if output_price is None and default_prices is not None:
        output_price = default_prices[1]
    estimated_cost: float | None = None
    estimated_probe_cost: float | None = None
    if input_price is not None and output_price is not None:
        uncached_prompt_tokens = max(0, call.prompt_tokens - call.cached_tokens)
        estimated_cost = (
            (
                uncached_prompt_tokens
                + call.cached_tokens * CACHE_HIT_PRICE_MULTIPLIER
            )
            / 1_000_000
            * input_price
            + call.completion_tokens / 1_000_000 * output_price
        )
        if probe is not None:
            uncached_probe_tokens = max(
                0, probe.prompt_tokens - probe.cached_tokens
            )
            estimated_probe_cost = (
                (
                    uncached_probe_tokens
                    + probe.cached_tokens * CACHE_HIT_PRICE_MULTIPLIER
                )
                / 1_000_000
                * input_price
                + probe.completion_tokens / 1_000_000 * output_price
            )

    manifest = {
        "schema_version": 1,
        "kind": "aliyun_general_whole_stage_benchmark",
        "stage_index": args.stage,
        "requested_model": args.model,
        "response_model": call.model,
        "source_queue": str(queue_path.relative_to(PROJECT_ROOT)),
        "source_queue_sha256": hashlib.sha256(queue_path.read_bytes()).hexdigest(),
        "stage_row_count": len(stage_rows),
        "full_stage_scope": full_stage_scope,
        "full_stage_translated_row_count": len(all_translated_rows),
        "translated_row_count": len(rows),
        "selected_unique_indices": [int(row["unique_index"]) for row in rows]
        if not full_stage_scope
        else None,
        "preserved_row_count": len(preserved),
        "committed_glossary_pair_count": len(committed_glossary),
        "stage_glossary_addition_count": stage_glossary_addition_count,
        "available_glossary_pair_count": len(complete_glossary),
        "glossary_scope": args.glossary_scope,
        "glossary_pair_count": len(glossary),
        "translation_memory_count": len(memory),
        "prompt_profile": args.prompt_profile,
        "stream": not args.nonstream,
        "temperature": 0.1,
        "enable_thinking": False,
        "max_completion_tokens": args.max_tokens,
        "message_content_char_count": sum(
            len(str(message["content"])) for message in messages
        ),
        "prompt_char_count": len(prompt_json),
        "prompt_byte_count": len(prompt_json.encode("utf-8")),
        "probe": call_record(probe) if probe is not None else None,
        "run": call_record(call),
        "format_audit": format_audit,
        "validation": {
            "parsed_candidate_count": len(parsed_candidates) + len(preserved),
            "passed_candidate_count": len(valid_candidates) + len(preserved),
            "failed_candidate_count": len(validation_errors),
            "errors": validation_errors,
            "final_audit_error": final_audit_error,
            "strict_stage_passed": strict_passed,
        },
        "pricing": {
            "as_of": "2026-08-03",
            "region": "China (Beijing)",
            "input_cny_per_million": input_price,
            "output_cny_per_million": output_price,
            "implicit_cache_hit_price_multiplier": CACHE_HIT_PRICE_MULTIPLIER,
            "estimated_run_cost_cny": (
                round(estimated_cost, 6) if estimated_cost is not None else None
            ),
            "estimated_probe_cost_cny": (
                round(estimated_probe_cost, 6)
                if estimated_probe_cost is not None
                else None
            ),
            "estimated_total_cost_cny": (
                round(estimated_cost + estimated_probe_cost, 6)
                if estimated_cost is not None and estimated_probe_cost is not None
                else round(estimated_cost, 6)
                if estimated_cost is not None
                else None
            ),
        },
        "artifacts": {
            "raw_response": str(raw_path.relative_to(PROJECT_ROOT)),
            "parsed_output": str(parsed_path.relative_to(PROJECT_ROOT)),
            "validated_output": str(validated_path.relative_to(PROJECT_ROOT)),
        },
    }
    write_json(manifest_path, manifest)
    print(
        f"model={args.model} run tokens={call.prompt_tokens}+{call.completion_tokens} "
        f"ttfb={call.first_content_seconds!s}s elapsed={call.elapsed_seconds:.3f}s "
        f"parsed={len(parsed_candidates)}/{len(rows)} "
        f"validated={len(valid_candidates)}/{len(rows)} strict={strict_passed}",
        flush=True,
    )
    print(manifest_path.relative_to(PROJECT_ROOT), flush=True)
    return 0 if strict_passed else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GeneralStageError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
