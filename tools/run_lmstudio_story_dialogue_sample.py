#!/usr/bin/env python3
"""Run a small, fail-closed story-dialogue sample through LM Studio.

This is an opt-in local smoke path, not a production translator.  It reads the
ignored local-model queue, selects a few unlocked rows, calls LM Studio's
localhost API, and emits only the strict model-output fields.  The native
endpoint is the default because it exposes an explicit ``reasoning=off``
switch, which is important for Qwen3.6 JSON-only translation.  The resulting
JSONL can be passed to
``import_story_dialogue_local_model_batch.py --allow-partial``.
"""

from __future__ import annotations

import argparse
import json
import sys
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
    from import_story_dialogue_local_model_batch import load_queue
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from tools.import_story_dialogue_local_model_batch import load_queue


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = PROJECT_ROOT / "work"
DEFAULT_INPUT = WORK_ROOT / "review" / "local-model" / "story-dialogue-unique.jsonl"
DEFAULT_OUTPUT = (
    WORK_ROOT / "review" / "local-model" / "lmstudio-samples"
    / "story-dialogue-sample.jsonl"
)
DEFAULT_RAW_OUTPUT = (
    WORK_ROOT / "review" / "local-model" / "lmstudio-samples"
    / "story-dialogue-sample-raw.jsonl"
)
DEFAULT_MANIFEST = (
    WORK_ROOT / "review" / "local-model" / "lmstudio-samples"
    / "story-dialogue-sample-manifest.json"
)


SYSTEM_PROMPT = """你是 SRWZ 简体中文剧情首译器。只处理给你的这一条 JSON。
返回一个严格合法的 JSON 对象，必须包含 stage_index、unique_index、source_text_sha256、translation，
可选 notes；不要返回 Markdown、解释或额外字段。不要改动三个定位字段。
JSON 的字符串值必须使用 ASCII 双引号；中文对白引号只能写成“”，不能用中文引号代替 JSON 分隔符。
把 source_text 翻译成自然简体中文：不能残留日文假名，不要使用日文角引号「」『』，
对话使用成对中文引号“”。translation 字段必须是单行字符串，绝对不能包含换行符；原文
换行只表示排版，翻译时按语义用空格或标点衔接，不要照搬断行。再次强调：translation 值中禁止 \\n 和 \\r；例如原文“怎么回事，伊扎克！\\n  这些家伙到底是什么人！？”必须输出成一行“怎么回事，伊扎克！这些家伙到底是什么人！？”。原文中的 {xx}、<name:xx>、$n、$F、● 等
控制/占位符必须逐个原样保留。优先使用 glossary_terms 的 canonical translation；
enforce=true 必须遵守，glossary_conflicts 需要在 notes 标记需人工确认。已有译文只作
上下文，当前行仍属于草稿，不要声称 reviewed 或 final。"""


BATCH_SYSTEM_PROMPT = """你是 SRWZ 简体中文剧情首译器。本次 user JSON 的顶层字段是 items 数组，
每个元素是一条独立剧情文本。返回一个严格合法的 JSON 对象，顶层只能有 translations 数组；
数组必须为每个输入 item 返回一个对象，且逐字保留 stage_index、unique_index、source_text_sha256
三个定位字段，并包含 translation，可选 notes。不要返回 Markdown、解释或额外字段，不要遗漏、
合并、复制或重排 item。
JSON 的字符串值必须使用 ASCII 双引号；中文对白引号只能写成“”，不能用中文引号代替 JSON 分隔符。
把 source_text 翻译成自然简体中文：不能残留日文假名，不要使用日文角引号「」『』，对话使用成对
中文引号“”。translation 字段必须是单行字符串，绝对不能包含换行符；原文换行只表示排版，翻译
时按语义用空格或标点衔接，不要照搬断行。dialogue_quoted 行必须以“开头并以”结尾。原文中的
{xx}、<name:xx>、$n、$F、● 等控制/占位符必须逐个原样保留。优先使用 glossary_terms 的
canonical translation；enforce=true 必须遵守，glossary_conflicts 需要在 notes 标记需人工确认。
已有译文只作上下文，当前行仍属于草稿，不要声称 reviewed 或 final。"""


def _path(value: Path) -> Path:
    return value if value.is_absolute() else PROJECT_ROOT / value


def _output(value: Path) -> Path:
    return require_work_output(_path(value), WORK_ROOT).resolve()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--base-url", default="http://localhost:1234")
    parser.add_argument("--model", help="LM Studio model id; defaults to a loaded LLM")
    parser.add_argument(
        "--api",
        choices=("native", "openai"),
        default="native",
        help="LM Studio API surface (native /api/v1/chat is the default)",
    )
    parser.add_argument(
        "--reasoning",
        choices=("off", "low", "medium", "high", "on"),
        default="off",
        help="native API reasoning setting; off is recommended for JSON output",
    )
    parser.add_argument("--stage", type=int)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="number of dialogue units per model request (default: 8)",
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _request_json(base_url: str, path: str, *, method: str = "GET", payload=None) -> Mapping[str, object]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        base_url.rstrip("/") + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=120) as response:
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise TranslationReviewError(
            f"LM Studio {method} {path} returned HTTP {error.code}: {detail[:500]}"
        ) from error
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise TranslationReviewError(
            f"cannot call LM Studio {method} {path}: {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise TranslationReviewError(f"LM Studio {path} returned a non-object JSON value")
    return value


def discover_model(base_url: str, requested: str | None = None) -> str:
    if requested:
        return requested
    api = _request_json(base_url, "/api/v1/models")
    models = api.get("models", [])
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, Mapping) or item.get("type") != "llm":
                continue
            loaded = item.get("loaded_instances", [])
            if isinstance(loaded, list) and loaded:
                key = item.get("key")
                if isinstance(key, str) and key:
                    return key
    raise TranslationReviewError(
        "LM Studio has no loaded LLM; load a translation-capable model first "
        "then rerun this sample"
    )


def select_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    stage: int | None,
    count: int,
) -> list[Mapping[str, object]]:
    if count <= 0:
        raise TranslationReviewError("--count must be positive")
    selected = []
    for row in rows:
        if row.get("review_state") == "locked_reviewed":
            continue
        if stage is not None and row.get("stage_index") != stage:
            continue
        if row.get("source_quote_shape") == "control_or_punctuation":
            continue
        selected.append(row)
        if len(selected) == count:
            break
    if not selected:
        scope = f"stage {stage:03d}" if stage is not None else "the queue"
        raise TranslationReviewError(f"no unlocked dialogue sample found in {scope}")
    return selected


def chunk_rows(
    rows: Sequence[Mapping[str, object]], batch_size: int
) -> list[list[Mapping[str, object]]]:
    if batch_size <= 0:
        raise TranslationReviewError("--batch-size must be positive")
    return [list(rows[start : start + batch_size]) for start in range(0, len(rows), batch_size)]


def _response_text(response: Mapping[str, object]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise TranslationReviewError("LM Studio response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise TranslationReviewError("LM Studio response choice is malformed")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise TranslationReviewError("LM Studio response has no message content")
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    reasoning_content = message.get("reasoning_content")
    if isinstance(reasoning_content, str) and reasoning_content.strip():
        return reasoning_content.strip()
    raise TranslationReviewError("LM Studio response has no message content")


def _native_response_text(response: Mapping[str, object]) -> str:
    output = response.get("output")
    if not isinstance(output, list):
        raise TranslationReviewError("LM Studio native response has no output list")
    messages = []
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            messages.append(content.strip())
    if not messages:
        raise TranslationReviewError("LM Studio native response has no message content")
    return "\n".join(messages)


def parse_model_object(text: str) -> dict[str, object]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise TranslationReviewError(f"LM Studio returned non-JSON content: {text[:300]!r}") from error
    if not isinstance(value, dict):
        raise TranslationReviewError("LM Studio output must be a JSON object")
    allowed = {
        "stage_index",
        "unique_index",
        "source_text_sha256",
        "translation",
        "notes",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TranslationReviewError(f"LM Studio output has unsupported fields: {unknown!r}")
    return value


def parse_model_batch(text: str) -> list[dict[str, object]]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise TranslationReviewError(
            f"LM Studio returned non-JSON batch content: {text[:300]!r}"
        ) from error
    if not isinstance(value, dict):
        raise TranslationReviewError("LM Studio batch output must be a JSON object")
    unknown = sorted(set(value) - {"translations"})
    if unknown:
        raise TranslationReviewError(
            f"LM Studio batch output has unsupported fields: {unknown!r}"
        )
    translations = value.get("translations")
    if not isinstance(translations, list) or not translations:
        raise TranslationReviewError("LM Studio batch output has no translations array")
    parsed = []
    for item in translations:
        if not isinstance(item, dict):
            raise TranslationReviewError("LM Studio batch translation item is not an object")
        parsed.append(
            parse_model_object(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        )
    return parsed


def _response_schema(batch: bool) -> dict[str, object]:
    item_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "stage_index": {"type": "integer"},
            "unique_index": {"type": "integer"},
            "source_text_sha256": {"type": "string"},
            "translation": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": [
            "stage_index",
            "unique_index",
            "source_text_sha256",
            "translation",
            "notes",
        ],
    }
    if batch:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "translations": {
                    "type": "array",
                    "items": item_schema,
                }
            },
            "required": ["translations"],
        }
        name = "story_dialogue_translation_batch"
    else:
        schema = item_schema
        name = "story_dialogue_translation"
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }


def _call_model(
    *,
    base_url: str,
    model: str,
    user_content: str,
    temperature: float,
    max_tokens: int,
    api: str,
    reasoning: str,
    batch: bool,
) -> tuple[Mapping[str, object], str]:
    if api == "native":
        response = _request_json(
            base_url,
            "/api/v1/chat",
            method="POST",
            payload={
                "model": model,
                "system_prompt": BATCH_SYSTEM_PROMPT if batch else SYSTEM_PROMPT,
                "input": user_content,
                "temperature": temperature,
                "max_output_tokens": max_tokens,
                "reasoning": reasoning,
                "store": False,
            },
        )
        return response, _native_response_text(response)
    if api == "openai":
        response = _request_json(
            base_url,
            "/v1/chat/completions",
            method="POST",
            payload={
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {
                        "role": "system",
                        "content": BATCH_SYSTEM_PROMPT if batch else SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": user_content},
                ],
                "response_format": _response_schema(batch),
            },
        )
        return response, _response_text(response)
    raise TranslationReviewError(f"unsupported LM Studio API mode: {api!r}")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _row_request_payload(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "stage_index": row["stage_index"],
        "unique_index": row["unique_index"],
        "source_text_sha256": row["source_text_sha256"],
        "source_text": row["source_text"],
        "source_quote_shape": row.get("source_quote_shape", ""),
        "existing_translation": row.get("existing_translation", ""),
        "glossary_terms": row.get("glossary_terms", []),
        "glossary_conflicts": row.get("glossary_conflicts", []),
    }


def _validate_candidate(
    candidate: Mapping[str, object], row: Mapping[str, object]
) -> dict[str, object]:
    context = f"stage {int(row['stage_index']):03d} unique {row['unique_index']}"
    for key in ("stage_index", "unique_index", "source_text_sha256", "translation"):
        if key not in candidate:
            raise TranslationReviewError(f"{context}: model output omitted {key!r}")
    if candidate["stage_index"] != row["stage_index"] or candidate["unique_index"] != row["unique_index"]:
        raise TranslationReviewError(f"{context}: model changed the sample stable ID")
    if candidate["source_text_sha256"] != row["source_text_sha256"]:
        raise TranslationReviewError(f"{context}: model changed the sample source hash")
    translation = candidate["translation"]
    if not isinstance(translation, str) or not translation:
        raise TranslationReviewError(f"{context}: translation must be a non-empty string")
    if "\n" in translation or "\r" in translation:
        raise TranslationReviewError(f"{context}: translation contains a manual line break")
    if any(mark in translation for mark in ("「", "」", "『", "』")):
        raise TranslationReviewError(f"{context}: translation uses Japanese corner quotes")
    if row.get("source_quote_shape") == "dialogue_quoted":
        stripped = translation.strip()
        if not (stripped.startswith("“") and stripped.endswith("”")):
            raise TranslationReviewError(
                f"{context}: quoted translation lacks paired Chinese quotation marks"
            )
    return dict(candidate)


def run_sample(
    rows: Sequence[Mapping[str, object]],
    *,
    base_url: str,
    model: str,
    temperature: float,
    max_tokens: int,
    api: str = "native",
    reasoning: str = "off",
    batch_size: int = 8,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    outputs = []
    raw_rows = []
    batches = chunk_rows(rows, batch_size)
    for batch_index, batch_rows in enumerate(batches):
        request_payload = {
            "items": [_row_request_payload(row) for row in batch_rows]
        }
        user_content = json.dumps(request_payload, ensure_ascii=False)
        response = None
        content = ""
        candidates: list[dict[str, object]] | None = None
        retry_errors = []
        for attempt in range(2):
            attempt_user_content = user_content
            if attempt:
                attempt_user_content += (
                    "\n格式修复：上一版输出未通过机器校验。请重新返回同一个 translations 数组，"
                    "必须为每个输入 item 返回一条，不能遗漏、合并、复制或重排；"
                    "translation 必须是单行字符串，删除其中所有换行和缩进；"
                    "对白必须使用中文引号“”，禁止使用「」『』；dialogue_quoted 行必须以“开头并以”结尾；"
                    "所有 JSON 字符串必须使用 ASCII 双引号，不要输出 Markdown、解释或额外字段。"
                    "上一版原始输出（只用于修复，不要照抄其错误格式）如下：\n"
                    + content
                )
            response, content = _call_model(
                base_url=base_url,
                model=model,
                user_content=attempt_user_content,
                temperature=temperature,
                max_tokens=max_tokens,
                api=api,
                reasoning=reasoning,
                batch=True,
            )
            try:
                parsed = parse_model_batch(content)
                if len(parsed) != len(batch_rows):
                    raise TranslationReviewError(
                        f"batch {batch_index}: expected {len(batch_rows)} translations, got {len(parsed)}"
                    )
                expected = {
                    (row["stage_index"], row["unique_index"]): row for row in batch_rows
                }
                by_key: dict[tuple[object, object], dict[str, object]] = {}
                for candidate in parsed:
                    key = (candidate.get("stage_index"), candidate.get("unique_index"))
                    try:
                        duplicate = key in by_key
                        row = expected.get(key)
                    except TypeError as error:
                        raise TranslationReviewError(
                            f"batch {batch_index}: translation ID is not hashable {key!r}"
                        ) from error
                    if duplicate:
                        raise TranslationReviewError(
                            f"batch {batch_index}: duplicate translation ID {key!r}"
                        )
                    if row is None:
                        raise TranslationReviewError(
                            f"batch {batch_index}: unexpected translation ID {key!r}"
                        )
                    by_key[key] = _validate_candidate(candidate, row)
                if set(by_key) != set(expected):
                    missing = sorted(set(expected) - set(by_key))
                    raise TranslationReviewError(
                        f"batch {batch_index}: missing translation IDs {missing!r}"
                    )
                candidates = [
                    by_key[(row["stage_index"], row["unique_index"])]
                    for row in batch_rows
                ]
                break
            except TranslationReviewError as error:
                retry_errors.append(str(error))
                if attempt == 1:
                    raise TranslationReviewError(
                        f"batch {batch_index} failed after format retry: {error}"
                    ) from error
        assert candidates is not None
        outputs.extend(candidates)
        raw_rows.append(
            {
                "batch_index": batch_index,
                "stage_indexes": [row["stage_index"] for row in batch_rows],
                "unique_indexes": [row["unique_index"] for row in batch_rows],
                "response": response,
                "content": content,
                "attempt_count": len(retry_errors) + 1,
                "retry_errors": retry_errors,
            }
        )
    return outputs, raw_rows


def main() -> int:
    args = _parse_args()
    if args.temperature < 0 or args.max_tokens <= 0 or args.batch_size <= 0:
        raise TranslationReviewError(
            "temperature must be non-negative, max-tokens positive, and batch-size positive"
        )
    input_path = _output(args.input)
    output_path = _output(args.output)
    raw_path = _output(args.raw_output)
    manifest_path = _output(args.manifest)
    if not args.force and any(path.exists() for path in (output_path, raw_path, manifest_path)):
        raise TranslationReviewError("LM Studio sample output exists; use --force")
    rows = select_rows(load_queue(input_path), stage=args.stage, count=args.count)
    model = discover_model(args.base_url, args.model)
    outputs, raw_rows = run_sample(
        rows,
        base_url=args.base_url,
        model=model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        api=args.api,
        reasoning=args.reasoning,
        batch_size=args.batch_size,
    )
    _write_jsonl(output_path, outputs)
    _write_jsonl(raw_path, raw_rows)
    manifest = {
        "schema_version": 1,
        "kind": "lmstudio_story_dialogue_sample",
        "input": str(input_path.relative_to(PROJECT_ROOT)),
        "model": model,
        "base_url": args.base_url,
        "api": args.api,
        "reasoning": args.reasoning if args.api == "native" else None,
        "batch_size": args.batch_size,
        "batch_count": len(raw_rows),
        "count": len(outputs),
        "rows": [
            {
                "stage_index": row["stage_index"],
                "unique_index": row["unique_index"],
                "source_text_sha256": row["source_text_sha256"],
            }
            for row in outputs
        ],
        "next_step": "validate with import_story_dialogue_local_model_batch.py --allow-partial",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"LM Studio sample complete: model={model} rows={len(outputs)} "
        f"batches={len(raw_rows)} batch_size={args.batch_size}"
    )
    print(f"model output: {output_path}")
    print(f"raw responses: {raw_path}")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, TranslationReviewError) as error:
        print(f"LM Studio sample failed: {error}", file=sys.stderr)
        raise SystemExit(1)
